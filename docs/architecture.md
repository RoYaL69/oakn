# OAKN MVP architecture

## Scope decision

The MVP is one Python package with three trust-separated areas:

- `knowledge/claims/`: canonical, immutable claim data.
- `src/oakn/`: trusted client, validator, index builder and MCP implementation.
- `.github/`: trusted GitHub enforcement and release automation.

A knowledge contribution is accepted only when its changed paths are exactly one
new `knowledge/claims/<claim-id>.json` file. The `pull_request_target` workflow
runs trusted base-branch code and reads those untrusted data files without
executing them. Non-data pull requests follow the separate no-secrets
control-plane path and require the configured approval gate. Branch protection
and CODEOWNERS are documented as required repository settings because
GitHub cannot make a repository file self-protecting without a protected default
branch. External control-plane pull requests require two independent approvals
from collaborators with write, maintain, or admin permission for the current
commit before the trusted test path runs. The workflow uses only GitHub API
metadata and never exposes secrets to the pull-request code.

## Core loop

1. `resolve_project` reads manifests and lockfiles for exact package versions.
2. `search` searches only a local, verified SQLite FTS5 index, filtered by
   package before BM25 ranking. A claim applies to its own evidence-bound
   version and to every version inside its optional `package.affected` VERS
   range (`vers:maven/>=1.5|<1.10.0`), compared with the ecosystem's own
   ordering through `univers`. The purl may omit its version; a version suffix
   that disagrees with `version` matches nothing.
3. A miss is broadened through query variants, then package-only search. The
   miss response lists the package's claims as `package_candidates`, applying
   ones first, each flagged `applies_to_version`; a claim for another version
   outside its range is a hint, never a hit. `checked` names exactly these
   steps. Duplicate detection runs at contribution time, not during search.
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
- For `pkg:golang/...` claims specifically: `go.mod` carries no version field
  (only the module path), so the package manifest alone cannot bind an exact
  version the way `package.json`/`pom.xml`/`Cargo.toml`/`pyproject.toml` do for
  the other ecosystems. The claimed version is verified independently against
  the public Go module proxy (`proxy.golang.org`'s checksum-addressed
  `@v/<version>.info` endpoint, part of the standard GOPROXY protocol) rather
  than trusted from the claim author's assertion. This is the one ecosystem
  where evidence verification reaches a second allowlisted host beyond GitHub.
- Source binding, authority, semantic support, executable verification,
  freshness and contradictions are independent states; no aggregate trust score
  exists.
- Unknown licenses permit facts only. Verbatim snippets are rejected unless an
  explicitly allowlisted compatible license is declared.
- Secret patterns, private hosts, credentials in URLs, prompt-injection phrases,
  private workspace markers and excessive text are rejected before a contribution
  can be staged.
- `package.affected` widens retrieval only. The evidence still binds the one
  exact version in `package.purl`; the range is the advisory's assertion, so it
  counts toward `semantic_support`, not `source_binding`.
- Executable verification has a state in the claim model but no fixture runner in
  this MVP; untrusted fixture code is therefore never executed.
- Control-plane changes from outside contributors remain untrusted until two
  independent trusted collaborators approve the exact current commit. A later
  approval, a non-maintainer approval, or an approval followed by a
  `CHANGES_REQUESTED` review does not satisfy the gate.

## Deliberate MVP limits

No embeddings, vector database, central service, telemetry upload, votes,
reputation, P2P or automatic broad crawling. Release publication uses GitHub
Actions and GitHub Releases; local and test flows can use a file URL bundle.
