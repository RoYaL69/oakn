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
PYTHONPATH=src python3 -m oakn.cli metrics --index local-data/index.sqlite
PYTHONPATH=src python3 -m oakn.cli record-outcome <claim-id> --index local-data/index.sqlite --accepted
PYTHONPATH=src python3 -m oakn.mcp  # explicit stdio MCP server; no Hermes config changes
```

The MCP exposes `resolve_project`, `search`, `get`, `contribute`, `record_outcome`,
`sync`, and `validate_candidate`. `search(query, purl, version, topic=None)`
takes the package purl with or without its version (`pkg:npm/p-limit` or
`pkg:npm/p-limit@4.0.0`); a version suffix must equal `version`. A claim matches
its own version and every version in its optional VERS `package.affected` range,
so a project on a vulnerable version finds the claim recorded against the fix.
See `docs/architecture.md` for the retrieval broadening sequence on a miss.
`record_outcome` records an explicit accepted or
rejected applicability outcome only in local metrics; it never alters a claim or
contacts GitHub. It is opt-in and session-local by default; see
`docs/session-local-mcp.md`. For a reproducible stdio sync-and-search run with no
Hermes configuration or GitHub writes, use `scripts/demo_local_mcp.py`; its
explicit repository-local procedure is in `skills/oakn-session-local/SKILL.md`
and is not installed or auto-loaded by Hermes.

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

## Pull requests and trust boundary

OAKN distinguishes between two kinds of pull requests:

- **Claim PRs** may be opened by anyone. They must change exactly one new
  `knowledge/claims/<uuid>.json` file. The trusted base-branch validator reads
  the file as data, validates its public evidence and schema, and never executes
  contribution code.
- **Control-plane PRs** change trusted files such as workflows, schemas,
  validators, scripts, source code or policies. External contributors may
  propose these changes, but the trusted test path runs only after two
  independent collaborators with administrator, maintainer or write permission
  approve the exact current commit. A later `CHANGES_REQUESTED` review or a new
  commit invalidates those approvals.

Control-plane tests run in an isolated job without repository secrets or write
tokens. The `validate` check must pass before merging, and protected paths also
require the CODEOWNER review configured in `CODEOWNERS`. If a pull request is
classified incorrectly, check that its changed paths contain only the single
claim file or ask a maintainer to review the control-plane change.

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
request uses the approval gate described above before trusted tests run, and
those tests receive no secrets or write tokens. The release job executes only
merged `main` code.

See `docs/architecture.md` for trust decisions and `docs/agent-rule.md` for the
agent loop. See `docs/contributing-claims.md` for a practical, ecosystem-by-
ecosystem walkthrough of what tends to trip people up the first time they
build and stage a real claim.
