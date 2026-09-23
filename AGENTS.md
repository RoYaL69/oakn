# OAKN repository rules

- Canonical knowledge is JSON data in `knowledge/claims/` only.
- Untrusted knowledge contributions may only add a claim JSON file; they may not modify code, schemas, workflows, policies, or build files.
- Trusted control-plane pull requests are limited to the repository owner, run without secrets, and may change the control plane only after normal code review.
- The validator treats claim content as untrusted data and never executes it.
- Runtime retrieval uses a local SQLite index; it never queries GitHub.
- Public contributions may contain only public source metadata and concise, non-verbatim facts.
- Run `python3 -m unittest discover -s tests -v`, `ruff check .`, `ruff format --check .`, and `mypy src` before delivery.
