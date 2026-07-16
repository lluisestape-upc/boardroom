"""Reproducible defect injection for the BoardRoom benchmark.

Given a clean KiCad board copy, apply one or more *seed* transforms to the root
schematic and record a ground-truth manifest of what a correct reviewer must
flag. Every transform is a deterministic, text-level operation on the
``.kicad_sch`` s-expression, so the same clean input always yields byte-identical
mutated output. Defects are "reversible by reseeding from clean": nothing is
edited in place -- ``seed_board`` reads the clean copy and writes a fresh mutated
copy, so re-running from the clean source reproduces (or reverts) any state.

Seed types (each detects its own applicability and skips cleanly if the board
lacks a target):

    remove_decoupling_cap  delete one bypass cap symbol (0.1uF/100nF family)
    swap_i2c_sda_scl       swap an SDA/SCL net-label pair
    remove_i2c_pullups     delete pull-up resistor(s) on an I2C bus
    float_enable_pin       orphan one node of an enable/reset net
    rename_rail_net        rename one node of a power rail so it floats

These are SYNTHETIC defects for benchmarking: transforms operate on labels,
sheet pins, power symbols and component symbols that are reliably identifiable in
the s-expression. Ground truth records exactly what was mutated, so scoring is
exact regardless of KiCad's geometric net inference. Applicability is
deliberately conservative -- a skip is a valid, logged outcome.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .corpus import BoardSpec

log = logging.getLogger("benchmark.seed")

# Fixed application order -> deterministic multi-defect boards.
SEED_TYPES: tuple[str, ...] = (
    "remove_decoupling_cap",
    "swap_i2c_sda_scl",
    "remove_i2c_pullups",
    "float_enable_pin",
    "rename_rail_net",
)

# Suffix appended to a net name to orphan/float a single node.
FLOAT_SUFFIX = "__SEED_FLOAT"

# Decoupling / bypass cap values (the classic 0.1uF-family + small bypass).
_DECOUPLING_VALUE_RE = re.compile(
    r"\b(0\.1\s*u|100\s*n|47\s*n|22\s*n|10\s*n|4\.7\s*n|1\s*n|0\.01\s*u)\s*f?\b", re.I
)
# Typical I2C pull-up resistor values, incl. KiCad "2k2"/"4k7" shorthand.
_PULLUP_VALUE_RE = re.compile(r"\b(1k|1k5|1\.5k|2k2|2\.2k|2k7|2\.7k|3k3|3\.3k|4k7|4\.7k|5k1|5\.1k|10k)\b", re.I)
# Enable / reset net keywords (whole-token, keyword may carry a ~ or {} prefix
# and an optional bus/index suffix like _IO, -, 0..9).
_ENABLE_RE = re.compile(
    r"^~?\{?(EN|ENB|CE|SHDN|PWR_EN|CHIP_EN|RESET|RST|RSTL|RSTI|RSTO|MCLR|NRST)\}?[-_/0-9A-Za-z]*$", re.I
)
# Power-rail net names: +3V3, 5V, 3V3_PI, VCC, VDD33, VBAT ... but not ground.
_RAIL_RE = re.compile(r"^[+-]?\d+V\d*([_-][0-9A-Za-z]+)?$|^V(CC|DD|BAT|BUS|IN|SYS|AA|DDA)[0-9A-Za-z_]*$", re.I)
_GROUND_RE = re.compile(r"^(GND|GNDA|GNDD|GNDPWR|AGND|DGND|EARTH|VSS|PWR_FLAG)[0-9A-Za-z_]*$", re.I)

_NET_LABEL_RE = re.compile(r'\((?:label|global_label|hierarchical_label) "([^"]*)"')
_SHEET_PIN_RE = re.compile(
    r'\(pin "([^"]*)"\s+(?:input|output|bidirectional|tri_state|passive|free|unspecified|power_in|power_out)'
)


@dataclass
class GroundTruthDefect:
    """One seeded defect: what a correct reviewer must flag."""

    defect_id: str
    type: str
    board_id: str
    expected_agent: str
    expected_severity: str
    affected_refs: list[str] = field(default_factory=list)
    affected_nets: list[str] = field(default_factory=list)
    description: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "GroundTruthDefect":
        return cls(
            defect_id=d["defect_id"],
            type=d["type"],
            board_id=d["board_id"],
            expected_agent=d["expected_agent"],
            expected_severity=d["expected_severity"],
            affected_refs=list(d.get("affected_refs", [])),
            affected_nets=list(d.get("affected_nets", [])),
            description=d.get("description", ""),
        )


@dataclass
class SeedOutcome:
    """Result of applying one seed transform to schematic text."""

    text: str
    defect: GroundTruthDefect | None
    skip_reason: str | None

    @property
    def applied(self) -> bool:
        return self.defect is not None


# --------------------------------------------------------------------------- #
# s-expression helpers (deterministic, quote-aware)                           #
# --------------------------------------------------------------------------- #


def _match_balanced(text: str, start: int) -> int:
    """Return the index one past the balanced s-expr beginning at ``text[start] == '('``."""
    depth = 0
    in_str = False
    esc = False
    i = start
    n = len(text)
    while i < n:
        c = text[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return n


def _symbol_instances(text: str) -> list[tuple[int, int, str]]:
    """All schematic symbol *instances* as (start, end, block_text), in file order.

    Instances start ``(symbol`` immediately followed by ``(lib_id ...``; library
    definitions in ``lib_symbols`` (``(symbol "Name"``) are excluded.
    """
    out: list[tuple[int, int, str]] = []
    for m in re.finditer(r"\(symbol\b", text):
        start = m.start()
        end = _match_balanced(text, start)
        block = text[start:end]
        if re.match(r"\(symbol\s+\(lib_id\b", block):
            out.append((start, end, block))
    return out


def _prop(block: str, name: str) -> str | None:
    m = re.search(rf'\(property "{re.escape(name)}" "([^"]*)"', block)
    return m.group(1) if m else None


def _ref_sort_key(ref: str) -> tuple[str, int, str]:
    """Sort refs by prefix then numeric index (C2 before C10)."""
    m = re.match(r"^([A-Za-z#]+)(\d+)", ref)
    if m:
        return (m.group(1), int(m.group(2)), ref)
    return (ref, 0, ref)


def _delete_block(text: str, start: int, end: int) -> str:
    """Remove text[start:end] plus its leading indentation and one trailing newline."""
    line_start = text.rfind("\n", 0, start) + 1
    tail = end
    if tail < len(text) and text[tail] == "\n":
        tail += 1
    return text[:line_start] + text[tail:]


def _net_names(text: str) -> list[str]:
    """All net-carrying label + sheet-pin names, in file order (with duplicates)."""
    names: list[tuple[int, str]] = []
    for m in _NET_LABEL_RE.finditer(text):
        names.append((m.start(), m.group(1)))
    for m in _SHEET_PIN_RE.finditer(text):
        names.append((m.start(), m.group(1)))
    names.sort()
    return [n for _, n in names]


# --------------------------------------------------------------------------- #
# individual seed transforms                                                  #
# --------------------------------------------------------------------------- #


def _seed_remove_decoupling_cap(text: str, board_id: str) -> SeedOutcome:
    candidates = []
    for start, end, block in _symbol_instances(text):
        ref = _prop(block, "Reference")
        val = _prop(block, "Value") or ""
        if ref and re.match(r"^C\d+$", ref) and _DECOUPLING_VALUE_RE.search(val):
            candidates.append((ref, val, start, end))
    if not candidates:
        return SeedOutcome(text, None, "no decoupling-value capacitor symbol found")
    ref, val, start, end = min(candidates, key=lambda c: _ref_sort_key(c[0]))
    new_text = _delete_block(text, start, end)
    defect = GroundTruthDefect(
        defect_id=f"{board_id}:remove_decoupling_cap",
        type="remove_decoupling_cap",
        board_id=board_id,
        expected_agent="power_integrity",
        expected_severity="major",
        affected_refs=[ref],
        affected_nets=[],
        description=f"Bypass capacitor {ref} ({val}) removed from a power pin; rail now lacks local decoupling.",
    )
    return SeedOutcome(new_text, defect, None)


def _find_i2c_pair(text: str) -> tuple[str, str] | None:
    """First (SDA, SCL) net pair sharing prefix+suffix, deterministically chosen."""
    names = set(_net_names(text))
    pairs: list[tuple[str, str]] = []
    for name in names:
        m = re.match(r"^(.*?)(SDA)(.*)$", name, re.I)
        if not m:
            continue
        partner = f"{m.group(1)}SCL{m.group(3)}"
        # match case-insensitively but keep the exact stored strings
        for cand in names:
            if cand.upper() == partner.upper():
                pairs.append((name, cand))
                break
    if not pairs:
        return None
    return sorted(pairs)[0]


def _seed_swap_i2c_sda_scl(text: str, board_id: str) -> SeedOutcome:
    pair = _find_i2c_pair(text)
    if pair is None:
        return SeedOutcome(text, None, "no SDA/SCL net-label pair found")
    sda, scl = pair
    tmp = '"__SEED_I2C_TMP__"'
    new_text = text.replace(f'"{sda}"', tmp).replace(f'"{scl}"', f'"{sda}"').replace(tmp, f'"{scl}"')
    defect = GroundTruthDefect(
        defect_id=f"{board_id}:swap_i2c_sda_scl",
        type="swap_i2c_sda_scl",
        board_id=board_id,
        expected_agent="connectivity_erc",
        expected_severity="major",
        affected_refs=[],
        affected_nets=[sda, scl],
        description=f"I2C net labels swapped: {sda} <-> {scl}. SDA and SCL are crossed on the bus.",
    )
    return SeedOutcome(new_text, defect, None)


def _seed_remove_i2c_pullups(text: str, board_id: str) -> SeedOutcome:
    pair = _find_i2c_pair(text)
    if pair is None:
        return SeedOutcome(text, None, "no I2C bus (SDA/SCL) present, so no pull-ups to remove")
    candidates = []
    for start, end, block in _symbol_instances(text):
        ref = _prop(block, "Reference")
        val = _prop(block, "Value") or ""
        if ref and re.match(r"^R\d+$", ref) and _PULLUP_VALUE_RE.search(val):
            candidates.append((ref, val, start, end))
    if not candidates:
        return SeedOutcome(text, None, "I2C bus present but no pull-up-valued resistor to remove")
    # Remove up to two lowest-ref pull-up resistors; delete from the end so earlier
    # offsets stay valid.
    chosen = sorted(candidates, key=lambda c: _ref_sort_key(c[0]))[:2]
    new_text = text
    for ref, val, start, end in sorted(chosen, key=lambda c: c[2], reverse=True):
        new_text = _delete_block(new_text, start, end)
    refs = [c[0] for c in chosen]
    defect = GroundTruthDefect(
        defect_id=f"{board_id}:remove_i2c_pullups",
        type="remove_i2c_pullups",
        board_id=board_id,
        expected_agent="signal_integrity",
        expected_severity="major",
        affected_refs=refs,
        affected_nets=list(pair),
        description=f"I2C pull-up resistor(s) {', '.join(refs)} removed; {pair[0]}/{pair[1]} left floating.",
    )
    return SeedOutcome(new_text, defect, None)


def _rename_one_net(text: str, net: str, new_net: str) -> str:
    """Rename the first quoted occurrence of ``net`` to ``new_net``."""
    needle = f'"{net}"'
    idx = text.find(needle)
    if idx == -1:
        return text
    return text[:idx] + f'"{new_net}"' + text[idx + len(needle):]


def _seed_float_enable_pin(text: str, board_id: str) -> SeedOutcome:
    candidates = sorted(
        {n for n in _net_names(text) if _ENABLE_RE.match(n) and not _RAIL_RE.match(n)}
    )
    if not candidates:
        return SeedOutcome(text, None, "no enable/reset net label found")
    net = candidates[0]
    new_text = _rename_one_net(text, net, f"{net}{FLOAT_SUFFIX}")
    defect = GroundTruthDefect(
        defect_id=f"{board_id}:float_enable_pin",
        type="float_enable_pin",
        board_id=board_id,
        expected_agent="firmware_bringup",
        expected_severity="critical",
        affected_refs=[],
        affected_nets=[net],
        description=f"Enable/reset net '{net}' disconnected at one node; pin now floats and the part may not come out of reset.",
    )
    return SeedOutcome(new_text, defect, None)


def _power_rails(text: str) -> dict[str, int]:
    """Rail name -> number of power-symbol instances, for non-ground rails."""
    counts: dict[str, int] = {}
    for _, _, block in _symbol_instances(text):
        if '(lib_id "power:' not in block:
            continue
        val = _prop(block, "Value")
        if val and _RAIL_RE.match(val) and not _GROUND_RE.match(val):
            counts[val] = counts.get(val, 0) + 1
    return counts


def _seed_rename_rail_net(text: str, board_id: str) -> SeedOutcome:
    rails = _power_rails(text)
    if rails:
        # Prefer the most-instanced rail (renaming one node still leaves a rail).
        rail = sorted(rails, key=lambda r: (-rails[r], r))[0]
        source = "power symbol"
    else:
        labels = sorted({n for n in _net_names(text) if _RAIL_RE.match(n) and not _GROUND_RE.match(n)})
        if not labels:
            return SeedOutcome(text, None, "no non-ground power rail (symbol or label) found")
        rail = labels[0]
        source = "power label"
    new_text = _rename_one_net(text, rail, f"{rail}{FLOAT_SUFFIX}")
    if new_text == text:
        # power-symbol rails carry the name only in a Value property, not a quoted net
        m = re.search(rf'\(property "Value" "{re.escape(rail)}"', text)
        if m:
            new_text = text[: m.start()] + f'(property "Value" "{rail}{FLOAT_SUFFIX}"' + text[m.end():]
    if new_text == text:
        return SeedOutcome(text, None, f"rail {rail} found but no rewritable occurrence")
    defect = GroundTruthDefect(
        defect_id=f"{board_id}:rename_rail_net",
        type="rename_rail_net",
        board_id=board_id,
        expected_agent="power_integrity",
        expected_severity="critical",
        affected_refs=[],
        affected_nets=[rail],
        description=f"Power rail '{rail}' renamed at one {source} node; that pin no longer connects to the rail and floats.",
    )
    return SeedOutcome(new_text, defect, None)


_SEED_FUNCS = {
    "remove_decoupling_cap": _seed_remove_decoupling_cap,
    "swap_i2c_sda_scl": _seed_swap_i2c_sda_scl,
    "remove_i2c_pullups": _seed_remove_i2c_pullups,
    "float_enable_pin": _seed_float_enable_pin,
    "rename_rail_net": _seed_rename_rail_net,
}


# --------------------------------------------------------------------------- #
# public API                                                                  #
# --------------------------------------------------------------------------- #


def apply_defect(sch_text: str, defect_type: str, board_id: str) -> SeedOutcome:
    """Apply one seed transform to schematic text. Pure; never touches disk."""
    if defect_type not in _SEED_FUNCS:
        raise ValueError(f"unknown defect type {defect_type!r}; known: {list(SEED_TYPES)}")
    return _SEED_FUNCS[defect_type](sch_text, board_id)


def seed_board(
    spec: BoardSpec,
    *,
    clean_dir: Path,
    out_dir: Path,
    ground_truth_dir: Path,
    types: list[str] | None = None,
) -> list[GroundTruthDefect]:
    """Seed all applicable defects into a fresh mutated copy of ``spec``.

    Reads the clean board from ``clean_dir/<id>/``, writes a mutated copy to
    ``out_dir/<id>/``, and writes the ground-truth manifest to
    ``ground_truth_dir/<id>.json``. Skips are logged with a reason. Returns the
    list of defects that were actually applied.
    """
    types = list(types or SEED_TYPES)
    clean_board = spec.board_dir(clean_dir)
    sch = clean_board / spec.schematic
    if not sch.is_file():
        raise FileNotFoundError(f"clean schematic missing: {sch} (run corpus/fetch.py first)")

    mutated_board = spec.board_dir(out_dir)
    if mutated_board.exists():
        shutil.rmtree(mutated_board)
    shutil.copytree(clean_board, mutated_board)

    text = sch.read_text(encoding="utf-8")
    defects: list[GroundTruthDefect] = []
    for dtype in types:
        outcome = apply_defect(text, dtype, spec.id)
        if outcome.applied:
            text = outcome.text
            defects.append(outcome.defect)
            log.info("seeded %s on %s (%s)", dtype, spec.id, outcome.defect.defect_id)
        else:
            log.info("skip   %s on %s: %s", dtype, spec.id, outcome.skip_reason)

    (mutated_board / spec.schematic).write_text(text, encoding="utf-8")
    write_ground_truth(spec.id, defects, ground_truth_dir / f"{spec.id}.json")
    return defects


def write_ground_truth(board_id: str, defects: list[GroundTruthDefect], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "board_id": board_id,
        "defect_count": len(defects),
        "defects": [d.to_dict() for d in defects],
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_ground_truth(path: Path) -> list[GroundTruthDefect]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return [GroundTruthDefect.from_dict(d) for d in data["defects"]]
