from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


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
            connection.execute(
                "INSERT INTO claims VALUES (?, ?, ?, ?, ?, ?)",
                (
                    claim_id,
                    package["purl"],
                    package["version"],
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
        finally:
            connection.close()
        return int(row[0])

    def search(
        self,
        query: str,
        purl: str,
        version: str,
        topic: str | None = None,
        limit: int = 3,
    ) -> list[dict[str, Any]]:
        text = " ".join(part for part in [query, topic] if part)
        fts_query = _fts_query(text)
        if not fts_query:
            return []
        connection = self._connect()
        try:
            rows = connection.execute(
                """
                SELECT claims.id, claims.summary, claims.purl, claims.version, claims.evidence_state,
                       bm25(claims_fts) AS rank
                FROM claims_fts
                JOIN claims ON claims.id = claims_fts.id
                WHERE claims_fts MATCH ? AND claims.purl = ? AND claims.version = ?
                ORDER BY rank ASC, claims.id ASC
                LIMIT ?
                """,
                (fts_query, purl, version, max(1, min(limit, 5))),
            ).fetchall()
        finally:
            connection.close()
        return [
            {
                "claim_id": row[0],
                "summary": row[1],
                "package": row[2],
                "version": row[3],
                "evidence_state": row[4],
                "relevance_score": round(-row[5], 6),
                "untrusted_reference_data": True,
            }
            for row in rows
        ]

    def package_claims(self, purl: str, version: str, limit: int = 5) -> list[dict[str, Any]]:
        connection = self._connect()
        try:
            rows = connection.execute(
                "SELECT id, summary, purl, version, evidence_state FROM claims WHERE purl = ? AND version = ? ORDER BY id LIMIT ?",
                (purl, version, max(1, min(limit, 5))),
            ).fetchall()
        finally:
            connection.close()
        return [
            {
                "claim_id": row[0],
                "summary": row[1],
                "package": row[2],
                "version": row[3],
                "evidence_state": row[4],
                "relevance_score": 0.0,
                "untrusted_reference_data": True,
            }
            for row in rows
        ]

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
