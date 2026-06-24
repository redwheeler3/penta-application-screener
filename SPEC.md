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

- **ID**: machine-readable slug (e.g. `real_estate_ownership`, `child_age_over_18`)
- **Display name**: human-readable label shown in the admin UI (e.g. "Real estate ownership")
- **Description**: explains what the rule checks and why
- **Outcome**: `filtered_out` (the only outcome — any rule that fires disqualifies)
- **Parameters**: configurable thresholds or values (e.g. income min/max, max adults, max pets). Not all rules have parameters.
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

**Age rules:**

| Rule ID | Description |
|---------|-------------|
| `child_age_over_18` | Any listed child has age 18 or older. The form states "children under 18." |
| `applicant_under_19` | Applicant age is under 19 (BC age of majority). |
| `co_applicant_under_19` | Co-applicant age is under 19. Indicates the co-applicant may actually be a child, not an adult household member. |
| `child_age_exceeds_parent` | Any child's age is older than the applicant's or co-applicant's age. Data entry error. |

**Financial rules:**

| Rule ID | Description |
|---------|-------------|
| `income_below_range` | Household gross income is below the configured minimum. Parameter: min_income (default $70,000). |
| `income_above_range` | Household gross income is above the configured maximum. Parameter: max_income (default $150,000). |
| `income_arithmetic_mismatch` | Applicant income + co-applicant income does not equal stated household total (tolerance: $1,000). |

**Property rules:**

| Rule ID | Description |
|---------|-------------|
| `real_estate_ownership` | Applicant owns real estate. |

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

The assistant does not "cut" candidates. At the expected scale (~300 applicants) it cannot ask the committee about candidates individually, and hard removal is the wrong model. Instead, the assistant **stack-ranks the entire qualified pool with a per-row rationale**, and the committee's answers re-sort that list. Narrowing answers adjust standing (soft ranking), never remove anyone — so a low-ranked candidate is never "rejected," just currently low, and a later answer can lift them back up. The committee draws the shortlist line wherever they choose by reading top-down.

Narrowing questions are global preference-elicitation, not per-candidate: e.g. "What matters more — financial stability or community involvement — or about equal?" Each answer reweights the ranking and the list re-sorts. The app should ask batches of 1 to 3 such questions based on discovered patterns. Questions should intentionally include some redundancy/overlap so that no single answer locks the order prematurely — a later, differently-framed question can rebalance the ranking and resurface candidates an earlier answer had pushed down. Each question should preview impact where possible, such as how the top of the list (e.g. the would-be top ~20) changes under each answer. The app should maintain a live count of how many applicants are currently above the user's chosen shortlist line. The user decides when the ranking is trustworthy enough for manual review. A likely target shortlist size is around 20, but this should not be hard-coded.

Users should be able to undo answers to AI-generated narrowing questions. Undo is a manual correction; the soft-ranking model above is what makes routine revisiting automatic (re-sorting rather than un-rejecting).

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

The defining architectural decision — **the LLM extracts scored features; ranking is deterministic math on top of them.** The model never produces "the ranking" *and never opines on importance.* It scores each candidate on a fixed set of discovered dimensions, and the ranking (milestone 8) is a plain weighted sum over those scores. Importance is a values judgment reserved for the human: the AI discovers *what varies*, the committee decides *what matters*. So milestone 8 starts every dimension at an **equal weight** — an honest "no judgment yet" baseline (fit is the plain average of a candidate's scores) — and milestone 9 is the only place weights diverge from equal, with every deviation traceable to a recorded human answer. A non-uniform AI-proposed default was rejected: it would quietly pre-commit the values question, presenting one applicant ahead of another before anyone said what they cared about. This is what makes the milestone 9 interactions — re-sort on answer, preview every answer's impact, live count above the shortlist line, and undo — cheap, instant, and *deterministic*: a narrowing answer only nudges weights, never re-invokes the model. Re-ranking the pool with the LLM on every answer was rejected: it is ~300× the cost per answer, slow, gives no cheap impact preview, and is nondeterministic (the order would jump for reasons unrelated to the answer). The SPEC's "hidden internal scores may be used to support ranking" points the same way — scores are the hidden support; labels and rationale are what the UI shows.

Two passes:

- **Pattern Finder (pool-level, one call, synthesis model).** Reads every eligible candidate's `EssayAnalysisReport` plus raw essays and discovers the **differentiating dimensions for this specific pool** — not a fixed rubric. Each dimension has a name, a definition, and a short why-it-differentiates note. It does *not* propose a weighting: importance is the committee's call, so weights are seeded equal at run creation and only the human moves them (milestone 9). Output is run-scoped (it describes the pool, not one candidate), stored on the `ScreeningRun`. Uses the synthesis model (Sonnet) because this is the cross-document judgment the synthesis tier is reserved for. This resolves the open question "pick a model for pattern discovery."
- **Dimension Scoring (per-candidate fan-out, first-pass model).** Scores each eligible candidate against the discovered dimensions: per dimension a score, a rationale, grounding evidence, and a confidence label. Starts on the first-pass model (Haiku) and upgrades to Sonnet only if an eval shows the scoring reads thin — the same empirical, measure-first stance milestone 6 takes on its model. The schema *shape* is fixed (`list[DimensionScore]`); only which dimensions appear is open, mirroring the `EssayAnalysisReport` discipline (fixed structure, open list contents).

Design constraints carried from the rest of the SPEC:

- **Scope:** eligible applications only, like essay analysis. Status-independent — scoring never touches `status`/`status_source`; it informs ranking, not the gate.
- **Cache key must include the dimensions.** The shared cache key is `(raw_row_hash, kind, model, prompt_version)` and does *not* see the prompt body — but a candidate's scores depend on the run's discovered dimensions. Two runs with different dimensions would otherwise collide and return stale scores. Fix: fold a short hash of the dimension set into the `kind` (e.g. `dimension_scoring:<dims-hash>`), so distinct dimension sets get distinct cache entries with no schema change.
- **Run-scoped, building on the existing `ScreeningRun` table.** The discovered dimensions are a property of a run, persisted in `ScreeningRun.criteria` (the table and JSON column already exist but are currently unwired). Milestone 7 wires the minimum the foundation needs; milestones 8–9 accrete weights, answers, and rankings onto the same run rather than adding a separate persistence milestone. Milestone 8 seeds `criteria.weights` (one entry per dimension key, all equal) and a `shortlist_size` default; the ranking engine reads `criteria.weights`, never a per-dimension field, so this map is the single seam milestone 9's narrowing answers mutate.
- **Surfacing (read-only):** the run's discovered dimensions are shown at the screening level; each candidate's per-dimension scores, rationale, and evidence appear on the candidate detail page. No ranked order yet — that is milestone 8. Numeric scores stay supporting detail; the committee-facing emphasis remains qualitative, per "Ranking And Outputs."
- **Schemas defined first.** `PoolPatternReport` (dimensions only — no weights; importance is the human's call) and `DimensionScoringReport` (`list[DimensionScore]`) land in `app/ai/schemas.py` before prompts/UI, per "AI output schemas should be defined before implementing the AI milestone." This resolves the open question "define schemas for pattern discovery and ranking."
- **Inputs: essays *and* structured facts.** Both passes see a shared `applicant_facts` view (household composition, ages, income + applicant/co-applicant split, employment tenure, pets) alongside the essays, so discovery can surface quantitative axes (income mix, employment stability, household-to-unit fit) and scoring can score them from the same facts. The view is defined once (`app/ai/applicant_facts.py`) so the two passes never drift — a fact-based dimension must be scoreable from the identical fact. Excluded: names/emails/phones (identifiers, no screening value) and **real-estate ownership** (a hard filter, so eligible applicants are uniformly non-owners — no residual signal). Fields that *are* hard filters but still vary (income within band, household size, pets) are framed for **residual variation** only (`FILTERED_FACTS_NOTE`): the model reads the variation that remains among the already-qualified pool, never the constant pass/fail fact, and never protected characteristics.
- **Dimension count is a guided range, not a fixed number.** Discovery targets **5–25 dimensions**, biased to *split* a broad axis into distinct, separately-weighable sub-dimensions rather than merge, but told explicitly not to pad to a number or invent axes the data does not distinguish. The range is wide because the right count depends on how richly the pool actually varies; the anti-padding guardrail keeps the ceiling from acting as a target. (Empirically, the real pool yields ~14–16.)
- **Discovery is uncached and not cap-gated.** Pattern discovery is a single synthesis call that writes to `ScreeningRun`, not through the per-application cache — so it is not invalidated by `PROMPT_VERSION` and re-running always produces a fresh run. It is not cap-gated (one cheap call, ~$0.07–0.11). Its model call is wrapped so a Bedrock failure returns a readable 502, not a bare 500. Scoring *is* cap-gated and cached; because re-discovery changes the dimensions-hash (and thus the scoring `kind`), it correctly forces a re-score.
- **Surfacing UX (built in M7).** The screening workflow is an ordered, gated strip in its own full-width row: Sync → Quality checks → Essays → Discover patterns → Score candidates. Each AI step shows live coverage of the *current* eligible set (`cached/inScope`) and goes amber-stale when results predate a re-sync, so "ran once" can't masquerade as "current." Discovery and sync persist a standalone value (dimension count, row count). All step outcomes surface as toasts: green auto-dismiss for success, red persistent (copyable) for errors. Every AI step confirms before running.

### Deterministic Ranked List (Milestone 8)

Milestone 8 turns the M7 per-candidate scores into the ranked shortlist. **No new model calls** — ranking is pure deterministic math over the cached `DimensionScore`s, which is exactly what makes the M9 interactions instant, free, and reproducible. Design decisions:

- **Equal-weight baseline.** Weights are seeded uniform at run creation (`criteria.weights`, one entry per dimension key). Fit for a candidate is the weight-normalized average of their per-dimension scores: `Σ(weight·score) / Σ(weight)` over dimensions with weight > 0. At M8 this is a plain average; M9's narrowing answers are the only thing that moves weights off equal. The AI never proposes importance (see the "Pattern Finder" note above) — discovering *what varies* is the model's job; deciding *what matters* is the committee's.
- **Confidence is surfaced, not discounted.** Each `DimensionScore` carries a confidence label; it is shown next to the score and rationale but **never folded into the fit number**. A score moves the ranking by exactly its weight and nothing else, so the ranking stays explainable top-down. (Confidence-weighting was considered and rejected for M8: it adds a hidden term that makes "why is this candidate here" harder to answer.)
- **Qualitative labels are relative bands, not fixed thresholds.** The committee-facing label on each row ("Strong fit", "Promising", "Mixed", "Limited") is assigned by the candidate's *position within this pool* (rank percentile), not an absolute score cutoff. This matches the "how does THIS pool vary" framing — bands always spread the pool and recompute as weights change — and keeps numbers as supporting detail, per "Ranking And Outputs." The raw fit number is available but never the headline.
- **Ranking is a pure domain function.** It lives in `app/domain/ranking.py` alongside `hard_filters.py` (deterministic logic, separate from AI per the engineering rules), takes already-fetched scores + weights and returns ordered rows with fit, band, rank, and per-dimension contributions preserved for explainability. No DB or provider access in the function itself — trivially unit-testable with hand-built scores, no mock provider needed.
- **Manual shortlist line + live count.** `criteria.shortlist_size` seeds the line (default ~20, not hard-coded as a rule); the user moves it and the UI shows a live count above it. The line never removes anyone — it is a reading aid over the soft ranking, per "Interactive Screening."
- **Surfacing: a separate ranked view, not an in-place re-sort** of the eligible table. Ranking is run-scoped and will grow the M9 question panel beside it, so it gets its own view rather than re-sorting the browse-applications table. The workflow strip is unchanged (ranking is a view over completed scoring, not a gated AI step). `GET /screening/ranking` returns the ordered rows + current weights + line + count; a shortlist-line endpoint persists the line. Both 409 if patterns/scores don't exist yet, matching the scoring endpoints.

### Agent Workflow

MVP implementation should bias toward simplicity, readability, and understandability over maximum agent sophistication.

The application is *designed as* a multi-agent system, but the agents are a conceptual model, not a mandate to build orchestrated LLM loops everywhere. The roles below are real and useful as a decomposition; how each is *implemented* depends on whether it benefits from coordination.

**Realized architecture (through milestone 7): a pipeline of single-purpose passes + human gating.** Each "agent" so far is a named, user-visible pass — deterministic code (hard filters) or one structured-output call (quality flags, essay analysis, pattern discovery, dimension scoring). State lives in the database between passes; the "orchestration" is the human clicking gated workflow steps in order plus deterministic control flow (`screen_applications` fanning out a batch, the dimensions-hash threading discovery into scoring). No LLM decides what runs next, and no agent calls another agent. This is deliberate, not a shortcut: the product's hard requirements — pre-run cost estimates and a spending cap, per-(candidate, kind, prompt-version) caching, auditability of every prompt/output/rationale, eval-replayable units, and reproducible structured output — all depend on the call graph being known in advance. A swarm whose calls are decided at runtime would fight all five. **Screening is a known, ordered task, so a pipeline is the right spine — not a fallback from a swarm.**

**Where genuine multi-agent coordination earns its place.** A `Coordination Agent` that plans work, routes between agents, and decides when an output needs revision before the user sees it *is* wanted — but only where the task has a feedback/revision loop or a runtime-variable call graph that a fixed pipeline cannot express. Those spots are specific, and coordination should be added there surgically (and stay **bounded** — generate→critique→retry-N, not open-ended), never as a swarm replacing the pipeline:

- `Evidence Auditor` (M8+): the first real loop. After ranking/recommendation, an auditor checks each recommendation is grounded in the application data and sends weakly-supported ones back for revision — a bounded generate→critique→maybe-regenerate cycle. This is the cleanest first place a Coordination Agent supervises a revision loop.
- **M9 narrowing loop**: ask 1–3 questions → re-weight → re-sort → ask again is loop-shaped, but by design the re-sort is deterministic math over cached scores (see M7), so the "loop" is human-in-the-loop + arithmetic, not an LLM orchestrator spending tokens per turn. A coordinator here decides *which questions to ask next* and *when the ranking is trustworthy*, not how to re-rank.
- `Screener-Evaluator` (M7+): evaluates the *system across runs*, not one candidate, and proposes human-approved, versioned improvements (a new named schema field + prompt-version bump, a prompt edit, a model swap). Loop-shaped but deliberately human-gated; schema/prompts are **never self-modified at runtime** — autonomous mutation would break comparability, caching, eval consistency, and auditability.
- A `Coordination Agent` becomes worthwhile once two or more of these loops run in one screening session and their order/retries need supervising (e.g. score → audit → re-score the flagged few → re-rank). Until then a coordinator over single-shot passes would be ceremony. Introduce it when the loops exist to coordinate, and have it orchestrate *bounded* sub-agent calls with explicit retry limits and a recorded decision trail — preserving the cost/audit/eval properties the pipeline gives us for free.

The full role set (each a pass today, some gaining loops later): `Ingestion Agent` (read rows, map columns, detect drift), `Hard Filter Agent` (deterministic eligibility, auditable reasons), `Essay Analyst` (M6, neutral extraction — does not judge fit), `Pattern Finder` (M7, discovers differentiating dimensions), `Dimension Scorer` (M7, scores candidates on those dimensions), `Criteria Coach` (M9, proposes narrowing questions), `Ranking Agent` (M8–9, deterministic weighted-sum re-rank on answers/weights), `Evidence Auditor`, `Report Agent` (M10, MOMI summaries/justifications/caveats), `Screener-Evaluator`, and the `Coordination Agent` above.

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

Admin settings such as Google Sheet link or ID, current unit size, move-in date, and spending cap should live in the database rather than `.env`.

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

- Current unit size
- Move-in date
- Household income screening range
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
8. Deterministic ranked list: equal-weight baseline, manual shortlist line, and live count above the line.
9. Narrowing questions, impact previews, and undo (the interactive re-sort).
10. Google Docs report generation.
11. Multi-member screening and merged shortlist comparison.

The old milestone 7 ("pattern discovery, narrowing questions, previews, undo, ranked shortlist") was a single oversized step; it is now split across milestones 7–9, which pushed report generation to 10 and multi-member to 11. The split keeps each slice independently reviewable: 7 derisks the AI foundation (do discovered dimensions and per-candidate scores look right?) before 8–9 build the interactive ranking on top.

Milestones 1–7 are complete and proven end-to-end against real Bedrock (sync → quality flags → essays → discover ~14–16 fact-aware dimensions → score 32 candidates). **The next milestone is 8: the deterministic ranked list** — a weighted sum over the M7 `DimensionScore`s (default weights from `PoolPatternReport`), a manual shortlist line, and a live count above it. No new model calls: ranking is math over cached scores. See "Resuming — state at end of the M7 session" below for the concrete starting point.

Milestone 5 (AI quality flags) also delivered the shared AI foundation originally listed under milestone 6: the provider-agnostic interface (Strands + Amazon Bedrock, with a deterministic mock for tests), cached per-application analysis keyed on content hash + model + prompt version, a token pricing table, cost estimate, per-run spending cap, member-accessible quality-check runs, and raw-debug access via the candidate detail page. Milestone 6 is therefore now scoped to essay analysis and committee-ready summaries on top of that foundation.

The status model was reworked during milestone 5 (see "Application Status Model"): `status` (eligible/ineligible) with a `status_source` (untouched/rules/ai/human), human override that is sticky against machine re-runs, and a staleness signal when machine findings change after a human review.

Jeff will handle commits at stable milestones.

### Resuming — state at end of the M7 session

What exists and works (all committed):
- M7 backend: `app/ai/pattern_discovery.py`, `app/ai/dimension_scoring.py`, `app/ai/applicant_facts.py` (shared facts view), `app/api/screening.py` (discover / current / scoring estimate+run), `app/services/screening_run.py` (wires the `ScreeningRun` table). Schemas `PoolPatternReport`, `PoolDimension`, `DimensionScoringReport`, `DimensionScore` in `app/ai/schemas.py`.
- Per-run scoring cache `kind = "dimension_scoring:<dims-hash>"`; dimensions persisted in `ScreeningRun.criteria` (`pattern_report`, `dims_hash`, discovery model/narrative/cost).
- Frontend: 5-step workflow strip in its own row with per-step coverage (`cached/inScope`, amber when stale) and standalone captions (rows, dimensions); every AI step confirms before running; unified toast system (green auto-dismiss 7s, red persistent + copyable for errors).
- 101 backend tests pass; frontend typechecks and builds.

Decisions locked this session (don't re-litigate):
- **LLM extracts scored features; ranking is deterministic math.** M8 weighted sum, M9 re-weight-and-re-sort — no model call per answer.
- **AI discovers what varies; the human decides what matters.** No AI-proposed weighting — `default_weight` was dropped from `PoolDimension`; M8 seeds `criteria.weights` equal and M9 is the only thing that moves them. Confidence is surfaced, not folded into fit. Fit labels are relative pool-position bands, not absolute thresholds. Ranking lives in `app/domain/ranking.py` (pure, deterministic) and surfaces as a separate ranked view, not an in-place re-sort of the eligible table.
- Dimension discovery: **5–25 range**, bias to split, anti-padding guardrail; real pool yields ~14–16.
- Both passes consume **essays + structured facts**; real-estate excluded (uniform among eligibles); filtered fields read for **residual variation** only.
- Discovery uses the **synthesis model (Sonnet)**, uncached, not cap-gated, wrapped for a 502 on failure. Scoring uses the **first-pass model (Haiku)**, cached, cap-gated; measure-first before upgrading.
- Architecture is a **pipeline of single-purpose passes + human gating**; bounded coordination/loops reserved for the Evidence Auditor (M8+), the M9 narrowing loop, and the Screener-Evaluator (see "Agent Workflow").

For M8, start here: read each eligible candidate's latest `dimension_scoring:<current dims-hash>` result, combine with the current run's `default_weight`s into a weighted sum, sort, and render a ranked list with per-row qualitative rationale (numbers stay supporting detail per "Ranking And Outputs"). The shortlist line and live count are client state over that ordering.

Known follow-ups still open (small, non-blocking):
- The M7 `fallback_output_tokens` estimate for scoring may be stale now that prompts include facts; it self-tunes from real usage, so only revisit if estimates look off.
- Re-scoring the full pool is ~$0.40 on Haiku against a $0.50 default cap — iterating on dimensions can approach the cap; raise it in settings if a run 402s.

## Remaining Open Questions

These are the questions that still need decisions or can wait until their implementation milestone.

### Before Google Integration

1. Create the separate Google Cloud project for OAuth and Sheets/Docs API access.
2. Translate the already-decided Google access needs into exact OAuth scope strings during implementation.

### Before AI Milestone

Decisions resolved during milestone 5:

- **Provider/SDK:** Strands Agents over Amazon Bedrock (`us-west-2`), behind a provider-agnostic interface; a deterministic mock provider backs tests with no AWS. Model IDs are Bedrock inference profile IDs (the `us.`/`global.` prefixed form), not bare on-demand IDs.
- **Models:** quality-flag first pass uses `us.anthropic.claude-haiku-4-5` (cheapest capable); a Sonnet synthesis model is configured for later judgment-heavy milestones. Both are Admin-configurable.
- **Spending cap:** default $0.50 per run, Admin-configurable; enforced against the estimate before a run starts.
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
