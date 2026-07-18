"""Eval INVARIANTS as the CI gate (M13 Pillar 4).

Each invariant runs over the committed fixture (a blessed real Rank) and hard-fails on
any breach — a prompt or schema regression that (e.g.) drops a pole, names a protected
class, or bundles two concepts turns the suite red at commit time.

These pass on the fixture because the recorded output is genuinely good, NOT because the
checks were tuned to it — if a real run regresses, re-record only after a human confirms
the new output is actually fine (rebaseline with a reason), never by weakening a check.

Only invariants gate CI. Judgement observations (overlap, carry-forward rate) that can't
honestly pass/fail aren't checked here or in the Evals tab — the Insights tab shows them
over the live run, better. Putting them in CI would just pressure us to soften them.
"""

import pytest

from app.evals.fixture import FIXTURE_PATH, load
from app.evals.invariants import INVARIANTS


@pytest.mark.skipif(not FIXTURE_PATH.exists(), reason="no eval fixture recorded yet")
@pytest.mark.parametrize("check", INVARIANTS, ids=lambda c: c.__name__.removeprefix("check_"))
def test_invariant_holds_on_baseline(check) -> None:
    violations = check(load())
    assert not violations, "\n".join(f"{v.subject}: {v.detail}" for v in violations)
