# OAKN MVP architecture

## Scope decision

The MVP is one Python package with three trust-separated areas:

- `knowledge/claims/`: canonical, immutable claim data.
- `src/oakn/`: trusted client, validator, index builder and MCP implementation.
- `.github/`: trusted GitHub enforcement and release automation.

A contribution is accepted only when its changed paths are exactly one new
`knowledge/claims/<claim-id>.json` file. The local validator and the
`pull_request_target` GitHub workflow run trusted code from the base branch;
untrusted contribution files are read as data only. Branch protection and
CODEOWNERS are documented as required repository settings because GitHub cannot
make a repository file self-protecting without a protected default branch.

## Core loop

1. `resolve_project` reads manifests and lockfiles for exact package versions.
2. `search` searches only a local, verified SQLite FTS5 index, filtered by purl
   and exact version before BM25 ranking.
3. A miss is broadened through query variants, package-only search, nearby
   version hints and duplicate-candidate detection. Only then is it a true miss.
4. A candidate constructed solely from public evidence is validated locally,
   staged as one claim file and optionally published as a GitHub PR.
5. Trusted CI validates data-only changes. A merge to `main` rebuilds the
   SQLite index and release bundle. `sync` verifies its SHA-256 before atomically
   replacing the local index.

## Trust and security decisions

- Claims are reference data, never instructions. MCP responses explicitly mark
  them `untrusted_reference_data`.
- Git evidence binds repository URL, immutable commit SHA, source path, content
  hash and package manifest hash. A network verifier fetches immutable GitHub raw
  URLs and checks the target package name/version from its manifest.
- Source binding, authority, semantic support, executable verification,
  freshness and contradictions are independent states; no aggregate trust score
  exists.
- Unknown licenses permit facts only. Verbatim snippets are rejected unless an
  explicitly allowlisted compatible license is declared.
- Secret patterns, private hosts, credentials in URLs, prompt-injection phrases,
  private workspace markers and excessive text are rejected before a contribution
  can be staged.
- Executable verification has a state in the claim model but no fixture runner in
  this MVP; untrusted fixture code is therefore never executed.

## Deliberate MVP limits

No embeddings, vector database, central service, telemetry upload, votes,
reputation, P2P or automatic broad crawling. Release publication uses GitHub
Actions and GitHub Releases; local and test flows can use a file URL bundle.
