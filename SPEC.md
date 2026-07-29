# Penta Application Screener Specification

This is the **current-state** spec — how the app works today and what is still open. Resolved
milestone history lives in [CHANGELOG.md](CHANGELOG.md); significant architectural decisions
(and the reasoning behind reversed ones) live in [docs/adr/](docs/adr/); the blow-by-blow of
the big experiments lives in `docs/case-studies/`.

## Purpose

The Penta Application Screener helps screen 300+ housing co-op applications for Penta Housing Coop. It imports application responses from a Google Sheets response spreadsheet in the Penta Google Drive folder, applies deterministic hard filters, uses AI-assisted review for essay answers, and produces a committee-ready report for MOMI (Move In Move Out).

The project is also a deliberate learning and portfolio project for Jeff to build practical expertise in AI product management, agentic workflows, evals, cost-aware model use, human-in-the-loop product design, and AI-assisted software delivery. The code may eventually be made public as part of Jeff's AI product management portfolio, so the implementation should be understandable, well-documented, and credible as a real product artifact while preserving applicant privacy.

## Primary User

The primary user is Jeff. The output audience is MOMI, who need a clear shortlist of applicants recommended for the interview stage, with justification.

## Source Materials

- Google Drive folder: application working folder containing forms, response sheets, and email templates
- Email list spreadsheet: `Penta Co-operative Housing Email List (Responses)`
- Application response spreadsheet: `Penta Co-operative Housing Application (Responses)`
- Application form: `Penta Co-operative Housing Application`
- Email list form: `Penta Co-operative Housing Email List`
- Email templates:
  - `Applications are open email - no application record.docx`
  - `Applications are open email - application already on file.docx`
  - `Application declined but on file email.docx`
  - `Application deleted email.docx`



Google Forms definitions were inspected through the authenticated browser/devtools MCP. The response sheets provide the effective column schema.

## Application Form

The application form is titled `Penta Co-operative Housing: Application For Membership`. 

The form introduction includes:

- Household eligibility declaration: 1 or 2 adults plus 1 or more children under 18 years old.
- Direction that people not interested in or eligible for the current unit should use the mailing list instead.
- Privacy/consent language describing who may access personal information, including auditors, lawyers, treasurer, directors, approved committee members, management company agents/staff, municipal employees for Home Owner Grant applications, and general membership only if relevant to an appeal.
- Permitted uses: application contact, housing and membership eligibility, Home Owner Grant eligibility, housing reference check, credit check, and internal move decisions.
- Retention schedule: non-members within 1 year of application closing date; members within 7 years of application closing date.
- Privacy Officer contact: `privacy@pentacoop.com`, with a stated 10 business day response window.

The application has 9 sections:

1. Application introduction and consent
2. Applicant and co-applicant details
3. Ineligible household-size message
4. Children
5. Current housing situation
6. Tell us more about you
7. Employment information
8. Household income
9. Declaration

The applicant/co-applicant section asks for applicant name, age, phone, and email; co-applicant name, age, relationship, phone, and email; and number of children under 18 living in the unit on the move-in date. Child-count options are `0`, `1`, `2`, `3`, `4`, and `More than 4`.

The form contains an ineligible branch titled `Sorry...` that says the current unit accepts families with at least 1 child and at most 4 children, invites people to use the mailing list, and restates unit-size requirements:

- 1 bedroom: 1 or 2 adults
- 2 bedroom: 1 or 2 adults plus 1 or more children under 18
- 3 bedroom: 1 or 2 adults plus 2 or more children under 18

The children section collects first name, last name, and age for up to 4 children, ordered from oldest to fourth oldest.

The housing section asks for address, whether the applicant has lived there for at least 2 years, whether the applicant owns real estate, current landlord contact, and previous landlord contact. The form explains that landlord reference checks are required before membership acceptance, will be performed only if selected for interview, and that owner-occupiers should enter their own contact information. Applicants who moved less than 2 years ago are asked to include previous landlord information.

The essay section tells applicants that members must share responsibility for operating and maintaining the co-op, attend the AGM and special general meetings, serve on one or more committees, and attend committee meetings. It says willingness to participate is a decisive selection factor and encourages detailed answers.

Essay questions are:

- Please introduce yourself and your family, including your employment background, interests, and values.
- Please tell us about any skills you and the co-applicant could actively contribute to the running and maintenance of the co-op.
- Please tell us about any previous co-op experience you or the co-applicant may have.
- Describe why you want to live in a co-op and in what ways you would be a valuable member to the co-op.

Optional questions are:

- Link to a photo of the applicant and household.
- Pets description. The form notes that the co-op pet policy allows one dog and one cat, of a size and type subject to Board approval.

Employment information asks for applicant and co-applicant job title, company name, start date, manager name, manager phone, and manager email. The form explains that employer reference checks are required before membership acceptance, will happen only if selected for interview, and self-employed applicants should enter their own contact information.

Household income asks for yearly before-tax gross income for applicant, co-applicant, and total household. Gross income includes employment and self-employment, investments including capital gains, social assistance/government benefits/pension, support payments, rental income, and RRSP income. If called for interview, adult household members must provide proof of income such as current pay stub, most recent income tax assessment, and employer salary letter. If shortlisted, the management company will carry out a credit check.

The declaration states that applicants understand:

- Minimum $1,000,000 personal property and liability insurance is mandatory.
- Share purchase is due at approval: $2,000 for 1 bedroom, $3,500 for 2 bedroom, or $4,000 for 3 bedroom.
- First month housing charge and monthly housing charge arrangements are made with the management company.
- References will be requested for shortlisted applicants.
- Accepted members agree to comply with the co-op Rules, Occupancy Agreement, and Policies.
- Information may be verified, including landlord, employment/income, and credit checks.
- Incomplete or false information is grounds for immediate termination of membership.

The final declaration checkbox text is: `I / We have read and agree to be bound by the conditions outlined above`.

Current application response columns include applicant/co-applicant identity and contact fields, household children fields, current address + duration, real-estate ownership, current and previous landlord references, the four essay fields, an optional household photo link, pets description, applicant/co-applicant employment fields, applicant/co-applicant/household gross yearly income, and the declaration. (Full column-by-column detail: [docs/form-field-reference.md](docs/form-field-reference.md).)

## Email List Form

The email-list form is titled `Penta Co-operative Housing: Email List`. It explains that applications are not currently being accepted, Penta no longer maintains a wait list, and paper applications are no longer processed. Applicants can provide an email address to receive a one-time notification when applications open (a unit generally becomes available every 2–3 years). One required checkbox question — "Please notify me when a unit of the following size is available" — with the three unit-size options (1 bedroom: 1–2 adults; 2 bedroom: 1–2 adults + 1+ children under 18; 3 bedroom: 1–2 adults + 2+ children under 18). Response columns: Timestamp, Email Address, requested unit sizes, month/year grouping.

## Prior Email Templates

The prior email templates establish these operational rules and tone:

- Applications are opened for a specific unit size, housing charge, target move-in date, and close date.
- For a 2-bedroom opening, stated eligibility was one or two adults and at least one child under 18.
- Email-list notifications are treated as one-time notifications; recipients without an existing application are removed from the mailing list after notification.
- People with applications already on file are told they will be considered and do not need to act, but may submit a new application.
- Declined applicants may have applications kept on file until a stated expiry date and considered for another unit before then.
- Applications are deleted after about a year in line with privacy policy.
- Penta does not maintain a waitlist; applicants are invited to apply only when a unit becomes available so information is current and applicants are actively looking.
- The tone is warm, concise, and co-operative, signed by the Penta Membership Committee.

## Product Concept

The screener proceeds in phases:

1. Import and normalize application data from Google Sheets.
2. Apply deterministic hard filters without AI.
3. Use AI to flag data-integrity concerns and discover the dimensions the pool varies on.
4. Let the committee weight those dimensions (a tier-list), re-sorting the ranked pool instantly.
5. Produce a MOMI-ready report with recommended interview candidates and justifications.

The screener supports multiple MOMI committee members running their own screening sessions independently (see "Multi-Member MOMI Workflow"). Each member may value different criteria; the app preserves and summarizes each member's criteria, shortlist, and rationale so MOMI can compare both applicant recommendations and the values behind them.

## Screening Scope

The screener should be configurable for any Penta unit size, but the current search is for a 2-bedroom unit with an expected move-in date of September 1, 2026.

The application form is responsible for collecting complete applications. The screener focuses on what happens after applications have been submitted.

## Dashboard

The app provides a dashboard summarizing the current application pool and screening state: total submitted applications, eligible applications after deterministic hard filters, filtered-out applications with reasons, applications ready for AI review, currently qualified applications, and the ranked shortlist. Every submitted application remains visible somewhere; deterministically disqualified applicants are excluded from AI review but remain accessible in a filtered-out view with their reasons.

## Sync And Run Records

The app uses a hybrid live-sync/run-record model:

- While applications are open, the app may sync live from the Google Sheets response spreadsheet.
- Once serious screening begins, each screening run records the application set and source sync state used for that run.
- The dashboard shows any new applications submitted after the run's recorded source sync state.
- Users can add newly synced applications to an existing run by updating the run record.
- Reports reference the exact sync/run record used.

Immutable snapshots are not required. This preserves convenience during intake while keeping screening decisions and reports understandable.

## Deterministic Eligibility Rules

### Rules Engine Architecture

The screening rules system is a configurable rules engine. Each rule is a discrete, named validation that produces a binary outcome: the application is either `eligible` or `filtered_out`.

Each rule has:

- **ID**: machine-readable slug (e.g. `owns_real_estate`, `child_age_over_max`)
- **Display name**: human-readable label shown in the admin UI
- **Description**: explains what the rule checks and why
- **Outcome**: `filtered_out` (the only outcome — any rule that fires disqualifies)
- **Parameters**: configurable thresholds or values (e.g. income min/max, min/max children, max child age, max pets). Not all rules have parameters.
- **Enabled**: toggle on/off per screening configuration

Rules are stored in the database as part of admin settings. The Admin settings UI shows the full rule list with toggles and parameter inputs. Disabled rules do not run during screening.

Adding a new rule requires code (a rule function that takes normalized application data and returns pass/fail with a reason). Once the code exists, the rule appears in the admin UI and can be configured. The rule logic is simple enough to add, and the admin controls which rules are active and what thresholds apply without code changes.

Rules run in a defined order. An application that fails any enabled rule is `filtered_out`. An application that passes all enabled rules is `eligible` and proceeds to AI screening. The pure logic lives in `app/domain/hard_filters.py`, separate from HTTP/ORM/Google concerns.

### Rule Catalog

**Household composition rules:**

| Rule ID | Description |
|---------|-------------|
| `child_count_mismatch` | Declared child count does not match the number of complete child detail blocks (first + last name + age all filled). |
| `too_few_children` | Household child count is below the configured minimum. Parameter: min_children (default 1). |
| `too_many_children` | Household child count is above the configured maximum. Parameter: max_children (default 4). |

**Age rules:**

| Rule ID | Description |
|---------|-------------|
| `child_age_over_max` | Any listed child is older than the configured maximum child age. Parameter: max_child_age (default 17). |
| `applicant_under_min_age` | Applicant age is under the configured minimum adult age. Parameter: min_adult_age (default 18). |
| `co_applicant_under_min_age` | Co-applicant age is under the configured minimum adult age (default 18). |
| `child_age_exceeds_parent` | Any child's age is older than the applicant's or co-applicant's age (data entry error; a sanity check against the household's own adults, not the policy ceiling). |

**Financial rules:**

| Rule ID | Description |
|---------|-------------|
| `income_below_range` | Household gross income is below the configured minimum. Parameter: min_income (default $70,000). |
| `income_above_range` | Household gross income is above the configured maximum. Parameter: max_income (default $150,000). |
| `income_arithmetic_mismatch` | Applicant income + co-applicant income does not exactly equal the stated household total. No tolerance. |

**Property rules:**

| Rule ID | Description |
|---------|-------------|
| `owns_real_estate` | Applicant owns real estate. |

**Data integrity rules:**

| Rule ID | Description |
|---------|-------------|
| `negative_number` | Any whole-number-validated field (age, income) contains a negative value. |
| `future_employment_start` | Employment start date is in the future. |
| `co_applicant_incomplete` | Some co-applicant fields are filled but others are blank (partially filled). |

### Rule Behavior Notes

- Living at the current address for less than 2 years is not disqualifying.
- Applicants outside Vancouver, BC, or Canada are eligible.
- Applications should be complete at submission time. The screener does not create applicant follow-up workflows.
- Applicants with an application already on file are not treated differently.
- Email-list signup date and notification history must not influence screening.
- For child age calculations, use age on the move-in date when a date is needed. A child turning 18 shortly after move-in does not matter.

### Application Status Model

Each application has a single mutable **status** with exactly two values:

- `eligible`: in the running, proceeds through screening
- `ineligible`: not in the running

Status is set by an actor, recorded in **`status_source`**:

- `untouched`: no actor has acted on it — it passed the rules and either AI has not run or AI did not flag it. The default for a clean eligible application.
- `rules`: the deterministic filters set it `ineligible` (high trust)
- `ai`: the AI screening pass set it `ineligible` (lower trust — the "needs review" bucket)
- `human`: a person set the status, in either direction

Only an actor that *acts* stamps itself. Rules passing an application through, or AI declining to flag it, leaves it `untouched`. Only a human can move an application from `ineligible` back to `eligible` (or the reverse).

There is no third status. The UI surfaces the `status_source = ai` group as an "AI Flagged" view, composed client-side as a filter over the real columns. This keeps status binary while distinguishing high-trust deterministic exclusions from AI exclusions. The labeling is deliberately factual ("AI Flagged" — what happened), not prescriptive. The backend never names these views; it returns counts and filters keyed by the real `status` and `status_source` columns, faceted so impossible combinations read zero.

**The "why" is kept separately as immutable records**, never mutated by a human:

- deterministic **filter reasons** (e.g. `Household gross income ($164,000) is above $150,000.`)
- **AI screening flags** (category, summary, evidence)

A human flipping the status never deletes these records — an applicant can be `eligible / human` while still showing the AI flags a reviewer chose to accept. This preserves the audit trail.

**Stickiness:** a machine actor (rules or AI) must never overwrite a `human` status. On re-sync or re-run, machine actors refresh the reason/flag records but leave a human-set status untouched.

**Clearing an override:** a human override can be removed, handing the decision back to the machine. Clearing recomputes the status from the *current* findings (rules then AI) and resets `status_source` to the machine source. The detail view models this as source ownership: a segmented **Decided by** control over `Automatic | Eligible | Ineligible`, where "Automatic" is selected whenever `status_source != human` and selecting it clears the override. The detail payload carries `autoStatus`/`autoStatusSource` (what the machine would decide right now). Clearing is idempotent.

**Staleness nudge:** because human decisions are sticky, a re-run can surface new findings on an application a human already cleared. When the machine records change after a human's review, the application is marked stale ("new findings since last review") so the reviewer can re-decide. Status does not move; staleness is derived by comparing the latest machine-record timestamp to when the human set the status.

### AI Screening (Integrity Flags)

Separately from eligibility, AI makes a screening/integrity pass over eligible applications to flag suspicious patterns too subjective or contextual for deterministic rules. When the AI pass flags an eligible application, it sets the status to `ineligible` with `status_source = ai` (the low-trust AI-excluded group) rather than excluding it outright. A human reviews these and either confirms the exclusion or restores the applicant to `eligible`. The flags are kept as immutable records regardless.

The pass also re-analyzes applications a *previous AI pass* marked ineligible, so a revised prompt can change the verdict in either direction. Applications the deterministic rules disqualified are excluded (rules outrank AI). Human-set statuses remain sticky.

Known patterns to detect (intentionally incomplete; grows over time):

- Child names that look like placeholders ("Baby", "TBD", "N/A", "Test")
- Applicant or child names that appear fake or nonsensical
- Essay responses that are suspiciously short or minimal
- Essay responses that appear to be advertising or spam
- Essay responses that appear to be AI-generated boilerplate with no personal detail
- Responses copy-pasted across multiple essay fields
- Internal inconsistencies between essays and other fields
- Phone numbers or emails that appear fake beyond format validation
- Pet descriptions that violate the co-op pet policy (more than 1 dog, more than 1 cat, or exotic/unusual pets — free text, too ambiguous for deterministic parsing)

AI screening flags are stored per-application and shown in the candidate detail view as informational notices, not filter reasons. Implementation depth: [docs/ai-screening.md](docs/ai-screening.md).

## AI-Assisted Screening

AI review runs only for candidates who pass deterministic hard filters (or are resolved eligible by a human). The full pipeline and file layout are in [docs/ai-screening.md](docs/ai-screening.md); the significant decisions are in [docs/adr/](docs/adr/). This section is the product-level current state.

### Provider And Cost Controls

The AI architecture is provider-adaptable behind an internal `AIProvider` interface — Amazon Bedrock (via Strands) is the implemented provider, with a deterministic `MockProvider` backing tests (no AWS). Direct OpenAI/Anthropic providers can be added later without touching callers. Model IDs are Bedrock inference-profile IDs (`us.`/`global.` prefixed). See ADR 0010.

Cost control is a core requirement. The app prefers: cached AI analysis per application and per run; smaller/cheaper models for high-volume passes and frontier models only for cross-document synthesis; short structured outputs; a visible AI cost estimate before running; and a configurable per-run spending cap (default `$2.00`, enforced against the estimate before any model call — an over-cap run fails fast with 402). Hard filters run automatically after import/sync; AI review starts only after the user sees the estimate and confirms.

### Interactive Screening And Ranking

The screener discovers the differentiating dimensions of *this* pool rather than starting from a fixed rubric, then lets the committee weight them. It is a screening assistant for a human, not an autonomous filter.

**The assistant does not "cut" candidates.** At ~300 applicants, hard removal is the wrong model. Instead it **stack-ranks the entire qualified pool with a per-row rationale**, and the committee's weighting re-sorts that list. Re-weighting adjusts standing (soft ranking), never removes anyone; the committee reads the stack rank top-down with no fixed cut line. Re-weighting is freely reversible.

**The committee expresses what matters with a tier-list maker** (`@dnd-kit`): the discovered dimensions are draggable chips sorted into self-defined importance tiers (Critical/Important/Minor by default, plus an Ignore zone), and the ranking re-sorts instantly as deterministic math over the cached scores — **no model call per change**. This replaced sequential pairwise narrowing questions; see ADR 0006. A future "Criteria Coach" may *ask* questions to help the committee reflect on the weighting they built (not to elicit it).

**The defining architectural decision (ADR 0005): the LLM extracts scored features; ranking is deterministic math on top.** The model scores each candidate on the discovered dimensions and never opines on importance. Weights start equal (an honest "no judgment yet" baseline) and only the committee's tiering moves them, so every deviation traces to a recorded human choice, and a weighting change re-runs only the math over cached scores.

The Rank chain is exposed as a **single button** — the committee never runs the sub-passes individually. In order:

1. **Pattern discovery** (synthesis model, ×K in parallel): reads the whole eligible pool (facts + raw essays) and discovers the dimensions it varies on — name, definition, why-it-differentiates. K blind fresh-context calls; their cross-call disagreement is diversity the next step needs. Committee proposals seed one worker. Targets 5–25 dimensions (empirically ~14–16), biased to split, anti-padding. Dimensions are **oriented so more-is-better fit** (no direction flag — see ADR 0004); "goldilocks" axes reframe to a monotonic concept or split into two more-is-better dimensions.
2. **Decomposition** (synthesis model): settles the K overlapping reports into one finest, non-overlapping set — collapses re-carvings of one concept, keeps genuinely distinct axes apart, protects committee-requested axes (a `from_committee_request` axis has a higher bar to merge away, with a deterministic backstop). See ADR 0007.
3. **Identity matching** (synthesis model): maps this run's dimensions onto *all prior runs'* by meaning, so a re-discovered concept re-adopts its old key and carries its tier placement + cached scores forward. A high bar (a wrong match corrupts a reused score), erring toward "new."
4. **Dimension scoring** (first-pass model, per candidate): scores each applicant on the signed **−1..+1** scale per dimension, with rationale, grounding evidence, and a confidence label. Silence scores 0 (never negative) — see ADR 0009. The per-dimension rationale + evidence is this pass's observability (no separate call-level narrative). Cached per (candidate, dimension) under `dimension_scoring:<dimension_key>`, so matched dimensions reuse scores by key across re-ranks and only new/unmatched ones are re-scored.
5. **Consolidation** (synthesis model): post-score cleanup — near-identical score vectors *nominate* suspected duplicates the definition-only match pass missed (Pearson ≥ 0.8), and one confirm call merges genuine ones by definition (aliasing the newer key to the older, so the key space converges). Distinct axes that merely correlate are kept apart. `dimension_aliases` is the durable merge-truth.

Then the ranked list is **pure deterministic math** (`app/domain/ranking.py`): fit is the weight-normalized average of a candidate's dimension scores, `Σ(weight·score) / Σ(weight)`; weights are derived from the tier layout (never stored); qualitative bands ("Strong fit" … "Limited") are relative to the pool (rank position), not absolute thresholds; confidence is surfaced next to each score but never folded into fit. The candidate detail page selects/orders per-dimension contributions by `abs(impact)` where `impact = weight × (score − pool_mean)`, so a heavy strike surfaces as readily as a strength.

**Two Rank modes.** *Discover new criteria* runs the full chain and may replace the criteria set. *Score missing applicants* runs only scoring, for eligible applicants missing a current-dimension result — preserving the run's dimensions and tier layout, independently cap-gated. Complete score coverage makes the retained criteria current for the changed pool.

**Cost gating and staleness.** The whole chain is gated on a **rank-inputs fingerprint** (`Analysis.rank_inputs_fingerprint`, an indexed column — a hash of the eligible pool *plus* each rank-chain prompt and model). If unchanged, the UI flags "up to date"; a re-run is still allowed (discovery is nondeterministic, so a member may want a fresh criteria set — the confirmation card explains nothing requires it). The workflow strip is three single-verb steps — **Import** (sync + hard filters), **Screen** (the AI integrity pass), **Rank** (this chain) — each amber-stale by the same signal its no-op gate uses (Import on a settings fingerprint, Screen on coverage, Rank on the rank-inputs fingerprint). Every AI step opens a confirmation card before running, even when there's nothing to do. Rank streams phase-aware progress; the opaque criteria/consolidation calls stream the model's live reasoning as a "thinking" panel. A completed Rank lands the user directly in the ranked view.

### Ranking And Outputs

The primary output is a ranked list. It is explainable and preserves evidence behind each recommendation. AI produces qualitative labels for user-facing screening; hidden internal scores support ranking, but the UI explains rankings in plain language rather than centering numeric scores. AI summaries use a neutral committee tone and stay transparent enough to detect bias or unsupported claims. Direct essay excerpts are used sparingly; entire essays are never reproduced in summaries or reports.

For debugging and learning, raw AI analysis, traces, prompts, and intermediate outputs are accessible to any logged-in member (the Observability tab + candidate detail pages). Each screening run is saved with its criteria, prompts, model outputs, ranking outputs, and shortlist. AI output schemas are defined in `app/ai/schemas.py`, shared by prompt, storage, API, UI, and evals.

### Essay Judgment

Strong negative essay signals include (not limited to): the applicant appears unaware of co-op obligations; treats the unit mainly as cheap rent without understanding shared work; expresses hostility or resistance to shared work; has an unclear or inconsistent household situation. Essay concerns may justify a "do not interview" recommendation — essay review is central, not a low-priority flag. Brief, awkward, translated, or non-native English answers are **not** penalized for writing polish; the AI judges evidence of co-op fit, participation commitment, and relevant signals rather than style or fluency. (The differentiating criteria are *discovered* against the pool at Rank time, not pre-committed; a standalone essay-analysis pass was built then removed — see ADR 0001.)

### Observability And Evals

The pipeline makes real, non-deterministic model judgments, so it is instrumented across four pillars (build history in CHANGELOG M13; grader design in ADR 0008 and [docs/ai-evals.md](docs/ai-evals.md)):

- **Cost** — an Observability "Cost" subtab: cumulative and last-run AI spend, per pass, with a token (in→out) + model breakdown and estimate-vs-actual reconciliation. All cost accounting flows through one `PassCost` value object into `run_cost_ledger` + `run_pass_cost`, which both Screen and Rank write and both surfaces read.
- **Per-pass AI trace viewer** — each pass's raw output is legible: per-application (screening flags, scoring rationale/evidence) on the candidate detail page; per-run (discovery, decomposition, matching, consolidation audits) on the Observability subtabs.
- **Operational metrics** — an Observability "Trends" subtab: per-run/per-pass cost, tokens, wall-clock latency, cache-hit rate, failure count, and dimension count over time.
- **Evals** — run in-app from the **Evals** tab, never gating a commit:
  - **Invariants** (deterministic, the only CI gate): things always a bug — every dimension has distinct high/low poles; no criterion keys on a protected class. "Re-baseline from current Rank" records the blessed fixture.
  - **Live per-pass evals** — each pass's golden cases fed through the *real* production prompt and graded by a grader matched to the output shape (categorical → exact-match; scoring → a band; screening → per-category), with a `?mode=stability` K-repeat run measuring verdict flips. See ADR 0008.
  - **Judge** — a blind label-auditor: an independent model reproduces each pass's output from an editable per-pass brief + the case's input, blind to the label; the harness grades it against the human label with that pass's own grader. Agreement (κ, failure-recall) calibrates the judge; a consistent disagreement flags the *label*. Run occasionally, not per-run. See ADR 0002.

Applicant-facing eval cases are protected by a synthetic-source guard (`require_synthetic_pool` refuses any run not traceable to an allowlisted synthetic sheet). Fixtures are PII-safe (opaque column indices; narratives/`why_it_differentiates` stripped). Golden sets are grown with the harvest scripts under `backend/scripts/` (co-authored, then labelled by hand).

### Agent Workflow

The application is *designed as* a multi-agent system, but the agents are a conceptual decomposition, not a mandate to build orchestrated LLM loops everywhere. **The realized architecture is a pipeline of single-purpose passes + human gating.** Each "agent" is a named, user-visible pass — deterministic code (hard filters, ranking math) or one structured-output call (screening, discovery, decomposition, matching, scoring, consolidation). State lives in the database between passes; orchestration is the human clicking gated workflow steps plus deterministic control flow. No LLM decides what runs next. This is deliberate: pre-run cost estimates + a cap, per-(candidate, kind, prompt-version) caching, auditability, eval-replayability, and reproducible structured output all depend on the call graph being known in advance.

Genuine multi-agent coordination is reserved for spots with a feedback/revision loop that a fixed pipeline can't express, added surgically and kept **bounded** (generate→critique→retry-N, not open-ended): a future `Evidence Auditor` (checks recommendations are grounded, sends weakly-supported ones back), the `Criteria Coach` (reflects on the committee's weighting), and a `Screener-Evaluator` (evaluates the system across runs and proposes human-approved, versioned improvements — schemas/prompts are never self-modified at runtime). A `Coordination Agent` becomes worthwhile only once two or more such loops run in one session. (The fan-out discovery redesign considered a multi-agent merger↔splitter loop and rejected it on measurement — ADR 0007.)

Every AI recommendation is reviewable and overrideable, and explains why a candidate advanced rather than only providing a numeric score.

### Privacy, Auditability, And Evals

It is acceptable to send full application context, including names/contact context, to the AI model. Redaction is not required. Applicant data is still treated as sensitive: deterministic filtering stays separate from AI judgment; prompts, model outputs, filter decisions, ranking rationales, and overrides are auditable; the app does not write back to source Google Sheets. The eval-oriented design (fixtures, schema-consistency checks, grounding/evidence-quality tracking, enough trace data to debug regressions) is built and described above.

## Multi-Member MOMI Workflow (Milestone 15)

**M15 is an *isolation* feature, not a merge feature.** Each of the ~5 committee members screens independently — their own eligibility rules, eligibility overrides, dimension tiering, ranking, and notes — layered on a **shared, compute-once substrate**: the applicant pool, the AI-discovered dimension set, and the expensive per-(applicant × dimension) scores. Members bring their own lists to a meeting and debate live; the app does **not** merge, compare, or reconcile them. (This supersedes the earlier merged-shortlist design — there is no merge formula, no disagreement flag, no criteria-comparison surface, and no cross-member visibility inside the app.)

**Shared / per-member boundary:**

| State | Scope | Notes |
|---|---|---|
| Applicant pool + sync | shared | one source of truth |
| Discovered dimension set | **shared union** | grown by any member's Rank, de-duped by the existing match pass + `dimension_aliases` |
| Per-(app, dim) AI scores | **shared** | content-addressed cache key has no member id — sharing is automatic |
| Cost ledger / traces / evals | shared | + a "triggered-by member" stamp per run; Observability stays committee-wide |
| Eligibility **rules** (income/age/children/pet thresholds, `disabled_rules`) | **per-member** | one shared committee default; a member's row is copy-on-write, created only when they diverge |
| Eligibility **overrides** (per applicant) | **per-member** | |
| Tier placement + ranking + new/revived/requested badges | **per-member** | weights stay **derived** from tiers, so per-member re-weighting is free math |
| Notes | per-member | already are, today |
| AI/model/cap/sheet settings | shared | infra config, not judgment — split out of the eligibility-rules blob |

**Union eligible pool.** An applicant is **globally eligible** if they pass *any* member's effective screen (that member's rules *or* an explicit override) — a derived predicate over the per-member views, not new stored state. Discovery and scoring operate on this union floor; **globally ineligible** applicants (no member passes them) are never scored — preserving "don't score applicants who won't clear the screen." A member's ranked list is the shared analysis **filtered to their eligible view and weighted by their tiers** — pure math, instant, free.

**How cost stays low (the payoff).** The score cache keys on `(raw_row_hash, dimension_key, model, prompt_version)` with no member id, so sharing rides on *applicant identity*, not pool identity. An applicant scored once (because any member ranked them eligible) is free for every other member who later includes them. **Staleness is per-member**, and reduces to a cache-gap check: a member sees "re-rank needed" only when their eligible view references an applicant not yet in the shared analysis. Member A marking applicant X eligible ambers only A's badge; once A runs it, X grounds discovery + gets scored, and B — including X later — rides the cache with no new spend. The only real AI cost is an applicant entering the union for the first time (or a rank-chain prompt/model change). A new shared dimension surfaced by one member's Rank lands on every board at **weight 0** (inert until that member tiers it), so it costs others nothing until they opt in. **Screening staleness works the same way per-member:** a member's eligibility-rule values fold into their screening prompt version (as the pet policy already does — see the versioning rule), so changing rules flips that member's screening cache while others' stays valid; members whose rule values coincide share the screening cache automatically. Staleness is detectable the moment an applicant enters a member's view — the amber signals uncached work waiting, before any run.

**Dimension survival on re-rank:** the shared set keeps any dimension in **any** member's working tier; a dimension drops only when no member has it working-tiered.

**Committee-proposed seeds** feed the one shared discovery (the resulting axis is shared), but the "you requested this" badge shows only for the requesting member (`from_committee_request` provenance is already per-run).

**Out of scope (M15):** merged shortlist, disagreement flags, criteria comparison, and cross-member list visibility. Notes remain private to their author, out of AI inputs and reports, on the author's printed candidate detail only. (`require_admin` + the allowlist landed in M15 1a; broader role exercise is M17.)

*(The per-member-pool / shared-content-cache decision is recorded in [ADR 0011](docs/adr/0011-per-member-eligible-pool-shared-content-cache.md); the sliced build history — allowlist, the `Analysis`/`MemberRanking`/`MemberEligibility` split, per-member rules, pets-as-facts, and the committee-union re-rank — is in [CHANGELOG.md](CHANGELOG.md) M15.)*

## Users, Roles, And Authentication

The MVP uses real Google login (multi-member screening is a major design requirement). Access is invitation/approval based when live; Jeff is the initial admin and can invite MOMI members. Roles:

- `Admin`: the initial account; will gate user management once invitations are built.
- `Member`: a MOMI committee screener — screens independently (own eligibility rules, overrides, tiering, ranking, notes) over the shared cached AI substrate; no merged comparison surface (M15 is isolation, not merge).

Every committee member is a trusted screener, so **the core screening workflow has no admin-only surface** — the raw source row and the raw AI narrative are available to any logged-in member (the outsider-vs-screener boundary is the primary trust boundary). M15 adds a *second*, intra-committee boundary: each member's eligibility rules, overrides, tiering, and ranking are **private per member** — shared artifacts stay open to all, personal judgment does not. The `Admin`/`Member` distinction is now load-bearing (M15 1a): admission is by an **email allowlist** whose entry role becomes the `User`'s role (the "first login = admin" rule is retired), and `require_admin` gates the genuinely admin-only surfaces — the allowlist itself, the committee-default rules, Admin Settings, and the Observability/Evals tabs. The Access subtab records successful allowlisted Google sign-ins and shows an account's name, email, role, first and latest sign-in, and sign-in count. Below it, a separate denied-attempts table aggregates unallowlisted Google login attempts by account and retains them for one year. Neither surface collects browser activity, IP addresses, devices, or OAuth tokens. The engineering default remains `require_current_user`; a role gate is added only for a genuinely admin-only capability, as a deliberate decision.

AI screening results are shared across users and cached per application content, model, and prompt version. Any logged-in member may run the checks; the cost concern is uncached work, not which member initiates a shared run.

## Screening Runs

Users may create multiple runs for the same pool ("Jeff first pass", "Jeff revised after thinking"). Runs preserve enough source information to understand what pool was used (a sync/run metadata record; no immutable snapshots). When criteria are revised after a completed run, the default is to update the same run, with the option to create a separate new run. Manual candidate notes are private to their author. AI-generated criteria summaries need no dedicated editing workflow, and an audit log is not required, for the initial design.

## Data Storage

- Google Sheets is the external source of truth for submitted applications.
- Application rows import into the app database for screening runs, AI outputs, notes, rankings, and reports.
- SQLite, and it **stays** for go-live: M17 hosts it on a persistent volume rather than moving to Postgres (ADR 0012), because at the expected ~5-member committee with light concurrency (hardened in M16 via WAL + a run lease) the data layer needs no change. The relational model is kept portable to Postgres should real growth or the deferred atomic-budget feature later warrant it — but that is explicitly *not* an M17 concern.
- Spreadsheet access is minimized — import/sync rows, then use the app DB for screening state.

Core data model:

- An `Application` represents one household/application (applicant, co-applicant, children, essays, references, income, pets, declaration, source + screening metadata). The raw Google Sheets row is preserved exactly as JSON alongside normalized fields.
- Primary application identity is the primary applicant email (normalized: trimmed + lowercased); each application also has an internal DB ID. Duplicate detection is by email; the newest row wins.
- Normalized fields computed at import/sync: `adult_count`, `child_count`, `children_under_18_at_move_in`, `has_real_estate`, `household_income`, `pet_count`, `pet_types`.
- Each sync creates a `SyncRun` record (timestamp, source sheet ID, `settings_fingerprint`). It records no eligibility tally — eligibility is a per-member on-read derivation now, so an import-time committee tally would be misleading.
- A shared `Analysis` (one current, `get_current_analysis()`) holds a Rank's discovered dimensions (`dimension_report`) and the `rank_inputs_fingerprint`; its 1:1 `analysis_audit` child holds the AI-legibility trail (discovery narrative + match/fan-out/decompose/consolidate audits) so the hot read path stays lean. The committee's mutable view is **per-member** in `MemberRanking` (member × analysis: `run_state` = tiers + new/revived/requested flags + pending proposals; weights are **derived** from the tiers, never stored). Per-member eligibility overrides live in `MemberEligibility` (member × applicant); a member's diverged eligibility rules in a copy-on-write `member_rules` row over the shared `committee_default_rules`. `dimension_aliases` is the sole merge-truth. Per-run/per-pass cost lives in `run_cost_ledger` (+ a nullable `triggered_by_user_id` attributing each shared run) + `run_pass_cost`; eval runs in `eval_runs`. (Schema layout: [docs/app-architecture.md](docs/app-architecture.md); the M15 per-member split: CHANGELOG M15; the M14 split of the old `criteria` blob: CHANGELOG M14 Phase 5.)

Settings live in the database, not `.env`, split by audience (M15): **Admin Settings** (shared infra — Google Sheet link/ID, AI spending cap, model choices, discovery fan-out) and per-member **Eligibility Settings** (income/age/children thresholds, pet limits, per-check toggles — over a shared committee default). Local `.env.local` holds secrets; `.env.example` holds safe placeholders. Never committed: `.env` files, OAuth credentials, SQLite DB files, applicant exports, AI traces, and raw prompts/outputs containing applicant data. During MVP iteration, local schema changes need no backward compatibility — deleting and recreating the SQLite file from migrations is acceptable.

## Reports

**The report format is the browser's print-to-PDF of the ranked view (Milestone 10).** The committee opens the ranking and clicks **Print**; the print stylesheet hides interactive chrome (`no-print`) and renders a clean artifact: the ranked shortlist with each candidate's band and rationale, plus a text **importance-tiers summary** (`TierSummaryForPrint`) so a reader sees which dimensions sat in which tier. The candidate detail page is independently printable.

This replaced the originally-planned Google Docs generation — print-to-PDF needs no Docs/Drive scopes, no second OAuth consent, no generated-file storage, and no "regenerate on change" story (the document is a live render). A Google Docs export could return later if a committee wants an editable, collaboratively-commentable artifact.

## MVP Shape And Tech Stack

The MVP is a web app that runs locally in the browser: a **Python/FastAPI** backend, a **Vite + React/TypeScript** frontend, **SQLite** (SQLAlchemy + Alembic), **Google OAuth** with signed server-side session cookies, read-only **Google Sheets** import/sync, and **Amazon Bedrock** (behind the provider-agnostic interface). Python deps via `uv`; frontend via `npm`; backend tests via `pytest`.

Google setup: a dedicated Google Cloud project; OAuth app named `Penta Application Screener`; scopes are the minimum the workflow needs — basic login profile/email + Google Sheets read-only (no Docs/Drive; reports are print-to-PDF). Local redirect URLs may use localhost. Once user management exists, login is restricted to invited/approved emails. Setup is documented in [docs/google-cloud-oauth-setup.md](docs/google-cloud-oauth-setup.md).

The settings surfaces (M15): **Eligibility Settings** (per-member) covers income range, min/max children + max child age, min adult age, pet limits, and per-check toggles; **Admin Settings** (admin-only) covers the AI spending cap, provider/model choices, discovery fan-out, the committee-default rules, the access allowlist, and the Google Sheet link/ID. If required configuration is missing after login, the app directs the user to settings; otherwise the first screen is the dashboard.

Implementation defaults:

- Readability first; avoid redundancy; prefer elegant, boring solutions over clever abstractions.
- Shared business rules, thresholds, field mappings, prompts, and schema definitions have a single clear home.
- Abstractions are added only when they reduce real duplication or clarify an important boundary.
- Clean changes over backward compatibility for internal APIs, local schemas, fixtures, and UI shapes; backward compatibility is added only when real users or real applicant data require it.
- Relational tables for workflow data, JSON columns for raw rows, flexible payloads, AI outputs, and debug traces; the relational model stays portable to Postgres.

**Milestones 1–18 are complete** and proven end-to-end against real Bedrock (sync → screen → discover ~30–35 fact-aware dimensions → score the pool → rank with the tier-list weighting → print a committee-ready PDF), now with per-member independent screening on a shared compute-once substrate, **hosted live at [screener.pentacoop.com](https://screener.pentacoop.com)** for the real committee. Per-milestone detail and every resolved decision/reversal are in [CHANGELOG.md](CHANGELOG.md). The last milestones landed as: **16 (concurrency & correctness — software: run lease, WAL, stale-view detection)**, **17 (hosting / go-live on Fly.io — see [ADR 0012](docs/adr/0012-hosting-platform-m17.md))**, and **18 (least-privilege Google auth — members log in identity-only; an admin links the response sheet via the Google Picker with `drive.file`)**.

## Remaining Open Questions

Decisions that still need making, or can wait until their implementation milestone.

### Reporting (M10 shipped) — ✅ closed, demand-driven from here

The report is the browser print of the ranked view. Three speculative refinements were considered and **deliberately not built** (Jeff, 2026-07-26): near-misses / filtered-out counts / filtered-out details in the print (today it's the ranked eligible pool only); report-specific applicant personal/contact-detail handling for MOMI reports; and an explicit recommendation + `why not selected` surface beyond the per-candidate rationale lines. Rationale: building report features nobody has asked for is speculative scope. The committee now has the app and an in-app **feedback mechanism** — real requests, not guesses, will drive any future reporting work.

### Multi-Member V2 (M15) — ✅ complete

M15 shipped: per-member independent screening on a shared compute-once substrate — no merge/disagreement/comparison surface (the earlier open questions on merge formula, disagreement flags, and criteria-comparison layout were dissolved, not answered). The current-state design is in "Multi-Member MOMI Workflow" above; the decision record is [ADR 0011](docs/adr/0011-per-member-eligible-pool-shared-content-cache.md); the full sliced build history (access allowlist + `require_admin`; the `RankingRun` → shared `Analysis` + per-member `MemberRanking`/`MemberEligibility` split; per-member eligibility rules over a committee default; pets-as-deterministic-facts; committee-editable defaults + member reset; the two-phase-mental-model restoration; committee-union re-rank; and the observability triggered-by stamp) is in [CHANGELOG.md](CHANGELOG.md) M15.

Two things were intentionally **not** built: per-*requester* proposal attribution (no deterministic proposal→axis-key link exists to attribute on — the shared "Requested" badge stands; see ADR 0011), and a committee-default-version "your default changed" nudge (the live divergence diff already shows current default values). Per-screening-check descriptions ship as info-icon tooltips (`CheckInfo` in `CheckToggles.tsx`, on both the member Eligibility Settings and admin Committee Defaults surfaces).

**How M15 resolved the single-tenant assumptions** (the load-bearing global singletons, now discharged):

1. **"Current run" was global-latest-wins** — the old `get_current_run` was `SELECT … ORDER BY id DESC LIMIT 1`, so one member's Rank silently became everyone's. **Resolved:** split into a shared `Analysis` (the AI output, one current, via `get_current_analysis()`) + per-member `MemberRanking` (the view).
2. **Settings was one global row** — `AdminSetting` keyed `"app_settings"`, last-write-wins. **Resolved:** eligibility rules became per-member (shared committee default + copy-on-write `member_rules`); infra config stays one shared row (last-write-wins is acceptable for ~5 trusted members — a concurrency guard is an M16 concern).
3. **The spending cap is per-request, read-then-act** — `enforce_cap` checks each run's own projection, not a shared budget. **M15 kept the per-run cap**; a true atomic shared-budget ceiling is M16 concurrency work (below). At ~5 members the caching (only first-time-eligible applicants cost anything) is the practical cost control.

### Concurrency & Correctness (M16) — software, not infra

Multi-member introduces real concurrent writes. This is a **software** concern (guards, leases, atomic accounting) that stands on its own regardless of where the DB lives — distinct from hosting (M17), which is infra. A multi-member concurrency audit (2026-07-24) classified the hazards; the load-bearing hardening is **done**, and the residual items are deliberately deferred (rationale below).

**Done (2026-07-24 → 25):**
- **Reads are safe by the shared-union design** — the screening/scoring cache is content-addressed with no member id, so after one member runs Screen/Rank every other member sees the result (their amber turns green) with no action and no re-bill; a no-op run is blocked (`unchanged_pool`). This is ADR 0011 working as intended, not luck.
- **SQLite `WAL` + `busy_timeout=5000`** (`app/db/session.py`) — readers no longer block the writer, and a colliding writer WAITS (up to 5s, retrying) instead of failing instantly with "database is locked". Runs commit per item (short locks), so this covers real overlap. Purely defensive; no behavior change.
- **A single run lease serializes the expensive runs** (`RunLock` + `services/run_lock`) — Screen / full Rank / score-current claim one DB-backed lease (atomic conditional UPDATE, 15-min TTL steal so a crashed run self-heals) and 409 (`run_in_progress`) if another holds it. This closes the one genuinely destructive overlap — two concurrent full Ranks each creating an `Analysis` and last-writer-wins stranding the loser's `MemberRanking` — and also eliminates concurrent-Screen double-billing. DB-backed (not in-process) so it survives multiple web workers under M17. The frontend surfaces the 409 detail as a toast.
- **Tier/seed edits are blocked during an in-flight rank** — a full rank snapshots the committee kept-list once at the start of discovery then supersedes the analysis, so an edit made after that snapshot (e.g. dragging an axis out of Ignore) could neither reach the run nor survive it, silently vanishing. `_require_viewed_analysis` rejects the save (`run_in_progress`, holder-agnostic so it covers the initiator's own run) rather than let the edit persist onto a doomed board.
- **Stale-view detection landed** — the deferred M15 1b "this ranking was refreshed by another member" UX now exists as a global toast with a Reload action, raised both on a `409 stale_analysis` save AND on tab focus/visibility (a cheap current-analysis-id check; no standing poll). Suppressed during the member's own run to avoid a self-inflicted false positive.
- **The settings PUT can't clobber the Picker-owned sheet link** (2026-07-26) — `PUT /settings` sends the whole `AppSettings` blob, but `google_sheet_id` / `google_sheet_reader_user_id` are owned by the link-sheet Picker flow, not the settings form. `update_settings` now keeps the server's current values for those two fields and applies only the AI settings, so a stale form (a second tab open from before a sheet was linked) can no longer null the reader id and silently break sync. This closes the *damaging* half of the settings-concurrency question by fixing field ownership — no version token or migration needed.

**Deferred (deliberate — recorded so it reads as a decision, not an oversight; Jeff, 2026-07-25):**
1. **Atomic shared spending budget** — *deferred, not needed yet.* Its original motivation (N concurrent runs racing past the cap) is **already closed by the run lease** — runs can't execute concurrently, so there's no live race on SQLite today. A true committee-wide budget is genuine feature work needing product decisions (scope: per-period vs lifetime? reset cadence? who sets it? remaining-budget UI?). Since M17 keeps SQLite (ADR 0012), this no longer rides a Postgres move; if built, its atomic accounting would be the trigger to reconsider Postgres, not the reverse. The per-run cap + near-100% cache hit-rate is the working control; the carry-forward validation (below) confirmed real runs stay well under it.
2. **Settings last-write-wins on the AI block** — *accepted (the damaging half is fixed above).* With the sheet-link fields now server-owned, what remains is two admins saving the AI settings (or the committee default) at the same instant — last-write-wins on that JSON, no field merge. Rare and low-consequence at ~5 trusted members (the losing write is a re-typeable AI knob, not a broken integration); optimistic concurrency for that alone is over-engineering. Revisit only if it bites.

### Hosting / Go-Live (M17) — infra — ✅ complete

The committee saw a demo and wanted it, so hosting was real scheduled work — pure **infra**, sequenced after the M16 concurrency software landed. The app is now **live at [screener.pentacoop.com](https://screener.pentacoop.com)** for the real ~5-member committee. The platform decision and its full verified tradeoff analysis (9 platforms priced and timeout-checked, 2026-07-25) live in [ADR 0012](docs/adr/0012-hosting-platform-m17.md); the operational runbook is [docs/deploy.md](docs/deploy.md).

**Decided (2026-07-25):**

- **Platform: Fly.io**, auto-stop Machines (`suspend`, sub-second resume) + a persistent volume — cheapest option (~$1–5/mo, near-zero idle) that keeps the DB on a durable disk. Deploys from GitHub via `fly.toml` + a `.github/workflows/fly-deploy.yml` workflow (push to `main` ships). Custom domain `screener.pentacoop.com` via A/AAAA records + free auto-TLS.
- **Storage: keep SQLite on the volume for launch** (Jeff) — zero data-layer change; fine for ~5 users. Managed Postgres (and M16's atomic-budget store) is a *later* move, only if that feature is built. This retires the earlier "M17 may re-touch the data layer for a hosted DB" tradeoff: at this scale we deliberately do not.

**Shipped (all verified against the deployed app, 2026-07-26):**

1. **Single-origin** — FastAPI serves the built Vite bundle via `StaticFiles` (`app/main.py`), so one origin, no CORS in prod (the frontend calls the API with relative URLs); a two-stage Dockerfile builds the bundle.
2. **Prod-hardened auth/session** — `https_only` cookie (derived from `frontend_url` scheme), real `SESSION_SECRET` + Google client + AWS keys as Fly secrets (never in the image), prod `FRONTEND_URL` / `GOOGLE_REDIRECT_URI` in `fly.toml`. Bedrock uses a static IAM key scoped to `bedrock:InvokeModel` in us-east-1 and its permitted cross-region destinations (no IAM role off-AWS).
3. **Stream heartbeat** — `HEARTBEAT_SECONDS = 15` in `app/api/ranking/run.py` emits a keepalive during the silent Sonnet passes, a 4× margin under Fly's 60s idle timeout on the multi-minute Rank stream.
4. **Auth/roles** — `require_admin` gate + email allowlist (from M15 1a), now exercised under real hosted use across the admin surfaces (settings, allowlist, feedback).
5. **Data protection at rest** — prod backup is scheduled Fly volume snapshots + an on-demand off-box `VACUUM INTO` copy (see deploy.md); the local post-rank auto-snapshot is disabled in prod (`LOCAL_DB_BACKUPS = "false"`).

### Scale-to-Zero Recovery (M19) — planned

**Goal:** return the single production Machine to Fly suspend-to-zero while bounding recovery from a resumed Machine that is running but failing its service health check. Normal suspend/resume remains sub-second; the 5–7-second clean startup applies to a stopped Machine, not a suspended one.

**Why:** on 2026-07-29, Fly resumed the single Machine but it did not become reachable. Fly correctly marked its `/health` check unhealthy and stopped routing requests, but does not restart a Machine merely because a service check fails. The immediate mitigation is one warm Machine; M19 replaces that recurring compute cost with targeted recovery while keeping the fast normal resume path.

**Design:**

1. Production temporarily uses `auto_stop_machines = "suspend"` and `min_machines_running = 0` while M19 is pending; deploy and verify the watchdog before treating this configuration as recovered reliability.
2. Keep Fly's `/health` service check at its existing 30-second interval. Run a small scheduled external watchdog once per minute. It calls Fly's Machines API for this app's current `app` Machine and its service-check state; it must not make an HTTP request to the application, which would wake a suspended Machine.
3. Ignore Machines in `suspended`, `stopped`, or startup states. A `started` Machine with a failed service check is restarted on the watchdog's first observation, then the watchdog reports the recovery attempt. The normal startup grace period and the one-minute watchdog cadence keep a brief clean start from being mistaken for a persistent failure.
4. Store a narrowly scoped Fly deploy token as the watchdog's secret. Derive the target from the app's Machine list rather than hard-coding a Machine ID; never log tokens, application data, or full API responses.
5. Prefer a free Cloudflare Worker Cron Trigger for the watchdog. Its expected workload is 43,200 lightweight checks per month, below the current free allowance; re-confirm provider limits and pricing when implementing.

**Validation and success criteria:**

- Test the watchdog decision table against recorded Machine API responses: suspended → ignored; starting → ignored; healthy started → ignored; unhealthy started → one restart.
- Exercise a controlled restart on an isolated/staging Machine with a persistent volume and prove it returns to a passing service check without data loss.
- Verify a real production suspend/resume remains sub-second under normal conditions, and that a failed health check is detected, restarted, and alerted within one 30-second service-check interval plus one watchdog interval.
- Confirm the watchdog's API polling leaves an idle production Machine suspended; it must not create ongoing Fly compute charges.

**Non-goals:** high availability across two Machines, replicated SQLite, an HTTP uptime probe that keeps the app awake, or hiding a cold start after an intentional full stop. Those are separate availability/cost decisions.

The production Machine currently suspends to zero while M19 is pending. A watchdog bounds the rare bad-resume outage; it does not make a single Machine highly available.

### Least-Privilege Google Auth (M18) — ✅ complete

For eventual Google app verification and to stop showing members a scary Drive/Sheets consent, M18 split the OAuth footprint: **members log in identity-only** (openid/email/profile — no Drive or Sheets scope), and **an admin links the response sheet via the Google Picker**, granting only `drive.file` (access to the one picked file). Sync reads the sheet with that admin's designated-reader token, so members never need a Drive/Sheets scope. The Picker uses the GIS code model (`ux_mode: popup`) exchanged server-side for a refresh token; `setAppId(<project number>)` is required for `drive.file` to authorize the picked file. Prod setup steps are in [docs/deploy.md](docs/deploy.md) §8.

### Validation Experiments On Real Bedrock — ✅ all closed

The mock suite proves plumbing, not judgment, so these judgment-dependent claims were owed on real data. **All are now resolved** (2026-07-26 audit); the earlier-concluded ones — K sensitivity, prompt-output trimming, the convergence experiment — are in CHANGELOG / `docs/case-studies/dimension-convergence.md`. Kept here as the closed record:

1. **Reconcile-era behavior is moot** (that subsystem was deleted; see ADR 0007). No action.
2. **Carry-forward cost win in the wild — ✅ validated (2026-07-25), with a caveat.** Across 17 real rank runs the recorded cache savings grow run-over-run as the pool stabilizes ($0 → ~$1.25/run), confirming per-dimension score reuse works in practice — the core claim. **Caveat found:** the re-rank cost *estimate* is NOT a guaranteed upper bound. It's a recency-weighted **average** of recent runs' actual scoring cost (`recent_pass_fresh_usd`), so by construction it's exceeded roughly half the time (8/17 runs came in over, up to ~142%) — a full discovery re-mints dimensions whose fresh scoring can outrun the historical mean. All runs stayed well under the spending cap regardless. Deliberately kept as an *expected*-cost estimate (the honest number to show at the confirm card) rather than padded into a false ceiling; the true atomic budget guard is M16/M17. Docstrings + this item corrected to say "expected cost," not "upper bound."
3. **Pet-fact extraction accuracy (M15 1e) — ✅ validated on a real run (2026-07-24).** A real Bedrock screening run over the live pool confirmed extraction is reliable across the phrasings that matter: multi-pet ("Three dogs, two cats, and a parrot" → `{3, 2, ['parrot']}`), multiple exotics ("penguin and iguana" → both in `other_pets`), three negation flavors ("I don't have any pets" / "No pets" / "N/A - no animals" → all zeros), and rabbit → `other_pets`. Every spot-check matched the source text. 57 of 58 screened apps carry pet facts on their latest result; the one exception (app 55) is rules-ineligible under the committee default (`child_count_mismatch`), so the screening gate correctly skips it — not a gap. The structural goldens hold against real output; no tuning needed. First real run also re-populated the screening cache under the new `screening_prompt_version()` (old results lacked `pets`).

### UI Consistency Walkthrough (✅ done 2026-07-25)

A systematic tab-by-tab, panel-by-panel walkthrough of the whole UI to find and fix cross-surface divergences — the kind that accrete when tabs/panels are built at different times. Prompted by the settings tabs shipping without the title heading every other tab (Observability/Evals) has (fixed 2026-07-24, but found by eye, not systematically). Closed: a fan-out audit checked every surface against the shared conventions (title heading present; sub-navigation style — the shared `.subtab` underline tabs; heading levels; empty/loading/error states; button placement + labels; `no-print` on interactive chrome; icon sizing) and produced a severity-graded catalog. The clear inconsistencies were fixed in one pass (audit commit `0bbd9a6`): Applications title heading, self-fetch panels' inline error states (a latent stuck-on-"Loading…" bug), `.back-button`→`.secondary-button`, topnav icon size, settings section headings `h3`→`h4`, `.eval-hint`/`.panel-hint` split, the "Saved" tick parity, and ellipsis standardization. The borderline findings were then walked with Jeff (`00bde48`): fixed the Applications empty-state flash-on-load, "Save settings"→"Save configuration", and print-hiding the toast stack; the rest (facet-filter classes, context-driven icon sizes) were accepted as intentional.

### Eval golden ergonomics — pipe-input sugar for any-of `fires` (✅ done 2026-07-24)

A screening golden's `fires` any-of group is stored as a nested list — `[["spam_essay", "minimal_essay"]]` = "at least one of these must fire" — but the eval *displays* it pipe-joined ("spam_essay | minimal_essay", see `fire_label`). That display↔input mismatch was a real footgun: hand-editing a golden, it's natural to type the pipe form back into the data, which is a bare string the grader can't iterate — and it killed the Evals page render once. Closed: `_normalize_fires` in `load_cases` (`app/evals/screening.py`) accepts a pipe-delimited string as sugar for an any-of group (`"a|b|c"` → `["a","b","c"]`, whitespace trimmed), and also tolerates the whole `fires` value being a bare string (the exact mistake) by wrapping it. Plain must-fire strings and existing nested lists pass through unchanged. Documented in `docs/eval-case-schema.md`; tested (`test_normalize_fires_accepts_pipe_input_sugar`).
