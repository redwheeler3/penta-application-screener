# AI Evaluations

This guide records how Penta evaluates AI-assisted ranking quality, the boundary
between the application and its evals, and the current maturity of each layer.

## Purpose

Ordinary tests answer whether the software works: an endpoint returns the right
shape, a cache invalidates, or a ranking run saves scores. AI evaluations answer
whether the model's *judgements* are good: criteria are meaningful, distinct,
oriented, and grounded in evidence.

Penta needs both. The final ranking is deterministic math over committee weights
and stored scores, but discovery, decomposition, matching, consolidation, and
scoring make semantic model judgements. Plausible-looking prose is not enough
evidence that those judgements are sound.

The practical goals are to:

- catch regressions when a production prompt or model changes;
- distinguish a prompt/model failure from a pipeline/storage bug or an unresolved
  committee policy decision;
- make known weak cases repeatable rather than relying on memory of a past run;
- keep evaluation separate from production ranking decisions.

## Layers

### Software tests

Unit and API tests prove the plumbing: schemas, caching, persistence, cost
accounting, and UI/API contracts. They are deterministic and run normally in
the test suite.

### Deterministic property evals

`backend/app/evals/` reads a committed, PII-safe Rank fixture. These checks split
into two honest categories:

| Category | Example | Behaviour |
| --- | --- | --- |
| Invariant | Every dimension has distinct high/low poles | Fails pytest: a breach is always a bug |
| Signal | Two dimensions have highly correlated score vectors | Reports for review: correlation can be legitimate |

Do not turn a judgement signal into a hard gate merely to make it measurable.
A check that would need weakening to stay green is a signal, not an invariant.

### Manual LLM judge

`backend/app/evals/judge.py` covers semantic questions a program cannot answer
honestly, such as whether a proposed merge loses a meaningful distinction or
whether a structured decomposition result follows its own written decision.

Run it explicitly:

```sh
bash ./judge.sh
bash ./judge.sh --case decompose_routing_drift
```

```powershell
./judge.ps1
./judge.ps1 -Case decompose_routing_drift
```

It is intentionally **manual and non-gating**:

- it never runs during Rank, pytest, or normal CI;
- it makes paid Bedrock calls only when someone invokes it;
- it cannot modify criteria, scores, rankings, or the database;
- a disagreement is a review signal, not an automated correction.

## Production vs. judge identity

There are two independent prompts and models:

```text
Production Rank                     Evaluation
---------------                     ----------
production prompt + model           judge prompt + model
          |                                     |
          v                                     v
criterion / score / decision  -->   verdict on that output
```

The production identity tells us what generated the output under review. The
judge identity tells us how it was evaluated. A mature eval record needs both;
otherwise a change in the judge can be mistaken for a change in production
quality.

The `Prompt:` and model line printed by the current judge command refer to the
**judge** prompt and model. The current seed cases are generalized historical
findings, so they do not yet capture the original production prompt/model.

## Application/eval interface

The boundary is one-way and explicit:

```text
Application database
  -> completed Rank output
  -> explicit PII-safe fixture capture
  -> offline deterministic evals and manual judge
```

`backend/app/evals/fixture.py` records a safe subset of a completed Rank:

- criterion definitions and poles;
- structured decomposition, match, and consolidation audits;
- score vectors whose application IDs are replaced by opaque positions.

It excludes applicant names, contact data, raw rows, essays, and model narrative
that can quote those sources. Evals consume this snapshot; they never feed a
verdict back into the application.

The current judge is a first checkpoint with two PII-safe seed cases encoded as
generalized historical findings. The findings came from real runs, but the
inputs are not yet exact captured artifacts from the fixture or current database.
That is sufficient to prove the command and review workflow, not to calibrate a
reliable judge.

## Human labels and judge disagreements

The first two seed cases have labels based on prior manual analysis recorded in
the project specification. They are not yet a formal independently-labelled
dataset. One case is deliberately contested: the existing judgement says two
health/social contribution criteria should merge because their scores move
together for nearly the full pool; the judge currently says to keep them apart
because one edge case distinguishes social-service from healthcare credentials.

That disagreement is useful evidence, but not an instruction to tune the judge
until it agrees. It may mean:

- the judge is over-weighting an edge case;
- the generalized case omitted important context;
- the original human label is legitimately debatable; or
- the product policy needs a clearer merge rule.

The judge's role is to expose this uncertainty for human review, not to create a
self-confirming answer key.

## Design rules

- The judge has a **separate prompt** from production. Production prompts ask the
  model to perform a task; a judge asks whether the resulting decision was
  defensible. Reusing the production prompt would repeat its framing and risk
  repeating its error.
- Give the judge the relevant production output, PII-safe evidence, and the
  applicable product rule. Do not reveal the expected human verdict.
- Keep the judge's prompt version derived and report its model, tokens, and cost.
- Use a structured verdict and concise reason so results can be compared.
- Do not make stochastic judge output a normal CI gate or a production mutation.
- Treat model disagreements as inputs to review, not proof that either side is
  correct.

## Next checkpoint

Before treating judge agreement as a meaningful quality measure:

1. Move seed cases into a dedicated PII-safe fixture with exact relevant
   production artifacts, production model/prompt metadata, a human label, and a
   written label rationale.
2. Build a small balanced labelled set: clear merges, clear keeps,
   narrative/output contradictions, and intentionally ambiguous cases.
3. Calibrate the judge on the clear cases first. Ambiguous cases remain review
   material, not pass/fail scoring.
4. Add persistence and a trend view only after the labelled set is useful.
5. Design a separate safe evidence fixture before adding score-defensibility
   cases, because that category is closest to applicant text.
