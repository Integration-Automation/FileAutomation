"""Action allow/deny list applied by :mod:`tcp_server` / :mod:`http_server`.

Policies are configured at server start; every incoming payload is run through
:meth:`ActionACL.filter` before dispatch. If any referenced action is denied
the whole payload is rejected — partial execution would leave the caller in an
ambiguous state.

An action may carry other actions in its arguments: ``FA_execute_action`` takes
an action list, ``FA_pipeline_run`` a definition whose tasks name actions, the
scheduler and the triggers a list to run later. The ACL therefore checks every
registered action name that appears anywhere in the arguments, not only the
names at the top of the payload. A string argument that happens to equal a
registered action name is checked as that action: the cautious reading.

What the payload does not contain cannot be checked: an action list or a
pipeline definition named by a file path (``FA_execute_files``,
``FA_pipeline_run`` with a path) and a stored run that ``FA_pipeline_resume``
continues. Deny those actions for a client that must stay inside the list.
"""

from __future__ import annotations

from collections.abc import Container, Iterable, Iterator
from dataclasses import dataclass, field

from automation_file.exceptions import FileAutomationException


class ActionNotPermittedException(FileAutomationException):
    """Raised when a payload references an action the ACL forbids."""


def _registered_names() -> Container[str]:
    """Return the names the shared executor dispatches, which is what a server runs."""
    from automation_file.core.action_executor import executor

    return executor.registry.event_dict


def nested_action_names(arguments: object, known: Container[str]) -> Iterator[str]:
    """Yield every name of ``known`` found at any depth of ``arguments``.

    A name counts wherever it stands: as a list element, a mapping value or a
    mapping key. The walk is iterative, so nesting cannot exhaust the stack.
    """
    pending = [arguments]
    while pending:
        value = pending.pop()
        if isinstance(value, str):
            if value in known:
                yield value
        elif isinstance(value, dict):
            pending.extend(value.keys())
            pending.extend(value.values())
        elif isinstance(value, (list, tuple)):
            pending.extend(value)


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
        known = _registered_names()
        for entry in payload:
            if isinstance(entry, list) and entry and isinstance(entry[0], str):
                yield entry[0]
                yield from nested_action_names(entry[1:], known)
