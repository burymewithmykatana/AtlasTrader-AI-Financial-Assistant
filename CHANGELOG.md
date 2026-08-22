# Changelog

All notable changes are recorded here. Tags follow the policy in `CONTRIBUTING.md`.

## Unreleased — Phase 1 hardening

- Detect leading, internal, trailing, and empty-range candle gaps.
- Move candle page-size capabilities into the public adapter contract.
- Normalize malformed Nobitex numerics into stable response errors.
- Protect stored markets from incomplete discovery snapshots.
- Persist candle-dataset fingerprints and complete backtest reproduction metadata.
- Propagate commit SHA through CI and Docker builds.

The reviewed merge of this work is intended to become `v0.1.0-phase1`. No tag should be
created before review and successful CI on `master`.
