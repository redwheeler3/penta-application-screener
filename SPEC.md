# Penta Application Screener Specification

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

Current application response columns include:

- Applicant and co-applicant identity/contact fields
- Household children fields
- Current address fields
- Current-address duration
- Real-estate ownership
- Current and previous landlord reference fields
- Essay fields:
  - Introduction, employment background, interests, and values
  - Skills the applicant/co-applicant could contribute to running and maintaining the co-op
  - Previous co-op experience
  - Why they want to live in a co-op and how they would be a valuable member
- Optional household photo link
- Pets description
- Applicant and co-applicant employment fields
- Applicant, co-applicant, and household gross yearly income
- Declaration

Current email list response columns include:

- Timestamp
- Email Address
- Requested unit sizes:
  - 1 bedroom: 1 or 2 adults
  - 2 bedroom: 1 or 2 adults plus 1 or more children under 18
  - 3 bedroom: 1 or 2 adults plus 2 or more children under 18
- Month/year grouping field

## Email List Form

The email-list form is titled `Penta Co-operative Housing: Email List`.

The form explains that applications are not currently being accepted, Penta no longer maintains a wait list, and paper applications are no longer processed. It says applicants can provide an email address to receive a one-time notification when applications open, and notes that Penta is a small co-op where a unit generally becomes available every 2 or 3 years.

The form has one required checkbox question:

- Please notify me when a unit of the following size is available

Options:

- 1 bedroom: 1 or 2 adults
- 2 bedroom: 1 or 2 adults plus 1 or more children under 18
- 3 bedroom: 1 or 2 adults plus 2 or more children under 18

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
3. Use AI agents to evaluate essay-question answers and surface patterns.
4. Ask the user targeted questions based on those patterns.
5. Re-rank or narrow candidates after each user answer.
6. Continue until the candidate list reaches a user-approved threshold for manual review.
7. Produce a MOMI-ready report with recommended interview candidates and justifications.

The screener should eventually support multiple MOMI committee members running their own screening sessions independently. Each member may value different criteria. The app must preserve and summarize each member's criteria, question answers, shortlist, and rationale so MOMI can compare both applicant recommendations and the values/criteria behind those recommendations.

## Screening Scope

The screener should be configurable for any Penta unit size, but the current search is for a 2-bedroom unit with an expected move-in date of September 1, 2026.

The application form is responsible for collecting complete applications. The screener focuses on what happens after applications have been submitted.

## Dashboard

The app should provide a dashboard summarizing the current application pool and screening state, including:

- Total submitted applications
- Eligible applications after deterministic hard filters
- Filtered-out applications with reasons
- Applications ready for AI review
- Currently qualified applications after user/AI narrowing
- Shortlisted applications
- Manual review pile

Every submitted application should remain visible somewhere in the app. Deterministically disqualified applicants should be excluded from AI essay review but remain accessible in a filtered-out view with the applicable reasons.

## Sync And Run Records

The app should use a hybrid live-sync/run-record model:

- While applications are open, the app may sync live from the Google Sheets response spreadsheet.
- Once serious screening begins, each screening run should record the application set and source sync state used for that run.
- The dashboard should show any new applications submitted after the run's recorded source sync state.
- Users should be able to add newly synced applications to an existing run by updating the run record.
- Reports must reference the exact sync/run record used.

Immutable snapshots are not required. This preserves convenience during intake while keeping screening decisions and reports understandable.

## Deterministic Eligibility Rules

### Rules Engine Architecture

The screening rules system is a configurable rules engine. Each rule is a discrete, named validation that produces a binary outcome: the application is either `eligible` or `filtered_out`.

Each rule has:

- **ID**: machine-readable slug (e.g. `owns_real_estate`, `child_age_over_max`)
- **Display name**: human-readable label shown in the admin UI (e.g. "Real estate ownership")
- **Description**: explains what the rule checks and why
- **Outcome**: `filtered_out` (the only outcome — any rule that fires disqualifies)
- **Parameters**: configurable thresholds or values (e.g. income min/max, min/max children, max child age, max pets). Not all rules have parameters.
- **Enabled**: toggle on/off per screening configuration

Rules are stored in the database as part of admin settings. The Admin settings UI shows the full rule list with toggles and parameter inputs. Disabled rules do not run during screening.

Adding a new rule requires code (a rule function that takes normalized application data and returns pass/fail with a reason). Once the code exists, the rule appears in the admin UI and can be configured. The goal is that the rule logic is simple enough to add and that the admin can control which rules are active and what thresholds apply without code changes.

Rules run in a defined order. An application that fails any enabled rule is `filtered_out`. An application that passes all enabled rules is `eligible` and proceeds to AI screening.

### Rule Catalog

The following rules should be implemented. Each rule is listed with its default outcome and parameters.

**Household composition rules:**

| Rule ID | Description |
|---------|-------------|
| `child_count_mismatch` | Declared child count does not match the number of complete child detail blocks. A complete block = first name + last name + age all filled. |
| `too_few_children` | Household child count is below the configured minimum. Parameter: min_children (default 1). Moved off the form so the form can drop branching validation. |
| `too_many_children` | Household child count is above the configured maximum. Parameter: max_children (default 4). Moved off the form likewise. |

**Age rules:**

| Rule ID | Description |
|---------|-------------|
| `child_age_over_max` | Any listed child is older than the configured maximum child age. Parameter: max_child_age (default 17 — i.e. the form's "children under 18"). Tunable for co-ops housing older dependants. |
| `applicant_under_min_age` | Applicant age is under the configured minimum adult age. Parameter: min_adult_age (default 18). |
| `co_applicant_under_min_age` | Co-applicant age is under the configured minimum adult age (default 18). Indicates the co-applicant may actually be a child, not an adult household member. |
| `child_age_exceeds_parent` | Any child's age is older than the applicant's or co-applicant's age. Data entry error. (Distinct from `child_age_over_max`: this is a sanity check against the household's own adults, not the policy ceiling.) |

**Financial rules:**

| Rule ID | Description |
|---------|-------------|
| `income_below_range` | Household gross income is below the configured minimum. Parameter: min_income (default $70,000). |
| `income_above_range` | Household gross income is above the configured maximum. Parameter: max_income (default $150,000). |
| `income_arithmetic_mismatch` | Applicant income + co-applicant income does not exactly equal the stated household total. No tolerance — any discrepancy is flagged. |

**Property rules:**

| Rule ID | Description |
|---------|-------------|
| `owns_real_estate` | Applicant owns real estate. |

**Data integrity rules:**

| Rule ID | Description |
|---------|-------------|
| `negative_number` | Any whole-number-validated field (age, income) contains a negative value. The form allows negative integers but they are clearly data entry errors. |
| `future_employment_start` | Employment start date is in the future. |
| `co_applicant_incomplete` | Some co-applicant fields are filled but others are blank (partially filled). Nothing or everything is fine; partial is not. |

### Rule Behavior Notes

- Living at the current address for less than 2 years is not disqualifying and does not trigger any rule.
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
- `ai`: the AI quality pass set it `ineligible` (lower trust — this is the "needs review" bucket)
- `human`: a person set the status, in either direction

Only an actor that *acts* stamps itself. Rules passing an application through, or AI declining to flag it, leaves it `untouched` — they do not "decide" eligibility, they hand it to the next step. Only a human can move an application from `ineligible` back to `eligible` (or the reverse).

There is no third status. The UI surfaces the `status_source = ai` group as an "AI Flagged" view, composed client-side as a filter over the real columns. This keeps status binary while distinguishing high-trust deterministic exclusions from AI exclusions. The labeling is deliberately factual ("AI Flagged" — what happened), not prescriptive ("Needs Review" — what the user must do): whether to review an AI exclusion, and which flags matter, is the human's judgment, not the system's. The backend never names these views; it returns counts and filters keyed by the real `status` and `status_source` columns. When the two filter groups combine, their counts are faceted — each group's counts reflect the other group's active filter (plus search) — so impossible combinations read zero rather than a misleading total.

**The "why" is kept separately as immutable records**, never mutated by a human:

- deterministic **filter reasons** (e.g. `Household gross income ($164,000) is above $150,000.`)
- **AI quality flags** (category, summary, evidence)

A human flipping the status never deletes these records — an applicant can be `eligible / human` while still showing the AI flags a reviewer chose to accept. This preserves the audit trail.

**Stickiness:** a machine actor (rules or AI) must never overwrite a `human` status. On re-sync or re-run, machine actors refresh the reason/flag records but leave a human-set status untouched.

**Clearing an override:** a human override can be removed, handing the decision back to the machine. Clearing recomputes the status from the *current* findings (rules then AI) and resets `status_source` to the machine source — so the result can differ from the pre-override value if findings changed since (which is the point of reverting to automatic). The detail view models this as source ownership: a segmented **Decided by** control over `Automatic | Eligible | Ineligible`, where "Automatic" is selected whenever `status_source != human` and selecting it clears the override. The detail payload carries `autoStatus`/`autoStatusSource` (what the machine would decide right now) so the UI can show the automatic verdict even while a human owns the status. Clearing is idempotent — a no-op on an already-machine-owned status.

**Staleness nudge:** because human decisions are sticky, a re-run can surface new findings on an application a human already cleared. When the machine records change after a human's review, the application is marked stale ("new findings since last review") so the reviewer can re-decide. Status does not move; staleness is derived by comparing the latest machine-record timestamp to when the human set the status.

### AI Quality Flags

Separately from AI triage (which resolves ambiguous data), AI should make a quality/integrity pass over eligible applications to flag suspicious patterns that are too subjective or contextual for deterministic rules. When the AI pass flags an eligible application, it sets the status to `ineligible` with `status_source = ai` — the low-trust AI-excluded group — rather than excluding it outright. A human reviews these and either confirms the exclusion or restores the applicant to `eligible`. The flags themselves are kept as immutable records regardless of the human's decision.

The pass also re-analyzes applications a *previous AI pass* marked ineligible, not only currently-eligible ones, so that a revised prompt can change the verdict in either direction — clearing a previously-flagged applicant back to `eligible`, not just flagging clean ones. Applications the deterministic rules disqualified are excluded from the pass (rules outrank AI, so re-running AI on them cannot change their status). Human-set statuses remain sticky: their flags refresh for the staleness nudge, but the status is never overwritten by a machine run.

Known patterns to detect (this list is intentionally incomplete and should grow over time):

- Child names that look like placeholders ("Baby", "TBD", "N/A", "Test")
- Applicant or child names that appear fake or nonsensical
- Essay responses that are suspiciously short or minimal (single sentences, "N/A")
- Essay responses that appear to be advertising or spam
- Essay responses that appear to be AI-generated boilerplate with no personal detail
- Responses that are copy-pasted across multiple essay fields
- Internal inconsistencies between essays and other fields (e.g. claims skills they can't have given stated employment)
- Phone numbers or emails that appear fake beyond format validation (e.g. all same digits)
- Pet descriptions that violate the co-op pet policy (more than 1 dog, more than 1 cat, or exotic/unusual pets). The pets field is free text and too ambiguous for deterministic parsing — negation ("I don't have pets"), unclear phrasing, and context-dependent language require AI judgment.

AI quality flags should be stored per-application and shown in the candidate detail view as informational notices, not as filter reasons.

## AI-Assisted Screening

AI essay review should only run for candidates who pass deterministic hard filters or are resolved as eligible by AI triage.

### Provider And Cost Controls

For MVP, keep the AI architecture provider-adaptable. Because Jeff may work on this project from AWS-managed laptops where direct OpenAI, Anthropic, or similar external AI API calls may be blocked, Amazon Bedrock is the likely first provider to implement. Direct OpenAI or Anthropic providers can still be added later if useful, but the application should depend on an internal AI provider interface rather than a specific vendor SDK.

Jeff will set up AWS credentials, CLI, and SDK support on the relevant machines before Bedrock integration begins.

The app should run locally as much as possible for MVP while staying cloud-ready for eventual MOMI use. Local-first implementation should not prevent later deployment to AWS or another hosted environment.

Cost control is a core product requirement. The app should prefer:

- Cached AI analysis per application and per run where possible
- Smaller/cheaper models for first-pass extraction and clustering
- Frontier models only for higher-judgment synthesis, adjudication, and final report generation
- Batch/asynchronous processing where latency is not important
- Short structured outputs rather than verbose freeform generations
- Avoiding repeated spreadsheet reads and repeated AI calls
- A visible AI cost estimate before running large reviews
- A configurable spending cap per screening run

Hard filters should run automatically after import/sync. AI review should not auto-run by default; it should start only after the user sees the cost estimate and confirms the run, unless an Admin explicitly enables an auto-run option later.

### Interactive Screening

The screening experience should discover patterns in essay responses and ask the user what matters, rather than starting from a fully fixed rubric. The likely high-level criterion is "fit for Penta," but this is intentionally opinionated and user-dependent. The patterns are not pre-defined: the AI discovers the differentiating dimensions that actually distinguish *this* applicant pool (the "Known patterns to detect" list under AI Quality Flags is for data-integrity flagging, not these screening differentiators). The screener is a screening assistant for a human, not an autonomous filter.

The assistant does not "cut" candidates. At the expected scale (~300 applicants) hard removal is the wrong model. Instead, the assistant **stack-ranks the entire qualified pool with a per-row rationale**, and the committee's weighting re-sorts that list. Re-weighting adjusts standing (soft ranking), never removes anyone — so a low-ranked candidate is never "rejected," just currently low, and a later weighting change can lift them back up. The committee reads the stack rank top-down as far as they like; there is no fixed cut line.

How the committee expresses what matters: a **tier-list maker** (built in milestone 9 — see "Interactive Weighting — Tier List"). The discovered dimensions are draggable chips the committee sorts into self-defined importance tiers (S/A/B by default, plus an Ignore zone), and the ranking re-sorts instantly as deterministic math over the cached scores — no model call per change. This replaced the originally-envisioned sequential pairwise narrowing questions ("what matters more — X or Y?"): direct tiering states a committee's known priorities in one pass, and because every dimension stays visible and re-draggable, there is no "premature lock-in" for the questions' deliberate redundancy to guard against. (A future "Criteria Coach" may still *ask* questions — but to help the committee reflect on and challenge the weighting they built, not to elicit it; see the fast-follows in the M9 design section.)

Re-weighting is freely reversible: the committee drags chips back at any time, and the ranking re-sorts. There is no separate undo to maintain — the soft-ranking model makes revisiting automatic (re-sorting rather than un-rejecting).

Users do not need a manual "pin candidate" workflow for the initial design.

Rubrics should generally remain stable within a screening run. After a run completes, users should be able to revise criteria/rubrics for future runs.

### Ranking And Outputs

The primary output should be a ranked list. The ranking should be explainable and should preserve evidence behind each recommendation.

AI should produce qualitative labels for user-facing screening. Hidden internal scores may be used to support ranking, but the UI should explain rankings in plain language rather than centering numeric scores.

AI candidate summaries should use a neutral committee tone and avoid unnecessary personal judgments. They should still be transparent enough that users can detect bias, unsupported claims, or questionable reasoning.

AI judgments should show:

- Direct quotes or short excerpts where useful
- Paraphrased evidence
- Source field references
- Score or ranking breakdown
- Rationale for the recommendation
- Confidence or uncertainty labels where useful

Direct essay excerpts should be used sparingly as supporting evidence. The app should not reproduce entire essays in AI summaries or reports.

For debugging and learning, raw AI analysis, traces, prompts, and intermediate outputs are accessible to any logged-in member (see "Users, Roles, And Authentication" — the workflow has no admin-only surface). The normal app experience should emphasize polished summaries, with the raw detail in collapsible debug sections.

The app should provide `why not selected` explanations for candidates who do not make a member's shortlist, especially for merged MOMI comparison. These explanations are internal only; applicants will not see them, so they can be transparent and candid while remaining respectful and evidence-based.

Each screening run should be saved with its criteria, prompts, model outputs, user answers, ranking outputs, shortlist, and final decisions.

AI output schemas should be defined before implementing the AI milestone so prompts, storage, caching, UI rendering, and eval checks share the same contract.

### Essay Judgment

Strong negative essay signals include, but are not limited to:

- Applicant appears unaware of co-op obligations
- Applicant treats the unit mainly as cheap rent without understanding shared work
- Applicant expresses hostility or resistance to shared work
- Applicant has an unclear or inconsistent household situation

Essay concerns may justify a "do not interview" recommendation. Essay review is central to the screening process, not merely a low-priority flag.

Brief, awkward, translated, or non-native English essay answers should not be penalized for writing polish. The AI should judge evidence of co-op fit, participation commitment, and relevant signals rather than style, fluency, or grammar.

### Essay Analysis (Milestone 6)

Milestone 6 adds a per-candidate essay-analysis pass on top of the shared AI foundation built in milestone 5 (the `analyze_application` engine, caching, cost estimate, spending cap, prompt versioning, narrative capture). It runs with `kind="essay_analysis"` through that engine, so it reuses all of the above for free.

The defining boundary: **milestone 6 extracts and normalizes what applicants said; it does not judge.** The "negative signals" and "do not interview" judgments described above under Essay Judgment belong to the milestone 7 ranker, because the differentiating criteria are *discovered* there against the actual pool. If milestone 6 emitted judgment on fixed dimensions, it would pre-commit the patterns and defeat that discovery. So essay analysis stays purely factual.

Decisions:

- **Output:** a neutral committee-facing summary plus structured per-signal fields. The summary lets a screener skim ~300 candidates without reading every essay; the structured fields feed the milestone 7 ranker.
- **Schema is fixed, not adhoc.** Normalization is the point — every candidate is described in the *same* structure so the committee can compare a column across the pool, milestone 7 reads a stable contract, and the output is evalable. The fields are locked; only the *contents* of list fields are open. The schema mirrors the four essay questions 1:1 — one field per thing the form explicitly asks for:

  ```python
  class EssayAnalysisReport(BaseModel):
      summary: str                          # 2-4 sentence neutral cross-cutting digest, no evaluation
      household_context: str | None         # who is in the household, as introduced (Q1)
      employment_background: str | None     # work situation as narrated, applicant + co-applicant (Q1)
      interests: list[str]                  # interests stated (Q1)
      values: list[str]                     # values expressed (Q1)
      skills_offered: list[str]             # skills offered to run/maintain the co-op (Q2)
      prior_co_op_experience: str | None    # prior co-op experience stated; null if none given (Q3)
      stated_motivations: list[str]         # reasons given for wanting co-op living (Q4)
      stated_contributions: list[str]       # ways they said they would be a valuable member (Q4)
      evidence: list[str]                   # short direct quotes grounding the extractions
  ```

  Extraction is cross-cutting (content bleeds across the four boxes — skills appear in the intro essay, etc.), not per-question. `null`/`[]` means "did not say," which milestone 7 may read as signal.
- **No `other`/catch-all field.** That would reintroduce the adhoc shape normalization exists to prevent. Off-question or cross-cutting nuance is covered two ways instead: the `summary` absorbs connective tissue, and the **raw essays and structured form fields are preserved**, so milestone 7's Pattern Finder reads the source directly and can discover anything the schema did not anticipate. Essay analysis is an *additive* lens, never a replacement for the source.
- **Model:** start on the first-pass model (Claude Haiku 4.5). Essays are short answers to fixed questions — extraction and summary, not the cross-document synthesis milestone 7 reserves for the synthesis model. Upgrade to Sonnet only if real output reads thin, decided empirically by comparing the same candidates. The model is Admin-configurable and the cost estimate self-tunes per model, so this is not a lock-in.
- **Scope:** eligible applications only. There is no value in summarizing essays for rules-disqualified applicants.
- **Status independence:** essay analysis is purely informational and never touches eligibility `status`/`status_source`. Unlike quality flags, it does not call `apply_machine_status`. Eligibility stays rules-and-flags driven; essay analysis informs the human ranking, not the gate.
- **Surfacing:** the summary and structured fields appear on the candidate detail page (committee-facing), but as a collapsed accordion among the other expandable sections near the bottom, *below* the raw essay responses — for a reviewer, reading the applicant's own words is the primary act, and the AI digest is a secondary aid available on demand.
- **No reasoning narrative.** Unlike the quality-flag pass, essay analysis does *not* ask the model for a free-text reasoning preamble. An A/B run over real candidates (same model, with vs. without the "explain first" instruction) showed the preamble produces no systematic change in the extracted fields — the with/without difference sat within the model's own run-to-run nondeterminism — while costing ~18% more output tokens per candidate. Because this pass extracts short answers to fixed questions, the structured output needs no chain-of-thought scaffold, so the prompt returns the structured analysis directly. (The quality-flag pass keeps its narrative: it makes a status-affecting judgment where the reasoning trail is worth the audit.)
- **Schema evolution is deliberate, never automatic.** If validation on real essays shows a signal that recurs across many candidates with no home and is too specific for the summary, add a *named, fixed* field and bump the prompt version — a human-approved, versioned change. Never an `other` escape hatch, and never a runtime self-modifying schema (see the Screener-Evaluator role below).

### Pattern Discovery And Dimension Scoring (Milestone 7)

Milestone 7 is the AI foundation for ranking. It is read-only: it discovers *how this pool varies* and scores each candidate on those axes, but does not yet rank, weight interactively, or ask questions (milestones 8–9). It builds on the same `analyze_application`/`screen_applications` engine, caching, cost estimate, spending cap, and prompt versioning as milestones 5–6.

The defining architectural decision — **the LLM extracts scored features; ranking is deterministic math on top of them.** The model never produces "the ranking" *and never opines on importance.* It scores each candidate on a fixed set of discovered dimensions, and the ranking (milestone 8) is a plain weighted sum over those scores. Importance is a values judgment reserved for the human: the AI discovers *what varies*, the committee decides *what matters*. So milestone 8 starts every dimension at an **equal weight** — an honest "no judgment yet" baseline (fit is the plain average of a candidate's scores) — and milestone 9 is the only place weights diverge from equal, with every deviation traceable to a recorded human answer. A non-uniform AI-proposed default was rejected: it would quietly pre-commit the values question, presenting one applicant ahead of another before anyone said what they cared about. This is what makes the milestone 9 interactions — re-sort instantly as the committee re-tiers the criteria — cheap, instant, and *deterministic*: a weighting change only re-runs the math over cached scores, never re-invokes the model. Re-ranking the pool with the LLM on every answer was rejected: it is ~300× the cost per answer, slow, gives no cheap impact preview, and is nondeterministic (the order would jump for reasons unrelated to the answer). The SPEC's "hidden internal scores may be used to support ranking" points the same way — scores are the hidden support; labels and rationale are what the UI shows.

Two passes:

- **Pattern Finder (pool-level, one call, synthesis model).** Reads every eligible candidate's `EssayAnalysisReport` plus raw essays and discovers the **differentiating dimensions for this specific pool** — not a fixed rubric. Each dimension has a name, a definition, and a short why-it-differentiates note. It does *not* propose a weighting: importance is the committee's call, so weights are seeded equal at run creation and only the human moves them (milestone 9). Output is run-scoped (it describes the pool, not one candidate), stored on the `ScreeningRun`. Uses the synthesis model (Sonnet) because this is the cross-document judgment the synthesis tier is reserved for. This resolves the open question "pick a model for pattern discovery."
- **Dimension Scoring (per-candidate fan-out, first-pass model).** Scores each eligible candidate against the discovered dimensions: per dimension a score, a rationale, grounding evidence, and a confidence label. Starts on the first-pass model (Haiku) and upgrades to Sonnet only if an eval shows the scoring reads thin — the same empirical, measure-first stance milestone 6 takes on its model. The schema *shape* is fixed (`list[DimensionScore]`); only which dimensions appear is open, mirroring the `EssayAnalysisReport` discipline (fixed structure, open list contents).

Design constraints carried from the rest of the SPEC:

- **Scope:** eligible applications only, like essay analysis. Status-independent — scoring never touches `status`/`status_source`; it informs ranking, not the gate.
- **Cache key must include the dimensions.** The shared cache key is `(raw_row_hash, kind, model, prompt_version)` and does *not* see the prompt body — but a candidate's scores depend on the run's discovered dimensions. Two runs with different dimensions would otherwise collide and return stale scores. Fix: fold a short hash of the dimension set into the `kind` (e.g. `dimension_scoring:<dims-hash>`), so distinct dimension sets get distinct cache entries with no schema change.
- **Run-scoped, building on the existing `ScreeningRun` table.** The discovered dimensions are a property of a run, persisted in `ScreeningRun.criteria` (the table and JSON column already exist but are currently unwired). Milestone 7 wires the minimum the foundation needs; milestones 8–9 accrete weights, answers, and rankings onto the same run rather than adding a separate persistence milestone. Milestone 8 seeds `criteria.weights` (one entry per dimension key, all equal); the ranking engine reads `criteria.weights`, never a per-dimension field, so this map is the single seam milestone 9's tier-list mutates.
- **Surfacing (read-only):** the run's discovered dimensions are shown at the screening level; each candidate's per-dimension scores, rationale, and evidence appear on the candidate detail page. No ranked order yet — that is milestone 8. Numeric scores stay supporting detail; the committee-facing emphasis remains qualitative, per "Ranking And Outputs."
- **Schemas defined first.** `PoolPatternReport` (dimensions only — no weights; importance is the human's call) and `DimensionScoringReport` (`list[DimensionScore]`) land in `app/ai/schemas.py` before prompts/UI, per "AI output schemas should be defined before implementing the AI milestone." This resolves the open question "define schemas for pattern discovery and ranking."
- **Inputs: essays *and* structured facts.** Both passes see a shared `applicant_facts` view (household composition, ages, income + applicant/co-applicant split, employment tenure, pets) alongside the essays, so discovery can surface quantitative axes (income mix, employment stability, household-to-unit fit) and scoring can score them from the same facts. The view is defined once (`app/ai/applicant_facts.py`) so the two passes never drift — a fact-based dimension must be scoreable from the identical fact. Excluded: names/emails/phones (identifiers, no screening value) and **real-estate ownership** (a hard filter, so eligible applicants are uniformly non-owners — no residual signal). Fields that *are* hard filters but still vary (income within band, household size, pets) are framed for **residual variation** only (`FILTERED_FACTS_NOTE`): the model reads the variation that remains among the already-qualified pool, never the constant pass/fail fact, and never protected characteristics.
- **Dimension count is a guided range, not a fixed number.** Discovery targets **5–25 dimensions**, biased to *split* a broad axis into distinct, separately-weighable sub-dimensions rather than merge, but told explicitly not to pad to a number or invent axes the data does not distinguish. The range is wide because the right count depends on how richly the pool actually varies; the anti-padding guardrail keeps the ceiling from acting as a target. (Empirically, the real pool yields ~14–16.)
- **Discovery is uncached and not cap-gated, but the whole Rank chain is gated on a pool fingerprint.** Pattern discovery is a single synthesis call that writes to `ScreeningRun`, not through the per-application cache — so it is not invalidated by `PROMPT_VERSION`. It is not cap-gated (one cheap call, ~$0.07–0.12). Its model call is wrapped so a Bedrock failure returns a readable 502, not a bare 500. Scoring *is* cap-gated and cached; because re-discovery changes the dimensions-hash (and thus the scoring `kind`), it forces a re-score. **That last property is exactly why a no-op re-run is wasteful:** discovery is nondeterministic, so re-running on an *unchanged* pool churns the dimension wording → new dims-hash → a full, pointless re-score (~$0.40). So the Rank chain (essays → criteria → scores) is gated on a **pool fingerprint** — a hash of the sorted `raw_row_hash`es of the eligible pool — stored on the run when it completes. If the fingerprint is unchanged since the current run, re-ranking is **blocked** (`/rank/run` → 409; `/rank/estimate` returns `ranking_current: true` so the UI says "ranking is up to date" instead of offering to spend). The pool must actually change — a new applicant, an edited application, or an eligibility flip — to re-rank. This supersedes the earlier "re-running always produces a fresh run" behavior: the committee can only re-rank when there is new information to rank on, which is the same per-essay→criteria→scores implication chain the dependency already encodes (no new essays ⇒ no new criteria ⇒ no new scoring; even one changed application re-opens the whole chain, since discovery reasons over the whole pool).
- **Surfacing UX (built in M7, simplified post-M8).** The screening workflow is an ordered, gated strip in its own full-width row, named with single verbs: **Import → Screen → Rank**. Import is sync (which runs the deterministic hard filters). Screen is the AI quality/integrity pass (flag suspicious submissions). **Rank is one button that runs the whole essays → criteria → scores chain** — the committee never runs those sub-passes individually, so they are collapsed into a single step under one combined cost estimate, with the cap enforced once over the combined cost. The three passes stay separate underneath (distinct schemas, cache kinds, and status behavior); only the UI and the orchestration endpoint are merged. The standalone per-pass endpoints were removed when the button merged (`remove completely` per the engineering rules); `screen_essays`, `discover_patterns`, and `screen_dimension_scores` are still the underlying passes, called by `POST /screening/rank/run`. Each AI step shows live coverage of the *current* eligible set (`cached/inScope`). A step goes **amber-stale** when it has run but is no longer current. Crucially, "current" is defined per step by the *same* signal its no-op gate uses, so the badge and the run button never disagree: **Import** stales on a **settings fingerprint** change (`importCurrent: false` — the import-relevant settings, i.e. sheet id + hard-filter thresholds + disabled rules, changed since the last sync, so a re-import would reclassify eligibility; pet limits and the AI cap are excluded since they don't affect import); **Screen** stales on coverage falling short (`cached < inScope`, i.e. a re-sync added uncovered candidates); **Rank** stales on the **pool fingerprint** changing (`rankingCurrent: false`) — not on coverage. (Import's green is "probably fresh," not a guarantee — we can't detect an edited spreadsheet — but a settings change is near-certain grounds to re-import.) This distinction matters because a pool change can leave Rank's score coverage *full* (e.g. toggling a previously-scored candidate back into the eligible pool): coverage alone would wrongly read "done/green," but the fingerprint correctly flags a re-rank is warranted. The dashboard returns `rankingCurrent` (computed by the same `ranking_is_current` the gate uses) precisely so the workflow strip reflects gate truth. Rank streams phase-aware progress (essays / criteria / scores). **Every AI step opens a confirmation card before running — always, even when there's nothing to do.** When a step is already up to date (Screen: nothing uncached; Rank: pool unchanged), the card states that and offers only **Close** (no run button — the action would be a server-blocked no-op), rather than firing a transient toast the user might miss. Run *completions* and *errors* still surface as toasts (green auto-dismiss; red persistent and copyable).

### Deterministic Ranked List (Milestone 8)

Milestone 8 turns the M7 per-candidate scores into the ranked shortlist. **No new model calls** — ranking is pure deterministic math over the cached `DimensionScore`s, which is exactly what makes the M9 interactions instant, free, and reproducible. Design decisions:

- **Equal-weight baseline.** Weights are seeded uniform at run creation (`criteria.weights`, one entry per dimension key). Fit for a candidate is the weight-normalized average of their per-dimension scores: `Σ(weight·score) / Σ(weight)` over dimensions with weight > 0. At M8 this is a plain average; M9's tier-list is the only thing that moves weights off equal. The AI never proposes importance (see the "Pattern Finder" note above) — discovering *what varies* is the model's job; deciding *what matters* is the committee's.
- **Confidence is surfaced, not discounted.** Each `DimensionScore` carries a confidence label; it is shown next to the score and rationale but **never folded into the fit number**. A score moves the ranking by exactly its weight and nothing else, so the ranking stays explainable top-down. (Confidence-weighting was considered and rejected for M8: it adds a hidden term that makes "why is this candidate here" harder to answer.)
- **Qualitative labels are relative bands, not fixed thresholds.** The committee-facing label on each row ("Strong fit", "Promising", "Mixed", "Limited") is assigned by the candidate's *position within this pool* (rank percentile), not an absolute score cutoff. This matches the "how does THIS pool vary" framing — bands always spread the pool and recompute as weights change — and keeps numbers as supporting detail, per "Ranking And Outputs." The raw fit number is available but never the headline.
- **Ranking is a pure domain function.** It lives in `app/domain/ranking.py` alongside `hard_filters.py` (deterministic logic, separate from AI per the engineering rules), takes already-fetched scores + weights and returns ordered rows with fit, band, rank, and per-dimension contributions preserved for explainability. No DB or provider access in the function itself — trivially unit-testable with hand-built scores, no mock provider needed.
- **No fixed shortlist line.** An earlier M8 build had a configurable "shortlist line" with a live above-line count; it was removed as unhelpful — the list is stack-ranked, so the committee simply reads top-down as far as they like and draws their own line by eye. (Removed completely: `criteria.shortlist_size`, the `/screening/shortlist-line` endpoint, and the `above_line` flag.)
- **Surfacing: a separate ranked view, not an in-place re-sort** of the eligible table. Ranking is run-scoped and grows the M9 tier-list beside it, so it gets its own view rather than re-sorting the browse-applications table. The workflow strip is unchanged (ranking is a view over completed scoring, not a gated AI step). `GET /screening/ranking` returns the ordered rows + current weights; it 409s if patterns/scores don't exist yet, matching the scoring endpoints.

### Interactive Weighting — Tier List (Milestone 9)

The M8 equal-weight ranking was validated against the real pool and judged not good enough — every discovered dimension counting equally does not reflect what the committee values. M9 lets the committee say what matters and re-sorts instantly, as **deterministic math over the cached `DimensionScore`s — no model call**.

**The interface is a tier-list maker, not sequential pairwise questions.** The committee drags the discovered dimensions into **importance tiers they define themselves** — from 2 tiers (Important / Ignore) to one-per-dimension (a strict stack rank), most landing in between — plus a bottom **Ignore** zone (weight 0). This was a deliberate move away from the SPEC's original "what matters more — X or Y?" framing:

- **Direct beats indirect for a committee that already has opinions.** Backing into a known preference via many pairwise questions is slow; dragging dimensions into tiers states it directly in one pass, and can zero out whole groups at once ("only the top 3 matter").
- **Always-editable controls remove the lock-in that pairwise redundancy guarded against.** The original design wove in redundant/overlapping questions so no single early answer "locked" the order prematurely. With a tier-list every dimension is visible and re-draggable at any time, so there is nothing to lock — the anti-lock-in machinery (and the constraint-solver that would integrate overlapping comparisons) is unnecessary.

Design:

- **Tier layout is the source of truth; weights are derived.** The run stores `criteria.tiers` (ordered list of `{id, label, dimension_keys}`, most→least important, with a conventional Ignore tier). A pure `weights_from_tiers(dimension_keys, tiers)` recomputes `criteria.weights` from the layout: non-ignore tiers get a descending weight by position (top = N, …, 1; equal within a tier), Ignore = 0. Every weight traces to a tier position — maximally auditable, matching "explain rankings in plain language / traceable to a recorded human choice." The exact weight curve is a tunable constant.
- **The ranking engine is untouched.** `weights_from_tiers` writes the same `criteria.weights` map `rank_candidates` already reads (M8). Re-sorting on a tier edit is the existing pure math; M9 adds only the tier→weights derivation and its persistence.
- **Default layout = familiar S-Tier / A-Tier / B-Tier + Ignore, with every dimension starting in A-Tier.** The named tiers give the committee an immediate tier-list mental model and room to both promote (to S) and demote (to B / Ignore); starting everything in one tier keeps the weights uniform, so the opening ranking is still the M8 equal-weight baseline (weight-normalized fit makes "all in A" identical to "all equal") until the committee moves something. The labels are just the default — tiers can be renamed, added, and removed freely.
- **Deterministic and trivially reversible.** Same tier layout → same weights → same order. Undo/redo is editing the layout; there is no separate weight state to keep in sync.
- **No AI, no cost gate in v1.** Manual tiering only — a tier-list UI (`@dnd-kit` for accessible drag), a pure derivation function, and thin persistence (`GET`/`PUT /screening/tiers`; PUT validates keys against the run's dimensions, persists `tiers` + derived `weights`, and returns the fresh ranking). Both 409 before a run exists.
- **Run-scoped.** Tiers reference dimension keys, so they belong to a run. Re-running Rank makes a new run with fresh dimensions and a default (single-tier) layout — correct, since old tiers would reference dead keys.

**Fast-follows (in order), recorded so they aren't lost:**

1. **Add a dimension mid-tiering** (next after v1). Dragging dimensions around is exactly when the committee notices a factor the AI missed, so the tier-list grows an "add dimension" affordance. A user-added dimension changes the dimension set → new `dims_hash` → it re-enters the **cap-gated scoring pass for that one dimension** (existing scores stay cached), then appears as a chip. No new AI surface — it reuses the existing scoring pass. This relocates the parked "human-editable criteria" enhancement into the M9 flow where the need actually arises.
2. **AI Criteria Coach** (later, after hands-on use). *Not* a propose-the-tiering tool — its role is to **help the committee understand the weighting they built and challenge it**: surface tensions ("income mix is in Ignore, but three of your top candidates lead mainly on it — intended?"), flag near-ties, prompt reflection. Deliberately deferred until the tier-list has been used against real data, because what is worth challenging only becomes clear from use. A cheap synthesis call when it lands.

### Agent Workflow

MVP implementation should bias toward simplicity, readability, and understandability over maximum agent sophistication.

The application is *designed as* a multi-agent system, but the agents are a conceptual model, not a mandate to build orchestrated LLM loops everywhere. The roles below are real and useful as a decomposition; how each is *implemented* depends on whether it benefits from coordination.

**Realized architecture (through milestone 7): a pipeline of single-purpose passes + human gating.** Each "agent" so far is a named, user-visible pass — deterministic code (hard filters) or one structured-output call (quality flags, essay analysis, pattern discovery, dimension scoring). State lives in the database between passes; the "orchestration" is the human clicking gated workflow steps in order plus deterministic control flow (`screen_applications` fanning out a batch, the dimensions-hash threading discovery into scoring). No LLM decides what runs next, and no agent calls another agent. This is deliberate, not a shortcut: the product's hard requirements — pre-run cost estimates and a spending cap, per-(candidate, kind, prompt-version) caching, auditability of every prompt/output/rationale, eval-replayable units, and reproducible structured output — all depend on the call graph being known in advance. A swarm whose calls are decided at runtime would fight all five. **Screening is a known, ordered task, so a pipeline is the right spine — not a fallback from a swarm.**

**Where genuine multi-agent coordination earns its place.** A `Coordination Agent` that plans work, routes between agents, and decides when an output needs revision before the user sees it *is* wanted — but only where the task has a feedback/revision loop or a runtime-variable call graph that a fixed pipeline cannot express. Those spots are specific, and coordination should be added there surgically (and stay **bounded** — generate→critique→retry-N, not open-ended), never as a swarm replacing the pipeline:

- `Evidence Auditor` (M8+): the first real loop. After ranking/recommendation, an auditor checks each recommendation is grounded in the application data and sends weakly-supported ones back for revision — a bounded generate→critique→maybe-regenerate cycle. This is the cleanest first place a Coordination Agent supervises a revision loop.
- **M9 re-weighting loop**: drag a criterion into a tier → re-sort → adjust again. By design the re-sort is deterministic math over cached scores (see M7), so the "loop" is human-in-the-loop + arithmetic, not an LLM orchestrator spending tokens per turn — there is no model call at all in M9 as shipped. (The future Criteria Coach fast-follow adds a *bounded* model touch: it reflects on the weighting the committee built and challenges it, but still does not re-rank.)
- `Screener-Evaluator` (M7+): evaluates the *system across runs*, not one candidate, and proposes human-approved, versioned improvements (a new named schema field + prompt-version bump, a prompt edit, a model swap). Loop-shaped but deliberately human-gated; schema/prompts are **never self-modified at runtime** — autonomous mutation would break comparability, caching, eval consistency, and auditability.
- A `Coordination Agent` becomes worthwhile once two or more of these loops run in one screening session and their order/retries need supervising (e.g. score → audit → re-score the flagged few → re-rank). Until then a coordinator over single-shot passes would be ceremony. Introduce it when the loops exist to coordinate, and have it orchestrate *bounded* sub-agent calls with explicit retry limits and a recorded decision trail — preserving the cost/audit/eval properties the pipeline gives us for free.

The full role set (each a pass today, some gaining loops later): `Ingestion Agent` (read rows, map columns, detect drift), `Hard Filter Agent` (deterministic eligibility, auditable reasons), `Essay Analyst` (M6, neutral extraction — does not judge fit), `Pattern Finder` (M7, discovers differentiating dimensions), `Dimension Scorer` (M7, scores candidates on those dimensions), `Criteria Coach` (M9 fast-follow, reflects on and challenges the committee's tier weighting — does not elicit or re-rank), `Ranking Agent` (M8–9, deterministic weighted-sum re-rank on the tier weighting), `Evidence Auditor`, `Report Agent` (M10, MOMI summaries/justifications/caveats), `Screener-Evaluator`, and the `Coordination Agent` above.

Every AI recommendation should be reviewable and overrideable. AI outputs should explain why a candidate advanced, not just provide a numeric score.

### Privacy, Auditability, And Evals

It is acceptable to send full application context, including names/contact context, to the AI model for this project. Redaction is not required for the initial design.

Applicant data should still be treated as sensitive personal information. The app should keep deterministic filtering separate from AI-assisted judgment, preserve auditability for prompts, model outputs, filter decisions, ranking rationales, and user overrides, and avoid writing back to source Google Sheets unless explicitly approved.

The app should include an eval-oriented design from early development:

- Maintain small fake fixture sets for deterministic-filter and AI-schema tests
- Test deterministic filters with unit tests
- Test AI output schemas for consistency
- Track whether agent recommendations are grounded in source fields
- Track hallucination, unsupported-claim, and evidence-quality failures
- Preserve enough trace data to debug regressions when models/prompts change

An explicit eval dashboard is not required for MVP, but the architecture should make it possible later.

Synthetic/sample applications are not required for MVP. Demos may use real co-op data only with people who are authorized to view it.

## Multi-Member MOMI Workflow

Each MOMI member should be able to run their own screening process separately. For each member, the app should preserve:

- The patterns surfaced by AI
- The questions asked by the app
- The member's answers
- The criteria or values inferred from those answers
- The resulting ranked shortlist
- Applicant-specific rationale and evidence

Each MOMI member should use their own login/name. Members may see each other's criteria and shortlists; anonymization is not required.

The app should then support combining member shortlists into a merged ranked list. The merged comparison should make criteria visible, so committee discussion can address not only which applicants were selected but why each member valued particular signals.

Merged shortlist behavior:

- Member rankings are weighted equally.
- Applicants appearing on multiple member shortlists should be prioritized.
- Applicants with strong disagreement, such as one member strongly rejecting a candidate while another ranks them highly, should be flagged for discussion.
- The merged output should include consensus recommendations, disagreement/discussion-needed candidates, and not-recommended candidates.
- A single-shortlist appearance may be shown if useful, but criteria comparison is more important than simply noting that an applicant appeared on one list.

Criteria comparison should identify:

- Criteria shared across committee members
- Criteria that differed between members
- Criteria unique to a member
- Plain-language summaries of each member's priorities, such as "prioritized practical co-op labour and clear participation commitment"

Members should be able to write manual candidate notes separate from AI-generated rationale.

For now, any user may finalize the merged recommendation list. In practice this is the MOMI chair's job, but a special chair account/role is not required for the initial design.

The committee-facing report should include both interview recommendations and a summary of how the pool was screened.

## Users, Roles, And Authentication

The MVP should support real Google login because multi-member screening is a major design requirement. For early MVP/testing, the app may run locally and Jeff may use multiple Google accounts to test authentication and role behavior.

Preferred authentication is Google login.

Access should be invitation/approval based when the app is live. Jeff is the initial admin and can invite MOMI members.

Roles:

- `Admin`: the initial account; can invite/manage users once invitations exist.
- `Member`: a MOMI committee screener — can run screening sessions, run shared cached AI quality checks, answer AI questions, rank candidates, add notes, and participate in merged comparison.

Every committee member is a trusted screener, so **the screening workflow has no admin-only surface.** Status overrides, the raw source row, and the raw AI narrative are all available to any logged-in member — these are just the source and reasoning behind data members already see, and the privacy boundary is screeners-vs-outsiders, with members inside it. The `Admin`/`Member` distinction exists in the data model (the first user created becomes admin) and is intended to gate user management when invitations are built, but it does not currently gate any route. Settings are login-only, not admin-only. The engineering default is `require_current_user`; add a role gate only for a genuinely admin-only capability, as a deliberate decision.

AI quality-check results are shared across users and cached per application content, model, and prompt version. Any logged-in member may run the checks; the cost-control concern is uncached work, not which member initiates a shared run.

A special MOMI chair/finalizer role is not required for the initial design.

## Screening Runs

Users may create multiple runs for the same application pool, such as "Jeff first pass" and "Jeff revised after thinking."

Screening runs should preserve enough source information to understand what application pool was used. The app does not need immutable snapshots; a sync/run metadata record is sufficient for MVP and likely sufficient long-term.

When criteria are revised after a completed run, the default behavior should be to update/overwrite the same run. The user should also be able to choose to create a separate new run instead.

Manual candidate notes may be visible to other members immediately.

AI-generated criteria summaries do not need a dedicated editing workflow for the initial design.

An audit log is not required for the initial design.

## Data Storage

Recommendation:

- Use Google Sheets as the external source of truth for submitted applications.
- Import application rows into the app database for screening runs, AI outputs, user answers, notes, rankings, criteria summaries, and reports.
- Use SQLite for the local MVP because it is simple, inspectable, and reliable for one machine/testing.
- Design the data layer so it can move to a hosted database for multi-user use.

The expected live committee size is about 5 MOMI members. They may sometimes use the app concurrently, but heavy simultaneous usage is unlikely. A hosted database will eventually be needed for true multi-user use across computers.

The app should minimize repeated spreadsheet access by importing/syncing rows and then using the app database for screening state. Google Sheets should be accessed for refresh/sync, not for every AI or UI operation.

Core data model decisions:

- An `Application` represents one household/application.
- Application data includes applicant, co-applicant, children, essays, references, income, pets, declaration, source metadata, and screening metadata.
- Preserve the raw Google Sheets row exactly as imported alongside normalized fields.
- Store the raw Google Sheets row as JSON in SQLite.
- Use the primary applicant email address as the primary application identity, while still giving each stored application an internal database ID for relationships and history.
- Normalize email identity by trimming whitespace and lowercasing before duplicate detection or primary-key use.
- If Google Sheets contains duplicate emails, use only the last-added row.
- If a source row changes after import, update the existing application when the user explicitly syncs and then re-run screening logic when the user tells the app to do so.
- Duplicate detection for MVP is based on email address.
- The newest application wins by default for duplicate email addresses.
- Compute normalized fields during import/sync, including `adult_count`, `child_count`, `children_under_18_at_move_in`, `has_real_estate`, `household_income`, `pet_count`, and `pet_types`.
- Income parsing is straightforward because the form uses whole-number validation. The field always contains a clean integer for new submissions.
- Each sync should create a `SyncRun` record with timestamp, source sheet ID, row count, duplicate count, imported count, updated count, eligible count, filtered-out count, and needs-review count.

Admin settings such as Google Sheet link or ID, the hard-filter thresholds (income band, min/max children, max child age, pet limits), and the AI spending cap should live in the database rather than `.env`.

Local `.env` files should be supported for secrets and local credentials.

Use `.env.local` for local secrets and `.env.example` for safe placeholder values.

The following must not be committed to the repo:

- `.env` files
- OAuth credentials/secrets
- SQLite database files
- Applicant exports
- AI traces
- Raw prompts or model outputs containing applicant data

The repo should include a `.gitignore` before implementation.

## Reports

The primary final report format should be Google Docs.

Generated report links should be stored in the app database and associated with the relevant screening run.

## MVP Shape

The MVP should be a web app that runs locally and is used in the browser.

Implementation should use a Python backend with a polished React frontend.

MVP should use real Google login from the start. Jeff can test multiple user flows with multiple Google accounts. Google OAuth setup should be part of implementation or a documented prerequisite.

The OAuth app should be named `Penta Application Screener`.

Google Cloud setup should use a separate project for this app. This keeps OAuth scopes, consent screen, credentials, quotas, and future sharing cleaner.

Local OAuth redirect URLs may use localhost, such as:

- `http://localhost:8000/auth/google/callback`
- `http://localhost:5173/auth/callback`

The app should connect directly to Google Sheets in read-only mode for application import/sync. Google login and Google Sheets API access should be requested together at login because Sheets access is required for the app's core workflow.

It is acceptable to request Google Docs/Drive write permissions early so later report generation can create Google Docs without a second consent/setup pass.

Once user management exists, Google login should be restricted to invited/approved email addresses.

For MVP, the logged-in Google account may also be the account used to access Sheets/Docs. Sheet sync is currently available to any logged-in member; restricting it to admins later is acceptable but not current behavior.

The app should include an Admin settings screen for:

- Household income screening range
- Min/max children per unit and max child age
- Pet limits (max dogs, max cats, allow-other-pets)
- Min adult age
- Per-rule enable/disable toggles
- AI spending cap
- Bedrock/provider model choices
- Google Sheet link or ID

AI provider/model configuration is part of settings, which are currently login-only (not yet admin-gated); restricting settings to admins is a reasonable future tightening, not current behavior.

Manual Google Sheet link or ID entry in Admin settings is good enough for MVP. A future Drive picker/browse flow is optional.

Initial Google scopes should use the minimum set that supports MVP plus reports:

- basic Google login profile/email
- Google Sheets read-only
- Google Docs create/edit
- Google Drive file creation/management for files created by the app

Generated Google Docs reports should be created in the MVP report folder:

- `https://drive.google.com/drive/u/0/folders/1ymZE9c-_puF-3nxwexPYRdsU5iD00jRb`

When report content changes, regenerating a fresh Google Doc is acceptable for MVP.

Google Docs report generation should remain a later MVP milestone after ranked shortlist generation works.

The repo should include a Google Cloud/OAuth setup checklist before implementation so setup is reproducible across computers.

If required configuration is missing after login, the app should direct the user to setup/settings. Otherwise, the first screen should be the dashboard.

The dashboard should include an obvious `Sync applications` action. Hard filters should run automatically after sync.

Filtered-out views should show the human-readable reasons plus pertinent applicant-entered details that caused filtering.

Eligible applications should be shown in a table with expandable details and a candidate detail page.

Candidate detail pages should show normalized fields, hard-filter results, and source references. Raw source JSON and the model's raw AI reasoning narrative (the free-text commentary emitted alongside the structured quality-flag output) are available in separate expandable/debug sections, visible to any logged-in member.

Filtered-out applicants should be searchable and sortable in a table. This view must be designed for hundreds of filtered-out applicants without becoming unwieldy.

MVP v1 should focus on single-member screening by the Admin. Authentication and roles can exist in v1, but the full multi-member screening workflow is v2. The data model and architecture should allow v2 to add multi-member screening and merged shortlist comparison.

Overall MVP target demo:

- Import/sync applications from Google Sheets
- Show dashboard
- Apply deterministic hard filters
- Generate AI essay summaries for eligible applications
- Surface AI pattern questions
- Produce a ranked shortlist
- Generate a Google Docs report

Initial technical direction:

- Backend: Python with FastAPI
- Frontend: Vite React
- Database: SQLite for local MVP
- Authentication: Google OAuth
- Google data: read-only Google Sheets import/sync
- AI provider: Bedrock likely first, behind a provider-agnostic interface

Implementation defaults:

- Code style should prioritize readability first, avoid redundancy, and prefer elegant, boring solutions over clever abstractions.
- Shared business rules, eligibility thresholds, field mappings, prompts, and schema definitions should have a single clear home.
- Abstractions should be added only when they reduce real duplication or clarify an important boundary.
- During MVP iteration, clean changes are more important than backward compatibility for internal APIs, local schemas, fixtures, and UI shapes. Backward compatibility should be added only when real users or real applicant data require it.
- Python environment and dependency management: `uv` with a project-local virtual environment.
- Backend ORM and migrations: SQLAlchemy with Alembic.
- Backend tests: `pytest`.
- Frontend package manager: `npm`.
- Frontend tooling: Vite React.
- Authentication/session handling: Google OAuth with signed server-side session cookies for the local MVP.
- Database design: relational tables for workflow data, with JSON columns for raw Google Sheets rows, flexible source payloads, AI outputs, and debug traces.
- Future hosted database path: keep the relational model portable to Postgres.

Suggested implementation milestones:

1. Project scaffold, local dev environment, Google OAuth setup, and SQLite schema.
2. Read-only Google Sheets import/sync and application dashboard.
3. Deterministic hard filters, configurable rules engine, and filtered-out view.
4. Application tables, candidate detail pages, and searchable/sortable views.
5. AI quality flags (cost estimate, user confirms, detect suspicious patterns in eligible applications).
6. AI provider adapter, cost estimate/cap, cached per-candidate essay analysis, and admin raw-debug view.
7. Pool pattern discovery and per-candidate dimension scoring (read-only surfacing) — the AI foundation for ranking.
8. Deterministic ranked list: equal-weight baseline over the cached dimension scores. (A configurable shortlist line was later removed — the stack rank is read top-down.)
9. Interactive weighting via a tier-list maker: the committee drags discovered dimensions into self-defined importance tiers (+ an Ignore zone), and the ranking re-sorts instantly. Deterministic — no model call.
10. Google Docs report generation.
11. Multi-member screening and merged shortlist comparison.

The old milestone 7 ("pattern discovery, narrowing questions, previews, undo, ranked shortlist") was a single oversized step; it is now split across milestones 7–9, which pushed report generation to 10 and multi-member to 11. The split keeps each slice independently reviewable: 7 derisks the AI foundation (do discovered dimensions and per-candidate scores look right?) before 8–9 build the interactive ranking on top.

Milestones 1–9 are complete and proven end-to-end against real Bedrock (sync → quality flags → essays → discover ~14–16 fact-aware dimensions → score the pool → rank with the tier-list weighting). M8 delivered the deterministic ranked list (weighted average over the M7 `DimensionScore`s, equal-weight baseline, relative bands); M9 layered the tier-list maker on top (the committee drags criteria into S/A/B/Ignore tiers and the list re-sorts — no model call). **The next milestone is 10: Google Docs report generation.** Two M9 fast-follows are also queued (see the M9 design section): add-a-dimension mid-tiering, then the AI Criteria Coach. No new model calls were added for ranking; it stays math over cached scores.

Milestone 5 (AI quality flags) also delivered the shared AI foundation originally listed under milestone 6: the provider-agnostic interface (Strands + Amazon Bedrock, with a deterministic mock for tests), cached per-application analysis keyed on content hash + model + prompt version, a token pricing table, cost estimate, per-run spending cap, member-accessible quality-check runs, and raw-debug access via the candidate detail page. Milestone 6 is therefore now scoped to essay analysis and committee-ready summaries on top of that foundation.

The status model was reworked during milestone 5 (see "Application Status Model"): `status` (eligible/ineligible) with a `status_source` (untouched/rules/ai/human), human override that is sticky against machine re-runs, and a staleness signal when machine findings change after a human review.

Jeff will handle commits at stable milestones.

### Resuming — current state (through M9)

What exists and works (all committed):
- AI passes: `app/ai/pattern_discovery.py`, `app/ai/dimension_scoring.py`, `app/ai/essay_analysis.py`, `app/ai/quality_flags.py`, `app/ai/applicant_facts.py` (shared facts view). Schemas in `app/ai/schemas.py`.
- `app/api/screening.py` exposes the merged **Rank chain** (`/rank/estimate`, `/rank/run` — essays → criteria → scores under one cost gate), `/current`, the deterministic `/ranking`, and the M9 `/tiers` (GET/PUT). `app/services/screening_run.py` wires `ScreeningRun.criteria` (`pattern_report`, `dims_hash`, `pool_fingerprint`, equal-seeded `weights`, `tiers`). `app/domain/ranking.py` is the pure ranking math.
- Per-run scoring cache `kind = "dimension_scoring:<dims-hash>"`; estimate self-tunes across dims-hashes via the `dimension_scoring:` prefix.
- Frontend: three single-verb workflow steps (Import → Screen → Rank) + a "View ranking" action; the ranked view hosts the `@dnd-kit` tier-list maker (drag criteria into S/A/B/Ignore tiers → instant re-sort) and confidence-colored per-driver rationale lines. No-op Screen/Rank re-runs are blocked server-side and surfaced in the confirmation card as an "up to date" state with only a Close button.
- 127 backend tests pass; frontend typechecks and builds.

The next milestone is **10: Google Docs report generation**; two M9 fast-follows are queued (add-a-dimension mid-tiering, then the AI Criteria Coach).

Decisions locked (don't re-litigate):
- **LLM extracts scored features; ranking is deterministic math.** M8 weighted sum, M9 re-weight-and-re-sort — no model call per answer.
- **AI discovers what varies; the human decides what matters.** No AI-proposed weighting — `default_weight` was dropped from `PoolDimension`; M8 seeds `criteria.weights` equal and M9 is the only thing that moves them. Confidence is surfaced, not folded into fit. Fit labels are relative pool-position bands, not absolute thresholds. Ranking lives in `app/domain/ranking.py` (pure, deterministic) and surfaces as a separate ranked view, not an in-place re-sort of the eligible table.
- Dimension discovery: **5–25 range**, bias to split, anti-padding guardrail; real pool yields ~14–16.
- Both passes consume **essays + structured facts**; real-estate excluded (uniform among eligibles); filtered fields read for **residual variation** only.
- Discovery uses the **synthesis model (Sonnet)**, uncached, not cap-gated, wrapped for a 502 on failure. Scoring uses the **first-pass model (Haiku)**, cached, cap-gated; measure-first before upgrading.
- Architecture is a **pipeline of single-purpose passes + human gating**; bounded coordination/loops reserved for the Evidence Auditor (M8+), the future Criteria Coach, and the Screener-Evaluator (see "Agent Workflow").
- **Workflow is three single-verb steps: Import → Screen → Rank.** Rank is one button orchestrating the essays → criteria → scores chain (sub-passes never run individually); the combined cost is estimated up front and the cap enforced once over the sum. The standalone per-pass endpoints (`/essay-analysis/*`, `/screening/discover`, `/screening/scoring/*`) were removed; only `POST /screening/rank/run` drives the chain. "Screen" is the AI integrity pass, not the eligibility gate (that is deterministic, at Import/sync).

M8 is complete: the ranked list reads each eligible candidate's latest `dimension_scoring:<current dims-hash>` result, combines with the run's equal `criteria.weights` into a weighted average, and renders a ranked view with relative bands and per-row rationale (numbers stay supporting detail per "Ranking And Outputs"). The committee reads the stack rank top-down; there is no fixed cut line.

Known follow-ups still open (small, non-blocking):
- Re-scoring the full pool is ~$0.40 on Haiku against the $1.00 default cap — iterating on dimensions can approach the cap; raise it in settings if a run 402s.

Resolved follow-ups:
- **Scoring cost estimate was ~2x low and didn't self-tune.** Two compounding causes: the scoring fallback under-counted output tokens (~700 vs. the real ~1800 — scoring emits a rationale + evidence for *every* dimension), and the estimate's observed-usage lookup keyed on the exact `dimension_scoring:<dims_hash>` kind, which changes every run, so real usage never accumulated under a stable key and the blind fallback was always used. Fixed by (a) correcting the fallback constants to observed averages and (b) adding `usage_kind_prefix` to `estimate_cost`, so scoring averages usage across *all* `dimension_scoring:*` rows (token cost depends on prompt shape, not which dimensions were discovered) — the estimate now self-tunes across runs like the other passes. Cache hits still key on the exact kind. The combined Rank estimate prices what is currently uncached, so it shows essays at ~$0 once they are cached (correct), and the headline lands near real per-run cost.
- **Run-total toast over-reported cost on cache hits.** The `RunTally` summed `outcome.cost_usd` for *every* result, but a cached outcome carries its *original first-run* cost (kept for auditing) — so a re-run that hit the essay cache added that essays' old cost to the toast even though no model call happened (e.g. a Rank re-run reported ~$0.68 when only ~$0.49 was actually spent). Fixed in both `RunTally`s (screening + quality flags): a cache hit contributes **$0** to the run total (it spent nothing now), while `cached`/`flagged` counts still include cached results. The toast now matches real spend and the pre-run estimate. This is also why the estimate (~$0.50) looked "wrong" against the toast — the estimate was right; the toast was double-counting cached work.
- **No-op Rank re-runs were allowed (and expensive).** Re-clicking Rank on an unchanged pool re-ran the whole chain — and because discovery is nondeterministic, it churned the dimension wording, changed the dims-hash, and forced a full ~$0.40 re-score for an identical result. Fixed with a **pool fingerprint** gate: the run stores a hash of the sorted eligible `raw_row_hash`es, and `/rank/run` blocks (409) when that fingerprint is unchanged; `/rank/estimate` returns `ranking_current` so the UI says "up to date" instead of offering to spend. Re-ranking requires a real pool change (new/edited/eligibility-flipped application). See "Pattern Discovery And Dimension Scoring" for the rationale; this supersedes the earlier always-fresh-run behavior.
- **No-op Screen re-runs now blocked too (symmetry).** Screen had the same shape — a fully-cached re-run was a $0 no-op — but only the UI avoided it; the API still allowed it. Made symmetric with Rank: `/quality-flags/run` blocks (409) when `to_analyze == 0` (nothing uncached), and the UI surfaces the same "already up to date" state. Screen needs no pool-fingerprint (its per-application cache already tells it what is uncached); the gate is simply "is there anything new to analyze." Both steps now behave identically — a no-op is blocked server-side. Note the human-sticky-status guarantee (a re-run never overwrites a human override) is now exercised on *partial* re-runs: a cached human-overridden application still flows through the status hook when a new applicant triggers the run.
- **Confirmation card always shows; no-op state lives in the card, not a toast.** Clicking Screen/Rank previously short-circuited to a transient toast when there was nothing to do (Screen fully cached / Rank pool unchanged), which was easy to miss and inconsistent with the confirm-first flow. Now the card *always* opens; in the nothing-to-do state it explains why and offers only **Close** (the run button is omitted, not just disabled — a disabled primary button still reads as actionable at `opacity: 0.7`). Toasts are now reserved for run completions and errors.
- **Rank workflow badge showed green while a re-rank was legitimately available.** The Rank step's amber-stale signal was derived from score *coverage* (`cached < inScope`), but Rank's real currency is the **pool fingerprint** the no-op gate checks. Moving a previously-scored candidate back into the eligible pool changes the fingerprint while leaving coverage full — so the badge read green even though re-ranking was warranted and allowed. Fixed by surfacing `rankingCurrent` (the same `ranking_is_current` the gate uses) from the dashboard and driving the Rank step's stale badge off it via an explicit `outOfDate` prop, instead of re-deriving from coverage. Coverage still drives the `cached/inScope` fraction and Screen's staleness. The badge and the gate now share one source of truth.
- **Import now flags amber when settings change.** Extended the same pattern to the Import step: each `SyncRun` stores a `settings_fingerprint` (hash of the import-relevant settings — sheet id + hard-filter thresholds + disabled rules), and the dashboard returns `importCurrent` by comparing it to the live settings. When they diverge, Import goes amber ("Settings changed since the last import — re-import to apply them"), since a re-import would reclassify eligibility. Pet limits and the AI cap are excluded (not hard filters). A null fingerprint (rows imported before the column existed) reads as current, so old data doesn't false-flag. Unlike Screen/Rank there is no server-side no-op gate to mirror — Import is cheap and idempotent, so this is purely an advisory badge. Disabled workflow steps also gained explanatory hover tooltips (`disabledTitle`): Import "Add a Google Sheet link…", Screen "Import applications first." / "No eligible applicants…", Rank "Run Screen first." / "No eligible applicants…". This replaced the standalone orange "Setup needed" callout, which was redundant with the already-disabled Import button.

## Remaining Open Questions

These are the questions that still need decisions or can wait until their implementation milestone.

### Before Google Integration

1. Create the separate Google Cloud project for OAuth and Sheets/Docs API access.
2. Translate the already-decided Google access needs into exact OAuth scope strings during implementation.

### Before AI Milestone

Decisions resolved during milestone 5:

- **Provider/SDK:** Strands Agents over Amazon Bedrock (`us-west-2`), behind a provider-agnostic interface; a deterministic mock provider backs tests with no AWS. Model IDs are Bedrock inference profile IDs (the `us.`/`global.` prefixed form), not bare on-demand IDs.
- **Models:** quality-flag first pass uses `us.anthropic.claude-haiku-4-5` (cheapest capable); a Sonnet synthesis model is configured for later judgment-heavy milestones. Both are Admin-configurable.
- **Spending cap:** default $1.00 per run, Admin-configurable; enforced against the estimate before a run starts.
- **Pricing:** hardcoded token table (the AWS Price List API carries no Claude model past v3, so it cannot price the models we use); unknown models fall back to Opus-tier so estimates never under-count.
- **AI-written answers:** the quality pass flags generic AI-boilerplate essays, but flagging is informational input to human review, never auto-disqualifying.

Still open for later AI milestones:

1. Pick models for recommendation challenge/audit and final report synthesis. (Pattern discovery resolved in milestone 7: synthesis model / Sonnet. Per-candidate dimension scoring starts on the first-pass model / Haiku, measure-first.)
2. Define structured output schemas for narrowing questions, evidence audit, and report sections (the quality-flag, essay-analysis, and — in milestone 7 — pattern-discovery and dimension-scoring schemas exist; `app/ai/schemas.py` is the shared home).
3. Define the first small eval/fixture strategy for AI schema consistency.

### Before Reporting

1. Define the Google Docs report outline.
2. Decide whether reports include recommended candidates only, near-misses, filtered-out counts, or filtered-out details.
3. Decide the amount of applicant personal/contact detail appropriate for MOMI reports.
4. Define the tone and format of recommendation and `why not selected` explanations.

### Before Multi-Member V2

1. Define the exact merged-ranking formula for equal-weight member rankings.
2. Define how disagreement flags should be calculated.
3. Define the criteria-comparison report layout.
4. Decide whether multi-member deployment requires hosted Postgres, AWS-hosted SQLite-compatible storage, or another hosted database.
5. Choose the eventual cloud deployment path, including whether AWS AgentCore is useful once the local MVP is working.

## Future Enhancements

Not scheduled into a milestone yet; captured so they aren't lost.

- **Human-editable screening criteria with in-place re-rank.** Today the criteria (`PoolDimension`s) are AI-discovered and fixed for a run; the human only adjusts weights (M9). A natural enhancement is letting the committee directly **edit the criteria themselves** — rename or reword a dimension, edit its definition, remove one that isn't useful, or add a dimension the AI missed — and then re-rank on the revised set. This is distinct from the existing note that criteria can be revised for *future* runs ("Interactive Screening"): this is editing the *current* run's criteria and re-ranking in place. Design implications to work through when scheduled: an added/edited dimension changes the dimension set, so the `dims_hash` changes and affected candidates need (re-)scoring on the new/changed dimension — i.e. it re-enters the cap-gated scoring pass for just those dimensions, not a full re-rank from scratch. Removing a dimension or editing only its display wording (name) needs no model call — it is a weight-zero drop or a relabel, and re-ranking stays pure math over cached scores. Editing a dimension's *definition* changes what it measures, so it should invalidate that dimension's scores and re-score. The weights map (`criteria.weights`) and the M9 tier-list layer cleanly on top of a human-edited criteria set. Fits the existing architecture: the AI proposes the axes, the human owns them.
