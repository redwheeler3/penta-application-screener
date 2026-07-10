# Case study: designing an AI feature without over-building it

*Requirements before architecture, the cheapest thing first, and naming as a
design tool — how one feature got specified, scoped, and built with a bias
against complexity.*

This is a companion to [dimension-convergence.md](dimension-convergence.md).
That one is about *measuring* an LLM feature; this one is about *designing* one —
the judgment calls made before and during the build of "automatic reconcile,"
the pass that re-checks dropped screening dimensions on a re-run. The feature
detail matters less than the practices, which transfer to any AI feature.

## The problem, in one line

Dimension discovery is nondeterministic, so a factor the committee cared about
can silently vanish when a later run happens not to re-surface it. "Don't lose a
valued axis" is the need. There were several plausible mechanisms. The story is
how the design got chosen and bounded.

## 1. Requirements before architecture

The first instinct — mine — was to jump to *how*: a menu of past dimensions? a
matching pass? The course-correction was to stop and lock **requirements first**,
as numbered, testable statements (RQ1–RQ8): what triggers a revival, who decides
(model, never member), how a revived axis arrives, what the audit must capture.
Only then did architecture get chosen.

Why it mattered: several of the requirements *eliminated* architectures before a
line was written. "The model, not the member, decides whether an axis still
applies" killed the browsable-menu design outright (it lets a member re-assert a
flat axis by hand). Locking that as a requirement made the design space small and
the build direct. **Requirements-first isn't ceremony; it's how you avoid
building the wrong thing well.**

## 2. The escalation ladder: don't build the impressive version first

The feature *could* have been a multi-agent orchestration from day one (parallel
judges, an adversarial skeptic). It was tempting — it's the kind of thing that
sounds sophisticated. Instead the design fixed an **escalation ladder**:

> single deterministic call → (if observability shows trouble) labeled eval → (only if that confirms it) multi-agent

and specified *the evidence that would justify each step up*. Build the simplest
thing; add an always-on audit (recovery rate) that would reveal if the simple
thing misbehaves; escalate only on data.

This is cost-aware AI design as a concrete artifact, not a slogan. It also aged
well: the [convergence experiment](dimension-convergence.md) later showed the
simple version *does* hit a structural wall — but now the escalation is
**evidence-driven**, and the multi-agent step is a justified decision with a
known reason, not a guess made up front. The ladder meant we neither
over-built early nor got stuck late.

## 3. Naming as a design tool

Midway through, two ideas were riding one word: "revived." One was
member-facing — *a dimension the committee saw before, gone a run, now back*
(drives a UI badge). The other was mechanism — *the reconcile pass pulled an axis
back that discovery missed* (drives an audit metric). They overlap but neither
contains the other: discovery can re-find a gapped axis (member-revived, not
pass-recovered); the pass can salvage an axis that never left the member's view
(recovered, not revived).

Splitting them into **"revived" (presence, UI) vs. "recovered" (mechanism,
audit)** wasn't wordsmithing — it prevented a class of bugs. A later
implementation test hinged exactly on this: a dimension the pass *recovered* but
that had *no presence gap* correctly showed **no** badge. If the two concepts had
stayed fused under one name, that case would have been a silent wrong-badge.
**Precise names are cheap; the bugs from imprecise ones are not.**

## 4. Reuse over invention — catching a parallel structure before it landed

Building the badge, I started to add a second stored field, `revived_dimension_keys`,
alongside the existing "new dimensions" set — a natural-looking parallel
structure. The project's own rule ("before adding a new identifier or parallel
data structure, ask whether existing data can carry the need") caught it.

The fix: keep **one** stored set of flagged dimensions; derive the *label*
(new vs. revived) from run history at read time. New-vs-revived is a fact about
presence across runs, not a thing to persist and keep in sync. That collapsed
what would have been a second field, a second acknowledge path, and a second
place to drift — into a read-time function. The related win came the same way:
one uniform "a flag clears on a member action, never on the system's
auto-placement" rule produced both the new-badge and revived-badge behaviors with
no per-badge branch. **The best structure was often one fewer than the obvious
one.**

## 5. Correcting the spec against reality (twice)

Two moments worth keeping because they're about honesty, not cleverness:

- The design doc claimed reconcile had "the same economics as the match pass."
  Reading the actual match code showed that was false — match compares two text
  lists and never sees the applicant pool; reconcile *must* read the pool to
  judge variance, so it's ~5× the cost shape. The wrong claim would have produced
  a wrong cost estimate. Caught by reading the code the claim was about, not
  trusting the claim.
- The spec later said a retired feature was "Removed:" when it was still fully
  wired in code — the rationale got written, the deletion didn't. Corrected to
  "decided, not yet done," with the removal list and a sequencing note.

Both are the same discipline: **the document is only as true as its last check
against the code.** Spec drift is a real cost; catching it is part of the job.

## The through-line

None of these are AI-specific tricks; they're engineering-and-product judgment
applied to an AI feature. But AI features punish their absence harder — a vague
requirement, an over-built agent loop, a fused concept, or a stale spec costs
more when the underlying model is nondeterministic and expensive to run. The bias
throughout was the same: **specify precisely, build the smallest thing that could
work, name concepts exactly, and let evidence (not ambition) decide when to add
more.**

For the experiment that tested whether the built feature's core strategy actually
holds, see [dimension-convergence.md](dimension-convergence.md). For the
build-facing detail, see the reconcile section of `SPEC.md`.
