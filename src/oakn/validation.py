from __future__ import annotations

import hashlib
import json
import re
import tomllib
import uuid
from collections.abc import Callable, Iterable
from datetime import date
from typing import Any
from urllib.parse import urlparse

import requests
from defusedxml import ElementTree as element_tree

from .versions import parse_affected


class ValidationError(ValueError):
    """A claim or contribution crosses an OAKN trust boundary."""


Fetch = Callable[[str], bytes]

_REQUIRED_TOP_LEVEL = {
    "schema_version",
    "id",
    "package",
    "claim_type",
    "summary",
    "conditions",
    "evidence",
    "provenance",
    "verification",
    "license",
    "lifecycle",
}
_ALLOWED_CLAIM_TYPES = {
    "API_BEHAVIOR",
    "CONFIGURATION",
    "MIGRATION",
    "BREAKING_CHANGE",
    "DOCUMENTED_BUG",
    "WORKAROUND",
    "SDK_CLI_BEHAVIOR",
}
_ALLOWED_STATES = {
    "verified",
    "asserted",
    "not_run",
    "current_at_creation",
    "none_known",
    "unknown",
}
_ALLOWED_HOSTS = {"github.com", "raw.githubusercontent.com"}
_GO_PROXY_HOST = "proxy.golang.org"
_SECRET_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key|secret|token|password)\s*[:=]\s*[^\s]{4,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9_]{20,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
]
_INSTRUCTION_PATTERNS = [
    re.compile(r"(?i)ignore (all |any |the )?previous instructions"),
    re.compile(r"(?i)(upload|send|exfiltrate).{0,80}(file|secret|environment|ssh)"),
    re.compile(r"(?i)read\s+~?/?\.ssh"),
]


_FETCH_ALLOWED_HOSTS = {"raw.githubusercontent.com", _GO_PROXY_HOST}


def _network_fetch(url: str) -> bytes:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in _FETCH_ALLOWED_HOSTS:
        raise ValidationError(
            "source fetch is restricted to immutable GitHub raw content "
            "or the public Go module proxy"
        )
    response = requests.get(url, timeout=15, allow_redirects=False)
    if response.status_code != 200:
        raise OSError(f"source fetch returned HTTP {response.status_code}")
    return response.content


def _all_strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from _all_strings(key)
            yield from _all_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _all_strings(item)


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _go_proxy_info_url(module_path: str, version: str) -> str:
    escaped_path = "".join(f"!{c.lower()}" if c.isupper() else c for c in module_path)
    escaped_version = "".join(f"!{c.lower()}" if c.isupper() else c for c in version)
    return f"https://{_GO_PROXY_HOST}/{escaped_path}/@v/{escaped_version}.info"


def _safe_go_proxy_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != _GO_PROXY_HOST:
        raise ValidationError("go module version must be verified via the public Go proxy")
    if parsed.username or parsed.password or parsed.port:
        raise ValidationError("go proxy URL may not contain credentials or a port")


def _raw_github_url(repository: str, commit_sha: str, path: str) -> str:
    parsed = urlparse(repository)
    repo_path = parsed.path.strip("/")
    return f"https://raw.githubusercontent.com/{repo_path}/{commit_sha}/{path}"


def _safe_source_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in _ALLOWED_HOSTS:
        raise ValidationError("source must be a public HTTPS GitHub URL")
    if parsed.username or parsed.password or parsed.port:
        raise ValidationError("source URL may not contain credentials or a port")


def _package_from_purl(purl: str) -> tuple[str, str, str]:
    match = re.fullmatch(r"pkg:(npm|maven|cargo|pypi|golang)/([^@?#]+)@([^?#]+)", purl)
    if not match:
        raise ValidationError(
            "package.purl must be an exact npm, maven, cargo, pypi or golang purl"
        )
    return match.group(1), match.group(2), match.group(3)


def _normalize_pypi_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _manifest_matches(package_type: str, name: str, version: str, manifest: bytes) -> bool:
    if package_type == "npm":
        payload = json.loads(manifest)
        return payload.get("name") == name and payload.get("version") == version
    if package_type == "cargo":
        payload = tomllib.loads(manifest.decode("utf-8"))
        package = payload.get("package", {})
        return package.get("name") == name and package.get("version") == version
    if package_type == "pypi":
        payload = tomllib.loads(manifest.decode("utf-8"))
        project = payload.get("project", {})
        manifest_name = project.get("name")
        return (
            isinstance(manifest_name, str)
            and _normalize_pypi_name(manifest_name) == _normalize_pypi_name(name)
            and project.get("version") == version
        )
    if package_type == "golang":
        # go.mod carries no version field; only the module path is verifiable
        # from the manifest itself. The claimed version is independently
        # verified against the Go module proxy's checksummed @v/<version>.info
        # endpoint in ClaimValidator._validate_evidence.
        declared = re.search(r"(?m)^module\s+(\S+)", manifest.decode("utf-8"))
        return declared is not None and declared.group(1) == name
    root = element_tree.fromstring(manifest)
    namespace = "{http://maven.apache.org/POM/4.0.0}"

    def _findtext(tag: str) -> str | None:
        return root.findtext(f"{namespace}{tag}") or root.findtext(tag)

    def _find_parent_text(tag: str) -> str | None:
        parent = root.find(f"{namespace}parent") or root.find("parent")
        if parent is None:
            return None
        return parent.findtext(f"{namespace}{tag}") or parent.findtext(tag)

    # Maven's own inheritance model lets a module's pom.xml omit <groupId>
    # and/or <version> at the top level and inherit them from its <parent>
    # instead -- a very common idiom for multi-module projects (e.g.
    # org.apache.commons:commons-text inherits <groupId> from its
    # commons-parent, while declaring its own <artifactId>/<version>).
    # Falling back to the parent's values mirrors what Maven itself does
    # when resolving the effective groupId/version.
    group = _findtext("groupId") or _find_parent_text("groupId")
    artifact = _findtext("artifactId")
    pom_version = _findtext("version") or _find_parent_text("version")
    return f"{group}/{artifact}" == name and pom_version == version


class ClaimValidator:
    """Validates untrusted claims without executing their content."""

    def __init__(self, fetch: Fetch | None = None) -> None:
        self._fetch = fetch or _network_fetch

    def validate(self, claim: dict[str, Any], verify_source_binding: bool = True) -> None:
        if not isinstance(claim, dict) or set(claim) != _REQUIRED_TOP_LEVEL:
            raise ValidationError("claim must contain exactly the canonical top-level fields")
        if claim["schema_version"] != 1:
            raise ValidationError("unsupported schema_version")
        try:
            uuid.UUID(claim["id"])
        except (ValueError, TypeError) as error:
            raise ValidationError("id must be a UUID") from error
        if claim["claim_type"] not in _ALLOWED_CLAIM_TYPES:
            raise ValidationError("unsupported claim_type")
        if not isinstance(claim["summary"], str) or not 1 <= len(claim["summary"]) <= 500:
            raise ValidationError("summary must be between 1 and 500 characters")
        if not isinstance(claim["conditions"], list) or not all(
            isinstance(item, str) for item in claim["conditions"]
        ):
            raise ValidationError("conditions must be a list of strings")
        if not isinstance(claim["package"], dict):
            raise ValidationError("package must be an object")
        package_type, package_name, purl_version = _package_from_purl(
            claim["package"].get("purl", "")
        )
        if claim["package"].get("version") != purl_version:
            raise ValidationError("package.version must exactly match package.purl")
        self._validate_affected(claim["package"], package_type)
        self._validate_text_safety(claim)
        self._validate_lifecycle(claim)
        self._validate_license(claim)
        self._validate_states(claim)
        self._validate_provenance(claim)
        self._validate_evidence(
            claim, package_type, package_name, purl_version, verify_source_binding
        )

    def _validate_affected(self, package: dict[str, Any], package_type: str) -> None:
        if not set(package) <= {"purl", "version", "affected"}:
            raise ValidationError("package may contain only purl, version and affected")
        if "affected" not in package:
            return
        affected = package["affected"]
        if not isinstance(affected, str) or len(affected) > 200:
            raise ValidationError(
                "package.affected must be a VERS string of at most 200 characters"
            )
        try:
            parse_affected(package_type, affected)
        except ValueError as error:
            raise ValidationError(f"package.affected is not a valid VERS range: {error}") from error

    def _validate_text_safety(self, claim: dict[str, Any]) -> None:
        for text in _all_strings(claim):
            if len(text) > 2000:
                raise ValidationError("claim text exceeds facts-only size limit")
            if any(pattern.search(text) for pattern in _SECRET_PATTERNS):
                raise ValidationError("claim contains a secret-like value")
            if any(pattern.search(text) for pattern in _INSTRUCTION_PATTERNS):
                raise ValidationError("claim contains instruction-like content")

    def _validate_lifecycle(self, claim: dict[str, Any]) -> None:
        lifecycle = claim["lifecycle"]
        if not isinstance(lifecycle, dict) or lifecycle.get("state") != "active":
            raise ValidationError("only active immutable claims are accepted")
        try:
            date.fromisoformat(lifecycle["created_at"])
        except (KeyError, TypeError, ValueError) as error:
            raise ValidationError("lifecycle.created_at must be an ISO date") from error
        supersedes = lifecycle.get("supersedes")
        if supersedes is not None:
            try:
                uuid.UUID(supersedes)
            except (ValueError, TypeError) as error:
                raise ValidationError("lifecycle.supersedes must be a UUID") from error

    def _validate_license(self, claim: dict[str, Any]) -> None:
        license_data = claim["license"]
        if not isinstance(license_data, dict) or not isinstance(license_data.get("verbatim"), bool):
            raise ValidationError("license must declare source_license and verbatim")
        source_license = license_data.get("source_license")
        if not isinstance(source_license, str) or not source_license:
            raise ValidationError("license.source_license is required")
        if source_license == "unknown" and license_data["verbatim"]:
            raise ValidationError("unknown licenses permit facts only")
        if license_data["verbatim"] and source_license not in {
            "MIT",
            "Apache-2.0",
            "BSD-2-Clause",
            "BSD-3-Clause",
        }:
            raise ValidationError("verbatim content requires a compatible source license")

    def _validate_states(self, claim: dict[str, Any]) -> None:
        verification = claim["verification"]
        expected = {
            "source_binding",
            "source_authority",
            "semantic_support",
            "executable_verification",
            "freshness",
            "contradictions",
        }
        if not isinstance(verification, dict) or set(verification) != expected:
            raise ValidationError("verification must retain independent evidence dimensions")
        if not all(value in _ALLOWED_STATES for value in verification.values()):
            raise ValidationError("unknown verification state")

    def _validate_provenance(self, claim: dict[str, Any]) -> None:
        provenance = claim["provenance"]
        if not isinstance(provenance, dict):
            raise ValidationError("provenance must be an object")
        source_url = provenance.get("source_url")
        if not isinstance(source_url, str):
            raise ValidationError("provenance.source_url is required")
        _safe_source_url(source_url)
        if provenance.get("source_authority") not in {"official", "maintainer"}:
            raise ValidationError("source authority must be official or maintainer")
        try:
            date.fromisoformat(provenance["retrieved_at"])
        except (KeyError, TypeError, ValueError) as error:
            raise ValidationError("provenance.retrieved_at must be an ISO date") from error

    def _validate_evidence(
        self,
        claim: dict[str, Any],
        package_type: str,
        package_name: str,
        version: str,
        verify_source_binding: bool,
    ) -> None:
        evidence_items = claim["evidence"]
        if not isinstance(evidence_items, list) or not evidence_items:
            raise ValidationError("at least one evidence item is required")
        for evidence in evidence_items:
            if not isinstance(evidence, dict) or evidence.get("kind") != "git":
                raise ValidationError("MVP evidence must be Git evidence")
            repository = evidence.get("repository")
            commit_sha = evidence.get("commit_sha")
            source_path = evidence.get("path")
            content_hash = evidence.get("content_sha256")
            if not isinstance(repository, str):
                raise ValidationError("evidence.repository is required")
            _safe_source_url(repository)
            if not isinstance(commit_sha, str) or not re.fullmatch(r"[0-9a-f]{40}", commit_sha):
                raise ValidationError("evidence.commit_sha must be an immutable lowercase SHA-1")
            if (
                not isinstance(source_path, str)
                or source_path.startswith("/")
                or ".." in source_path.split("/")
            ):
                raise ValidationError("evidence.path must be a safe repository-relative path")
            if not isinstance(content_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", content_hash):
                raise ValidationError("evidence.content_sha256 must be SHA-256")
            manifest = evidence.get("package_manifest")
            if not isinstance(manifest, dict):
                raise ValidationError("Git evidence requires package_manifest binding")
            manifest_path = manifest.get("path")
            manifest_hash = manifest.get("content_sha256")
            if (
                not isinstance(manifest_path, str)
                or manifest_path.startswith("/")
                or ".." in manifest_path.split("/")
                or not isinstance(manifest_hash, str)
                or not re.fullmatch(r"[0-9a-f]{64}", manifest_hash)
            ):
                raise ValidationError(
                    "package_manifest requires a safe path and SHA-256 content hash"
                )
            if verify_source_binding:
                try:
                    source_bytes = self._fetch(_raw_github_url(repository, commit_sha, source_path))
                    manifest_bytes = self._fetch(
                        _raw_github_url(repository, commit_sha, manifest_path)
                    )
                except OSError as error:
                    raise ValidationError("immutable public source could not be fetched") from error
                if _sha256(source_bytes) != content_hash:
                    raise ValidationError("source content hash does not bind the immutable source")
                if _sha256(manifest_bytes) != manifest_hash:
                    raise ValidationError(
                        "package manifest hash does not bind the immutable source"
                    )
                try:
                    matches = _manifest_matches(package_type, package_name, version, manifest_bytes)
                except (json.JSONDecodeError, element_tree.ParseError) as error:
                    raise ValidationError("package manifest is not parseable") from error
                if not matches:
                    raise ValidationError(
                        "package name or exact version does not match public manifest"
                    )
                if package_type == "golang":
                    self._verify_go_module_version(package_name, version)

    def _verify_go_module_version(self, module_path: str, version: str) -> None:
        # go.mod has no version field, so the claimed version is verified
        # independently against the Go module proxy: proxy.golang.org serves
        # an immutable, checksum-addressed .info document per module@version
        # (see https://proxy.golang.org/, GOPROXY protocol) rather than
        # trusting the claim author's stated version.
        proxy_url = _go_proxy_info_url(module_path, version)
        _safe_go_proxy_url(proxy_url)
        try:
            info_bytes = self._fetch(proxy_url)
        except OSError as error:
            raise ValidationError("go module version could not be verified via proxy") from error
        try:
            info = json.loads(info_bytes)
        except json.JSONDecodeError as error:
            raise ValidationError("go proxy version info is not parseable") from error
        if info.get("Version") != version:
            raise ValidationError("go proxy does not confirm the claimed module version")


def validate_contribution_paths(changes: Iterable[tuple[str, str]]) -> str:
    """Return the only permitted added data path or reject untrusted changes."""
    changes = list(changes)
    if len(changes) != 1:
        raise ValidationError("a contribution must change exactly one claim data file")
    status, path = changes[0]
    if status != "A" or not re.fullmatch(r"knowledge/claims/[0-9a-f-]{36}\.json", path):
        raise ValidationError("contributions may only add knowledge/claims/<uuid>.json")
    return path
