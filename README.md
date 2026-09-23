# Open Agent Knowledge Network — MVP

OAKN is a local-first knowledge loop for coding agents. Canonical claims live in
GitHub; normal retrieval never calls GitHub. Clients sync a checksummed,
rebuildable SQLite FTS5 index and return a few compact claims as **untrusted
reference data**.

## Run locally

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -v
PYTHONPATH=src python3 -m oakn.cli resolve-project /path/to/project
PYTHONPATH=src python3 -m oakn.cli build-index knowledge/claims local-data/index.sqlite
PYTHONPATH=src python3 -m oakn.mcp  # explicit stdio MCP server; no Hermes config changes
```

The MCP exposes `resolve_project`, `search`, `get`, `contribute`, `sync`, and
`validate_candidate`. It is opt-in and session-local by default; see
`docs/session-local-mcp.md`. For a no-write, reproducible stdio sync-and-search
run, use `scripts/demo_local_mcp.py`; its explicit repository-local procedure is
in `skills/oakn-session-local/SKILL.md` and is not installed or auto-loaded by
Hermes.

## Canonical data and contribution boundary

`knowledge/claims/` starts empty. One contribution may add exactly one
`knowledge/claims/<uuid>.json` file. It cannot alter workflow, policy, schema,
validator, script or executable code. Validation rejects private/non-GitHub
URLs, URLs with credentials, secret-like content, prompt-injection phrases,
invalid purls, wrong exact versions, unknown-license verbatim content, bad Git
source bindings and duplicate claims.

Git evidence uses a public GitHub repository, immutable 40-character commit SHA,
repository-relative source and package-manifest paths, and SHA-256 hashes for
both. The package manifest must prove the purl's exact package/version.

## GitHub installation requirements

1. Seed the trusted control plane (this repository's code and workflows) on
   `main` once, then protect `main`; untrusted knowledge contributions begin
   only after this bootstrap.
2. Require the `validate` status check on `main`. For a multi-maintainer
   repository, also enable required CODEOWNER review; this single-maintainer MVP
   maps protected paths to `@RoYaL69`.
3. Permit Actions to create releases. The trusted `push` workflow publishes a
   compressed index plus manifest to a GitHub Release.
4. Configure clients with the immutable release `manifest.json` URL and call
   `sync`; its SHA-256 check and SQLite integrity check run before replacement.

`pull_request_target` is deliberate: a data-only contribution is checked with
base-branch validator code and its files are never executed. A non-data pull
request is rejected unless its author is the repository owner; that trusted
control-plane path runs without secrets. The release job executes only merged
`main` code.

See `docs/architecture.md` for trust decisions and `docs/agent-rule.md` for the
agent loop.
