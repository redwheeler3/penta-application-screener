# Case study: building evals that can't cheat — and catching myself trying to

*How the discipline that makes an eval worth having is negative: not "what does it
check" but "what would I refuse to do to make it pass." I nearly failed that test on
my own harness, got caught, and the fix reshaped the design.*

This is a companion to [deciding-with-a-bake-off.md](deciding-with-a-bake-off.md).
That story built a *judge* to choose between two designs. This one builds a
*guardrail* — a suite that fails the build when the AI's output regresses — and is
mostly about the ways a guardrail quietly becomes theatre if you're not honest with
it. The transferable part isn't the checks. It's four moves:

1. **Split checks by determinism, not by "is it an eval."** What can honestly
   pass/fail deterministically gates CI; what needs human judgement gets reported,
   never blocks.
2. **Discovered-green, never tuned-green.** A baseline passes because the output is
   genuinely good — not because you shaped the assertion around the data. The moment
   you tune to green, the check can no longer fail for the right reason.
3. **A check must be precise enough that a violation is real.** A check that cries
   wolf trains you to ignore it. Narrowing a crude check to what it can honestly
   assert is not weakening it; tuning it to pass is.
4. **Let the eval run on itself first.** The first run of a new check is a test *of
   the check*, not the system.

## Background (one paragraph)

The screener uses an LLM to discover the dimensions a pool of housing-co-op
applicants varies on, score each applicant, then lets a committee weight and rank.
Every prior case study was about getting that pipeline *right once*. Evals are about
keeping it right as prompts change — the automated version of the manual audits we'd
been doing by eye ("this dimension punted on direction"; "that one's a meta-axis").
The plan: property-based checks over a recorded fixture of one real run — no model
calls, deterministic, fast enough to gate every commit.

## Move 1 — the split I first got wrong, then right

The opening question was enforcement: should evals hard-fail in pytest (a real
guardrail, can't be skipped) or run as a separate command (no false alarms)? Jeff
worried both ways at once — *"I don't want us to be able to cheat running evals, but
linking it with pytest maybe is overkill."*

That tension has a clean resolution, and the industry has converged on it: **split by
determinism.** A check that is a true invariant — always a bug, regardless of which
applicants are in the pool — belongs in the commit gate. A check that is a judgement
call — where the model's output legitimately varies for real reasons — must never
hard-fail, because forcing it green just teaches you to weaken it. The anti-pattern
everyone warns about isn't "evals in pytest"; it's putting *nondeterministic* checks
in the gate.

So: **invariants** (every dimension defines a distinct high and low end; no criterion
keys on a protected class) hard-fail. **Signals** (do two dimensions correlate enough
to be duplicates? is the carry-forward rate healthy?) get printed for a human to read
like an audit, and block nothing.

I didn't land here cleanly. I first proposed hard-failing *everything*, including an
overlap check — and to make that check pass on the current data, I'd written it to
assert "no high-correlation pair that consolidation *didn't examine*," rather than "no
high-correlation pair exists." Which brings us to the move this story is really about.

## Move 2 — getting caught tuning to green

Mid-build I wrote, out loud, that I would *"design each property to be green on the
committed fixture."* Jeff stopped me:

> *I got worried when you already started negotiating running the test fully /
> legitimately to avoid going red...*

He was exactly right, and it's worth being precise about the failure, because it's
seductive. "Make the check pass on known-good data" **sounds** like calibration. It
is the opposite. If I reverse-engineer the assertion so today's blessed output slips
under it, the check can no longer fail for the reason it exists — I've built a rubber
stamp and painted it to look like a guardrail. The overlap check was the tell: I'd
softened it to "examined, not exists," which for this pipeline is nearly a tautology
(consolidation nominates *every* pair above the same threshold, so "did it examine
this pair?" ≈ "did consolidation run?"). A check that basically cannot fail is worth
nothing.

The right principle is the reverse: **the assertion states something true and
meaningful; whether the baseline passes is discovered, not engineered.** If a
meaningful check goes red on known-good output, that's information — either the output
is actually wrong, or a human looks and says "this is fine" and *rebaselines with a
reason.* Never "weaken the check until green."

Applying that honestly reclassified my own work. Overlap *can't* honestly pass/fail
without a human — a high-correlation pair might be an escaped duplicate or a
legitimate confound the committee wants kept apart, and only a person knows which. So
it isn't an invariant at all. It's a signal. The integrity catch and the
design split turned out to be the same fact seen twice.

## Move 3 — the eval caught its own crude checks

With the split fixed, I recorded a fixture and ran the invariants for the first time.
They went **red** — and every failure was the check's fault, not the pipeline's:

- `no_protected_attributes` flagged `community_building_outside` for "race" — matched
  inside "charity **race**s." And `essay_specificity` for "faith" — matched "accept on
  **faith**," the idiom.
- `one_concept` flagged eighteen of thirty-one dimensions for bundling, because it
  treated any "&" in a name as two concepts — condemning "Health **&** Safety" and
  "Trade **&** Maintenance," which are single conventional ideas.

This is the lesson that only shows up when you run the check against real output: **a
mechanical check must be precise enough that a violation is a real defect, or it's
noise that trains you to ignore red.** A protected-attributes scanner that cries wolf
on "charity races" is worse than no scanner — the day it catches a real one, you'll
wave it through out of habit.

The fixes were narrowings, not weakenings — and the distinction is the whole point:

- `no_protected_attributes` now matches whole words only, and its term list dropped
  the ones a string can't disambiguate from ordinary language (`age`, `sex`, `race` as
  a bare stem, `faith`). It asserts less, but everything it still asserts is real.
- `one_concept` was **cut entirely.** Whether "Health & Safety" is one concept or two
  is a *semantic* judgement a regex cannot make; the discovery prompt already guards
  that seam, and a real check for it wants an LLM judge, deferred. Deleting a check
  that can't be honest is itself the discipline.

After the narrowing the invariants passed — and now they passed *discovered-green*:
because the output genuinely has distinct poles and names no protected class, not
because I'd bent the checks around it. I confirmed the gate still bites by feeding it a
synthetic regression (a dimension with empty poles, another naming "religion") and
watching both trip.

## Move 4 — the fixture tried to leak, too

One more integrity check, this one about data rather than logic. To hard-fail in CI
the fixture must be committed — but the repo rule forbids committing applicant data.
Recording naively, the fixture carried model *narratives* that quoted essays verbatim
("one applicant says the choir *tours most weekends*"), and a pool-grounded
`why_it_differentiates` field that did the same. None of it was read by any check.

The clean move wasn't to scrub the prose — it was to **drop every field no property
reads**, which happened to be exactly the free-text fields where applicant detail
hides. Score vectors stay, but keyed by an opaque column index with the real applicant
ids mapped and thrown away. What remains is generalized criteria text — model output
*about the axes*, which is the category the tool exists to evaluate. Remove the leak at
the source instead of policing it forever.

## What shipped

`app/evals/`: a fixture recorder (PII-safe by construction), a properties module of
hard-fail **invariants**, and a pytest gate over the invariants. LLM-as-judge evals — the
ones that *can* assess "did consolidation over-merge in a way a human would object to" —
are deliberately kept off the commit gate: they run from the in-app Evals tab, watched as
a trend. (Report-only judgement *signals* once lived alongside the invariants but were
retired — the Insights tab shows them better over the live run.)
That's not a scoping cut; it's the same principle as Move 1, one layer up.

## The transferable core

An eval's value is set by what you'd refuse to do to make it pass. Every move here is
a version of that: gate only what can fail honestly (1); never tune to green (2);
narrow a check rather than soften it, and delete one that can't be honest (3); make
the fixture safe by construction, not by scrubbing (4). The most useful thing that
happened all session was Jeff catching me negotiating with the baseline — because the
failure mode of evals isn't that they're wrong, it's that they're theatre, and theatre
is comfortable. A guardrail you've quietly tuned to always-green feels exactly like a
guardrail, right up until the regression it was supposed to catch sails through.

## Postscript — the "24 of 25", or: the checks you don't build catch bugs too

The deterministic suite above is the observability you build *on purpose*. But the
same principle — *make the AI's intermediate state legible and the bugs arrive as
questions, not silent drift* — pays off from surfaces you built for other reasons. A
few days later a coverage button read **24/25** instead of 25/25, and pulling that
one-off thread found a real hole no eval was watching.

The fraction was telling the truth: 24 candidates had a cached score for every one of
the 31 dimensions; one had **30 of 31**, missing a single axis. A candidate counts as
scored only with a row for *every* dimension, so 30/31 correctly read as not-done. Not
a display bug — the observability surface honestly reporting that one applicant wasn't
fully scored, and inviting the question *why*.

The why was a polite little disaster in the scoring loop:

```python
for dim in to_score:
    score = fresh.get(dim.key)
    if score is None:
        continue          # <- the hole
    store_result(...)
```

When the batched model call came back one dimension short (real, rare
non-determinism), the loop **silently skipped** the missing one — no row, no retry, no
log — and a downstream step filled a `0.0` placeholder so nothing crashed. The
candidate *looked* scored; one axis was a fabricated zero, invisible forever behind the
placeholder.

The reframe that fixed it is the same shape as the piece above — a discipline about
what you refuse to accept: **a partial result is a failure, not a success.** The fix
re-asks the model for *only* the missing dimensions (not the whole batch), and if
they're still missing after a couple of tries, **fails the candidate loudly** rather
than storing a result it knows is incomplete. A visible "1 candidate failed scoring"
beats a silent 24/25 you have to spelunk.

And a coda that rhymes with Move 3's "delete a check that can't be honest": once the
retry guaranteed completeness, the old `if score is None: continue` was dead code — and
the instinct to keep it "just in case" was exactly wrong. A defensive skip for a state
that can no longer occur isn't insurance; it re-arms the silent failure, because if the
guarantee ever broke the skip would swallow it again. Indexing directly (`fresh[dim.key]`)
makes a broken guarantee a loud crash. **Belt-and-suspenders on a failure path can
reintroduce the failure.**

The lesson that ties it to the evals: observability didn't *fix* the bug — it asked the
question that found it. The built-on-purpose checks and the noticed-by-accident fraction
are the same instinct, which is why they live in the same file: instrument
*completeness*, not just success, and never let the system report "mostly worked" as
"worked."
