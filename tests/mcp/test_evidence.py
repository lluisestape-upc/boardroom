"""Evidence cache: stable ids, dedup, lookup, and the no-evidence-on-failure rule."""

from __future__ import annotations

import pytest

import samples
from mcp.adapters import run_tool
from mcp.errors import EvidenceNotFoundError, ToolExecutionError
from mcp.evidence import EvidenceCache, canonical_key


def test_put_assigns_sequential_stable_ids(cache):
    e1 = cache.put("run_erc", {"schematic_path": "a.kicad_sch"}, raw="r1", summary="s1")
    e2 = cache.put("run_drc", {"pcb_path": "b.kicad_pcb"}, raw="r2", summary="s2")
    assert e1.evidence_id == "EV-0001"
    assert e2.evidence_id == "EV-0002"
    assert len(cache) == 2


def test_put_is_idempotent_for_same_call(cache):
    args = {"schematic_path": "a.kicad_sch"}
    e1 = cache.put("run_erc", args, raw="r", summary="s")
    e2 = cache.put("run_erc", args, raw="different raw", summary="different")
    assert e2.evidence_id == e1.evidence_id
    assert e2.raw == "r"  # first write wins; ids stay stable within a session
    assert len(cache) == 1


def test_canonical_key_is_arg_order_insensitive():
    k1 = canonical_key("t", {"a": 1, "b": 2})
    k2 = canonical_key("t", {"b": 2, "a": 1})
    assert k1 == k2


def test_get_counts_hits_and_misses(cache):
    args = {"schematic_path": "a.kicad_sch"}
    assert cache.get("run_erc", args) is None
    cache.put("run_erc", args, raw="r", summary="s")
    assert cache.get("run_erc", args) is not None
    assert cache.stats() == {"entries": 1, "hits": 1, "misses": 1}


def test_lookup_unknown_id_raises(cache):
    with pytest.raises(EvidenceNotFoundError):
        cache.lookup("EV-9999")


def test_contains_and_entries_order(cache):
    e1 = cache.put("run_erc", {"schematic_path": "a.kicad_sch"}, raw="r", summary="s")
    e2 = cache.put("run_drc", {"pcb_path": "b.kicad_pcb"}, raw="r", summary="s")
    assert e1.evidence_id in cache
    assert [e.evidence_id for e in cache.entries()] == [e1.evidence_id, e2.evidence_id]


def test_as_finding_evidence_shape_matches_schema(cache):
    entry = cache.put("run_erc", {"schematic_path": "a.kicad_sch"}, raw="r", summary="neutral")
    item = entry.as_finding_evidence()
    assert set(item) == {"evidence_id", "tool", "summary"}
    claim_specific = entry.as_finding_evidence("2 unconnected pins on U3")
    assert claim_specific["summary"] == "2 unconnected pins on U3"
    assert claim_specific["evidence_id"] == entry.evidence_id


@pytest.mark.asyncio
async def test_run_tool_dedups_identical_calls(fake_session, cache):
    args = {"schematic_path": "C:/boards/demo/demo.kicad_sch"}
    first = await run_tool(fake_session, cache, "run_erc", args)
    second = await run_tool(fake_session, cache, "run_erc", args)
    assert not first.cached and second.cached
    assert second.evidence.evidence_id == first.evidence.evidence_id
    assert fake_session.call_count("run_erc") == 1  # one server round-trip only
    assert cache.stats()["entries"] == 1


@pytest.mark.asyncio
async def test_failed_tool_call_produces_no_evidence(cache):
    from fake_kicad import FakeKicadSession

    session = FakeKicadSession(mcp_error_tools={"run_erc"})
    with pytest.raises(ToolExecutionError):
        await run_tool(
            session, cache, "run_erc", {"schematic_path": "C:/boards/demo/demo.kicad_sch"}
        )
    assert len(cache) == 0  # failures are never citable

    # A later retry is not poisoned by a cached failure.
    session.mcp_error_tools.clear()
    outcome = await run_tool(
        session, cache, "run_erc", {"schematic_path": "C:/boards/demo/demo.kicad_sch"}
    )
    assert not outcome.cached
    assert outcome.evidence.evidence_id == "EV-0001"
