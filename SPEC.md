# Penta Application Screener Specification

## Purpose

The Penta Application Screener helps screen 300+ housing co-op applications for Penta Housing Coop. It imports application responses from a Google Sheets response spreadsheet in the Penta Google Drive folder, applies deterministic hard filters, uses AI-assisted review for essay answers, and produces a committee-ready report for MOMI (Move In Move Out).

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

## AI Direction

The application should be designed as a multi-agent system. Candidate architecture:

- `Ingestion Agent`: reads application rows, maps columns, validates required fields, and detects schema drift.
- `Hard Filter Agent`: applies deterministic eligibility and completeness rules, producing auditable pass/fail reasons.
- `Essay Analysis Agent`: evaluates essay answers against defined rubrics and extracts evidence.
- `Pattern Discovery Agent`: finds themes, differentiators, risks, and clusters across qualified candidates.
- `Questioning Agent`: proposes high-value questions for the user that will meaningfully narrow the pool.
- `Ranking Agent`: updates candidate ranking/shortlist after user answers and rubric changes.
- `Report Agent`: produces MOMI-facing summaries, justifications, and caveats.
- `Audit Agent`: checks that outputs are grounded in application data and flags unsupported claims or sensitive-data issues.

## Principles

- Treat applicant data as sensitive personal information.
- Keep deterministic filtering separate from AI-assisted judgment.
- Preserve auditability for prompts, model outputs, filter decisions, score rationales, and user overrides.
- Make every AI recommendation reviewable and overrideable.
- Avoid writing back to source Google Sheets unless explicitly approved.
- Prefer outputs that explain why a candidate advanced, not just a numeric score.

## Open Questions

### Eligibility And Hard Filters

1. What unit size or sizes are being filled first: 1 bedroom, 2 bedroom, 3 bedroom, or multiple simultaneous lists?
2. What are the hard eligibility rules for household size by unit type?
3. Is income a hard filter, a ranking factor, or both?
4. What are the exact income thresholds or affordability constraints?
5. Does owning real estate automatically disqualify an applicant?
6. Does living at the current address for less than two years affect eligibility, or only reference requirements?
7. Are incomplete landlord or employment references hard failures, warnings, or follow-up items?
8. Are duplicate applications expected, and how should they be merged or rejected?
9. Should prior email-list signup date influence priority?
10. Are there legal, co-op bylaw, or housing-policy constraints we must encode exactly?

### Essay Review

1. What qualities should the essay review reward?
2. What qualities should it penalize or flag for manual review?
3. Are there disallowed criteria the AI must never use?
4. Should each essay question have a separate rubric?
5. Should the app score essays numerically, categorize them qualitatively, or both?
6. What evidence should be shown for each AI assessment?
7. How should we handle applicants whose writing is brief, awkward, translated, or non-native English?
8. Should the app detect likely AI-written answers, and if so, what should it do with that signal?
9. Should the review favor co-op experience, practical maintenance skills, committee experience, community values, long-term stability, or some balance?
10. What makes a candidate clearly worth interviewing?

### Interactive Narrowing

1. What is the target shortlist size before manual review?
2. Do you want the app to ask one question at a time or present batches?
3. What kinds of questions should the app ask you: value tradeoffs, threshold decisions, tie-breakers, or candidate comparisons?
4. Should user answers become permanent screening criteria for the run?
5. Should the app show how many candidates would be affected before applying an answer?
6. Should you be able to undo or branch a screening decision?
7. Should different screening runs be saved and compared?
8. How should the app handle uncertainty or close calls?

### Output And Committee Report

1. What should MOMI receive: PDF, Google Doc, spreadsheet, HTML report, or multiple formats?
2. Should the report include all candidates, only recommended candidates, or recommended plus near-misses?
3. How much personal detail should be included in the MOMI version?
4. Should rejected candidates have reasons recorded privately but omitted from the shared report?
5. What tone should the justifications use?
6. Should the report include dissenting signals or caveats for recommended candidates?
7. Do you need anonymized/blinded review options?

### App Shape

1. Should this be a local-only app, a hosted web app, or a CLI plus local web UI?
2. How will authentication to Google Drive and Sheets work across multiple computers?
3. Which AI provider/model should we use?
4. Do you want the app to store data locally, and if so, where?
5. Should runs be resumable after closing the app?
6. Do you need multi-user access, or is sharing the final report enough?
7. What should happen when new applications arrive after a screening run starts?
8. Should the app continuously sync, manually refresh, or import snapshots?

### Risk, Privacy, And Audit

1. What applicant data should never be sent to an AI model?
2. Is it acceptable to send essay answers to an AI model?
3. Do we need applicant consent language or internal policy notes?
4. How long should imported data, AI outputs, and audit logs be retained?
5. Should every shortlist decision be traceable to exact source fields?
6. Who besides Jeff can view raw applicant data?
7. Should the app redact contact information from AI prompts when possible?
