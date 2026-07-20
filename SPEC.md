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

The folder also contains `Olga Ahmad Application`, which must not be read or imported for this planning phase.

Google Forms definitions were inspected through the authenticated browser/devtools MCP. The response sheets provide the effective column schema.

## Application Form

The application form is titled `Penta Co-operative Housing: Application For Membership`. The inspected version is configured for a 2-bedroom unit near Jericho Beach with a monthly housing charge of $1,092, a target move-in date of September 1, 2024, and an application close date of June 26, 2024.

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

**Cost gating and staleness.** The whole chain is gated on a **rank-inputs fingerprint** (`RankingRun.rank_inputs_fingerprint`, an indexed column — a hash of the eligible pool *plus* each rank-chain prompt and model). If unchanged, the UI flags "up to date"; a re-run is still allowed (discovery is nondeterministic, so a member may want a fresh criteria set — the confirmation card explains nothing requires it). The workflow strip is three single-verb steps — **Import** (sync + hard filters), **Screen** (the AI integrity pass), **Rank** (this chain) — each amber-stale by the same signal its no-op gate uses (Import on a settings fingerprint, Screen on coverage, Rank on the rank-inputs fingerprint). Every AI step opens a confirmation card before running, even when there's nothing to do. Rank streams phase-aware progress; the opaque criteria/consolidation calls stream the model's live reasoning as a "thinking" panel. A completed Rank lands the user directly in the ranked view.

### Ranking And Outputs

The primary output is a ranked list. It is explainable and preserves evidence behind each recommendation. AI produces qualitative labels for user-facing screening; hidden internal scores support ranking, but the UI explains rankings in plain language rather than centering numeric scores. AI summaries use a neutral committee tone and stay transparent enough to detect bias or unsupported claims. Direct essay excerpts are used sparingly; entire essays are never reproduced in summaries or reports.

For debugging and learning, raw AI analysis, traces, prompts, and intermediate outputs are accessible to any logged-in member (the Observability tab + candidate detail pages). The app provides `why not selected` explanations for candidates below a member's shortlist, for merged MOMI comparison (internal only). Each screening run is saved with its criteria, prompts, model outputs, ranking outputs, and shortlist. AI output schemas are defined in `app/ai/schemas.py`, shared by prompt, storage, API, UI, and evals.

### Essay Judgment

Strong negative essay signals include (not limited to): the applicant appears unaware of co-op obligations; treats the unit mainly as cheap rent without understanding shared work; expresses hostility or resistance to shared work; has an unclear or inconsistent household situation. Essay concerns may justify a "do not interview" recommendation — essay review is central, not a low-priority flag. Brief, awkward, translated, or non-native English answers are **not** penalized for writing polish; the AI judges evidence of co-op fit, participation commitment, and relevant signals rather than style or fluency. (The differentiating criteria are *discovered* against the pool at Rank time, not pre-committed; a standalone essay-analysis pass was built then removed — see ADR 0001.)

### Observability And Evals

The pipeline makes real, non-deterministic model judgments, so it is instrumented across four pillars (build history in CHANGELOG M13; grader design in ADR 0008 and [docs/ai-evals.md](docs/ai-evals.md)):

- **Cost** — an Insights "Cost" subtab: cumulative and last-run AI spend, per pass, with a token (in→out) + model breakdown and estimate-vs-actual reconciliation. All cost accounting flows through one `PassCost` value object into `run_cost_ledger` + `run_pass_cost`, which both Screen and Rank write and both surfaces read.
- **Per-pass AI trace viewer** — each pass's raw output is legible: per-application (screening flags, scoring rationale/evidence) on the candidate detail page; per-run (discovery, decomposition, matching, consolidation audits) on the Insights subtabs.
- **Operational metrics** — an Insights "Trends" subtab: per-run/per-pass cost, tokens, wall-clock latency, cache-hit rate, failure count, and dimension count over time.
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

## Multi-Member MOMI Workflow

Each MOMI member can run their own screening process separately. For each member the app preserves: the patterns surfaced by AI, the member's tier weighting and inferred priorities, the resulting ranked shortlist, and applicant-specific rationale and evidence. Each member uses their own login; members may see each other's criteria and shortlists (anonymization is not required).

The app then supports combining member shortlists into a merged ranked list, making criteria visible so committee discussion can address not only *which* applicants were selected but *why* each member valued particular signals. Merged behavior:

- Member rankings are weighted equally.
- Applicants appearing on multiple member shortlists are prioritized.
- Strong disagreement (one member strongly rejecting a candidate another ranks highly) is flagged for discussion.
- The merged output includes consensus recommendations, disagreement/discussion-needed candidates, and not-recommended candidates.

Criteria comparison identifies: criteria shared across members, criteria that differed, criteria unique to a member, and plain-language summaries of each member's priorities. Members can write private, per-applicant notes separate from AI rationale — notes belong to their author, stay out of AI inputs and shared reports, and never appear to other members (they remain on the author's printed candidate detail). Any user may finalize the merged list (in practice the MOMI chair's job; no special chair role required). The committee-facing report includes both interview recommendations and a summary of how the pool was screened.

*(The exact merged-ranking formula, disagreement-flag calculation, and criteria-comparison layout are open — see "Remaining Open Questions". Multi-member is Milestone 15.)*

## Users, Roles, And Authentication

The MVP uses real Google login (multi-member screening is a major design requirement). Access is invitation/approval based when live; Jeff is the initial admin and can invite MOMI members. Roles:

- `Admin`: the initial account; will gate user management once invitations are built.
- `Member`: a MOMI committee screener — runs screening sessions, runs shared cached AI runs, ranks candidates, adds notes, participates in merged comparison.

Every committee member is a trusted screener, so **the screening workflow has no admin-only surface.** Status overrides, the raw source row, and the raw AI narrative are all available to any logged-in member — the privacy boundary is screeners-vs-outsiders, with members inside it. The `Admin`/`Member` distinction exists in the data model (the first user created becomes admin) and is intended to gate user management, but does not currently gate any route. Settings are login-only. The engineering default is `require_current_user`; a role gate is added only for a genuinely admin-only capability, as a deliberate decision (re-add `require_admin` when multi-member roles land — M15/M16).

AI screening results are shared across users and cached per application content, model, and prompt version. Any logged-in member may run the checks; the cost concern is uncached work, not which member initiates a shared run.

## Screening Runs

Users may create multiple runs for the same pool ("Jeff first pass", "Jeff revised after thinking"). Runs preserve enough source information to understand what pool was used (a sync/run metadata record; no immutable snapshots). When criteria are revised after a completed run, the default is to update the same run, with the option to create a separate new run. Manual candidate notes are private to their author. AI-generated criteria summaries need no dedicated editing workflow, and an audit log is not required, for the initial design.

## Data Storage

- Google Sheets is the external source of truth for submitted applications.
- Application rows import into the app database for screening runs, AI outputs, notes, rankings, and reports.
- SQLite for the local MVP (simple, inspectable, reliable for one machine); the data layer is kept portable to a hosted database (Postgres) for multi-user use. Expected live committee size ~5 members with light concurrency; a hosted DB is a Milestone 16 concern.
- Spreadsheet access is minimized — import/sync rows, then use the app DB for screening state.

Core data model:

- An `Application` represents one household/application (applicant, co-applicant, children, essays, references, income, pets, declaration, source + screening metadata). The raw Google Sheets row is preserved exactly as JSON alongside normalized fields.
- Primary application identity is the primary applicant email (normalized: trimmed + lowercased); each application also has an internal DB ID. Duplicate detection is by email; the newest row wins.
- Normalized fields computed at import/sync: `adult_count`, `child_count`, `children_under_18_at_move_in`, `has_real_estate`, `household_income`, `pet_count`, `pet_types`.
- Each sync creates a `SyncRun` record (timestamp, source sheet ID, counts, `settings_fingerprint`).
- A `RankingRun` holds a Rank's discovered dimensions (`dimension_report`), the committee's mutable view (`run_state` = tiers + new-dimension flags + pending proposals; weights are **derived** from the tiers, never stored), and the `rank_inputs_fingerprint`. Its 1:1 `ranking_run_audit` child holds the AI-legibility trail (discovery narrative + match/fan-out/decompose/consolidate audits) so the hot read path stays lean. `dimension_aliases` is the sole merge-truth. Per-run/per-pass cost lives in `run_cost_ledger` + `run_pass_cost`; eval runs in `eval_runs`. (Schema layout: [docs/app-architecture.md](docs/app-architecture.md); the M14 split of the old `criteria` blob: CHANGELOG M14 Phase 5.)

Admin settings (Google Sheet link/ID, hard-filter thresholds, pet limits, AI spending cap, model choices) live in the database, not `.env`. Local `.env.local` holds secrets; `.env.example` holds safe placeholders. Never committed: `.env` files, OAuth credentials, SQLite DB files, applicant exports, AI traces, and raw prompts/outputs containing applicant data. During MVP iteration, local schema changes need no backward compatibility — deleting and recreating the SQLite file from migrations is acceptable.

## Reports

**The report format is the browser's print-to-PDF of the ranked view (Milestone 10).** The committee opens the ranking and clicks **Print**; the print stylesheet hides interactive chrome (`no-print`) and renders a clean artifact: the ranked shortlist with each candidate's band and rationale, plus a text **importance-tiers summary** (`TierSummaryForPrint`) so a reader sees which dimensions sat in which tier. The candidate detail page is independently printable.

This replaced the originally-planned Google Docs generation — print-to-PDF needs no Docs/Drive scopes, no second OAuth consent, no generated-file storage, and no "regenerate on change" story (the document is a live render). A Google Docs export could return later if a committee wants an editable, collaboratively-commentable artifact.

## MVP Shape And Tech Stack

The MVP is a web app that runs locally in the browser: a **Python/FastAPI** backend, a **Vite + React/TypeScript** frontend, **SQLite** (SQLAlchemy + Alembic), **Google OAuth** with signed server-side session cookies, read-only **Google Sheets** import/sync, and **Amazon Bedrock** (behind the provider-agnostic interface). Python deps via `uv`; frontend via `npm`; backend tests via `pytest`.

Google setup: a dedicated Google Cloud project; OAuth app named `Penta Application Screener`; scopes are the minimum the workflow needs — basic login profile/email + Google Sheets read-only (no Docs/Drive; reports are print-to-PDF). Local redirect URLs may use localhost. Once user management exists, login is restricted to invited/approved emails. Setup is documented in [docs/google-cloud-oauth-setup.md](docs/google-cloud-oauth-setup.md).

Admin settings screen covers: income range, min/max children + max child age, pet limits, min adult age, per-rule toggles, AI spending cap, provider/model choices, and the Google Sheet link/ID. If required configuration is missing after login, the app directs the user to settings; otherwise the first screen is the dashboard.

Implementation defaults:

- Readability first; avoid redundancy; prefer elegant, boring solutions over clever abstractions.
- Shared business rules, thresholds, field mappings, prompts, and schema definitions have a single clear home.
- Abstractions are added only when they reduce real duplication or clarify an important boundary.
- Clean changes over backward compatibility for internal APIs, local schemas, fixtures, and UI shapes; backward compatibility is added only when real users or real applicant data require it.
- Relational tables for workflow data, JSON columns for raw rows, flexible payloads, AI outputs, and debug traces; the relational model stays portable to Postgres.

**Milestones 1–14 are complete** and proven end-to-end against real Bedrock (sync → screen → discover ~14–16 fact-aware dimensions → score the pool → rank with the tier-list weighting → print a committee-ready PDF). Per-milestone detail and every resolved decision/reversal are in [CHANGELOG.md](CHANGELOG.md). The remaining milestones are **15 (multi-member screening + merged shortlist comparison)** and **16 (hosting / go-live)**.

## Remaining Open Questions

Decisions that still need making, or can wait until their implementation milestone.

### Reporting (M10 shipped; refinements open)

The report is the browser print of the ranked view, so the format question is resolved. Open refinements if a committee wants more than the live render:

1. Whether the print should include near-misses, filtered-out counts, or filtered-out details (currently the ranked eligible pool only).
2. The amount of applicant personal/contact detail appropriate for MOMI reports.
3. The tone/format of an explicit recommendation and `why not selected` explanation, if wanted beyond the per-candidate rationale lines.

### Before Multi-Member V2 (M15)

Multi-member *logic*, to resolve when scoping M15:

1. The exact merged-ranking formula for equal-weight member rankings.
2. How disagreement flags are calculated.
3. The criteria-comparison report layout.

### Hosting / Go-Live (M16)

The committee saw a demo and wants it, so hosting is real scheduled work, sequenced **after M15** as pure deployment. M15 stays on SQLite; M16 owns the move to a hosted, multi-user, concurrent-write footing. Accepted tradeoff (Jeff, 2026-07-16): because M15 builds per-member state on SQLite, M16 may re-touch part of that data layer when it moves to a hosted DB — chosen over a pre-M15 DB spike so M15 stays unblocked and its real shape informs the DB choice. Open decisions:

1. **Database target** — hosted Postgres or another hosted DB (the load-bearing choice: it drives concurrency, the Alembic target, and the data migration off local SQLite).
2. **Concurrency** — simultaneous members reading/writing (tiering, notes, per-member rankings); today's single-writer assumptions and the local backup/restore scheme need revisiting.
3. **Cloud deployment path** — where the FastAPI backend + Vite frontend run, secrets/OAuth in a hosted context.
4. **Auth/roles** — re-add the `require_admin` gate deferred through M13; multi-member + hosted is when member-vs-admin roles become load-bearing.
5. **Data protection at rest** — applicant PII in a hosted DB raises retention/access questions the local-first posture sidestepped.

### Validation Experiments Owed On Real Bedrock

The mock suite proves plumbing, not judgment. Still owed on real data (parked so they aren't forgotten; the concluded ones — K sensitivity, prompt-output trimming, the convergence experiment — are in CHANGELOG / `docs/case-studies/dimension-convergence.md`):

1. **Reconcile-era behavior is moot** (that subsystem was deleted; see ADR 0007). No action.
2. **Carry-forward cost win in the wild** — per-dimension score reuse + the ceiling estimate are built and unit-tested; a real-Bedrock re-rank to confirm the actual run comes in under the ceiling is the remaining validation.

## Future Enhancements

Not scheduled into a milestone; captured so they aren't lost.

- **Human-editable screening criteria with in-place re-rank.** *Adding* a dimension is done (the Committee-Proposed Criteria feature). What remains is direct editing of *existing* criteria on the current run — rename/reword, edit a definition, or remove one. Removing a dimension or editing only its display name needs no model call (a weight-zero drop or relabel; re-ranking stays pure math). Editing a definition changes what it measures, so it must change that dimension's key to force a re-score (the cache keys on the dimension key, not definition text). Fits the existing architecture: the AI proposes the axes, the human owns them.
- **AI Criteria Coach** — reflects on and challenges the committee's tier weighting (does not elicit or re-rank). Deferred until the tier-list has been used against real committee data.
- **M14 follow-up — a second cleanup pass. _(done)_** A fresh-eyes read over the modules the M14 splits churned most (the ranking + evals API packages, the extracted cost module and hooks, the big eval components), looking for what the first pass was too close to catch. It confirmed the refactor was structurally sound — the large abstractions (the `CategoricalPass` factory, the worker-thread reasoning bridge, the extracted hooks, `App.tsx` as orchestrator) were correctly judged and left alone — and landed a set of small, behavior-preserving fixes: removed a `CRITERIA_STAGES` identity dict; renumbered fossilized phase comments; de-privatized `missing_dimensions_by_application` (an M14 split had turned a same-file helper into a cross-module import); typed the scoring estimate (`ScoringEstimate` TypedDict) and RunnableEval's whole result-render path (`EvalCaseResult`/`EvalRunResult`, replacing pervasive `any` that had been silently disabling the sole `tsc` guard — which surfaced three unguarded-optional reads); centralized the eval-key unions on the canonical `EvalKey`; and cleared assorted naming/comment drift. Same governing rules held throughout — behavior-preserving, tree green each step, rule-of-three (over-abstraction is as bad as sloppiness).
- **M14 follow-up — a broad sweep across every layer. _(done)_** A second, wider review over the *whole* M14 surface (all of `app/ai`, `app/evals` + `app/api/evals`, `app/services` + `app/db`, `app/schemas`/`domain`/`core` + the top-level API, every frontend component, and all docs), looking for improvements on their own merits — not only split seams. Landed as focused, tree-green commits: **dead code** removed (four unused pass `KIND` constants, `format_agreement`, `JudgeStabilityReport.counts`); **de-duplication** (`_BACKGROUND_PASSES` identity map collapsed, `seed_str` delegating to each pass's own formatter, a shared `_resolve_chains` chain-walk, `_audit_field` for the 7× audit-null guard, `current_dimension_kinds` for a 2-site null-dance); **type tightening** (a shared `CostEstimate` TypedDict for `estimate_cost`/`enforce_cap`/`estimate_screening`; `StatusOverride` on `RequestModel`; a promoted `InsightRunKind`; centralized `EvalRunMode`/`EvalFixtureKey` reuse); **eval-reframe fossils** cleaned (stale `EvalCaseEditor` templates that would have seeded invalid cases, `readProblem` re-use, an unreachable add-field branch); **six docs drift fixes** verified against code (dead Quality-Flags section, removed Harvest panel, `capture_*`→`harvest_*` CLIs, `decompose_drift` path, two-tab structure, baseline migration filename); and three approved structural changes — removed the test-only `analyze_one`/`analyze_application` screening path (coverage preserved via the production path), converted `DiscoveryPanel` to `useFetchOnce`, wired the previously-dead judge `label_rationale` into the Judge tab, and dropped the always-NULL `ranking_runs.owner_user_id` column (reversible migration, verified round-trip on a DB copy, live DB backed up first). Deliberately left alone as correctly-judged: the `CategoricalPass` factory, the worker-thread bridge, `WorkflowBar`'s prop breadth, and `streamNdjson`'s `any` (a genuinely heterogeneous stream boundary).
