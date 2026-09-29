from __future__ import annotations

import re

from univers.version_range import VersionRange

_PURL = re.compile(r"pkg:([a-z]+)/([^@?#]+)(?:@([^?#]+))?")


def split_purl(purl: str) -> tuple[str, str, str | None]:
    """Split a purl into its type, its versionless base and its version, if any.

    ``pkg:npm/p-limit@4.0.0`` gives ``("npm", "pkg:npm/p-limit", "4.0.0")``.
    Qualifiers and subpaths are dropped. Raises ``ValueError`` for a string
    that is not a purl.
    """
    match = _PURL.fullmatch(purl.split("?", 1)[0].split("#", 1)[0])
    if not match:
        raise ValueError(f"not a package purl: {purl!r}")
    package_type, name, version = match.groups()
    return package_type, f"pkg:{package_type}/{name}", version


def parse_affected(package_type: str, affected: str) -> VersionRange:
    """Parse a VERS range and require its scheme to be ``package_type``.

    Raises ``ValueError`` for a malformed range, an unknown scheme or a
    scheme that differs from the claim's purl type.
    """
    version_range = VersionRange.from_string(affected)
    if version_range.scheme != package_type:
        raise ValueError(
            f"affected range scheme {version_range.scheme!r} does not match purl type "
            f"{package_type!r}"
        )
    return version_range


def applies_to(package_type: str, claim_version: str, affected: str | None, version: str) -> bool:
    """Return whether a claim applies to ``version`` of its package.

    A claim applies to its own evidence-bound ``claim_version`` and to every
    version inside its optional VERS ``affected`` range, compared with the
    ecosystem's own ordering. A version or range the ecosystem cannot parse
    applies to nothing rather than raising.
    """
    if version == claim_version:
        return True
    if not affected:
        return False
    try:
        version_range = parse_affected(package_type, affected)
        # from_string returns a per-scheme subclass, and each one sets version_class.
        assert version_range.version_class is not None
        return version_range.version_class(version) in version_range
    except ValueError:
        return False
