# Contributing to AtlasTrader

## Branch and review policy

`master` is the reviewed release line. Do not develop a phase directly on `master`.

- Phase work: `phase/<number>-<scope>` (for example `phase/1-hardening`).
- Focused fixes: `fix/<issue>-<scope>`.
- Documentation/process: `docs/<scope>` or `chore/<scope>`.

Open a pull request into `master`, link the relevant issues, and require review plus the
GitHub Actions `quality` and `container` jobs before merge. Configure branch protection to
block direct pushes and require those checks. Never rewrite shared release history merely
to make an old phase boundary look cleaner.

## Required local checks

```bash
python -m pytest
python -m ruff check .
python -m ruff format --check .
python -m mypy
docker compose config --quiet
alembic upgrade head
alembic check
docker compose build
```

Set `GIT_SHA` to the commit being validated when practical. CI supplies `${{ github.sha }}`
to tests and as the Docker build argument. Local runs explicitly record `unavailable` when
it is absent.

## Releases and tags

Tags are annotated and created from reviewed commits on `master`, never from an unreviewed
feature branch:

- Public market data/backtesting: `v0.1.0-phase1`
- Paper execution milestone: `v0.2.0-paper`
- Testnet execution milestone: `v0.3.0-testnet`
- Controlled-live readiness milestone: `v1.0.0-controlled-live`

Update `CHANGELOG.md`, merge the reviewed PR, verify CI on `master`, then create and push the
tag. Do not create `phase-0-complete` on the existing foundational commit because it already
contains Phase 1 code.

Phase 1 hardening does not authorize Phase 2 execution functionality.
