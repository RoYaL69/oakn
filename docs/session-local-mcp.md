# Session-local OAKN MCP

`oakn-mcp` is a standards-compliant stdio MCP server. It is intentionally not
registered in Hermes configuration by this repository and it never changes a
Hermes profile, plugin list or global toolset.

## Explicit local launch

Run it only from an OAKN checkout and only when you intend to inspect or call
its tools:

```sh
cd /path/to/oakn
OAKN_INDEX_PATH="$PWD/.oakn/session-index.sqlite" \
OAKN_CLAIMS_DIR="$PWD/knowledge/claims" \
PYTHONPATH=src .venv/bin/python -m oakn.mcp
```

The server exposes `resolve_project`, `search`, `get`, `validate_candidate`,
`contribute` and `sync`. Each retrieved result carries the untrusted-reference
data marker and safety notice.

`contribute` defaults to local validation and staging. It creates a GitHub draft PR
only when the caller explicitly sets `publish_mode: "draft_pr"` and supplies both
an explicit local `repository_path` and matching `github_repository`. Publication
uses an isolated Git worktree and validates the candidate again before staging.

## Hermes boundary

Do **not** run `hermes mcp add` for this MVP. Native Hermes MCP registration is
persistent and discovered tools are injected into future sessions after restart.
Hermes also does not hot-load a new MCP tool into this already-running desktop
session. The supported session-only test is the stdio protocol test in
`tests/test_mcp_protocol.py` or a manually launched local MCP client.

When the experiment is ready for a deliberate opt-in, use a separate temporary
Hermes profile or config directory, register this exact stdio command there,
start a new session, and remove that profile/config after the experiment.
