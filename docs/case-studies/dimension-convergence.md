# Case study: measuring an LLM feature before building it

*How a cheap experiment killed an appealing design — and a reasoning trace turned "it doesn't work" into "here's exactly why, and what to build instead."*

This is a decision story, not a feature tour. It covers one question the Penta
screener raised, how I answered it with evidence instead of intuition, and what
the evidence changed. The technical subject is dimension discovery; the
transferable part is the **method** — treating LLM nondeterminism as something
to *measure*, and letting the data overrule the plan.

## Background (one paragraph)

The screener uses an LLM to *discover* the dimensions a specific pool of housing
co-op applicants varies on (e.g. "participation commitment," "financial
stability," "pet load on shared spaces"), then scores each applicant on those
dimensions so a committee can weight what matters and rank. Discovery is a
generative call: **it is nondeterministic — the same pool yields a somewhat
different set of dimensions each run.**

## The bet I was tempted to make

The dominant real-world case is a **locked pool** (screening happens after
applications close). That raised an appealing idea: since discovery is
nondeterministic, why not **run it several times and accumulate the union** —
harvest the "fullest set" of dimensions the committee could choose from? Re-runs
already carried committee tier placements forward via a "match" pass and a
"reconcile" pass (which re-checks dropped dimensions against the pool). So
"just run it a few times until the set stabilizes" seemed nearly free.

It's the kind of idea that demos fine and ships as a bug. The assumption buried
inside it — **that repeated discovery converges** — was never tested. So I
tested it before writing the accumulation feature.

## The instrument (cheap on purpose)

No new product surface. One read-only analysis script
(`backend/scripts/analyze_convergence.py`) that reads every ranking run from the
database and prints, per run: the dimensions produced, how many were *new* versus
the running union, the cumulative distinct-key count, and the reconcile pass's
recover/decline decisions. Then: lock a pool, run the chain unchanged N times,
read the trend.

Total build cost to answer a question that gates a much larger design: a few
dozen lines and an afternoon of runs.

## What the data said

Cumulative distinct dimensions across 8 unchanged-pool runs:

| Run | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 |
|-----|---|---|---|---|---|---|---|---|
| **Union** | 13 | 17 | 21 | 24 | 27 | 27 | 30 | 33 |
| **New this run** | 13 | +4 | +4 | +3 | +3 | +0 | +3 | +3 |

**It does not converge — it creeps, roughly linearly.** A converging process
would trend toward +0 new dimensions per run; this held around +3 to +4 and kept
climbing. Two runs (4 and 6) *looked* like they might be leveling off — and both
times I was tempted to call a ceiling. Both times the next run resumed the climb.
(Logged as its own lesson: on a noisy signal, a single flat point means nothing —
wait for the second.)

The mechanism was visible in the details: the per-run *count* was stable (~24),
which felt like settling, but it was a **rotating cast** — each run swapped a few
dimensions for differently-grained versions of the same concepts. "Participation
/ governance" got sliced into more and more overlapping axes as runs accumulated
(2 → 9 by run 8): `participation_commitment_depth`,
`governance_participation_commitment`, `maintenance_participation_commitment`,
`meeting_facilitation_skills`, `proactive_initiative`… all real, all overlapping.
Discovery wasn't finding *new* things about the pool; it was **re-carving the
same territory at a different grain every pass**, and the accumulation machinery
hoarded every carving.

That alone killed the "run until stable" idea. But the sharper finding came from
reading *why* the reconcile pass never pushed back.

## The reasoning trace turned a metric into a mechanism

I'd instrumented the reconcile pass to persist its own natural-language
reasoning (not just its yes/no decisions). Reading run 8's trace was the moment
the diagnosis went from *what* to *why*:

Reconcile was offered 17 dropped dimensions and **revived all 17** — and every
line of its reasoning was *correct*. It asks one question of each axis: **"does
this pool vary on it?"** For `income_level`, applicants spanned $72k–$142k — yes.
For `health_safety_skills`, two registered nurses vs. everyone else — yes. For
every axis, honestly, yes.

That's the trap, and the trace made it undeniable: **the question is nearly
unfalsifiable.** Discovery only ever coins an axis *because it saw variance on
it*, so asking reconcile "does the pool vary on this?" will almost always return
yes. The pass's skeptic instruction ("decline most") was fighting a question
whose structural answer is yes. The recover-rate trajectory across runs — 100%,
100%, 88%, 67%, 79%, 100%, 100% — shows exactly that: a brief flicker of
skepticism, then collapse back to reviving everything as the offered set filled
with axes that each, individually, do vary.

The numbers said "it creeps." The reasoning said "the model is being asked a
question it cannot answer no to" — a different, and far more actionable,
diagnosis.

## What it changed

Two concrete decisions fell out, both now driving the next build:

1. **Variance is the wrong filter; redundancy is the right one.** No amount of
   prompt-tuning the "does it vary?" question will help, because the answer is
   genuinely yes. The only question that can discriminate is **"is this already
   covered by dimensions we have?"** — "you already have participation nine ways."
   That reframes the fix from *prompt* to *the question being asked*.

2. **The architecture has to change, and now I can say precisely why.** A
   sequential re-run sees one carving at a time against an accumulated history —
   it structurally cannot tell a re-grain from a genuinely new axis. A
   **fan-out** design (run discovery K times in parallel, then a single union
   step reconciles all K outputs at once) can: shown nine carvings of
   "participation" together, it can be asked "pick the grain" — a *decidable*
   question that the sequential shape can't pose. Same model; the architecture
   determines whether it's asked something answerable.

The multi-agent fan-out was already parked as a "maybe someday" idea. The
experiment is what turned it from a preference into a justified decision — and
told me the exact property the union step must have.

## Why this is the part worth keeping

- **The appealing design was wrong, and cheap evidence caught it** before it
  shipped as silent dimension-bloat and a distorted ranking (nine overlapping
  "participation" chips would let a committee unknowingly weight that concept 9×).
- **Instrument first, build second.** A read-only script answered an
  architecture question for the price of an afternoon.
- **Reasoning traces are product instrumentation, not debug output.** Persisting
  the model's own reasoning is what converted a vague "it creeps" into a specific,
  structural cause. It's why the reconcile reasoning is a first-class panel in the
  app, not a log line.
- **Nondeterminism is empirical.** The whole story is about refusing to reason
  about a generative system from first principles when I could just run it 8 times
  and look.

For the full build-facing detail (the fix candidates, the fan-out design seams,
the badge logic this experiment also validated), see the reconcile section of
`SPEC.md`. This document is the story; that one is the blueprint. For the design
judgment *behind* the feature this experiment tested — requirements-first, the
escalation ladder, naming as a design tool — see the companion,
[designing-an-ai-feature.md](designing-an-ai-feature.md).
