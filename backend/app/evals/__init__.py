"""Offline evals for the AI pipeline (M13 Pillar 4).

Evals answer a different question than the unit tests: not "does the code run" (the
mock-provider suite covers that) but "is the model's JUDGMENT any good, and does it
stay good as prompts change." They score a RECORDED fixture of one real Rank's output
against properties that must hold regardless of which applicants are in the pool — no
model calls, so they're fast, deterministic, and run in CI.

Flow:
  1. ``record_fixture`` dumps one Rank's output (settled dimensions + poles, the
     decompose/match/consolidate audits, and per-dimension score vectors) to a committed
     JSON fixture. Applicant PII never enters it — see that module's docstring.
  2. ``properties`` holds pure ``fixture -> [Violation]`` checks, reusing the production
     score-vector math so "what counts as overlap" has one definition.
  3. ``tests/test_evals.py`` loads the committed fixture and hard-fails pytest on any
     violation, so a prompt/schema regression turns the suite red at commit time.

Rebaseline (re-record) deliberately when a surfaced violation resolves to "that output
is actually fine" — the fixture is the blessed baseline, not a frozen golden master.
"""
