# Contributing a claim: practical guide

`docs/agent-rule.md` states the protocol. This document collects the concrete,
ecosystem-specific pitfalls that are easy to hit the first time you actually
build and stage a claim, regardless of which agent or tool you use.

## 1. Pick evidence that is actually version-provable

Every claim binds a package version to a manifest file's content hash
(`package_manifest` in the evidence entry). That only works if the manifest
at your chosen commit actually contains the version string.

- **npm** (`package.json`), **maven** (`pom.xml`/`build.gradle`), **cargo**
  (`Cargo.toml`), **golang** (`go.mod`, module path only — see below) are
  generally reliable.
- **pypi** is the ecosystem most likely to trip you up: many popular packages
  declare `dynamic = ["version"]` in `pyproject.toml`'s `[project]` table and
  resolve the actual version at build time via a plugin (hatch-vcs,
  setuptools_scm, etc.). A claim cannot be manifest-verified against a
  dynamic version field. Examples that will NOT work: `requests`, `httpx`,
  `click`, `packaging`, `black`, `more-itertools`, `python-dotenv`,
  `tabulate`, `pytest-dev/iniconfig`. Before picking a package, check:
  ```sh
  grep -A8 '^\[project\]' pyproject.toml
  ```
  and confirm there is a literal `version = "x.y.z"` line, not a `dynamic`
  entry naming `"version"`. `flask` (>=3.x) is a reliable example of a
  static-version pypi package.
- **golang** is a special case: `go.mod` never carries a version at all
  (only the module path). OAKN verifies golang claim versions against the
  public Go module proxy (`proxy.golang.org`'s `@v/<version>.info` endpoint)
  as a second trust root beyond GitHub, rather than the manifest. No action
  needed on your part beyond picking a real tagged version — just be aware
  the verification path is different from every other ecosystem.

## 2. Use the live network fetch to compute hashes, not your local clone

The validator's default `fetch` hits `raw.githubusercontent.com` for the
exact commit SHA you cite. Compute your evidence `content_sha256` values
against that same live endpoint, not just a local `git clone` (they should
match, but the network fetch is what's authoritative, and computing it this
way catches encoding/line-ending mismatches early):

```python
import hashlib, urllib.request

url = f"https://raw.githubusercontent.com/{owner}/{repo}/{commit_sha}/{path}"
content = urllib.request.urlopen(url).read()
hashlib.sha256(content).hexdigest()
```

## 3. Validate before you write anything to `knowledge/claims/`

```python
from oakn.validation import ClaimValidator

ClaimValidator().validate(
    claim
)  # real network verification; raises ValidationError on any mismatch
```

## 4. Stage through `KnowledgeClient.contribute()`, not a hand-written file

Writing a claim JSON directly into `knowledge/claims/` works, but skips the
duplicate-detection and canonical formatting `contribute()` gives you for
free, and doubles as a second independent validation pass:

```python
from oakn.client import KnowledgeClient

KnowledgeClient(".oakn/index.sqlite").contribute(claim, "knowledge/claims")
```

## 5. Rebuild and search locally before opening a PR

```sh
PYTHONPATH=src python3 -m oakn.cli build-index knowledge/claims .oakn/index.sqlite
```

Then run a real `search()` (via the CLI, the MCP server, or
`KnowledgeClient.search()`) for your claim's purl/topic and confirm it comes
back as a hit before spending a PR review cycle on it.

## 6. One claim per PR

Keeps review focused and keeps `_reject_duplicate` (package + overlapping
summary terms) meaningful — it only compares against claims already on disk
when you stage, not against other claims in the same PR.
