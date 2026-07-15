"""Review-session state machine with JSON persistence.

States (ARCHITECTURE.md "Review session lifecycle"):

    created → manifest → reviewing → negotiating → signed
       └────────┴────────────┴───────────┴──→ failed

``signed`` and ``failed`` are terminal. Every transition is validated against
``ALLOWED_TRANSITIONS`` and persisted immediately, so sessions survive a process
restart: the store reads session.json from disk on every ``get``.

Layout on disk (root from env ``BOARDROOM_SESSIONS_DIR``, default ``./sessions``):

    <root>/session_<id>/session.json   — the Session model
    <root>/session_<id>/review.json    — the signed review (NEGOTIATION_PROTOCOL.md §5)
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, Field

DEFAULT_SESSIONS_DIR = "./sessions"
SESSIONS_DIR_ENV = "BOARDROOM_SESSIONS_DIR"


class SessionState(str, Enum):
    CREATED = "created"
    MANIFEST = "manifest"
    REVIEWING = "reviewing"
    NEGOTIATING = "negotiating"
    SIGNED = "signed"
    FAILED = "failed"


#: The complete transition table. Anything not listed here raises InvalidTransition.
ALLOWED_TRANSITIONS: dict[SessionState, frozenset[SessionState]] = {
    SessionState.CREATED: frozenset({SessionState.MANIFEST, SessionState.FAILED}),
    SessionState.MANIFEST: frozenset({SessionState.REVIEWING, SessionState.FAILED}),
    SessionState.REVIEWING: frozenset({SessionState.NEGOTIATING, SessionState.FAILED}),
    SessionState.NEGOTIATING: frozenset({SessionState.SIGNED, SessionState.FAILED}),
    SessionState.SIGNED: frozenset(),
    SessionState.FAILED: frozenset(),
}

TERMINAL_STATES = frozenset({SessionState.SIGNED, SessionState.FAILED})


class InvalidTransition(RuntimeError):
    def __init__(self, current: SessionState, requested: SessionState):
        super().__init__(f"invalid transition: {current.value} → {requested.value}")
        self.current = current
        self.requested = requested


class UnknownSession(KeyError):
    def __init__(self, session_id: str):
        super().__init__(session_id)
        self.session_id = session_id


class ReviewNotReady(RuntimeError):
    """Raised when review.json is requested before the session is signed."""


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class Session(BaseModel):
    id: str
    project_path: str
    state: SessionState = SessionState.CREATED
    created_at: str = Field(default_factory=_utcnow)
    updated_at: str = Field(default_factory=_utcnow)
    manifest: dict | None = None
    progress: dict = Field(default_factory=dict)
    coverage_notes: list[dict] = Field(default_factory=list)
    error: str | None = None
    #: Append-only transition log — demo material and debugging aid.
    history: list[dict] = Field(default_factory=list)


class SessionStore:
    """JSON-on-disk session persistence. No database — 5-day build."""

    def __init__(self, root: str | Path | None = None):
        self.root = Path(
            root or os.environ.get(SESSIONS_DIR_ENV, DEFAULT_SESSIONS_DIR)
        )

    # -- paths -------------------------------------------------------------

    def session_dir(self, session_id: str) -> Path:
        return self.root / f"session_{session_id}"

    def _session_file(self, session_id: str) -> Path:
        return self.session_dir(session_id) / "session.json"

    def review_path(self, session_id: str) -> Path:
        return self.session_dir(session_id) / "review.json"

    # -- CRUD ----------------------------------------------------------------

    def create(self, project_path: str) -> Session:
        session = Session(id=uuid.uuid4().hex[:12], project_path=str(project_path))
        session.history.append(
            {"from": None, "to": session.state.value, "at": session.created_at}
        )
        self.save(session)
        return session

    def get(self, session_id: str) -> Session:
        """Always reads from disk — this is what makes restarts free."""
        path = self._session_file(session_id)
        if not path.exists():
            raise UnknownSession(session_id)
        return Session.model_validate_json(path.read_text(encoding="utf-8"))

    def list_ids(self) -> list[str]:
        if not self.root.exists():
            return []
        return sorted(
            p.name.removeprefix("session_")
            for p in self.root.iterdir()
            if p.is_dir() and (p / "session.json").exists()
        )

    def save(self, session: Session) -> None:
        session.updated_at = _utcnow()
        self._atomic_write(
            self._session_file(session.id),
            session.model_dump_json(indent=2),
        )

    # -- state machine ---------------------------------------------------------

    def transition(
        self,
        session: Session,
        new_state: SessionState,
        *,
        error: str | None = None,
    ) -> Session:
        if new_state not in ALLOWED_TRANSITIONS[session.state]:
            raise InvalidTransition(session.state, new_state)
        session.history.append(
            {
                "from": session.state.value,
                "to": new_state.value,
                "at": _utcnow(),
                **({"error": error} if error else {}),
            }
        )
        session.state = new_state
        if error is not None:
            session.error = error
        self.save(session)
        return session

    def fail(self, session_id: str, error: str) -> Session:
        session = self.get(session_id)
        if session.state in TERMINAL_STATES:
            return session  # nothing to do; never raise from the failure path
        return self.transition(session, SessionState.FAILED, error=error)

    # -- review ---------------------------------------------------------------

    def write_review(self, session_id: str, review: dict) -> Path:
        path = self.review_path(session_id)
        self._atomic_write(path, json.dumps(review, indent=2))
        return path

    def read_review(self, session_id: str) -> dict:
        session = self.get(session_id)  # raises UnknownSession
        path = self.review_path(session_id)
        if session.state is not SessionState.SIGNED or not path.exists():
            raise ReviewNotReady(
                f"session {session_id} is '{session.state.value}', not 'signed'"
            )
        return json.loads(path.read_text(encoding="utf-8"))

    # -- internals --------------------------------------------------------------

    @staticmethod
    def _atomic_write(path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)
