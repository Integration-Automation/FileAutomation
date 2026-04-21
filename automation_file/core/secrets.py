"""Secret provider abstraction.

A secret is a (name -> value) lookup. Three built-in providers compose via
:class:`ChainedSecretProvider`:

    - :class:`EnvSecretProvider` resolves from ``os.environ``
    - :class:`FileSecretProvider` resolves from a directory of per-secret files
      (Docker / K8s secrets layout)
    - :class:`ChainedSecretProvider` tries a list in order

The purpose is to keep secrets out of the config file itself. Callers
write references like ``${env:SLACK_WEBHOOK_URL}`` inside
``automation_file.toml``; :func:`resolve_secret_refs` walks the document
and substitutes. Missing secrets raise :class:`SecretNotFoundException`
so a typo in a reference never silently becomes an empty string.
"""

from __future__ import annotations

import os
import re
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from automation_file.exceptions import FileAutomationException
from automation_file.logging_config import file_automation_logger

_SECRET_PATTERN = re.compile(r"\$\{(env|file):([^}]+)\}")


class SecretException(FileAutomationException):
    """Base for secret-provider failures."""


class SecretNotFoundException(SecretException):
    """Raised when a ``${provider:name}`` reference cannot be resolved."""


class SecretProvider(ABC):
    """Contract for a read-only secret lookup."""

    scheme: str

    @abstractmethod
    def get(self, name: str) -> str | None:
        """Return the secret's value, or ``None`` if this provider has no entry."""


class EnvSecretProvider(SecretProvider):
    """Read secrets from process environment variables."""

    scheme = "env"

    def get(self, name: str) -> str | None:
        return os.environ.get(name)


class FileSecretProvider(SecretProvider):
    """Read secrets from ``<root>/<name>`` (e.g., ``/run/secrets/<name>``)."""

    scheme = "file"

    def __init__(self, root: str | os.PathLike[str]) -> None:
        self._root = Path(root)

    def get(self, name: str) -> str | None:
        candidate = self._root / name
        if not candidate.is_file():
            return None
        try:
            return candidate.read_text(encoding="utf-8").rstrip("\r\n")
        except OSError as err:
            file_automation_logger.warning("FileSecretProvider: read %s failed: %r", candidate, err)
            return None


class ChainedSecretProvider(SecretProvider):
    """Try each child provider in order; return the first non-``None`` value.

    Providers are grouped by ``scheme`` — ``${env:X}`` only consults
    :class:`EnvSecretProvider` children, ``${file:X}`` only consults
    :class:`FileSecretProvider` children. Unknown schemes raise
    :class:`SecretNotFoundException` at resolution time.
    """

    scheme = "*"

    def __init__(self, providers: list[SecretProvider]) -> None:
        self._providers = list(providers)

    def get(self, name: str) -> str | None:
        # Default: consult every child regardless of scheme. Callers who
        # want scheme-scoped lookup should go through resolve_one().
        for provider in self._providers:
            value = provider.get(name)
            if value is not None:
                return value
        return None

    def resolve_one(self, scheme: str, name: str) -> str:
        for provider in self._providers:
            if provider.scheme not in (scheme, "*"):
                continue
            value = provider.get(name)
            if value is not None:
                return value
        raise SecretNotFoundException(f"no secret for ${{{scheme}:{name}}}")


def resolve_secret_refs(value: Any, provider: ChainedSecretProvider) -> Any:
    """Walk ``value`` (dict/list/str) and substitute every ``${scheme:name}``.

    Strings without references are returned unchanged; non-string scalars
    pass through untouched. Any unresolved reference raises
    :class:`SecretNotFoundException` — callers should treat this as a hard
    configuration error rather than continuing with a hole in the config.
    """
    if isinstance(value, str):
        return _resolve_string(value, provider)
    if isinstance(value, dict):
        return {key: resolve_secret_refs(item, provider) for key, item in value.items()}
    if isinstance(value, list):
        return [resolve_secret_refs(item, provider) for item in value]
    return value


def _resolve_string(text: str, provider: ChainedSecretProvider) -> str:
    def substitute(match: re.Match[str]) -> str:
        scheme, name = match.group(1), match.group(2).strip()
        return provider.resolve_one(scheme, name)

    return _SECRET_PATTERN.sub(substitute, text)


def default_provider(file_root: str | os.PathLike[str] | None = None) -> ChainedSecretProvider:
    """Return an env-first chain, optionally augmented with a file provider."""
    providers: list[SecretProvider] = [EnvSecretProvider()]
    if file_root is not None:
        providers.append(FileSecretProvider(file_root))
    return ChainedSecretProvider(providers)
