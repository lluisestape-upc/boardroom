"""State machine transitions + JSON persistence round-trip."""

import pytest

from backend.app.sessions import (
    ALLOWED_TRANSITIONS,
    InvalidTransition,
    ReviewNotReady,
    SessionState,
    SessionStore,
    UnknownSession,
)


@pytest.fixture
def store(tmp_path):
    return SessionStore(tmp_path / "sessions")


HAPPY_PATH = [
    SessionState.MANIFEST,
    SessionState.REVIEWING,
    SessionState.NEGOTIATING,
    SessionState.SIGNED,
]


def test_happy_path_transitions(store):
    session = store.create("C:/some/project")
    assert session.state is SessionState.CREATED
    for state in HAPPY_PATH:
        session = store.transition(session, state)
    assert session.state is SessionState.SIGNED
    # history logs created + 4 transitions
    assert [h["to"] for h in session.history] == ["created"] + [s.value for s in HAPPY_PATH]


@pytest.mark.parametrize(
    "skip_to",
    [SessionState.REVIEWING, SessionState.NEGOTIATING, SessionState.SIGNED],
)
def test_skipping_states_is_rejected(store, skip_to):
    session = store.create("p")
    with pytest.raises(InvalidTransition):
        store.transition(session, skip_to)


@pytest.mark.parametrize(
    "state",
    [s for s, allowed in ALLOWED_TRANSITIONS.items() if SessionState.FAILED in allowed],
)
def test_every_nonterminal_state_can_fail(store, state):
    session = store.create("p")
    session.state = state  # force-position, then transition through the store
    session = store.transition(session, SessionState.FAILED, error="boom")
    assert session.state is SessionState.FAILED
    assert session.error == "boom"


@pytest.mark.parametrize("terminal", [SessionState.SIGNED, SessionState.FAILED])
def test_terminal_states_reject_all_transitions(store, terminal):
    session = store.create("p")
    session.state = terminal
    for target in SessionState:
        with pytest.raises(InvalidTransition):
            store.transition(session, target)


def test_persistence_round_trip_survives_restart(store, tmp_path):
    session = store.create("C:/kicad/proj")
    store.transition(session, SessionState.MANIFEST)
    session.manifest = {"kicad_files": ["a.kicad_pcb"]}
    session.progress = {"specialists_total": 2}
    store.save(session)

    # simulate process restart: brand-new store over the same directory
    reborn = SessionStore(tmp_path / "sessions")
    loaded = reborn.get(session.id)
    assert loaded.id == session.id
    assert loaded.state is SessionState.MANIFEST
    assert loaded.manifest == {"kicad_files": ["a.kicad_pcb"]}
    assert loaded.progress == {"specialists_total": 2}
    assert loaded.history[-1]["to"] == "manifest"
    assert reborn.list_ids() == [session.id]


def test_get_unknown_session_raises(store):
    with pytest.raises(UnknownSession):
        store.get("nope")


def test_fail_is_idempotent_on_terminal_sessions(store):
    session = store.create("p")
    for state in HAPPY_PATH:
        session = store.transition(session, state)
    # failing a signed session is a no-op, never an exception
    result = store.fail(session.id, "too late")
    assert result.state is SessionState.SIGNED
    assert result.error is None


def test_review_not_ready_until_signed(store):
    session = store.create("p")
    store.write_review(session.id, {"findings": []})
    with pytest.raises(ReviewNotReady):
        store.read_review(session.id)  # review file exists but state != signed
    for state in HAPPY_PATH:
        session = store.transition(session, state)
    assert store.read_review(session.id) == {"findings": []}


def test_sessions_dir_from_env(monkeypatch, tmp_path):
    monkeypatch.setenv("BOARDROOM_SESSIONS_DIR", str(tmp_path / "envdir"))
    store = SessionStore()
    session = store.create("p")
    assert (tmp_path / "envdir" / f"session_{session.id}" / "session.json").exists()
