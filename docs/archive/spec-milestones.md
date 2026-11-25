# Completed specification milestones

Archived from `SPEC.md` on November 24, 2026. This is delivery history, including
point-in-time plans and measurements; [the current specification](../../SPEC.md) owns current behavior.
Some earlier acceptance criteria were superseded by later decisions.

## Completed Milestones And Optional Future Work

The committed product roadmap is complete. The sections below record delivered milestones and
ideas that are explicitly optional, out of scope, or demand-driven rather than unfinished work.

### OpenAI-Versus-Anthropic Model Bake-Off (M20) — complete; production switch is operator-controlled

The application supports Claude and GPT through either Bedrock or their direct provider APIs behind
one provider-neutral boundary. The model catalog is the routing authority; settings store the exact
route and reasoning effort for each pass, while caches and captured Rank provenance use a provider-neutral
model identity. Switching only between certified-equivalent routes preserves valid cached work;
changing the underlying model or effective reasoning invalidates it.

The evidence-backed OpenAI configuration is direct Luna at reasoning `low` for Screening and
Dimension scoring, and direct Terra at reasoning `low` for Pattern discovery, Dimension
decomposition, Dimension matching, and Dimension consolidation. Reasoning is explicit so provider
defaults cannot silently change quality, latency, or cost. OpenAI audit output is an exposed
reasoning summary or concise user-visible preamble, not raw private chain of thought.

Production continues to use Bedrock Haiku and Sonnet until an admin deliberately changes the
per-pass settings. Direct Luna-low and Terra-low passed synthetic, schema-constrained probes from
the production Fly Machine on August 22, 2026, so both direct routes are available for an admin to
select. Credentials remain server-side secrets, and routes without their required credentials
cannot be saved. The co-op accepts the documented provider privacy tradeoffs for applicant-bearing
passes; the selected route determines which provider's current API terms apply.

Detailed implementation history and measured results live in [CHANGELOG.md](../../CHANGELOG.md). The
selection evidence and reproduction commands are in
[ADR 0013](../adr/0013-openai-model-selection.md); the routing architecture is in
[ADR 0014](../adr/0014-multi-provider-model-routing.md) and the Bedrock Runtime migration is in
[ADR 0016](../adr/0016-global-openai-bedrock-runtime.md).

### Built-In Applications And Committee Access (M21) — complete

**Goal:** replace the external Google Form/Sheet intake path with a first-party public
application experience at a separate applicant-facing hostname, add email-delivered access for
applicants and committee members, and reduce committee Google sign-in to identity-only OpenID
Connect. The product contract is specified in
[Built-In Application Intake](../../SPEC.md#built-in-application-intake); this section defines the
implementation boundary and sequence.

M21 is one milestone because intake identity, private drafts, publication, email access,
and removal of the Google source are one correctness boundary. Splitting them into independently
shippable production states would either expose unauthenticated PII, permit identity collisions,
or require the dual Google/built-in transition that the between-cycle cutover deliberately avoids.
The work is delivered in internal stages and released only when the end-to-end replacement is
ready.

All seven delivery stages are complete. The browser form includes
immediate private Save and return later, seven-day access links with regeneration and cross-session
choice, declaration acceptance, and restoration of an existing application without allowing
pending answers to overwrite it. Applicant and committee sign-in default to shared-device-safe
non-persistent browser credentials with an explicit remembered-device opt-in. Private
working copies are excluded from every committee and AI query. Publication validates the complete
form and declaration, records an immutable dated application version, and atomically updates the
applicant's explicit participation in one or more openings. Opening selection, date-derived
lifecycle enforcement, submission-date household age checks, and committee opening
visibility/filtering and the optional household photo link are implemented. Submitted applications
appear without a committee sync action; Screen and Rank currentness derives from the stored pool.
The committed synthetic fixture now mirrors the canonical intake schema, and a fail-closed,
email-free local loader can migrate it into one or more published openings. The first-party intake
path is deployed and verified at the applicant hostname.

**Delivery stages:**

1. **Canonical intake model (complete)** — make application fields independent of spreadsheet headings;
   introduce one durable application with private working and committee-facing submitted copies,
   opening participation, and dated application versions. Preserve the existing content hash as the
   boundary for stale AI results.
2. **Transactional email and sessions (complete)** — add the provider-neutral sender with SocketLabs, domain
   authentication, passwordless email access, collision-safe account
   claiming, revocable server-side sessions, allowlist authorization, and delivery observability.
   Refactor Google committee sign-in to issue the same server-side session rather than retaining a
   parallel signed-cookie session.
3. **Applicant form (complete)** — build the field-reference sections, in-page guest draft, explicit
   Save and return later, validation/review/Submit flow, calculated household income, optional
   household photo link, persistent unsubmitted-change warning, and accessible responsive behavior.
4. **Publication and opening behavior (complete)** — configure and publish dated openings;
   atomically publish initial and updated working copies; keep drafts invisible; record dated
   application versions and explicit multi-opening participation; and enforce open, closed, and
   archived behavior from the opening decision.
5. **Committee intake workflow (complete)** — remove the Sync step; refresh submitted applications
   automatically; keep the list compact; show submission/version metadata in coherent application
   details; and derive stale Screen/Rank state from the submitted pool without routine committee
   email.
6. **Retention and opening closeout (complete)** — add explicit per-opening
   selected/unsuccessful outcomes,
   permanent selected-applicant confirmation after close, immediate eligible unsuccessful email,
   decision-anchored retention for submitted applications, close-anchored expiry for never-submitted
   drafts, complete application purge, credential-safe lifecycle email delivery,
   and once-per-Pacific-day automatic maintenance.
7. **Between-cycle cutover (complete)** — configure and verify the applicant hostname, exercise
   SocketLabs in production with controlled data, and retain existing production records as
   specified below.
   Application import, Picker, Drive credentials/tokens, and Google data scopes have already been
   removed from the codebase. Retain only identity-scoped Google committee sign-in and its OAuth
   client configuration.

The applicant hostname is `applications.pentacoop.com`. Existing production application records
and committee history are retained at cutover rather than reset. They are not sent unsolicited
access messages; a returning applicant may claim the existing record only by verifying its
recorded primary email. Records with a missing, duplicated, or inaccessible address require
administrator-mediated recovery and are never guessed or automatically combined.

While a retained pre-cutover application is editable, its Google Form answers are mapped into the
current working form. Every fact that maps exactly is prefilled; facts the old form did not collect,
including birth dates and explicit employment status, remain blank so ordinary validation requires
them before submission. The read does not mutate the submitted application. The first explicit Save
persists a native working copy, and Submit remains the only action that replaces the committee-facing
copy. The form does not offer restoration from the legacy submitted document.

The retained pre-cutover applications participate in historical opening 1: a 3-bedroom opening
that ran from July 6 through July 31, 2026, with a $1,226 monthly housing charge and November 1,
2026 move-in date. The opening is closed, all 232 submitted non-withdrawn applications retain their
original submission timestamps, and no vacancy notice was queued by the migration. An administrator
may record the selected household or no-household decision; the dashboard requires that decision at
move-in. Recording its outcome archives it immediately and releases eligible unsuccessful notices.

**Non-goals:** a general-purpose form builder; separate co-applicant access; simultaneous Google
Form/Sheet and built-in intake; multiple applications per primary applicant; committee-visible
drafts; automatic AI screening on submission; inbound email handling; or shared-database
multi-tenancy. M21 should leave clean tenant boundaries possible, but onboarding other co-ops is a
separate milestone with its own storage, hostname, and isolation decisions.

**Definition of done:**

- A guest can complete and submit the entire form without signing in. Durable progress before
  submission requires Save and return later; a successful submission publishes immediately and
  emails secure access for future edits.
- Save and return later preserves a private server-side draft and restores it from a fresh email
  link on another browser; committee members cannot read it.
- Applicant and committee links are single-use for seven days. Repeated requests leave earlier
  unused links valid until any sibling succeeds; recognizable stale links can request a replacement,
  and a different active applicant session always presents both emails and requires an explicit
  keep/switch choice before the valid credential is consumed.
- An unauthenticated submission using an existing email cannot reveal, replace, hide, or publish
  over that person's application.
- A submitted edit leaves the previous committee copy visible until the applicant explicitly
  republishes, then invalidates derived screening/ranking currency by content hash.
- One application can participate in later and simultaneous openings, the committee can filter by
  those selections, and the latest submitted application remains the normal committee view.
- Committee members sign in through an allowlisted magic link or identity-only Google OIDC; both
  issue the same server-side session and support the same revocation, expiry, and remembered-device
  choice. Role/access changes revoke those sessions server-side.
- The optional household photo link is private until submission, is available to the committee
  afterward, and is excluded from AI prompts.
- An administrator may permanently confirm the selected applicant after an opening closes.
  Confirmation archives the opening and sends only to applicants for whom every entered opening has
  a decision and none selected them. An opening that reaches move-in without a decision produces an
  administrator action banner rather than guessing an outcome.
- Unsuccessful and withdrawn applications are completely purged one year after their retention
  anchor. Selected-member applications use the seven-year period. Purge notices and unsuccessful
  notices invite the recipient to join the vacancy notification list without subscribing them.
- SocketLabs send failure, retry, rate-limit, and quota-blocked paths are observable without logging
  tokens, email bodies, or applicant content. SocketLabs owns bounce, complaint, suppression, and
  account-level reporting.
- Automated tests and normal local development capture email without sending it. Explicit live
  development tests send only synthetic messages to exact `@jeffo.net` or `@pentacoop.com`
  recipients, enforced before the provider call with no per-message bypass.
- At the M21 release gate, the production application accepted built-in submissions at the
  applicant hostname, the screener reflected new/updated submissions, and Google runtime use was
  limited to committee identity. M23 deliberately extends identity-only Google use to applicants.
- The committed canonical synthetic fixture can be loaded into every selected local opening, sends
  no email, and cannot overwrite an application that is not explicitly stamped synthetic.
- Backend tests, frontend build, database migration against a production-shaped copy, synthetic
  browser submission/edit/collision checks, email delivery checks, and permission/retention checks
  pass before the cycle opens.

**Production backup decision:** Fly takes daily volume snapshots and retains them for 30 days.
That bounded window is the production recovery policy. A separate deletion-preserving Fly-volume
restore procedure is deliberately excluded: restore-only reconciliation state and ordering rules
would add failure modes to a rarely exercised disaster path without proportionate benefit.
Applicant deletion, deletion-ledger-aware local restores, the opportunistic retention sweep, and
administrator delivery-status banners are implemented.

### Built-In Vacancy Notifications (M22) — complete

**Goal:** operate the minimal one-notice subscription described in
[Built-In Vacancy Notification List](../../SPEC.md#built-in-vacancy-notification-list).

**Implementation and cutover stages:**

1. Add the public email-and-unit-size form, rate limiting, non-enumerating duplicate handling, and
   the minimal consent/subscription record.
2. Add an administrator report with the active total, overlapping counts for 1-, 2-, and 3-bedroom
   preferences, and a monthly active-subscription bar chart that emulates the current spreadsheet.
   Add exact-email lookup for narrow add, replace, and delete operations, plus a preview of the
   exact audience for an opening without exposing addresses in routine reports.
3. Make application-intake opening creation the application-open event. The creation flow previews the matching
   audience count, exact message variants, current SocketLabs usage and allowance, and projected
   post-send usage. It then requires the administrator to confirm both opening the applications and
   launching the vacancy notifications. A successful create transaction persists
   the opening and durably queues the matching notices before reporting success, even when provider
   quota prevents immediate delivery. Send through a retry-safe outbox, consume each subscription
   after provider acceptance, and show delivery outcomes to administrators. There is no separate
   future-open state or opened-versus-notified lifecycle to reconcile.
4. **Production cutover (complete, August 29, 2026):** activate and verify the applicant hostname;
   create historical opening 1 and attach all 232 submitted, non-withdrawn applications without
   queueing email; freeze and validate the authoritative Google vacancy export; and import it
   without `--allow-upsert`. The resulting 1,478 active subscriptions reconciled exactly to
   1BR=894, 2BR=707, and 3BR=111, including every monthly chart bucket. The shared grandfathered
   SocketLabs server passed a controlled approved-domain template/link test before production
   delivery was enabled. The public website's built-in signup, preference replacement, and deletion
   returned the report to the imported baseline. The retired Google forms and response sheets stay
   frozen until opening 1 is finalized; Jeff will delete them after that November 2026 closeout.
   No migration email was sent.

**Non-goals:** applicant accounts; email-address verification; recurring newsletters; a wait-list
position or ordering; automatic application creation; multiple notices from one subscription;
a permanent application-managed suppression list; and retaining a subscription after its first
matching vacancy notice.

**Definition of done:**

- A visitor can request one notice for one or more unit sizes without creating an application or
  receiving a confirmation email.
- The public website remains usable while the application service is suspended. Subscription
  submission visibly waits and retries through an ordinary Fly recovery, never reports an
  unconfirmed success, and offers the Tech Support manual-entry path after bounded retries fail.
- A later submission for the same normalized email replaces, rather than merges with, the prior
  unit-size preferences and does not reveal that a prior record existed.
- Administrators can see the active total, overlapping unit-size counts, and monthly distribution
  without routinely exposing addresses, and can manage one exact address for a support or privacy
  request.
- Creating an application-intake opening opens applications immediately. Before confirmation, the administrator sees
  the matching audience count, exact message variants, and current and projected SocketLabs usage;
  after confirmation, the opening exists and every matching notice is durably queued as one
  operation.
- The first matching opening sends one notice and consumes the entire record regardless of how
  many sizes were selected. One delivery owns that consent generation across transient failures;
  its attempt lease survives lifecycle changes while the provider is sending. Competing list-only
  deliveries defer, while independently authorized application notices still send without claiming
  list completion. Acceptance consumes only the matching generation. Recorded acceptance prevents
  another notice; ambiguous provider acceptance after timeout cannot guarantee exactly-once delivery. The notice explains the removal and offers a link to subscribe again.
- Application withdrawal and vacancy-request deletion remain independent, and application activity
  never silently subscribes an address.
- Every vacancy-list message uses the common SocketLabs permanent-unsubscribe footer. SocketLabs
  owns unsubscribe, hard-bounce, complaint, and durable suppression for all email from the shared
  grandfathered server; unsubscribing also blocks later application-access messages.
- The production website uses the built-in form; vacancy subscriptions have no external form,
  spreadsheet, import, or synchronization dependency.

**Production gate (completed August 29, 2026):** the reviewed notice, privacy copy, email footer,
consent evidence, and application-withdrawal semantics were deployed together before production
signups moved to the built-in service.

### Applicant Google Sign-In (M23) — complete; production verified August 30, 2026

**Goal:** add the optional Google-first applicant access described in
[Applicant Google Sign-In](../../SPEC.md#applicant-google-sign-in) without creating applicant
accounts, weakening email ownership, or disturbing the guest and email-link paths.

**Implementation stages:**

1. **Shared Google button and access layout** — apply Google's current light outlined branding to
   one shared component while preserving the existing server-side OIDC transport. Use it first in
   both 620 px applicant and committee panels; keep the email field and link button side by side on
   desktop and stacked on mobile. Keep applicant guest controls independent of Google availability.
2. **Applicant identity binding** — add a nullable unique Google subject to the active application
   identity. Implement one resolver that checks subject, `email_verified`, and normalized email
   together, preserves the committee-style collision guards, claims pending drafts, creates a blank
   private application only while applications are open, and always issues the existing applicant
   `BrowserSession`.
3. **Applicant journeys and conflicts** — make Google the first entry action, email secondary, and
   guest tertiary; reuse saved-draft claiming and saved-versus-guest reconciliation; preserve an
   existing session when a different Google identity returns; and provide useful Google-denied,
   unavailable, closed-cycle, session-conflict, and Tech Support states.
4. **Credential lifecycle** — atomically clear the Google subject when a primary-email change is
   confirmed or an application is withdrawn; leave it intact while an email change is merely
   pending or cancelled. Revoke affected links and sessions through the existing identity lifecycle,
   keep the old-address security notice, and state the Google disconnection on the success screen.
5. **Production configuration and verification** — register the applicant origin and credential
   endpoint in the existing Google project, apply the additive migration to a production-shaped
   database, verify both hostnames and their separate cookies, and exercise controlled synthetic
   Google, email, guest, email-change, collision, withdrawal, and recovery journeys before release.

**Non-goals:** Google-only access; One Tap, automatic, or silent sign-in; Google profile prefill;
Google API authorization or data scopes; a general social-identity framework; separate applicant
accounts; co-applicant access; automatic record merging; changing an application email from a
Google claim; or restoring any Google Forms/Sheets intake dependency.

**Definition of done:**

- The applicant entry panel uses the shared Google-branded **Continue with Google** button first,
  a secondary email-link form second, and a tertiary guest button third; blocking or failing the
  Google path leaves the other two paths usable. The committee panel uses the same button and width.
- Any Google identity with `email_verified=true` and a normalized email matching an unlinked active
  application or draft attaches its stable `sub` and opens that same application. A new matching
  identity creates a private application only while new applications are open. Applicant and
  committee access deliberately use the same rule without separate domain or `hd` handling.
- A linked subject with a different returned email, an email linked to a different subject, and a
  subject/email pair resolving to different applications are all refused without mutation, merge,
  or disclosure.
- Google and email access for the same applicant issue indistinguishable applicant browser sessions
  keyed by `Application.id`, with the same expiry, remembered-device, sign-out, revocation,
  authorization, and no-store behavior.
- A browser already signed in to another applicant preserves that current session and requires the
  applicant to sign out before using a different Google identity. Google cancellation, denial, and
  provider failure never revoke the current session.
- Google is offered before a visitor enters the guest form, so no in-page guest answers cross the
  OAuth redirect. A matching server-side email draft is claimed without overwriting an existing
  application; the existing saved-versus-guest reconciliation remains authoritative for email-link
  access to a separately preserved guest copy.
- Confirming a primary-email change clears the old Google subject in the same transaction as the
  email update. Pending, failed, expired, replaced, and cancelled email changes do not clear it.
  Google can be linked again only when its verified email equals the newly confirmed address.
- Withdrawal and purge leave no usable applicant Google binding. A retained legal-hold record is
  neither accessible nor exposed as a Google collision.
- The backend validates the server-side OAuth state and authorization-code exchange and persists no
  Google access/refresh tokens, names, avatars, or profile data. Logs and denial responses contain
  no applicant PII beyond existing bounded operational handling.
- Committee Google and email sign-in retain their existing UI behavior, allowlist, account-linking,
  denial, session, and remembered-device behavior; M23 does not migrate that proven auth flow.
- Focused backend and frontend tests, the full backend suite, frontend build, additive migration,
  production-shaped upgrade, and synthetic browser verification all pass before release.

The applicant production and local callback URIs were added to the existing verified Google OAuth
client on August 30, 2026; saving them did not change the project's verified-brand or data-access
status. The production deploy applied the additive migration and returned Fly Machine version 71
with its service check passing. A real applicant Google callback authenticated successfully and,
for an email with no current application while applications were closed, showed the expected
closed-cycle refusal without creating a record. Committee Google sign-in remained healthy. The
existing-application branch was then verified against submitted synthetic production application
252: the matching Google identity linked successfully and opened the application.

### Opening-Specific Committee Workflow (M24) — ✅ complete

**Goal:** make one selected opening the complete context for committee review. Eligibility policy,
member decisions, the shared shortlist, Screen, and Rank all belong to that opening's applicant pool
rather than one global union. This is necessary because openings can have materially different income
and household-size requirements, and their pools can support different ranking dimensions: a
children-related axis that differentiates a 2-bedroom family pool may be meaningless in a 1-bedroom
no-children pool.

M24 is a product and data-model change, not merely a single-select control. The prior implementation
had one global committee default, one rules row per member, one override per member/application, one
application-global Shared shortlist, and one globally current Analysis. All opening-dependent state
now carries the same opening identity so the UI cannot show a ranking, status, or stale indicator
computed for a different pool.

**One opening context:** the committee opening selector becomes single-select and always identifies
the workspace shown below it. Prefer the earliest-move-in non-archived opening on first load; when no
current opening is available, select the most recently archived visible opening. Preserve the last
valid choice in browser navigation state. If that choice is no longer visible, fall back through the
same current-then-archived ordering; if no opening qualifies, show the empty Applications state.
There is no combined `All openings` Screen or Rank mode.
An application that entered several openings appears independently in each applicable workspace.

The three pool boundaries are deliberately different:

1. **Selector visibility:** show an opening only while at least one retained, non-withdrawn applicant
   who was not selected for any opening remains attached to it. A selected household never keeps an
   opening in the selector by itself.
2. **Committee-visible pool:** while the opening is visible, show its retained non-withdrawn
   participants plus the household selected for that opening. A household selected elsewhere is not
   returned to another opening's applicant universe merely because it once participated there. The
   selected household is read-only and carries its selected outcome, but remains viewable in the
   opening where it was selected.
3. **AI pool:** Screen and Rank include only the opening's retained, non-selected applicants. The
   selected household never affects coverage, eligibility union, discovery, scoring, rank order, or
   cost estimates.

An opening disappears automatically when its last retained non-selected applicant is purged, even
though the Opening row and a seven-year selected-member record may remain available through the
administrator audit. Opening rows themselves do not need a new purge policy.

**Opening-specific human state:**

- Each opening owns a full committee-default `EligibilityRules` document. A newly created
  application-intake opening copies the committee defaults from the most recently created prior
  application-intake opening as an independent snapshot; if none exists, it starts from schema
  defaults. Later edits to either opening do not propagate. The creation/admin flow identifies the
  source opening and makes the copied defaults immediately available for review and editing before
  the committee relies on Screen or Rank. Member overrides, eligibility decisions, shortlist state,
  analyses, rankings, and outcomes never carry forward.
- A member's diverged rules are keyed by `(opening, member)` and inherit only that opening's committee
  defaults.
- A manual eligibility override and its reviewed-findings fingerprint are keyed by
  `(opening, application, member)` because the same household may legitimately be eligible for one
  opening and ineligible for another.
- Shared shortlist membership is keyed by `(opening, application)`. The shortlist in opening A has no
  effect on opening B. Private favourites, private notes, and committee notes remain application-wide.
- Application list status, source, facets, details, and stale-override indicators are resolved in the
  selected opening context.

**Opening-specific AI state:**

- `Analysis` is keyed to one opening; “current analysis” means the newest analysis for that opening.
  Each member's `MemberRanking` remains a private child of that analysis.
- Screen scope, Rank scope, estimates, coverage, workflow state, rank-input fingerprints, currentness,
  score-current, audit endpoints, and run-cost attribution all take the selected opening explicitly.
  Lower layers receive the resolved application pool rather than calling a global pool helper.
- Application AI results remain content-addressed shared cache entries. Screening work can be reused
  across openings when application content, prompt identity, model, reasoning, and applicable rule
  inputs match. Dimension scores can be reused when the canonical dimension identity also matches.
- Dimension aliases and the canonical dimension history remain shared across openings. Discovery is
  still grounded only in the selected pool; matching may recover a genuinely equivalent prior axis,
  while a children dimension absent from a 1-bedroom pool is never injected merely because another
  opening once used it.

Separate pools provide isolation, not guaranteed zero cost. Selecting or viewing an existing current
ranking is free, and cache reuse may make overlapping work cheap. Each opening's first Rank still runs
pool-specific discovery, decomposition, matching, and consolidation, and different dimensions may
require fresh scores. Estimates must show that opening's actual expected cost rather than imply that
another opening already paid for it.

**Archived openings:** archived openings remain selectable while the selector-visibility rule holds.
Their retained applications, member rules, overrides, favourites, notes, Shared shortlist, screening
findings, ranking, tiers, and audits remain available in the same opening context. Archival means the
opening has a permanent selected-household or no-household decision, so existing Screen and Rank
results remain visible but paid run actions are disabled; rerunning AI after final outcome is not a
committee workflow.

**Production migration:** preserve the current live behavior before changing keys.

1. Create opening-default rules for existing openings from the current saved committee default so
   eligibility does not change merely because M24 deploys. Openings created afterward use the
   prior-opening snapshot rule above, falling back to schema defaults only when no prior
   application-intake opening exists.
2. Copy each member's current rules into every existing opening context they can review, preserving
   whether the member follows the opening default or has diverged.
3. Expand each current member/application eligibility override into the retained non-selected opening
   participations where it presently applies. Preserve status, reviewed fingerprint, timestamps, and
   author.
4. Migrate the already-deployed application-global Shared shortlist without guessing. A preflight
   maps an entry automatically only when its application has exactly one retained non-selected
   opening context. Zero-context and multi-context entries fail the preflight and are resolved through
   an explicit private operator mapping; no entry is silently dropped or copied to every opening.
   Preserve its creator and timestamps in the opening-specific row. The expected current production
   case is unambiguous because there is one global opening and the shortlist has not been used; the
   preflight remains the authority rather than relying on that recollection.
5. Add nullable `opening_id` provenance to existing Analyses and cost ledgers. When exactly one
   application-intake Opening exists, it is the only possible owner: assign all existing Analyses,
   their MemberRanking children, and run-cost history to it unconditionally so the production
   committee's current ranking, tiers, and results do not change at deployment. When several
   openings exist, a global fingerprint does not prove opening ownership; preserve those analyses
   as unscoped audit history. The first opening-specific Rank creates that opening's active analysis.
   This preservation logic lives only in the migration; do not retain a runtime compatibility path or
   delete paid historical runs and eval evidence.
6. Produce a PII-safe before/after reconciliation: opening pool counts, per-member eligibility counts,
   override counts, shortlist counts, retained selected visibility, and unchanged application content
   hashes. Apply additive migrations in place; never reset the database.

**Implementation slices:**

1. Opening-scoped pool queries and the selector/view/AI boundary tests.
2. Single-select opening context threaded through dashboard, Applications, Ranking, settings, and URL
   navigation.
3. Opening committee defaults, per-member rules, and opening-specific overrides with production-safe
   backfill.
4. Opening-specific Shared shortlist migration and UI; application-wide favourites and private notes
   remain unchanged. Committee notes later add an explicitly shared application-wide stream.
5. Screen scope, coverage, estimates, currentness, and cost attribution by opening while retaining
   cross-opening cache reuse.
6. Analysis/MemberRanking currentness, Rank chain, score-current, audit routes, and print output by
   opening; retain old unscoped analyses as history only.
7. Archived-opening lifecycle: visible pools, selected-household inclusion, selector disappearance,
   final-outcome AI lock, and retained administrative fallback.
8. Production-shaped migration rehearsal, complete backend/frontend checks, and Chrome verification
   across multiple current and archived openings on desktop and mobile.

**Definition of done:** switching openings changes every opening-dependent surface together without
cross-pool leakage; changing rules or running Screen/Rank for opening A does not stale or replace
opening B; an application can have different effective statuses, overrides, and shortlist membership
between openings; selected applicants are excluded from AI but viewable in their selected opening
while another retained non-selected applicant keeps it visible; an opening with only its selected
applicant is absent from the selector; closed undecided openings may run AI, archived openings retain
readable results with run actions disabled; and all migrated production counts and
application hashes reconcile exactly. Real-model validation over materially different synthetic or
PII-safe pools must confirm that pool-specific discovery behaves as intended—for example, a
no-children 1-bedroom pool does not retain a children differentiator solely because a prior
2-bedroom analysis used one—and must report actual cache reuse and spend rather than assuming zero
marginal cost.

**Validation and production closeout (2026-09-01):** the prepared four-household synthetic
1BR/no-children pool completed Screen and the full Rank chain on Bedrock Haiku/Sonnet. Five discovery
branches proposed 8, 10, 10, 13, and 10 dimensions; decomposition and consolidation settled on 13.
The only dimension mentioning children checked the completeness and consistency of structured household
facts rather than treating children as a fit differentiator. Six dimensions matched canonical history.
The run cost $0.509249 against a $0.6536 estimate; a follow-up score-current pass reused 48 scores and
computed four, costing $0.016567 and avoiding an estimated $0.041136 of work. The original discovery
prompt remained unchanged.

The production migration assigned the sole existing opening to all two analyses, 11 member rankings,
and 46 cost runs without changing their counts or the configured Bedrock Haiku/Sonnet routes. It also
created the opening's default rules and left no unscoped member rules, member eligibility rows, analyses,
or cost runs. Both public services passed health checks after Fly Machine version 78 deployed, and the
backend's 665 tests, frontend production build, and lint checks were green. Provider isolation separately
showed Bedrock Terra stalling before response headers while the same discovery input completed on Luna and
Sonnet; the adapter now times out silent streams, retries timed-out per-applicant work once, and always
releases the run lease on failure.

**Non-goals:** a combined multi-opening ranking, merged committee ranking, cross-opening shortlist,
automatic transfer of an override or outcome between openings, reopening selected applicants,
rerunning AI after an archived outcome is final, a new retention policy for Opening rows, or making
private favourites and notes opening-specific.

### Reporting (M10 shipped) — ✅ closed, demand-driven from here

The report is the browser print of the ranked view. Three speculative refinements were considered and **deliberately not built** (Jeff, 2026-07-26): near-misses / filtered-out counts / filtered-out details in the print (today it's the ranked eligible pool only); report-specific applicant personal/contact-detail handling for MOMI reports; and an explicit recommendation + `why not selected` surface beyond the per-candidate rationale lines. Rationale: building report features nobody has asked for is speculative scope. The committee now has the app and an in-app **feedback mechanism** — real requests, not guesses, will drive any future reporting work.

### Multi-Member V2 (M15) — ✅ complete

M15 shipped: per-member independent screening on a shared compute-once substrate — no merge/disagreement/comparison surface (the earlier open questions on merge formula, disagreement flags, and criteria-comparison layout were dissolved, not answered). The current-state design is in "Multi-Member MOMI Workflow" above; the decision record is [ADR 0011](../adr/0011-per-member-eligible-pool-shared-content-cache.md); the full sliced build history (access allowlist + `require_admin`; the `RankingRun` → shared `Analysis` + per-member `MemberRanking`/`MemberEligibility` split; per-member eligibility rules over a committee default; pets-as-deterministic-facts; committee-editable defaults + member reset; the two-phase-mental-model restoration; committee-union re-rank; and the observability triggered-by stamp) is in [CHANGELOG.md](../../CHANGELOG.md) M15.

Two things were intentionally **not** built: per-*requester* proposal attribution (no deterministic proposal→axis-key link exists to attribute on — the shared "Requested" badge stands; see ADR 0011), and a committee-default-version "your default changed" nudge (the live divergence diff already shows current default values). Per-screening-check descriptions ship as info-icon tooltips (`CheckInfo` in `CheckToggles.tsx`, on both `My rules` and the admin-only `Committee default` subtab in Eligibility Settings).

**How M15 resolved the single-tenant assumptions** (the load-bearing global singletons, now discharged):

1. **"Current run" was global-latest-wins** — the old `get_current_run` was `SELECT … ORDER BY id DESC LIMIT 1`, so one member's Rank silently became everyone's. **Resolved:** split into an opening-scoped `Analysis` (the AI output, one current per opening via `get_current_analysis(db, opening_id)`) + per-member `MemberRanking` (the view).
2. **Settings was one global row** — `AdminSetting` keyed `"app_settings"`, last-write-wins. **Resolved:** eligibility rules became per-member (shared committee default + copy-on-write `member_rules`); infra config stays one shared row (last-write-wins is acceptable for ~5 trusted members — a concurrency guard is an M16 concern).
3. **The spending cap is per-request, read-then-act** — `enforce_cap` checks each run's own projection, not a shared budget. **M15 kept the per-run cap**; a true atomic shared-budget ceiling is M16 concurrency work (below). At ~5 members the caching (only first-time-eligible applicants cost anything) is the practical cost control.

### Concurrency & Correctness (M16) — software, not infra

Multi-member introduces real concurrent writes. This is a **software** concern (guards, leases, atomic accounting) that stands on its own regardless of where the DB lives — distinct from hosting (M17), which is infra. A multi-member concurrency audit (2026-07-24) classified the hazards; the load-bearing hardening is **done**, and the residual items are deliberately deferred (rationale below).

**Done (2026-07-24 → 25):**
- **Reads are safe by the shared-union design** — the screening/scoring cache is content-addressed with no member id, so after one member runs Screen/Rank every other member sees the result (their amber turns green) with no action and no re-bill; Screen blocks a true no-op (`unchanged_pool`); matching cached results are adopted automatically in the background at zero provider cost. Full Rank remains available for another discovery attempt. This is ADR 0011 working as intended, not luck.
- **SQLite `WAL` + `busy_timeout=5000`** (`app/db/session.py`) — readers no longer block the writer, and a colliding writer WAITS (up to 5s, retrying) instead of failing instantly with "database is locked". Runs commit per item (short locks), so this covers real overlap. Purely defensive; no behavior change.
- **A single run lease serializes the expensive runs** (`RunLock` + `services/run_lock`) — Screen / full Rank / score-current claim one DB-backed lease (atomic conditional UPDATE, 15-min TTL steal so a crashed run self-heals) and 409 (`run_in_progress`) if another holds it. `held_since` identifies the acquisition; `renewed_at` advances once per minute during provider waits and inside each guarded result commit. `services/run_stream` owns renewal in a separate session, verifies ownership in the same transaction before every commit, and rolls back pending work on failure or disconnect. An expired or replaced run stops with a stream error and cannot commit over its successor or release that successor's lease. Tier edits remain blocked throughout a live full Rank. DB-backed ownership survives multiple web workers under M17. The frontend surfaces the 409 detail as a toast.
- **Tier/seed edits are blocked during an in-flight rank** — a full rank snapshots the committee kept-list once at the start of discovery then supersedes the analysis, so an edit made after that snapshot (e.g. dragging an axis out of Ignore) could neither reach the run nor survive it, silently vanishing. `_require_viewed_analysis` rejects the save (`run_in_progress`, holder-agnostic so it covers the initiator's own run) rather than let the edit persist onto a doomed board.
- **Stale-view detection landed** — the deferred M15 1b "this ranking was refreshed by another member" UX now exists as a global toast with a Reload action, raised both on a `409 stale_analysis` save AND on tab focus/visibility (a cheap current-analysis-id check; no standing poll). Suppressed during the member's own run to avoid a self-inflicted false positive.

**Explicitly out of scope (Jeff, 2026-07-29):**

1. **Committee-wide spending budget** — the run lease already prevents concurrent runs, and the per-run cap plus cache reuse is sufficient for this app. A period-based shared budget would add product policy and UI that the committee does not need.
2. **Optimistic concurrency for AI settings** — two trusted admins simultaneously changing re-typeable AI settings remains last-write-wins.

### Hosting / Go-Live (M17) — infra — ✅ complete

The committee saw a demo and wanted it, so hosting was real scheduled work — pure **infra**, sequenced after the M16 concurrency software landed. The app is now **live at [screener.pentacoop.com](https://screener.pentacoop.com)** for the real ~5-member committee. The platform decision and its full verified tradeoff analysis (9 platforms priced and timeout-checked, 2026-07-25) live in [ADR 0012](../adr/0012-hosting-platform-m17.md); the operational runbook is [docs/deploy.md](../deploy.md).

**Decided (2026-07-25):**

- **Platform: Fly.io**, auto-stop Machines (`suspend`, sub-second resume) + a persistent volume — cheapest option (~$1–5/mo, near-zero idle) that keeps the DB on a durable disk. Production deploys are an explicit operator action with `fly deploy --remote-only`; pushing `main` does not release. Custom domains use A/AAAA records + free auto-TLS.
- **Storage: keep SQLite on the volume for launch** (Jeff) — zero data-layer change; fine for ~5 users. Managed Postgres (and M16's atomic-budget store) is a *later* move, only if that feature is built. This retires the earlier "M17 may re-touch the data layer for a hosted DB" tradeoff: at this scale we deliberately do not.

**Shipped (all verified against the deployed app, 2026-07-26):**

1. **Single-origin** — FastAPI serves the built Vite bundle via `StaticFiles` (`app/main.py`), so one origin, no CORS in prod (the frontend calls the API with relative URLs); a two-stage Dockerfile builds the bundle.
2. **Prod-hardened auth/session** — `https_only` cookie (derived from `frontend_url` scheme), real `SESSION_SECRET` + Google client + AWS keys as Fly secrets (never in the image), prod `FRONTEND_URL` / `GOOGLE_REDIRECT_URI` in `fly.toml`. Bedrock uses a static IAM key scoped to `bedrock:InvokeModel` in us-east-1 and its permitted cross-region destinations (no IAM role off-AWS).
3. **Stream heartbeat** — `HEARTBEAT_SECONDS = 15` in `app/api/ranking/run.py` emits a keepalive during the silent Sonnet passes, a 4× margin under Fly's 60s idle timeout on the multi-minute Rank stream.
4. **Auth/roles** — `require_admin` gate + email allowlist (from M15 1a), now exercised under real hosted use across the admin surfaces (settings, allowlist, feedback).
5. **Data protection at rest** — production uses scheduled Fly volume snapshots plus an on-demand off-box `VACUUM INTO` copy (see deploy.md); local durability comes from the machine's daily backup system. The reusable local backup service supports explicit recovery workflows.

### Scale-to-Zero Recovery (M19) — ✅ complete 2026-07-29

**Goal:** return the single production Machine to Fly suspend-to-zero while bounding recovery from a resumed Machine that is running but failing its service health check. Normal suspend/resume remains sub-second; the 5–7-second clean startup applies to a stopped Machine, not a suspended one.

**Why:** on 2026-07-29, Fly resumed the single Machine but it did not become reachable. Fly correctly marked its `/health` check unhealthy and stopped routing requests, but does not restart a Machine merely because a service check fails. The immediate mitigation is one warm Machine; M19 replaces that recurring compute cost with targeted recovery while keeping the fast normal resume path.

**Design:**

1. Production uses `auto_stop_machines = "suspend"` and `min_machines_running = 0`; the watchdog is deployed and verified before treating this configuration as recovered reliability.
2. Keep Fly's `/health` service check at its existing 30-second interval. Run a small Cloudflare Worker backed by one Durable Object/Agent, using its persisted 30-second interval scheduler. It calls Fly's Machines API for this app's current `app` Machine and its service-check state; it must not make an HTTP request to the application, which would wake a suspended Machine.
3. Check host availability first: two `unreachable` or `unknown` host observations raise an operator alert regardless of the Machine's last state, normally 30 seconds apart. An explicit `ok` host observation clears pending failure confirmation; failed lookups and missing host status preserve it because they provide no recovery evidence. Pausing clears pending failure confirmation. Identify unavailable app Machines using Fly's `incomplete_config` metadata; missing or multiple app Machines raise an immediate alert. On reachable hosts, ignore Machines in `suspended`, `stopped`, startup, or `warning` states. A `started` Machine with an explicitly `critical` service check is restarted on the watchdog's first observation. Every restart attempt produces an immediate alert distinguishing acceptance, rejection, and an unknown outcome; acceptance is not proof of recovery. The normal startup grace period keeps a brief clean start from being mistaken for a persistent failure. Host outages require Fly recovery or an explicitly approved database snapshot restore; the watchdog cannot restart an unavailable physical host.
4. Store a narrowly scoped Fly deploy token as the watchdog's secret. Bound each Fly API call with a short client deadline and retry a failed read-only Machine lookup once after a transport error or transient HTTP status. Alert after two consecutive polls exhaust those retries, not the first failed poll. A successful lookup silently clears an unannounced failure. Send one successfully delivered alert per continuous lookup outage, followed by one recovery message after two successful lookups; monitoring visibility does not establish website availability. Retry failed outage/recovery delivery on later polls. Pauses and non-transient errors reset lookup confirmation counts without forgetting delivered alerts. Authentication/configuration and other non-transient errors alert immediately, retaining a five-minute repeat cooldown that resets on successful lookup. Handled polling failures are logged without throwing so the persisted scheduler owns retries. Never repeat an ambiguously failed restart request inside the same poll. Derive the target from the app's Machine list rather than hard-coding a Machine ID, and never log tokens, application data, or full API responses.
5. Use Cloudflare's free Durable Object/Agent offering rather than a one-minute Cron Trigger. Its persisted 30-second scheduler performs about 172,800 lightweight checks per 30-day month; ensure the object hibernates between polls, and re-confirm provider limits and pricing when implementing.
6. Keep an explicit `WATCHDOG_ENABLED` Cloudflare secret, defaulting to enabled. Setting it to `false` clears the persisted 30-second alarm and prevents Fly API calls; setting it to `true` lets the one-minute bootstrap Cron restore the alarm.
7. Persist host-outage notification state: send one successfully delivered alert per continuous outage, grouping `unknown` and `unreachable`. After two consecutive observations of the same Machine on an explicitly `ok` host, send one recovery alert and re-arm outage notification. Recovery requires a suspended Machine or a running Machine with at least one service check and all checks passing; a suspended recovery message confirms host reachability without claiming the website was tested. Failed lookups, startup/warning/stopped observations, and watchdog pauses reset recovery confirmation. Retry failed notification delivery on later polls; suppress an unpaired recovery message if the outage alert was never delivered. Every Discord notification starts with `Fly watchdog:` and reports the observed event or restart outcome without routine operator instructions.

**Validation evidence:**

- Host notification sequences cover persistent outages, `unknown`/`unreachable` changes, object recreation, two-check recovery, brief recovery followed by another failure, failed lookups and pauses, replacement Machines, failed webhook delivery, and re-arming after recovery.
- Watchdog tests also cover silent isolated host/lookup failures, two-poll lookup confirmation and recovery, retry success within a poll, permanent lookup errors, failed notification delivery, and immediate accepted/rejected/unknown restart notifications.
- The watchdog decision table is covered by tests: suspended, starting, healthy, and `warning` Machines are ignored; a `critical` started Machine restarts once per cooldown window.
- A disposable Fly app with an isolated encrypted 1 GB volume was given an intentional failing service check while its Machine remained `started`. The watchdog restarted it; after restoring `/health`, it returned to `1/1` passing and a marker file remained on the volume. The disposable app, volume, token, and Cloudflare Worker were deleted afterward.
- Production normally resumes from suspend in under a second. On 2026-07-29, Fly cordoned the idle production Machine, reported the expected transient `warning`, and suspended it while the watchdog was enabled. The watchdog ignored the warning and did not restart or wake the Machine.

**Non-goals:** high availability across two Machines, replicated SQLite, an HTTP uptime probe that keeps the app awake, or hiding a cold start after an intentional full stop. Those are separate availability/cost decisions.

The production Machine currently suspends to zero. The watchdog bounds the rare bad-resume outage; it does not make a single Machine highly available.

### Least-Privilege Google Auth (M18) — ✅ complete

Committee Google sign-in is identity-only: `openid`, `email`, and `profile`. It requests no Google
data scope, stores no provider access or refresh token, and issues the same revocable server-side
session as email sign-in. Setup is in
[docs/google-cloud-oauth-setup.md](../google-cloud-oauth-setup.md).

### Validation Experiments On Real Bedrock — ✅ all closed

The mock suite proves plumbing, not judgment, so these judgment-dependent claims were owed on real data. **All are now resolved** (2026-07-26 audit); the earlier-concluded ones — K sensitivity, prompt-output trimming, the convergence experiment — are in CHANGELOG / `docs/case-studies/dimension-convergence.md`. Kept here as the closed record:

1. **Reconcile-era behavior is moot** (that subsystem was deleted; see ADR 0007). No action.
2. **Carry-forward cost win in the wild — ✅ validated (2026-07-25), with a caveat.** Across 17 real rank runs the recorded cache savings grow run-over-run as the pool stabilizes ($0 → ~$1.25/run), confirming per-dimension score reuse works in practice — the core claim. **Caveat found:** the re-rank cost *estimate* is NOT a guaranteed upper bound. It's a recency-weighted **average** of recent runs' actual scoring cost (`project_pass_cost_from_history`), so by construction it's exceeded roughly half the time (8/17 runs came in over, up to ~142%) — a full discovery re-mints dimensions whose fresh scoring can outrun the historical mean. All runs stayed well under the spending cap regardless. Deliberately kept as an *expected*-cost estimate (the honest number to show at the confirm card) rather than padded into a false ceiling; the true atomic budget guard is M16/M17. Docstrings + this item corrected to say "expected cost," not "upper bound."
3. **Pet-fact extraction accuracy (M15 1e) — ✅ validated on a real run (2026-07-24).** A real Bedrock screening run over the live pool confirmed extraction is reliable across the phrasings that matter: multi-pet ("Three dogs, two cats, and a parrot" → `{3, 2, ['parrot']}`), multiple exotics ("penguin and iguana" → both in `other_pets`), three negation flavors ("I don't have any pets" / "No pets" / "N/A - no animals" → all zeros), and rabbit → `other_pets`. Every spot-check matched the source text. 57 of 58 screened apps carry pet facts on their latest result; the one exception was rules-ineligible under the committee default, so the screening gate correctly skipped it — not a gap. The structural goldens hold against real output; no tuning needed. First real run also re-populated the screening cache under the new `screening_prompt_version()` (old results lacked `pets`).

### UI Consistency Walkthrough (✅ done 2026-07-25)

A systematic tab-by-tab, panel-by-panel walkthrough of the whole UI to find and fix cross-surface divergences — the kind that accrete when tabs/panels are built at different times. Prompted by the settings tabs shipping without the title heading every other tab (Observability/Evals) has (fixed 2026-07-24, but found by eye, not systematically). Closed: a fan-out audit checked every surface against the shared conventions (title heading present; sub-navigation style — the shared `.subtab` underline tabs; heading levels; empty/loading/error states; button placement + labels; `no-print` on interactive chrome; icon sizing) and produced a severity-graded catalog. The clear inconsistencies were fixed in one pass (audit commit `0bbd9a6`): Applications title heading, self-fetch panels' inline error states (a latent stuck-on-"Loading…" bug), `.back-button`→`.secondary-button`, topnav icon size, settings section headings `h3`→`h4`, `.eval-hint`/`.panel-hint` split, the "Saved" tick parity, and ellipsis standardization. The borderline findings were then walked with Jeff (`00bde48`): fixed the Applications empty-state flash-on-load, "Save settings"→"Save configuration", and print-hiding the toast stack; the rest (facet-filter classes, context-driven icon sizes) were accepted as intentional.

### Eval golden ergonomics — pipe-input sugar for any-of `fires` (✅ done 2026-07-24)

A screening golden's `fires` any-of group is stored as a nested list — `[["spam_essay", "minimal_essay"]]` = "at least one of these must fire" — but the eval *displays* it pipe-joined ("spam_essay | minimal_essay", see `fire_label`). That display↔input mismatch was a real footgun: hand-editing a golden, it's natural to type the pipe form back into the data, which is a bare string the grader can't iterate — and it killed the Evals page render once. Closed: `_normalize_fires` in `load_cases` (`app/evals/screening.py`) accepts a pipe-delimited string as sugar for an any-of group (`"a|b|c"` → `["a","b","c"]`, whitespace trimmed), and also tolerates the whole `fires` value being a bare string (the exact mistake) by wrapping it. Plain must-fire strings and existing nested lists pass through unchanged. Documented in `docs/eval-case-schema.md`; tested (`test_normalize_fires_accepts_pipe_input_sugar`).

## Local database overhead measurements

Local synthetic measurements (2026-10-04, auth/network/provider time excluded): screening
preparation for 100 applicants fell from 15 to 9 SELECTs (ten-sample median 9.65 to 5.32 ms).
Persisting 20 candidates with 15 dimensions on SQLite WAL/FULL fell from 300 to 20 commits
(three-sample median 415.56 to 194.53 ms). These isolate local overhead, not production latency.

Local synthetic measurement (2026-10-03, SQLite WAL/FULL, 15 repetitions, median):
100 applicants × 15 dimensions with 30,000 historical rows read in 5.7 ms versus
37.1 ms with newest-row selection. Switching 1,500 references and committing took
8.0 ms; unchanged references took 3.0 ms. A fresh result's existing commit grew from
0.72 to 1.05 ms. These isolate database overhead and are not production latency promises.
