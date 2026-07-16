"""Seed applicability, determinism, and ground-truth correctness."""

from __future__ import annotations

import re

import pytest

from benchmark.seed import (
    SEED_TYPES,
    GroundTruthDefect,
    apply_defect,
    load_ground_truth,
    seed_board,
)


# --------------------------------------------------------------------------- #
# applicability                                                               #
# --------------------------------------------------------------------------- #


def test_stickhub_applies_decoupling_cap(stickhub_sch_text):
    out = apply_defect(stickhub_sch_text, "remove_decoupling_cap", "stickhub")
    assert out.applied
    assert out.defect.type == "remove_decoupling_cap"
    assert out.defect.affected_refs and out.defect.affected_refs[0].startswith("C")
    assert out.text != stickhub_sch_text


@pytest.mark.parametrize(
    "dtype,reason_substr",
    [
        ("swap_i2c_sda_scl", "SDA/SCL"),
        ("remove_i2c_pullups", "I2C"),
        ("float_enable_pin", "enable/reset"),
        ("rename_rail_net", "power rail"),
    ],
)
def test_stickhub_skips_inapplicable_with_reason(stickhub_sch_text, dtype, reason_substr):
    out = apply_defect(stickhub_sch_text, dtype, "stickhub")
    assert not out.applied
    assert out.defect is None
    assert out.skip_reason and reason_substr in out.skip_reason
    assert out.text == stickhub_sch_text  # skip leaves text untouched


def test_unknown_defect_type_raises(stickhub_sch_text):
    with pytest.raises(ValueError):
        apply_defect(stickhub_sch_text, "not_a_real_seed", "stickhub")


# --------------------------------------------------------------------------- #
# determinism                                                                 #
# --------------------------------------------------------------------------- #


def test_apply_defect_is_byte_deterministic(stickhub_sch_text):
    a = apply_defect(stickhub_sch_text, "remove_decoupling_cap", "stickhub")
    b = apply_defect(stickhub_sch_text, "remove_decoupling_cap", "stickhub")
    assert a.text == b.text
    assert a.defect.to_dict() == b.defect.to_dict()


def test_seed_board_is_byte_deterministic(stickhub_spec, clean_dir, tmp_path):
    out1 = tmp_path / "s1"
    out2 = tmp_path / "s2"
    gt1 = tmp_path / "gt1"
    gt2 = tmp_path / "gt2"
    d1 = seed_board(stickhub_spec, clean_dir=clean_dir, out_dir=out1, ground_truth_dir=gt1)
    d2 = seed_board(stickhub_spec, clean_dir=clean_dir, out_dir=out2, ground_truth_dir=gt2)

    sch1 = stickhub_spec.schematic_path(out1).read_bytes()
    sch2 = stickhub_spec.schematic_path(out2).read_bytes()
    assert sch1 == sch2
    assert [d.to_dict() for d in d1] == [d.to_dict() for d in d2]
    # ground-truth json is identical too
    assert (gt1 / "stickhub.json").read_bytes() == (gt2 / "stickhub.json").read_bytes()


# --------------------------------------------------------------------------- #
# ground-truth correctness                                                    #
# --------------------------------------------------------------------------- #


def test_seed_board_removes_the_recorded_cap(stickhub_spec, clean_dir, tmp_path):
    out = tmp_path / "seeded"
    gt = tmp_path / "gt"
    defects = seed_board(stickhub_spec, clean_dir=clean_dir, out_dir=out, ground_truth_dir=gt)

    cap_defects = [d for d in defects if d.type == "remove_decoupling_cap"]
    assert len(cap_defects) == 1
    ref = cap_defects[0].affected_refs[0]

    clean_text = stickhub_spec.schematic_path(clean_dir).read_text(encoding="utf-8")
    mutated_text = stickhub_spec.schematic_path(out).read_text(encoding="utf-8")

    ref_re = re.compile(rf'\(property "Reference" "{re.escape(ref)}"')
    assert ref_re.search(clean_text), "cap should exist in the clean board"
    assert not ref_re.search(mutated_text), "seeded cap must be removed from the mutated board"
    assert len(mutated_text) < len(clean_text)


def test_seed_board_writes_loadable_ground_truth(stickhub_spec, clean_dir, tmp_path):
    out = tmp_path / "seeded"
    gt = tmp_path / "gt"
    defects = seed_board(stickhub_spec, clean_dir=clean_dir, out_dir=out, ground_truth_dir=gt)

    loaded = load_ground_truth(gt / "stickhub.json")
    assert [d.to_dict() for d in loaded] == [d.to_dict() for d in defects]
    for d in loaded:
        assert isinstance(d, GroundTruthDefect)
        assert d.board_id == "stickhub"
        assert d.expected_agent in {
            "power_integrity",
            "signal_integrity",
            "connectivity_erc",
            "dfm_layout",
            "firmware_bringup",
            "moderator",
        }
        assert d.expected_severity in {"critical", "major", "minor", "info"}
        assert d.defect_id and d.description


def test_pcb_is_copied_alongside_mutated_schematic(stickhub_spec, clean_dir, tmp_path):
    out = tmp_path / "seeded"
    gt = tmp_path / "gt"
    seed_board(stickhub_spec, clean_dir=clean_dir, out_dir=out, ground_truth_dir=gt)
    assert stickhub_spec.pcb_path(out).is_file()
    # pcb is untouched (all seeds are schematic-level)
    assert stickhub_spec.pcb_path(out).read_bytes() == stickhub_spec.pcb_path(clean_dir).read_bytes()


def test_all_seed_types_covered_by_constant():
    assert set(SEED_TYPES) == {
        "remove_decoupling_cap",
        "swap_i2c_sda_scl",
        "remove_i2c_pullups",
        "float_enable_pin",
        "rename_rail_net",
    }
