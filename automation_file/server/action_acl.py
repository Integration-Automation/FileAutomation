"""Action allow/deny list applied by :mod:`tcp_server` / :mod:`http_server`.

Policies are configured at server start; every incoming payload is run through
:meth:`ActionACL.filter` before dispatch. If any referenced action is denied
the whole payload is rejected — partial execution would leave the caller in an
ambiguous state.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from automation_file.exceptions import FileAutomationException


class ActionNotPermittedException(FileAutomationException):
    """Raised when a payload references an action the ACL forbids."""


@dataclass(frozen=True)
class ActionACL:
    """Allow/deny list for inbound action names.

    * ``allowed`` — when non-empty, only names in this set are accepted.
      ``None`` (the default) disables the allowlist.
    * ``denied`` — names in this set are always rejected. Checked after
      ``allowed`` so an explicit deny overrides an allowlist match.
    """

    allowed: frozenset[str] | None = None
    denied: frozenset[str] = field(default_factory=frozenset)

    @classmethod
    def build(
        cls,
        allowed: Iterable[str] | None = None,
        denied: Iterable[str] | None = None,
    ) -> ActionACL:
        return cls(
            allowed=frozenset(allowed) if allowed is not None else None,
            denied=frozenset(denied or ()),
        )

    def is_allowed(self, name: str) -> bool:
        if name in self.denied:
            return False
        return self.allowed is None or name in self.allowed

    def enforce(self, payload: object) -> None:
        """Raise :class:`ActionNotPermittedException` if any action is denied."""
        for name in self._iter_names(payload):
            if not self.is_allowed(name):
                raise ActionNotPermittedException(f"action not permitted: {name}")

    @staticmethod
    def _iter_names(payload: object) -> Iterable[str]:
        if isinstance(payload, dict):
            payload = payload.get("actions", [])
        if not isinstance(payload, list):
            return
        for entry in payload:
            if isinstance(entry, list) and entry and isinstance(entry[0], str):
                yield entry[0]
