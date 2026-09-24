from __future__ import annotations

import gzip
import hashlib
import json
import os
import shutil
import tempfile
import time
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urljoin, urlparse

import requests

from .index import ClaimIndex, IndexError
from .validation import ClaimValidator, ValidationError


def _fetch(url: str, allow_file_urls: bool = False, redirects: int = 0) -> bytes:
    if redirects > 3:
        raise ValidationError("release redirect limit exceeded")
    parsed = urlparse(url)
    if parsed.scheme == "file" and allow_file_urls:
        return Path(unquote(parsed.path)).read_bytes()
    allowed_hosts = {
        "github.com",
        "objects.githubusercontent.com",
        "github-releases.githubusercontent.com",
        "release-assets.githubusercontent.com",
    }
    if (
        parsed.scheme != "https"
        or parsed.hostname not in allowed_hosts
        or parsed.username
        or parsed.password
    ):
        raise ValidationError("release URL must be public HTTPS")
    response = requests.get(url, timeout=30, allow_redirects=False)
    if response.is_redirect:
        location = response.headers.get("Location")
        if not location:
            raise ValidationError("release redirect has no location")
        return _fetch(urljoin(url, location), allow_file_urls, redirects + 1)
    if response.status_code != 200:
        raise ValidationError(f"release fetch returned HTTP {response.status_code}")
    return response.content


def build_bundle(index_path: str | Path, release_directory: str | Path) -> Path:
    """Create a checksummed compressed derived-index bundle for a release."""
    index = Path(index_path)
    release = Path(release_directory)
    release.mkdir(parents=True, exist_ok=True)
    compressed = release / "index.sqlite.gz"
    with index.open("rb") as source, compressed.open("wb") as raw_destination:
        with gzip.GzipFile(fileobj=raw_destination, mode="wb", mtime=0) as destination:
            shutil.copyfileobj(source, destination)
    manifest = {
        "schema_version": 1,
        "artifact": compressed.name,
        "sha256": hashlib.sha256(compressed.read_bytes()).hexdigest(),
        "index_bytes": index.stat().st_size,
    }
    manifest_path = release / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest_path


def _terms(text: str) -> set[str]:
    return {item.lower() for item in text.replace("-", " ").split() if item.isalnum()}


class KnowledgeClient:
    """Local-first client boundary for untrusted OAKN claim data."""

    def __init__(
        self,
        index_path: str | Path,
        metrics_path: str | Path | None = None,
        allow_file_urls: bool = False,
    ) -> None:
        self.index_path = Path(index_path)
        self.metrics_path = (
            Path(metrics_path) if metrics_path else self.index_path.with_suffix(".metrics.json")
        )
        self.allow_file_urls = allow_file_urls

    def _metrics(self) -> Counter[str]:
        if not self.metrics_path.exists():
            return Counter()
        return Counter(json.loads(self.metrics_path.read_text()))

    def _save_metrics(self, metrics: Counter[str]) -> None:
        self.metrics_path.parent.mkdir(parents=True, exist_ok=True)
        self.metrics_path.write_text(json.dumps(dict(sorted(metrics.items())), indent=2) + "\n")

    def _record(self, **increments: int) -> dict[str, int]:
        metrics = self._metrics()
        metrics.update(increments)
        self._save_metrics(metrics)
        return dict(metrics)

    def metrics(self) -> dict[str, Any]:
        """Return local, derived effectiveness metrics without any network access."""
        recorded = self._metrics()
        searches = int(recorded["search_count"])
        hits = int(recorded["knowledge_hits"])
        misses = int(recorded["true_misses"])
        contribution_candidates = int(recorded["contribution_candidates"])
        contributions = int(recorded["contribution_count"])
        accepted_outcomes = int(recorded["accepted_outcome_count"])
        rejected_outcomes = int(recorded["rejected_outcome_count"])
        feedback_count = accepted_outcomes + rejected_outcomes
        index_size = self.index_path.stat().st_size if self.index_path.exists() else 0
        claim_count = ClaimIndex(self.index_path).count() if self.index_path.exists() else 0

        def ratio(numerator: int, denominator: int) -> float | None:
            return round(numerator / denominator, 4) if denominator else None

        return {
            "search_count": searches,
            "knowledge_hits": hits,
            "true_misses": misses,
            "knowledge_hit_rate": ratio(hits, searches),
            "true_miss_rate": ratio(misses, searches),
            "retrieval_precision": ratio(accepted_outcomes, feedback_count),
            "retrieval_precision_feedback_count": feedback_count,
            "accepted_outcome_count": accepted_outcomes,
            "rejected_outcome_count": rejected_outcomes,
            "average_retrieval_latency_ms": ratio(int(recorded["retrieval_latency_ms"]), searches),
            "contribution_count": contributions,
            "duplicate_candidate_count": int(recorded["duplicate_candidate_count"]),
            "duplicate_candidate_rate": ratio(
                int(recorded["duplicate_candidate_count"]), contribution_candidates
            ),
            "estimated_contribution_cost_units": ratio(
                int(recorded["contribution_tokens"]), contributions
            ),
            "retrieval_tokens": int(recorded["retrieval_tokens"]),
            "contribution_tokens": int(recorded["contribution_tokens"]),
            "estimated_research_tokens_avoided": int(recorded["research_tokens_avoided"]),
            "index_size_bytes": index_size,
            "claim_count": claim_count,
        }

    def record_outcome(self, claim_id: str, accepted: bool) -> dict[str, Any]:
        """Record explicit local applicability feedback for one indexed claim."""
        if not self.index_path.exists() or self._index().get(claim_id) is None:
            raise ValueError("outcome feedback requires an indexed claim")
        self._record(
            **({"accepted_outcome_count": 1} if accepted else {"rejected_outcome_count": 1})
        )
        return self.metrics()

    def _index(self) -> ClaimIndex:
        return ClaimIndex(self.index_path)

    def search(
        self, query: str, purl: str, version: str, topic: str | None = None
    ) -> dict[str, Any]:
        started = time.perf_counter()
        variants = [query, query.replace("-", " "), query.replace("configuration", "config")]
        results: list[dict[str, Any]] = []
        package_results: list[dict[str, Any]] = []
        if self.index_path.exists():
            index = ClaimIndex(self.index_path)
            for variant in dict.fromkeys(variants):
                results = index.search(variant, purl, version, topic)
                if results:
                    break
            if not results:
                package_results = index.package_claims(purl, version)
        elapsed_ms = round((time.perf_counter() - started) * 1000)
        if results:
            metrics = self._record(
                search_count=1,
                knowledge_hits=1,
                retrieval_latency_ms=elapsed_ms,
                retrieval_tokens=1,
                research_tokens_avoided=1,
            )
            return {
                "status": "hit",
                "results": results[:3],
                "metrics": metrics,
                "untrusted_reference_data": True,
            }
        metrics = self._record(
            search_count=1,
            true_misses=1,
            retrieval_latency_ms=elapsed_ms,
            retrieval_tokens=1,
        )
        return {
            "status": "true_miss",
            "results": [],
            "package_candidates": package_results[:5],
            "checked": [
                "exact",
                "query_variants",
                "package_only",
                "nearby_versions_hint",
                "duplicate_candidates",
            ],
            "metrics": metrics,
            "untrusted_reference_data": True,
        }

    def contribute(
        self,
        candidate: dict[str, Any],
        claims_directory: str | Path,
        fetch=None,
    ) -> Path:
        """Validate and stage exactly one public claim in canonical data storage."""
        validator = ClaimValidator(fetch=fetch)
        validator.validate(candidate)
        self._record(contribution_candidates=1)
        claims = Path(claims_directory)
        claims.mkdir(parents=True, exist_ok=True)
        self._reject_duplicate(candidate, claims)
        target = claims / f"{candidate['id']}.json"
        if target.exists():
            raise ValidationError("immutable claim id already exists")
        target.write_text(json.dumps(candidate, indent=2, sort_keys=True) + "\n")
        self._record(contribution_count=1, contribution_tokens=1)
        return target

    def _reject_duplicate(self, candidate: dict[str, Any], claims: Path) -> None:
        candidate_terms = _terms(candidate["summary"])
        for path in claims.glob("*.json"):
            existing = json.loads(path.read_text())
            if existing.get("package") != candidate["package"]:
                continue
            existing_terms = _terms(existing.get("summary", ""))
            union = candidate_terms | existing_terms
            similarity = len(candidate_terms & existing_terms) / len(union) if union else 0.0
            if similarity >= 0.8:
                self._record(duplicate_candidate_count=1)
                raise ValidationError(f"duplicate candidate of {existing.get('id')}")

    def sync(self, manifest_url: str) -> None:
        """Verify, decompress, integrity-check and atomically install a release index."""
        parsed = urlparse(manifest_url)
        if parsed.scheme != "https" and not (parsed.scheme == "file" and self.allow_file_urls):
            raise ValidationError("sync manifest URL must use public HTTPS")
        manifest = json.loads(_fetch(manifest_url, self.allow_file_urls))
        if manifest.get("schema_version") != 1:
            raise ValidationError("unsupported release manifest")
        artifact = manifest.get("artifact")
        digest = manifest.get("sha256")
        if not isinstance(artifact, str) or "/" in artifact or not isinstance(digest, str):
            raise ValidationError("invalid release manifest")
        artifact_url = urljoin(manifest_url, artifact)
        compressed = _fetch(artifact_url, self.allow_file_urls)
        if hashlib.sha256(compressed).hexdigest() != digest:
            raise ValidationError("release artifact checksum mismatch")
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=self.index_path.parent) as directory:
            candidate = Path(directory) / "index.sqlite"
            try:
                candidate.write_bytes(gzip.decompress(compressed))
            except OSError as error:
                raise ValidationError("release artifact is not valid gzip") from error
            try:
                ClaimIndex(candidate)._connect().close()
            except IndexError as error:
                raise ValidationError("release index is corrupt") from error
            os.replace(candidate, self.index_path)
        self._record(index_sync_count=1, index_size_bytes=self.index_path.stat().st_size)
