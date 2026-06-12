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

### Hard Filter Outputs

- `eligible`: application passes all enabled rules and proceeds to AI screening
- `filtered_out`: application fails one or more deterministic rules and is excluded

Hard filter reasons must be human-readable, such as `Household has 3 adults; maximum is 2`. There is no intermediate state — rules are binary filters.

### AI Quality Flags

Separately from AI triage (which resolves ambiguous data), AI should make a quality/integrity pass over eligible applications to flag suspicious patterns that are too subjective or contextual for deterministic rules. This is not filtering — it's surfacing things for the screener to be aware of. Flags are informational, not disqualifying.

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

For MVP, use OpenAI as the default AI provider while keeping the architecture provider-adaptable. A future cloud deployment may use AWS and should leave room to evaluate Amazon Bedrock AgentCore or similar managed agent platforms.

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

The screening experience should discover patterns in essay responses and ask the user what matters, rather than starting from a fully fixed rubric. The likely high-level criterion is "fit for Penta," but this is intentionally opinionated and user-dependent.

The app should ask the user batches of 1 to 3 narrowing questions based on discovered patterns. Each question should preview impact where possible, such as how many candidates would remain under each answer. The app should maintain a live count of how many applicants are currently qualified after each user answer or screening criterion. The user decides when the pool has been narrowed enough for manual review. A likely target shortlist size is around 20, but this should not be hard-coded.

Users should be able to undo answers to AI-generated narrowing questions.

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

For admin debugging and learning, raw AI analysis, traces, prompts, and intermediate outputs should be accessible to Admin users. The normal app experience should emphasize polished summaries.

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

### Agent Workflow

MVP implementation should bias toward simplicity, readability, and understandability over maximum agent sophistication.

The application should be designed as a multi-agent system, but the initial implementation can use simple service boundaries that make agent roles visible in the UI. Initial roles may include:

- `Coordination Agent`: plans and supervises the screening workflow, routes work between agents, tracks run state, and decides when outputs need revision before they are shown to the user.
- `Ingestion Agent`: reads application rows, maps columns, validates required fields, and detects schema drift.
- `Hard Filter Agent`: applies deterministic eligibility and completeness rules, producing auditable pass/fail reasons.
- `Essay Analyst`: evaluates essay answers and extracts evidence.
- `Pattern Finder`: finds themes, differentiators, risks, and clusters across qualified candidates.
- `Criteria Coach`: proposes high-value questions for the user that will meaningfully narrow the pool.
- `Ranking Agent`: updates candidate ranking/shortlist after user answers and rubric changes.
- `Evidence Auditor`: checks that outputs are grounded in application data and sends unsupported or weakly supported recommendations back for revision.
- `Report Agent`: produces MOMI-facing summaries, justifications, and caveats.

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

- `Admin`: can invite/manage users and finalize administrative settings.
- `Member`: can run screening sessions, answer AI questions, rank candidates, add notes, and participate in merged comparison.

Admin users should have all normal MOMI member capabilities plus access to admin panels, provider/model settings, raw AI debugging details, and other extra information.

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

For MVP, the logged-in Google account may also be the account used to access Sheets/Docs. Admin-only sheet sync is acceptable for MVP.

The app should include an Admin settings screen for:

- Current unit size
- Move-in date
- Household income screening range
- AI spending cap
- OpenAI/provider model choices
- Google Sheet link or ID

AI provider/model configuration should be Admin-only.

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

Candidate detail pages should show normalized fields, hard-filter results, and source references. Raw source JSON should be available in an Admin-only expandable/debug section.

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
- AI provider: OpenAI adapter behind a provider-agnostic interface

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
7. Pattern discovery, 1 to 3 narrowing questions, impact previews, undo, and ranked shortlist.
8. Google Docs report generation.
9. Multi-member screening and merged shortlist comparison.

Milestones 1–4 are complete. The next milestone is AI quality flags (milestone 5).

Jeff will handle commits at stable milestones.

## Remaining Open Questions

These are the questions that still need decisions or can wait until their implementation milestone.

### Before Google Integration

1. Create the separate Google Cloud project for OAuth and Sheets/Docs API access.
2. Translate the already-decided Google access needs into exact OAuth scope strings during implementation.

### Before AI Milestone

1. Pick initial OpenAI models for:
   - first-pass candidate analysis
   - pattern discovery
   - recommendation challenge/audit
   - final report synthesis
2. Set default per-run AI spending cap.
3. Define structured AI output schemas for candidate analysis, pattern discovery, narrowing questions, ranking, evidence audit, and report sections.
4. Decide whether likely AI-written answers should be detected or ignored.
5. Define the first small eval/fixture strategy for deterministic filters and AI schema consistency.

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
