# FABINZI WEB v1.0 — Build & Release Reproducibility

## Source identity

The candidate is one exact Git commit. PR CI is configured to check out the PR **head SHA itself**, not GitHub's synthetic merge ref, and verifies `git rev-parse HEAD` against the event head SHA.

## Runtime freeze

- Python: `3.12.14` in `.python-version`, CI and Docker base tag.
- `requirements.txt`: supported dependency envelope.
- `constraints-release.txt`: exact package resolution already proven by PLG CI #342.
- Build/install command: `python -m pip install -r requirements.txt -c constraints-release.txt`.
- `python -m pip check` is required.

CI also pins the PostgreSQL/Redis service patch versions and the exact GitHub Action revisions used by the accepted predecessor run, reducing unrelated workflow drift during the release freeze.

## Static and migration freeze

Release CI fails if files under `static/` or local Django migration files differ from integration base `802dc0f091287f778d4e623caa375a32c67f97dc`. The final release-contract artifact records source-static SHA256 hashes, migration plan, installed package freeze and source-change inventory.

## Release evidence artifact

Successful CI creates `web-v1-release-contract` containing release manifests, changelog, constraints, `.python-version`, WEB v1 release documents, exact source SHA metadata, migration plan, `pip freeze`, `pip check`, static source hashes, collected-static file count and release-input hashes.

## Reproducibility boundary

This is a reproducible source/runtime dependency contract, not a claim of bit-for-bit container-image reproducibility. The Python Docker tag is patch-pinned but not content-digest-pinned, and hosted Render infrastructure remains provider-managed. A later production release should record the deployed container/revision identity supplied by the platform.
