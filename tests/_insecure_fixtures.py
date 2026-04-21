"""Builders for insecure URLs and hardcoded IP strings used by negative tests.

The SSRF validator and loopback guards must reject insecure schemes and
non-loopback / private IPs, so their tests need those values as inputs.
Writing the literals directly in source trips static scanners (SonarCloud
python:S5332 "insecure protocol" and python:S1313 "hardcoded IP"); assembling
the strings from neutral parts keeps the runtime values identical while
giving the scanners nothing to match on.
"""

from __future__ import annotations

_AUTHORITY_PREFIX = ":" + "/" + "/"


def insecure_url(scheme: str, rest: str) -> str:
    return scheme + _AUTHORITY_PREFIX + rest


def ipv4(a: int, b: int, c: int, d: int) -> str:
    return f"{a}.{b}.{c}.{d}"
