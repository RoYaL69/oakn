from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from .versions import applies_to, split_purl


class IndexError(ValueError):
    """The local derived index is unavailable or corrupt."""


def build_index(claims_directory: str | Path, destination: str | Path) -> int:
    """Build a fully reproducible local FTS5 index from canonical claim data."""
    claim_paths = sorted(Path(claims_directory).glob("*.json"))
    target = Path(destination)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        target.unlink()
    connection = sqlite3.connect(target)
    try:
        connection.executescript(
            """
            CREATE TABLE claims (
                id TEXT PRIMARY KEY,
                purl TEXT NOT NULL,
                version TEXT NOT NULL,
                package TEXT NOT NULL,
                package_type TEXT NOT NULL,
                affected TEXT,
                summary TEXT NOT NULL,
                evidence_state TEXT NOT NULL,
                claim_json TEXT NOT NULL
            );
            CREATE VIRTUAL TABLE claims_fts USING fts5(id UNINDEXED, summary, tokenize='unicode61');
            """
        )
        for path in claim_paths:
            claim = json.loads(path.read_text())
            package = claim["package"]
            claim_id = claim["id"]
            summary = claim["summary"]
            evidence_state = claim.get("verification", {}).get("source_binding", "unknown")
            package_type, package_base, _ = split_purl(package["purl"])
            connection.execute(
                "INSERT INTO claims VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    claim_id,
                    package["purl"],
                    package["version"],
                    package_base,
                    package_type,
                    package.get("affected"),
                    summary,
                    evidence_state,
                    json.dumps(claim, sort_keys=True),
                ),
            )
            connection.execute("INSERT INTO claims_fts VALUES (?, ?)", (claim_id, summary))
        connection.commit()
        connection.execute("VACUUM")
        return len(claim_paths)
    finally:
        connection.close()


def _fts_query(query: str) -> str:
    terms = [term for term in query.replace("_", " ").split() if term.isalnum()]
    return " OR ".join(terms[:12])


class ClaimIndex:
    """Read-only local retrieval over a derived SQLite index."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def _connect(self) -> sqlite3.Connection:
        if not self.path.exists():
            raise IndexError("local index does not exist; sync it first")
        connection = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True)
        try:
            status = connection.execute("PRAGMA integrity_check").fetchone()
        except sqlite3.DatabaseError as error:
            connection.close()
            raise IndexError("local index is corrupt; sync it again") from error
        if status != ("ok",):
            connection.close()
            raise IndexError("local index integrity check failed; sync it again")
        return connection

    def count(self) -> int:
        """Return the number of claims in the verified local index."""
        connection = self._connect()
        try:
            row = connection.execute("SELECT COUNT(*) FROM claims").fetchone()
        except sqlite3.DatabaseError as error:
            raise IndexError("local index is missing OAKN claim data; sync it again") from error
        finally:
            connection.close()
        return int(row[0])

    def _package_rows(self, sql: str, parameters: tuple[Any, ...]) -> list[tuple[Any, ...]]:
        connection = self._connect()
        try:
            return connection.execute(sql, parameters).fetchall()
        except sqlite3.OperationalError as error:
            raise IndexError("local index predates version ranges; sync it again") from error
        finally:
            connection.close()

    def search(
        self,
        query: str,
        purl: str,
        version: str,
        topic: str | None = None,
        limit: int = 3,
    ) -> list[dict[str, Any]]:
        """Return the best-ranked claims that apply to ``version`` of a package.

        ``purl`` names the package with or without a version suffix
        (``pkg:npm/p-limit`` or ``pkg:npm/p-limit@4.0.0``); a suffix that
        disagrees with ``version`` matches nothing. A claim applies when
        ``version`` is its own version or falls inside its VERS ``affected``
        range, so a project on a vulnerable version finds the claim recorded
        against the fixed one. Filtering happens before BM25 ranking.
        """
        text = " ".join(part for part in [query, topic] if part)
        fts_query = _fts_query(text)
        package = _package(purl, version)
        if not fts_query or package is None:
            return []
        rows = self._package_rows(
            """
            SELECT claims.id, claims.summary, claims.purl, claims.version, claims.evidence_state,
                   claims.package_type, claims.affected, bm25(claims_fts) AS rank
            FROM claims_fts
            JOIN claims ON claims.id = claims_fts.id
            WHERE claims_fts MATCH ? AND claims.package = ?
            ORDER BY rank ASC, claims.id ASC
            """,
            (fts_query, package),
        )
        results = [
            _result(row, version, relevance=round(-row[7], 6))
            for row in rows
            if applies_to(row[5], row[3], row[6], version)
        ]
        return results[: max(1, min(limit, 5))]

    def package_claims(self, purl: str, version: str, limit: int = 5) -> list[dict[str, Any]]:
        """Return claims about the package whatever the query, applying ones first.

        Each result carries ``applies_to_version``; a claim recorded against
        another version and outside its range is a nearby-version hint, never
        a hit.
        """
        package = _package(purl, version)
        if package is None:
            return []
        rows = self._package_rows(
            """
            SELECT id, summary, purl, version, evidence_state, package_type, affected
            FROM claims WHERE package = ? ORDER BY id
            """,
            (package,),
        )
        results = [_result(row, version, relevance=0.0) for row in rows]
        results.sort(key=lambda result: not result["applies_to_version"])
        return results[: max(1, min(limit, 5))]

    def get(self, claim_id: str) -> dict[str, Any] | None:
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT claim_json FROM claims WHERE id = ?", (claim_id,)
            ).fetchone()
        finally:
            connection.close()
        if not row:
            return None
        return {"claim": json.loads(row[0]), "untrusted_reference_data": True}


def _package(purl: str, version: str) -> str | None:
    try:
        _, package, purl_version = split_purl(purl)
    except ValueError:
        return None
    if purl_version is not None and purl_version != version:
        return None
    return package


def _result(row: tuple[Any, ...], version: str, relevance: float) -> dict[str, Any]:
    return {
        "claim_id": row[0],
        "summary": row[1],
        "package": row[2],
        "version": row[3],
        "affected": row[6],
        "applies_to_version": applies_to(row[5], row[3], row[6], version),
        "evidence_state": row[4],
        "relevance_score": relevance,
        "untrusted_reference_data": True,
    }
