# Penta Application Screener Specification

This is the **current-state** spec — how the app works today and what is still open. Resolved
milestone history lives in [CHANGELOG.md](CHANGELOG.md) and the
[completed milestone archive](docs/archive/spec-milestones.md); significant architectural decisions
(and the reasoning behind reversed ones) live in [docs/adr/](docs/adr/); the blow-by-blow of
the big experiments lives in `docs/case-studies/`.

## Purpose

The Penta Application Screener collects housing co-op applications, applies deterministic hard filters, uses AI-assisted review for essay answers, and produces a committee-ready report for MOMI (Move In Move Out).

The project is also a deliberate learning and portfolio project for Jeff to build practical expertise in AI product management, agentic workflows, evals, cost-aware model use, human-in-the-loop product design, and AI-assisted software delivery. The code may eventually be made public as part of Jeff's AI product management portfolio, so the implementation should be understandable, well-documented, and credible as a real product artifact while preserving applicant privacy.

Anonymous draft saves, submission checks, submissions and access-email requests share a
source-address quota of 30 requests per 15 minutes. It uses the same validated Fly ingress-address
policy as vacancy signup and retains only transient in-process counters. Recipient coalescing
still applies; authenticated revision saves are unaffected.

The application API serves the browser surfaces and our manual tests. It is not an external
integration API. Endpoints and contracts can evolve with their browser callers and tests;
unused alternatives do not need to remain available for hypothetical external clients.

## Primary User

The primary users are Penta applicants and the approximately five MOMI committee members.
Jeff administers and develops the system. MOMI needs a clear shortlist of applicants recommended
for the interview stage, with justification.

## Application Form

The built-in application form begins with opening selection and a point-of-collection privacy notice.
The notice identifies the purposes for collection, people and service-provider categories that may
receive information where necessary, opening-based retention periods, and the Privacy Officer. The
form then collects household details, current housing, essay answers, employment, and income before
showing a review summary and declaration. The summary intentionally focuses on fields most likely
to contain mistakes: opening choices, household names and primary email, child count, optional
photo link, current housing, employment and total household income. It is not a complete copy of
every answer; omitted answers, including essays, remain part of the submission.

The external form is retired and will not receive new submissions. Applications collected
through it remain supported stored records: their answers must stay readable for committee
review, eligibility, ranking, applicant working copies, retention, and recovery. Retaining
these data readers does not require retaining an external-form ingestion integration or
reopening that intake path.

The applicant/co-applicant section asks for applicant name, date of birth, phone, and email;
co-applicant name, date of birth, relationship, phone, and email; and the children who will live in
the unit. Ages are calculated from those birth dates as of the application's last submitted edit.

Opening cards state the applicable household-size requirements:

- 1 bedroom: 1 or 2 adults
- 2 bedroom: 1 or 2 adults plus 1 or more children under 18
- 3 bedroom: 1 or 2 adults plus 2 or more children under 18

The children section collects first name, last name, and age for up to 4 children, ordered from oldest to fourth oldest.

The housing section asks for the current address and move-in date, then collects earlier addresses
and their move-in dates until the history reaches two years before the earliest application close
date shown on the form. Archived participation remains immutable but adds no hidden address-history
requirement. It also asks whether the applicant owns real estate and collects current
and previous landlord contacts. The form explains that landlord reference checks are required
before membership acceptance and will be performed only if selected for interview.

The essay section tells applicants that members must share responsibility for operating and maintaining the co-op, attend the AGM and special general meetings, serve on one or more committees, and attend committee meetings. It says willingness to participate is a decisive selection factor and encourages detailed answers.

Essay questions are:

- Who is in your household, and what would you like us to know about you?
- What skills could your household contribute to Penta?
- What previous co-op experience does your household have?
- Why does your household want to live in a co-op?

Optional questions are:

- Is there anything else you would like us to know?
- Link to a photo of the applicant and household.
- What pets would live with your household?

Employment information asks for applicant and co-applicant job title, company name, start date, manager name, manager phone, and manager email. The form explains that employer reference checks are required before membership acceptance, will happen only if selected for interview, and self-employed applicants should enter their own contact information.

Household income asks for yearly before-tax gross income for applicant, co-applicant, and total household. Gross income includes employment and self-employment, investments including capital gains, social assistance/government benefits/pension, support payments, rental income, and RRSP income.

The declaration states that applicants understand:

- Minimum $1,000,000 personal property and liability insurance is mandatory.
- Share purchase is due at approval: $2,000 for 1 bedroom, $3,500 for 2 bedroom, or $4,000 for 3 bedroom.
- First month housing charge and monthly housing charge arrangements are made with the management company.
- References will be requested for shortlisted applicants.
- Accepted members agree to comply with the co-op Rules, Occupancy Agreement, and Policies.
- Information may be verified, including landlord, employment/income, and credit checks.
- Incomplete or false information is grounds for immediate termination of membership.

The final declaration checkbox text is: `I / We have read and agree to be bound by the conditions outlined above`.

Current application answers include applicant and co-applicant identity and contact fields,
household children, structured residence history, real-estate ownership, current and previous
housing references, four required essays, optional additional information, an optional household
photo link, pets, employment, and gross yearly income. The canonical contract is
`backend/app/schemas/applicant/answers.py`.

## Built-In Application Intake

The built-in application form is the sole intake path; there is no parallel external-form intake.
The field reference remains the baseline for the form.

### One application, working and submitted copies

Each primary applicant has exactly one application in the system. The application is durable
across openings: a later opening uses the same application information rather than creating a
second application for the same person.

An application has at most two copies of its answers:

- The **working copy** is the applicant's private in-progress content. This is either the
  initial application before its first submission or edits being prepared after submission.
  Committee members cannot see it.
- The **submitted copy** is the current committee-facing application. It does not change while
  the applicant edits the working copy.

The first Submit action publishes the working copy. A later Submit action atomically replaces
the committee-facing copy with the completed working copy; it does not create another
application. Until that action, the committee continues to see the prior submitted copy. The
app clearly and persistently warns an applicant when changes have not been submitted, including
before they leave the editing flow. Wording must distinguish **saved** changes from
**submitted** changes so an applicant cannot reasonably believe the committee has received an
edit that remains private.

Committee members never see an application that has not been submitted at least once. Screening,
AI analysis, eligibility, notes, and ranking consume only the submitted copy. Publishing changed
answers changes the application's content hash and makes any derived screening/ranking state
stale through the existing content-addressed mechanisms.

Each Submit action also records an immutable, dated application version for audit history. Versions
belong to the durable application rather than to an opening. Committee members normally see the
latest submitted copy, including when filtering applicants from an older opening; the version
history exists for audit rather than as a separate opening-specific view.

### Applicant access and draft persistence

Applicants can begin filling out the form as guests without authenticating. Guest answers remain
only in the open page until **Save and return later** writes the current answers to a private
server-side pending draft and emails an access link. The save accepts an incomplete application as
long as the primary email is valid. It does not enter a separate verification or polling state,
and the form remains usable after the save. The email heading is **Your application draft has been
saved**, explicitly says it has not been submitted to the membership committee, and uses
**Continue your application** for its return link. Submission is always a deliberate action after
reviewing the completed application.
The long form and review do not carry a separate private-draft warning. The final review leads with
**Review your answers, then submit your application**, presents the intentional summary described
above, and ends with the declaration and explicit submission action. Authentication through Google
or email does not publish an application.
For an authenticated applicant, the corresponding **Save and review** action first persists the
private working copy and opens the review only after that save succeeds. A signed-out **Review
application** action validates and previews the in-page answers without creating a server record or
sending email. **Submit application** publishes the application and queues its confirmation in
one transaction, then returns before provider delivery. The confirmation carries secure access
for future edits; initial submission does not wait for the applicant to follow that link.
An authenticated primary applicant may edit while at least one published opening is open or while
they participate in a closed opening that has no decision. Before the next open date, or after every
relevant opening has a decision, application content is read-only. An applicant-withdrawn legal-hold
record is not active and is not available through this flow.

An authenticated applicant can choose **Delete my profile** without contacting the Privacy
Officer. The profile wording distinguishes this whole-application action from withdrawing from
individual openings with the selected-opening checkboxes. The confirmation reads **Delete your
profile?** and **This will withdraw your application from every opening and remove your access.
You'll be signed out, and this cannot be undone.** Its actions are **Keep my profile** and **Delete
my profile**. Confirming immediately retracts every active participation,
excludes the application from all committee views and future consideration, discards unsubmitted
changes, revokes applicant sessions and unused links, and removes applicant access. The confirmation
does not restate the retention policy. Deleting a profile does not send an email.
A never-submitted draft is physically purged immediately. Submitted information that must be
retained becomes a read-only legal-hold record excluded from applicant and committee APIs until
its scheduled purge. Privacy access requests are handled through restricted operational access.
The record cannot be restored into active consideration.

Saves and submissions carry an optimistic working-copy revision: a stale tab is refused rather
than silently overwriting a newer save, and the applicant can deliberately reload the latest saved
copy. Saved private edits are corrected in the form or replaced by the next submission; there is no
separate action that restores the last submitted version.
Destructive actions initiated inside the application use styled, in-page confirmations. Browser-
native confirmation is reserved for leaving or reloading a page with unsaved answers, where the
browser controls the warning.

If the same verified address applies again while an older withdrawn record remains under legal hold,
the applicant starts a blank current application. The retained record is never returned,
pre-populated, or exposed as an email collision; it remains linked only as needed to enforce its
retention and purge date. There is still at most one current application for the address.

Applicants may use optional identity-only Google sign-in alongside passwordless email access;
both methods establish the same application session and neither creates a separate applicant
account. The durable identity remains the internal application ID. A secure email-access flow sends
a seven-day, single-use link to the primary applicant's email address; consuming it establishes an
HTTPS-only application session and removes the credential from the browser URL. Tokens are stored
only as hashes, expire, cannot be reused, and are protected by rate limits and non-enumerating
responses. Only the primary applicant receives access links and application updates; the
co-applicant does not have separate editing access. Google linking and collision behavior are
specified in [Applicant Google Sign-In](#applicant-google-sign-in).

Before showing the form, a signed-out visitor sees Google first, email second, and guest access
third. Google is the fastest path but remains optional. The single email action serves both new and
returning applicants without revealing which addresses the system knows. While applications are
open, a new address creates an email-only private draft and receives its first access link; a known
address receives access to its existing draft or application. During the closed phase, new guest
and new Google applications are unavailable, but an applicant already participating in a closed
opening may still sign in to edit or withdraw. A known applicant with nothing actionable receives
an email directing them to the public vacancy page instead of a credential. An unknown address
receives the same useful email outcome rather than silence. Every accepted application-access
request shows one non-enumerating **Check your email** confirmation in the browser; the email, not
the browser response, explains whether an application can be opened. Repeated recent requests rely
on the message already sent.
If no published opening is open or closed, the entry page disables both
sign-in and guest access and shows the applications-unavailable state.
An upcoming opening is visible to administrators for scheduling but remains hidden from applicants
until its application open date.

After each initial or updated submission, the product sends the primary applicant a confirmation
email with secure application access. There is no opt-in checkbox: the applicant may ignore or delete
the message, and can request a fresh access email later through the same flow.
The submitted screen and confirmation email thank the applicant and show a separate timeline for
each opening in that submission. Each timeline says that shortlisted applicants may be contacted
after the opening's close date and that the applicant will receive an email as soon as the committee
has completed every decision affecting their application. Both surfaces remind the applicant that
they can return to update the application or delete their profile themselves.

The access link proves control of the primary email before an existing application can be changed.
A first guest submission may be published before email control is proven, then its confirmation
provides secure access for future edits. Saving a private pending draft likewise does not require a
separate email-verification transaction. A save request gives the same response whether its email
is new or already known, so it does not reveal which people have applications.

After sign-in, the verified primary email is read-only in the application form. **Change email
address** sends a seven-day, single-use confirmation link to the proposed address and leaves the current
identity unchanged until that link is consumed. Confirmation atomically updates the application
identity and private working answers, sends the previous address a security notice naming the new
address and directing an unexpected change to Penta Tech Support, revokes other application
sessions and unused links, and establishes a session in the confirmation tab.
The session that initiated the change remains valid so its original tab can
refresh the identity when it next becomes visible; there is no polling dependency. If the proposed
address already belongs to another current application, neither application changes and they are
never merged. Repeated confirmation requests follow the common magic-link rule: they coexist until
one succeeds, which revokes its siblings. The applicant may cancel all unconfirmed changes.

An unauthenticated browser can never overwrite an existing working or submitted copy merely by
entering the same primary email. Before opening the guest review, the server preserves the guest
answers as a private pending copy, emails the address owner an access link, and requires
authentication instead. The submission endpoint repeats the identity check as a race-condition
safeguard. After sign-in, the applicant sees only fields that differ between the saved application
and the answers just entered, then chooses **Keep my saved application** or **Use the answers I just
entered**. This is a whole-copy choice, never a field-level merge. Its authoritative acknowledgement
replaces any unchosen remembered browser copy. If acknowledgement or recovery is uncertain, the
comparison remains blocked and retryable; newer browser storage from another tab is not cleared. The exact pending copy is bound
to the resulting browser session; a newer collision supersedes older unclaimed copies. Either
choice changes only the private working copy. The committee-facing submitted copy remains unchanged
until the applicant explicitly submits again. Requests are rate-limited and notification emails
are coalesced so this protection cannot become an email-bombing tool.

An emailed credential is not a permanent bearer link. Every applicant and committee magic link is
valid for seven days and single-use. Anonymous renewal of an access link must still prove the
current mailbox. Cancelled or completed email-change proposals cannot restart through renewal;
expired unused proposals may renew. A valid durable email retry retains its separate authority
after a failed provider attempt revokes that attempt's token. Repeated requests may leave several unused links valid so a
provider-delayed earlier email does not arrive broken; consuming any link revokes its unused siblings
for the same identity and purpose and creates a revocable server-side session. Applicants can sign
out the current browser and revoke all application
sessions; an administrator can also revoke them. If the email account itself is compromised,
recovery is administrator-mediated because another message to the same mailbox would not restore
identity assurance.

An administrator may initiate a fresh magic-link email to the application's already recorded
primary address, but cannot see or copy the credential. Administrators cannot edit applicant answers.

A dedicated **Save and return later** action deliberately moves a signed-out working copy from the
open page into private server-side draft storage and emails the primary applicant an access link.
This is the only way an unauthenticated, unsubmitted draft leaves the page. It lets an applicant
preserve unfinished work across browsers or devices without creating a password. Once signed in,
the same action saves directly to the authenticated private working copy and does not send an
unnecessary email. An unclaimed pending draft expires after its last applicable opening closes.

Access-link handling follows one explicit decision table:

| Link and browser state | Result |
| --- | --- |
| Valid link; no applicant session | Offer the remembered-device choice, then consume the link, open or create the application, and establish a session. |
| Valid link; same applicant session | Offer the remembered-device choice, then consume the link, refresh the session, and open the application. |
| Expired, used, or replaced link; same applicant session | Ignore the stale credential and open the already-authenticated application. |
| Expired, used, or replaced link; no applicant session | Explain that the application remains saved and offer to email a fresh seven-day link without asking for the address again. |
| Recognizable link; different applicant session | Before consuming anything or requesting another link, show who is signed in now and who received the link, then require a choice. A valid link offers **Stay signed in as [current email]** or **Sign in as [link email]**; a stale link offers the same stay-signed-in action or **Email a new link to [link email]**. |
| Invalid or abandoned-draft link | Do not reveal an address or establish a session; direct the visitor back to the application entry point. |

After a fresh-link request succeeds, the page shows the same **Check your email**
confirmation rather than attempting to load application data before authentication. A link to a
draft or application that is no longer editable cannot establish a new session; requesting a
replacement instead sends the application-access-unavailable email.

A selected application is a separate unavailable state. An email access request always returns the
same non-enumerating **Check your email** browser response used for known and unknown addresses. The
verified mailbox receives no credential; it receives a factual **Your Penta application is
complete** email explaining that the household is now a member and the finalized application can no
longer be changed online. No action is required, and Tech Support is the contact only if the message
appears mistaken. A verified Google identity receives the same member-and-finalized explanation in
the browser without a new session. Both states are included in the development preview galleries.

An applicant-session conflict is resolved before link validity changes behavior. Choosing the
current application leaves its session and browser-local draft untouched. Choosing the linked
application revokes only the current applicant-session credential, then consumes the valid link.
Browser-local drafts are scoped to their pending-draft or application identity so answers never
follow a session switch. Applicant and committee cookies remain independent.

### Committee authentication providers

Committee members may either request the same kind of passwordless email link or sign in with
Google. Both methods prove an allowlisted committee identity and then issue the same revocable
server-side browser session. Provider choice does not create a second user, cookie, session
policy, authorization path, or logout/revocation mechanism.

Google is an optional identity provider for applicants and committee members and an operational
alternative when transactional email is unavailable. It uses standard OpenID Connect with only
`openid`, `email`, and `profile`; verifies the returned identity and email; and associates Google's
stable subject identifier with the existing application or committee user. It does not request
offline access, force repeated consent, retain access or refresh tokens, or grant access to Drive,
Sheets, or any other Google data.

Committee access remains allowlist-gated with the existing admin/member roles regardless of the
authentication provider. Control of an email address or Google account does not grant access
unless its verified address is active on the allowlist. A Google outage leaves email sign-in
available, and an email-provider outage leaves Google sign-in available to applicants and committee
members who otherwise qualify for access.

When an administrator adds a new member or admin to the allowlist, the service creates or
reactivates the committee user and queues a role-specific invitation in the same transaction.
The response returns before provider delivery; the worker creates its private magic link when
sending. Changing an existing entry's role does not send another invitation. Access remains saved
if delivery fails; the Access panel confirms queueing and Email delivery shows its outcome.

Committee email credentials use the same seven-day lifetime as applicant links. Following a stale
link while its matching committee session remains active simply continues that session. If the
browser is signed in as a different committee member, the screener shows both email addresses
before doing anything: a valid link offers to keep the current member or explicitly switch, while
a stale link offers to keep the current member or email a fresh link to the linked member. A
switch revokes the browser's previous committee session before establishing the new one. Without
an active session, a recognizable stale link can email its allowlisted member a replacement
without asking them to re-enter the address; an invalid link reveals nothing.

### Browser sessions and shared devices

Opening an applicant access link offers **Keep me signed in on this device**, unchecked by default.
Applicant and committee Google entry instead say **Stay signed in on this device when using Google**
so the choice is visibly scoped to the adjacent Google action. An email-link choice appears
on the device that actually opens the link, immediately before the link is consumed. Without the
opt-in, the app issues a
non-persistent session cookie and does not retain applicant answers after the page closes. With it,
the cookie and authenticated applicant draft storage may survive browser restarts. Either kind of
server-side session expires after 7 days without activity or after 30 days in total, whichever
comes first. Ordinary activity may extend the idle deadline but never the absolute deadline. These
are explicit product settings, not framework defaults.
Session activity and idle-deadline writes are coalesced over five minutes, so ordinary
authenticated reads do not contend for SQLite's writer. The recorded idle deadline may trail
the latest activity by up to five minutes; revocation and both expiry limits are still checked
on every request. Conditional touches preserve a newer deadline or concurrent revocation.

Closing a window is not treated as a guaranteed security boundary because browsers may restore
session cookies and tabs. People using a shared device should leave the opt-in unchecked and
explicitly sign out when finished. Sign-out revokes the captured server session and clears browser-held applicant data.
Failed reads, logout and withdrawal do not delete credential cookies: a late response must not
erase a newer sign-in. A revoked HTTP-only token cannot authenticate and is replaced by the
next explicit sign-in.
Remembered draft writes and clearing share a browser Web Lock. Each tab binds writes to the
consent lifetime stored in the preference value; clearing or replacing that value invalidates
older queued saves. A tab receiving a storage reset stops browser persistence while keeping
its in-memory answers. The leaving warning stays active until the exact current draft has
been stored or saved to the server. Browser storage failures, or unavailable cross-tab locking,
keep answers in memory and do not claim that browser recovery is available.
Successful submission clears only the matching browser record captured before that request,
comparing it under the same lock. Another tab's newer answers or base revision remain stored.

Signing out revokes the current server-side session immediately. **Sign out all devices** revokes
every session for that identity. Administrators can revoke a committee member's sessions, and
deactivation, removal from the allowlist, a role change, or a primary-email change invalidates
affected sessions. Any otherwise valid session may perform the actions authorized for its identity
and role; the application does not impose an additional recent-sign-in check on sensitive actions.

Session cookies are host-only, `Secure`, `HttpOnly`, and `SameSite=Lax`; raw session credentials are
not stored in browser-readable storage. The server records only hashed session credentials plus
creation, last-activity, expiry, and revocation metadata, without IP addresses or device
fingerprints. Applicant API responses use `Cache-Control: no-store` so application content is not
retained in the browser's HTTP cache.

Applicant and committee access remain separate identities even when the same person and email
address have both. The applications hostname authenticates the retained application; the screener
hostname authenticates the allowlisted committee user. Becoming a committee member neither merges
nor changes the retention or access rules for that person's application.

### Transactional email

SocketLabs sends applicant access, save-and-return, submission, update, and
security-notification messages through its Injection API. The application calls it through a
small provider-neutral email-sender interface so authentication and intake behavior do not depend
on SocketLabs-specific response shapes. A provider change is an explicit implementation and
operational action, never an automatic retry after an ambiguous send result.

SocketLabs uses a dedicated Server ID and Injection API key stored as Fly secrets. The sending
domain is authenticated with DKIM, SPF, and DMARC. Messages use `Penta Co-operative Housing` as
the display name and `applications@pentacoop.com` as the sender. The common footer identifies Penta
at 1717 Wallace Street, Vancouver, BC V6R 4J7 and states that the sending address is not monitored.
Privacy contact information remains in the collection notice and Privacy Policy rather than every
transactional email.

Every message uses the same legal identity, address, and unsubscribe footer:
**Click here to permanently unsubscribe. Penta will no longer be able to email you, including
secure sign-in links.** SocketLabs replaces
its native unsubscribe tags in the HTML and plain-text bodies and adds a confirmed unsubscribe to
the server suppression list. Penta treats that suppression as permanent. Individual message
templates do not add footer variants. The notification sent to a previous address after an email
change is the deliberate body-copy exception: it directs an unexpected change to
`techsupport@pentacoop.com`, because the browser confirmation alone cannot alert the original
address owner to a compromised session.

Email is a load-bearing part of applicant access. A failed access-link or save-and-return send
leaves the private pending draft intact and directs the applicant to Penta Tech Support rather than
asking them to retry an unexpected failure. Confirmation failures are recorded for administrators.
Sending is rate-limited. Repeated credential requests retain older queued requests because either
email may arrive first at the mailbox. A provider-temporary failure leaves a semantic request in a
durable outbox for the next daily
maintenance pass. Post-write draining sends eligible first attempts and recovers expired attempt
leases; unrelated writes do not immediately retry prior provider/quota failures. The outbox never stores a rendered message, applicant answers, or a raw access
token: a credential email receives a fresh token immediately before each provider attempt, and an
unsuccessful attempt revokes that token. Operational records contain only the provider message ID,
message kind, recipient identifier, delivery state, and the minimum data needed to rebuild the
message.

SocketLabs remains the source of truth for bounces, complaints, suppression, and account-level
reporting; the application does not ingest provider webhooks or duplicate its suppression list.
Every injection carries a unique provider message ID and a stable message-kind MailingID for
diagnosis; neither changes delivery priority.
The current plan permits 2,000 messages per billing period, and this server also carries Penta mail
sent outside the application. The SocketLabs usage-summary API returns the server's billing-period
boundaries, messages used, message allowance, percentage used, and overage policy. Administrator
send previews show the audience immediately and load the current provider snapshot and projected
usage in a separate request. Usage is advisory: confirmation remains available while reporting
loads, and an unavailable summary is reported as unknown rather than replaced with a guess.
The provider reporting API is read on demand and cached for five minutes. Login screens first read
the last in-memory observation without waiting, then hold a separate refresh request open while
SocketLabs responds and update the notice only if the aggregate changes. Normal Fly suspend/resume
preserves that process cache; a cold start begins without one and fails open. Because the legacy plan
returns message-level records rather than a queue aggregate, Penta reads at most the current and two
previous Pacific dates, immediately projects them to pending count and oldest queued time, and never
stores or logs provider recipient, subject, or message content. A queue is considered delayed at 10
pending messages. If reporting is unavailable,
email remains enabled and no unsupported delay is claimed. Applicant and committee entry screens
use the same delay notice, say that the delay is temporary and may last up to 48 hours, and identify
Google as immediate.

Admin Email Delivery uses the same stale-while-revalidate pattern: local delivery issues and the
last provider observation render immediately, while a separate authenticated request refreshes only
the SocketLabs status block. Manual Refresh repeats both requests without blanking the existing view.

Locally queued mail and quota-blocked mail appear in the administrator action banner and retry on the
ordinary once-per-Pacific-day maintenance cadence. Unexpected terminal failures also appear in the
banner for seven days. The Email Delivery report lists current queued and failed messages with the
actual queued/failed recipient address, attempted time, email type, state, attempt count, and error
classification. The attempted address is cleared after acceptance or aggregate purge; missing
historical recipient evidence is unavailable rather than inferred from a mutable account address.
Expected cancellations, such as mail cancelled by withdrawal, do
not appear as failures. The report never stores or displays rendered message contents or
credentials. The application cannot email an alert through the same suspended account, so
SocketLabs' own account notifications remain the out-of-band warning.
Automated tests and normal local development use a captured fake sender and never deliver real
email.

SocketLabs' normal click-tracking configuration applies to email action links. The provider already
receives the complete message body to deliver it, while the application-facing credential remains
short-lived, single-use, and carried in a URL fragment that is not sent in application HTTP requests.
SocketLabs also generates the common provider-managed unsubscribe link so it can confirm the
request and place the address on the suppression list.

Developers may explicitly enable live SocketLabs delivery for end-to-end email testing. Every
development subject is prefixed with `[Penta development]`. The central email-sender boundary
normalizes and parses every sender, Reply-To, To, CC, and BCC mailbox and rejects the entire
message before calling SocketLabs unless every domain is exactly `jeffo.net` or `pentacoop.com`
(not a subdomain or a suffix match). There is no per-message bypass. Development uses only
synthetic applicant data and never copies production applicant or vacancy-list records into email
tests.

The committee login page offers email sign-in only when `EMAIL_DELIVERY_MODE` is explicitly
`development` or `production`. The default `capture` mode presents Google alone, so a partial or
accidental deployment cannot promise an email that will never be delivered.

Every applicant transactional message clearly says that it was sent because the recipient has or
requested access to a Penta application, not because they are on the vacancy-notification list. It
links to the authenticated **Delete my profile** flow and explains that deleting the profile stops ordinary
application messages, while a required security notice may still be sent.
The link opens a review/confirmation page and never changes state on its initial `GET`, so an email
security scanner cannot delete an application by following it.

Committee transactional messages instead explain that they were sent because the address has
active committee access and direct the recipient to a Penta administrator if that access should be
removed. They do not show an applicant-removal link.

### Form behavior

- The form preserves the field-reference questions and required/optional behavior. Applicant,
  co-applicant, and child ages are collected as dates of birth so the application can calculate age
  on the last submitted edit instead of becoming stale. Trusted committee detail shows birth dates
  alongside those calculated ages and retains access to the submitted source answers. Structured
  Screen and Rank inputs include submission-time ages for adults and children, with no birth dates.
  Screen retains household names for integrity checks; discovery/scoring structured facts omit
  adult and child names. Essay text remains unredacted and can contain identifying information.
  Existing submitted integer ages
  remain unchanged in their historical snapshots; they are never converted into invented birth
  dates. A returning applicant must provide the missing birth dates in the working copy before
  submitting for another opening.
- The introduction explains the current eligibility criteria, but the form has no eligibility
  hard stops. Every applicant may complete and submit it. Deterministic rules and human overrides
  remain part of committee screening, not intake gating.
- Applicant and co-applicant gross yearly income are entered separately. Household income is a
  read-only calculated value; the form adds the two inputs rather than asking the applicant to
  repeat the total.
- Each adult selects `Employed`, `Self-employed`, or `Not currently employed`. Employed adults
  provide employer and manager details; self-employed adults provide business details without an
  artificial manager reference; unemployed adults are not asked for inapplicable employer fields.
- Housing ownership uses two plain questions: whether the applicant owns the home where they
  currently live, and whether they own another home or land. Either answer supplies the broader
  real-estate ownership fact used by screening. Current-landlord fields are shown only to renters;
  previous-landlord fields are shown only to renters whose required residence history extends
  beyond their current home. Committee details keep each stored address structured but display it
  as one compact row, followed by its move-in date.
- The form accepts one optional web link to a household photo. Applicants are reminded to use a
  link the committee can open. The link follows the same private-working-copy and submitted-copy
  visibility rules as every other answer and never enters AI prompts.
- The introduction provides the collection purposes, disclosure categories, retention schedule,
  Privacy Officer contact, and privacy-policy link before any server save. The final
  **Declaration** presents the membership conditions and explicit verification and credit-check
  consent. Merely continuing or entering an email is not consent. The primary applicant must
  accept the declaration before every initial or updated Submit action. The server rejects a Submit
  action unless that acceptance accompanies it, and the immutable application version records the
  submission time.
- Every opening records its intake mode, move-in date, unit size, and monthly housing charge. An
  opening also records a planned application deadline. Its actual application open date remains
  unset until an administrator opens applications. The deadline is on or before move-in. A committee
  decision archives the opening; the calendar closes intake without deciding its outcome.
- The monthly housing charge starts blank for a new opening and is required before saving.
  Editing an existing opening shows its saved charge, including an explicitly saved zero.
- Opening and applicant dates share the native date control: keyboard entry and calendar selection,
  a four-digit year limit, and existing required/future-date restrictions.
- Creating an opening returns to its visible card without a redundant success message.
- Opening-management introductory and success copy describes creating and managing available homes.
  Retention protection is an edge case explained in the policy and relevant action confirmations.
- **Preparing** is the initial stage of a new opening. Creation records home details and a required
  planned application deadline, sends no email, and does not expose the opening to applicants.
  It captures currently retained submitted, non-withdrawn, non-selected applications for temporary
  retention protection. This administrative association is separate from applicant participation.
- **Open applications** explicitly publishes a Preparing opening, records that day's actual open
  date, and queues the confirmed current notification audience in the same transaction. The saved
  details and audience are revalidated. Repeating publication cannot queue duplicate announcements.
  An elapsed deadline must be extended before publication. Opening creation is independently
  retry-safe through its creation request identity and original facts.
- **Fill from previous applicants** finalizes an existing Preparing opening after the administrator
  confirms the household's interest outside the system. Name/email search finds available retained
  submitted applications with prior participation, excluding withdrawn and selected households.
  The selected participation and opening decision are committed atomically. No other applicant is
  enrolled or recorded unsuccessful, no notification-list request is consumed, and no mail is queued.
  The selected application is retained for seven years after the decision and its access is revoked.
- A Preparing opening can be cancelled by recording a permanent no-household decision without
  applicant participation or outcome email. Filling or cancelling releases that opening's protection.
- A direct-selection opening is archived immediately, never appears in applicant choices and has
  a permanent decision. Its planned deadline remains historical opening information.
- Application-close timing does not prevent an existing application's information from being
  reused for a later opening. Each opening has a separate participation record that says the
  applicant affirmatively wants their one application considered for that opening. Participation
  attaches the applicant, not a separate copy of their application, to the opening.
- An existing applicant enters a later opening by following their access flow, reviewing or
  updating the retained application, accepting the declaration again, and explicitly submitting
  it for that opening. An invitation or an existing application alone does not enroll them.
- Multiple openings may be active at the same time. The applicant form shows every relevant
  opening's three dates, unit size, and housing charge. Opening selection is a multi-select that is
  always visible: exactly one open offering is selected by default, while multiple open offerings
  start unselected and require at least one selection before submission. Committee views use one
  selected opening as the complete eligibility, screening, and ranking workspace.
- Before and through the application close date, an applicant may select or unselect an opening.
  After the close date and before the committee decision, an existing participant may unselect it to
  withdraw but nobody may newly select it. Because working selections remain private until Submit,
  the participant may reverse that pending choice in either direction before submitting. Once the
  committee records the opening decision, it is archived and its participation can neither be
  selected nor withdrawn. If another opening still permits editing, a later publication updates the retained
  application record without returning archived-only applicants to ordinary committee workflows.
- Before submission, the review page separately names every opening the applicant will remain
  enrolled in and every existing participation that the submission will withdraw.
- Archived openings are not offered in the applicant selector or review. They remain in the admin
  opening list and are selectable by the committee while at least one retained non-selected
  applicant remains attached. Their retained applications and existing Screen/Rank results stay
  available; paid AI actions are disabled after the opening has a final outcome.
- Applications enter an opening's ordinary committee and AI workflows only through retained,
  non-withdrawn participation in that opening. A selected household stays committee-visible in the
  opening where it was selected but is excluded from AI and never keeps an opening selectable by
  itself. Retention never enrolls someone in a later opening. Opening-withdrawn and
  application-withdrawn applications are excluded from ordinary committee and AI workflows.
- Administrators may edit archived opening facts to correct the historical record. Changing a
  move-in date does not change application retention.
- The server's Pacific calendar date determines which actions are allowed. Merely receiving an
  announcement, following its access link, editing, saving, or reviewing does not create
  participation. Submission creates or updates participation for the selected openings.
- Applicant, co-applicant, and child age checks use each person's age on the application version's
  last submitted edit date in Penta's Pacific time zone. Ages remain stable while the committee
  reviews that version and update only when the applicant submits an edit. Age eligibility is
  application-wide and has no dependency on selected openings or their move-in dates.

### Opening decision closeout

An administrator may select and confirm the successful applicant after an opening closes. The
committee decision archives the opening immediately; the move-in date remains the expected
occupancy date and makes an undecided opening overdue for administrator action.
Applicants cannot newly apply after the close date, regardless of whether the committee has
completed closeout. The candidate picker can filter the already-loaded candidates by name or email;
the filter does not make another request or change the candidate set. Confirming the selection
records the selected participation and records every other active participation in that opening as
unsuccessful. AI eligibility and ranking never imply that decision. Selecting an applicant excludes
that application from future Screen and Rank work and every successful-applicant picker, while the
Applications list and detail view retain persisted AI evidence, eligibility badges, and read-only
notes. Selected households cannot change eligibility overrides, favourites, or shortlist state.
Their ordinary detail keeps Back to list; retained admin review remains a distinct navigation mode. The detail view shows both the purple Selected state and the member's underlying
Eligible/Ineligible status; status filters continue to use that underlying eligibility. The opening
card shows the selected household as an ordinary read-only fact and links to the full retained
application. Only an undecided closed opening offers the action to record a decision; a finalized
opening has no second decision-management surface. Selection also locks the
applicant boundary immediately: the submitted record, working copy, opening choices, primary
email, and profile status cannot be changed online while any participation is selected. Confirming
either an application-intake or direct selection revokes every applicant browser session and unused
access or email-change link. A stale page may retain a device-local copy, but every server mutation
rejects it. A later opening never makes a selected application editable again. Unsuccessful
applications remain live in the ordinary committee workflow until their one-year purge date.

Every confirmed decision is permanent. It cannot be undone or replaced through the application,
because eligible outcome messages leave the system immediately and cannot be recalled. A household
that later declines is a new operational event rather than a reason to rewrite the archived decision.

An opening decision has three explicit states: **pending** (no decision yet), **selected** (one
household selected), or **no household selected** (the administrator deliberately closes the
opening without choosing a household). “No household selected” records every active participation
as unsuccessful and archives the opening. It is not inferred from a missing selected applicant, so
an overdue closed opening still demands administrator action.

The selection confirmation previews its permanent consequences. Confirming archives the opening and
immediately releases eligible unsuccessful notices. A notice is eligible only when every opening
that applicant actively entered has a confirmed decision and none selected that applicant. This
avoids sending an unsuccessful notice to someone
whose result in another simultaneous opening remains pending or who was selected elsewhere. The
confirmation commits its decision and due email intents together and returns the updated opening
list and queued count before provider delivery. The existing outbox sends the notices in the
background; Email delivery reports pending or failed messages independently. Retries remain safe,
and provider acceptance and participation notification markers are recorded together to prevent
duplicate sends. The message acknowledges the time and effort involved in applying, closes the loop without
implying fault, and invites the applicant to join the vacancy notification list for future openings.

The committee screener shows administrators an action banner when an opening reaches its move-in
date without a decision. The banner links to the relevant review flow and disappears after
confirmation. Whether a second
banner should require an administrator to review one-year purges is still an open decision.

### Committee intake awareness

Submitted applications appear directly in the committee list. The screener refreshes its
lightweight application and workflow reads on focus, on visibility return, and every 60 seconds
while visible. There is no import, acknowledgement, or manual synchronization action.

A newly submitted application or version makes **Screen** and **Rank** amber when their
content-addressed state no longer covers the submitted pool. The list stays compact;
submission and version timestamps belong on the application detail page. Routine
applicant updates do not email the committee.

### Primary email changes

The primary email is the applicant's contact and access address, not the application's permanent
database identity. An authenticated applicant may change it only after verifying the new address;
the prior address is notified. If the applicant cannot authenticate, an administrator must handle
recovery. Changing email does not create a second application or transfer one merely because an
unauthenticated form contains the same address.

Email identity prevents an unauthenticated collision on the same address; it does not attempt to
prove that similarly named people or households using different verified addresses are the same.
Those records remain separate applications. The service performs no automatic merge and provides
no administrator merge operation.

### Retained pre-cutover applications

While a retained pre-cutover application is editable, its Google Form answers are mapped into the
current working form. Every fact that maps exactly is prefilled; facts the old form did not collect,
including birth dates and explicit employment status, remain blank so ordinary validation requires
them before submission. The read does not mutate the submitted application. The first explicit Save
persists a native working copy, and Submit remains the only action that replaces the committee-facing
copy. The form does not offer restoration from the legacy submitted document.

### Intake data boundary

The built-in form writes canonical application fields directly; provider-specific headings do not
define the domain model. The submitted copy retains the exact answers needed by the committee and
AI passes, while normalized values remain the deterministic screening input. Household photo links
never enter AI prompts.

The implementation must preserve the current privacy boundary: drafts and submitted applicant
data are sensitive PII; they do not enter logs, source control, fixtures, or general operational
reports.

Drafts do not have a separate retention period. A never-submitted server draft remains available
only while at least one applicable opening accepts submissions and is deleted after the last such
opening closes. Private creation and selection changes update that deadline atomically, including
the available-opening fallback for an empty selection. Publishing another opening refreshes
still-current empty-selection copies; explicit choices remain tied to their chosen openings.
Ordinary opening edits do not reactivate either private record type after its Pacific expiry
date has arrived. Closing the last fallback opening leaves
a finite close-anchored deadline, never an indefinite one. Resolved, superseded, and revoked temporary copies are deleted once they no longer
serve the access flow. Private working changes on a submitted application do not extend retention
and are discarded once all relevant openings have decisions. Remembered-device draft
storage likewise has no independent 30-day timer and is removed by sign-out, clearing the device,
or an explicit application-withdrawal flow. Server retention cleanup cannot erase storage on a
browser that never returns; remembered-device storage is therefore an applicant-controlled device
copy rather than part of the server retention guarantee.

Clearing a guest copy physically removes its answers and credential/delivery references;
it detaches any pending-comparison reference without ending application authentication.
Explicit draft/profile deletion leaves the same non-identifying deletion fact as scheduled
purge. Discarding private working changes advances the working revision only when that
copy changes, so an earlier browser cannot continue treating discarded answers as saved.

Once an applicant affirmatively submits for one or more openings, the latest committee decision
affecting that application is its single retention anchor. Applications with no selected
participation are retained for one year after that decision; a withdrawal changes access and scope
but does not create or restart a retention clock. A selected application is retained for seven
years after its selected opening's decision. When an application spans simultaneous openings, its
one-year period begins after the last decision. Move-in dates do not change retention.

The public privacy policy explains these retention periods and the restricted legal-hold behavior;
the ordinary applicant interface does not restate that policy in the **Delete my profile** confirmation.

A Preparing or accepting opening temporarily protects the available submitted pool through its
application deadline, inclusive in Pacific time. The latest applicable deadline across protecting
openings applies. The original decision-based retention date is preserved. Shortening a deadline,
filling or cancelling the opening releases its protection immediately; a record already past its
ordinary expiry becomes unavailable and due for deletion unless another opening still protects it.
Extending, creating or publishing an opening captures only currently available records under the
SQLite writer lock and cannot revive expired data awaiting purge. Protection does not enroll an
applicant, create unsuccessful outcomes, or restart a year. Submitting for the opening establishes
normal participation and retention through the final decision, then one year if unsuccessful or
seven years if selected. Authentication, committee scope, notifications and purge use the same
protection-aware retention boundary. Migration preserves existing openings and captures currently
available applications for existing undecided openings whose deadlines have not elapsed.

The Pacific purge date is the first unavailable day. Reads, authentication, writes, direct
selection and email preparation enforce that boundary even before daily maintenance runs.
Maintenance purges expired data before processing email. A new submission for an expired
identity removes the expired record under the writer lock and starts a distinct application;
it never reactivates old answers or credentials.

There is no advance retention-expiry warning or separate purge confirmation. When retention ends,
the application is purged without preserving personal information solely to deliver another message.

Deletion covers the working and submitted answers, dated application versions,
application participation, AI outputs and caches, eligibility and
ranking data tied to the applicant, committee notes, sessions and unused login tokens, and
applicant-identifying delivery records. Production uses daily Fly volume snapshots retained for
30 days. A snapshot restore may reintroduce data deleted after that snapshot; the bounded backup
window is the accepted disaster-recovery tradeoff, and production does not maintain a separate
deletion-preserving restore ledger. The built-in local restore path does reapply its current
hard-purge ledger. Local restoration uses SQLite's backup API so leftover WAL pages cannot
override the selected snapshot, retains a pre-restore recovery point, and checks the reopened
database's integrity. Only a non-identifying audit fact that a record was deleted under a named
retention rule may remain in the live database. At the first contributing applicant purge,
whole pool-level AI narratives and applicant-specific justifications are erased, including inherited
copies. Generic criterion names/definitions/poles, retained applicants' own evidence and numeric
cost history remain. Captured source application IDs use the existing application identity;
`pool_text_purged` prevents a late consolidation reply from recreating an expired explanation.
Historical analyses with unknown sources use conservative opening scope; local restores apply
the same cleanup, including when only a deletion receipt and the pool text remain.

Integer record IDs use persistent, monotonic SQLite allocation. Existing IDs remain unchanged;
future allocation skips the legacy range and remains representable by browser numbers. Local
restore prepares a separate candidate database, upgrades its schema, reapplies the newest deletion
bounds and preserves live allocation high-water marks before replacing data through SQLite's
journal protocol. A later record generation is not deleted by an older fact; an ambiguous legacy
match stops the restore before live replacement. Integrity and foreign-key checks cover the result.
Local application snapshots must identify their Alembic revision. Preparation upgrades them
before using the normal aggregate-erasure mechanics; unversioned application schemas are rejected.
Restored browser sessions, one-time credentials, and credential-issuing email retries are invalidated.
Orphaned run/maintenance ownership is released; ordinary queued notifications remain subject to
the outbox's lifecycle checks. Fresh sign-in is required. This does not preserve every access-list,
consent, note, or business-data change across rollback, and does not change the Fly restore policy.

Retention is enforced automatically and opportunistically at most once per Pacific calendar day
when the deployed service receives ordinary browser or API traffic. Health checks, static assets,
and CORS preflight requests do not wake the sweep, and no external scheduler exists solely to wake
a suspended Fly Machine. A durable lease prevents concurrent requests from running the
same sweep. The ordered pass purges due applicant data, queues due unsuccessful notices, retries
queued email, and deletes expired list-only delivery failures. A record may remain somewhat past its
scheduled date while the service is unused; the first subsequent real use starts the due work in the background.

Scheduled purge physically removes each due aggregate without depending on email delivery. Explicit
deletion of a never-submitted draft likewise removes the draft and its email address immediately.

### Applicant lifecycle reconciliation

**Direct selection acknowledgement:** a timeout, server error or incomplete successful response
does not prove that the permanent selection failed. Keep the submitted facts, refresh openings
in the background and offer Review openings before another attempt. A definite validation
refusal leaves the form editable.

Applicant opening choices omit closed openings without active participation, including
withdrawn choices. Closed openings with an active participation remain available for
withdrawal or undoing a private, unsubmitted withdrawal. Historical participation and
server deadline/selection validation remain intact.

Applicant session invalidation releases transient email Sending state. Recovery preserves the
pending address, unsaved answers and acknowledged revision while the lifecycle read reconciles
current identity; an abandoned response cannot keep recovered save controls busy.

## Built-In Vacancy Notification List

The application service owns a minimal one-time vacancy-notification list, not a wait list, applicant
account, newsletter, or promise of consideration.

The public form collects only an email address and one or more requested unit sizes, along with
the consent time needed to operate the list. It does not verify control of the address: the
requested vacancy notice is the only email the subscription sends. Submission is rate-limited and
does not reveal whether the address is already present. Applying does not subscribe someone, and
subscribing does not create or preserve an application.

The form remains on the always-available static `www.pentacoop.com/apply.html` page and submits
directly to a public endpoint on `applications.pentacoop.com`, which owns validation and durable
storage. A request may need to wake or recover the suspended Fly Machine. The form therefore shows
an immediate **Submitting...** state, then explains after a few seconds that the signup service is
waking and will retry automatically. After roughly one minute, the status says that the request has
not yet been saved and that automatic retries will continue for another 60 seconds. The browser
makes one immediate attempt, then one non-overlapping attempt every 10 seconds until the 120-second
deadline. Retries are safe because submitting the same normalized address replaces its complete
unit-size selection. The form reports success only after the service confirms the database write;
it retains the entered values while retrying. Validation errors are reported immediately rather
than retried. If recovery is exhausted, the form apologizes and directs the visitor to email
`techsupport@pentacoop.com` with the requested unit sizes for manual entry.

The committee Google-session check and the applicant application's initial load use the same
bounded recovery schedule. Their waiting surfaces replace manual retry buttons: after five seconds
they explain that the service is waking, after one minute they announce the final 60-second window,
and after two minutes they stop and link to `techsupport@pentacoop.com`. Both retry every 10 seconds.
The two normal committee checks share the **Signing you in** heading and distinguish the Google
session from an emailed sign-in link in the green status box.

There is one subscription per normalized email address. A later submission for the same address
replaces the entire earlier unit-size selection and becomes the current subscription. This is the
intentional no-verification tradeoff that lets a person update their preferences without receiving
or following a confirmation email; preferences are never merged.

Administrators have a vacancy-list report showing the total active subscriptions, counts for 1-,
2-, and 3-bedroom preferences, and a monthly bar chart grouped by current consent month.
The size counts overlap because one subscription may request more than one size. The monthly chart
groups active records by their current consent month, so its bars add up to the displayed active
total. Routine reporting does not expose email addresses. A separate exact-email lookup shows when
the person first subscribed, when the current preferences were last updated, and the current source;
it lets an administrator add or replace a subscription after a person requests manual help, or
delete one on request. Added or replaced subscriptions retain the source of the request.

When any requested unit size becomes available, the transactional email provider sends one vacancy
notice and the entire list record is consumed, even if the person selected other unit sizes.
Consumption occurs only after the provider accepts the message for delivery so a transient send
failure can be retried without losing the recipient. The notice clearly says that the address has
been removed from the list and links to
the public form so the recipient can create a new one-notice subscription if they want future
notifications. Resubscribing creates a new record; it does not reactivate or retain the consumed
one. SocketLabs applies hard-bounce, complaint, and unsubscribe suppression to future delivery. The
application does not ingest those events or duplicate SocketLabs' permanent suppression list.
On consumption, the application deletes the subscription, including the email address, and retains
no separate consent receipt, vacancy-list audit record, or list-only delivery record. A terminal
delivery failure retains its delivery record for 30 days so an administrator can investigate; the
active subscription remains because no notice was accepted. The next maintenance pass deletes the
failed delivery record after that window ends.

Every vacancy-list message uses the common SocketLabs unsubscribe footer. Confirming that
provider-managed link permanently suppresses the address from all Penta email sent through the
server, including secure sign-in links. A vacancy notice still states that its one-notice
subscription has been consumed and offers the public sign-up link for recipients who have not
permanently unsubscribed.

Vacancy notices use the same grandfathered SocketLabs server as transactional application email;
the free 2,000-message allowance is tied to that server rather than the account. The resulting
server-wide suppression is intentional: someone who uses
the provider-managed unsubscribe is unsubscribed from all Penta email, including secure application
access messages.

## Applicant Google Sign-In

Applicants may use optional identity-only Google sign-in. The internal record ID is the durable
identity, normalized email is the email credential, and an optional unique Google subject is a
second credential on the same record. For applicants, `Application.id` remains the identity carried
by access links, browser sessions, working copies, submissions, retention, and audit history.
Google does not create a parallel applicant account or a second application identity.

Google is offered because it is expected to cover much of the applicant population, including the
many applicants who use Gmail, and removes the wait for an access email on the common path. It is
never required. Email access remains the universal sign-in and recovery method, and a visitor may
still complete and submit the whole application as a guest while applications are open.

### Entry UI and hierarchy

The applicant entry panel follows the committee sign-in pattern but keeps applicant-specific state
and copy. The visual and keyboard order is:

```text
Application access
Start or continue an application

[ ] Stay signed in on this device when using Google
[ G  Continue with Google                 ]  primary path

---------------- or use email ----------------
Email address
[                             ][ Send sign-in link ]  secondary path

-------------------- or ----------------------
[ Continue as a guest                     ]  tertiary path
You can save your application and receive a link to open it later.
```

Google is first and full-width. A shared Penta component follows Google's current light outlined
button treatment, including the official multicolour mark, approved **Continue with Google**
wording, padding, type scale, border, and focus treatment, while preserving the existing
server-side OIDC flow. Email is a normal secondary action: its button sits beside the address field
on desktop and stacks below it on narrow screens. Guest access is a quieter tertiary action but
remains a real full-width button with visible focus treatment and no wording that implies a lesser
application. When no new application may be started, the guest divider, button, and note disappear;
Google and email remain available to eligible returning applicants.

The closed entry uses **Continue your application** as its heading and places a warm status panel
before the sign-in controls. The panel says that new applications are not being accepted, explains
that an existing applicant may still review, update, or withdraw, and links the one-email vacancy
notification list in that same explanation. The deadline status is never relegated beneath the
authentication choices.

The remembered-device checkbox beside Google applies to the Google action. Email-link visitors
continue to choose **Keep me signed in on this device** on the device that opens the link, before
the link is consumed. This preserves the current shared-device guarantee when a link is requested
on one device and opened on another. Google One Tap, automatic sign-in, and silent sign-in are out
of scope: choosing the Google button must be deliberate, and the applicant must be able to choose
the intended Google account on a shared browser. Email and guest access render independently and
remain usable if Google authentication is unavailable.

The applicant and committee surfaces use the same branded Google-button component and the same
620 px access-panel envelope. Both place **Send sign-in link**, with an envelope icon, beside the
email field on desktop and stack it on mobile. Their callback endpoints, sessions, authorization,
conflict handling, and page copy remain separate domains.

### Identity and linking invariant

An accessible current application may store one nullable, unique Google `sub`. The existing
server-side OIDC authorization-code flow validates OAuth state and exchanges the callback before
using `sub`, email, and `email_verified` to resolve an identity. It stores no Google access token,
refresh token, name, avatar, or profile data and requests no Google data scope. Applicant and
committee callback endpoints, transient OAuth state, return destinations, and host-only browser-
session cookies remain separate even when one person uses the same Google account in both roles.

The normalized verified Google email and the application's normalized primary email must always be
the same when a Google identity is linked or used. Applicant access deliberately uses the current
committee rule for every Google account: `email_verified` must be true, the normalized emails must
match, and the subject/email collision guards below must pass. It does not add separate `hd` or
email-domain policy. This keeps both audiences on one understandable identity rule and avoids a
second email-proof state inside Google sign-in.

| Existing Google subject | Current application for verified Google email | Result |
| --- | --- | --- |
| Subject is linked to that application | Same application | Sign in and issue the ordinary applicant session. |
| Subject is not linked | One unlinked application or saved draft | Attach the subject, claim the draft if needed, and issue the ordinary applicant session. |
| Subject is not linked | No application or draft; applications are open | Create the new private application for that email, attach the subject, and sign in. |
| Subject is not linked | No application or draft; applications are closed | Do not create a record; show that new applications are unavailable and link to vacancy information. |
| Subject or verified email resolves to a selected application | Selected application | Do not issue a session, create another application, or change the Google binding. Show the verified user that the profile is locked because the household was selected. |
| Subject is linked to a different email | Any | Refuse Google sign-in; never change either email or binding. Offer another Google account, email access, and Tech Support. |
| Email is linked to a different Google subject | Same email | Refuse Google sign-in; never replace the existing binding. Offer email access and Tech Support. |
| Subject and email resolve to different applications | Different applications | Refuse Google sign-in; never reveal, merge, or mutate either application. |

Google matching uses only an active, ordinarily accessible application. A withdrawn legal-hold
record is not returned as a collision and cannot receive Google access. Withdrawal clears the
Google subject as part of removing ordinary applicant access; physical purge removes it with the
application. A later application using the same email begins blank and may establish a new Google
binding without exposing the retained record.

A successful Google claim of an email-only pending draft performs the same claim as its access
link: it preserves the server-side answers, resolves the draft into the application, and makes old
draft links recognizable but unusable. If the browser also contains a different in-page guest
copy, the existing saved-versus-guest comparison appears after Google sign-in; Google credential
state never carries applicant answers or other PII.

If a different applicant session is already active in the browser, Google authentication preserves
it and asks the applicant to sign out before continuing with the other Google account. Email-link
conflicts use the explicit keep/switch choice described above. Cancelling Google, an OAuth/provider
failure, an unverified email, or a refused collision leaves the existing session intact.

### Changing the primary email

The primary email remains both the application contact address and the email identity to which a
Google subject may be bound. Changing it continues to require the current explicit flow:

1. An authenticated applicant enters a different address.
2. Penta sends a single-use confirmation link to the proposed address. Until that link is opened,
   the primary email and Google binding do not change; replacing or cancelling the pending request
   leaves the existing Google sign-in working.
3. Opening the valid link refuses an address already owned by another active application and never
   merges records.
4. On success, one transaction updates the primary email and private working answers, clears the
   existing Google subject, revokes unused applicant links and the affected old sessions, and
   issues the continuing browser a fresh application session.
5. Penta sends the existing security notice to the old address. The success screen explicitly says
   that Google sign-in was disconnected because it belonged to the old email.

The applicant may immediately choose Google again, but it links only when Google's verified email
matches the newly confirmed primary email. The old Google identity can no longer reopen that
application or reverse the email change. If its old email no longer belongs to any active
application and new applications are open, using it later follows the ordinary new-applicant path
and opens a blank private application form; if applications are closed, it cannot create one.
Google authentication never confirms a pending email change, even if Google returns the proposed
address; the emailed confirmation link remains the proof that Penta can deliver future application
communication there.

There is no separate connected-accounts settings surface. Linking is automatic only on an
unambiguous email match, and changing the primary email is the supported way to disconnect a binding
that belongs to the old address. An applicant who needs a different Google subject for the same
unchanged email uses email access and Tech Support; the application never silently replaces one
Google subject with another.

### Additional corner cases and boundaries

- Only the primary applicant may authenticate. A co-applicant's Google account or matching
  co-applicant email grants no access and cannot be linked.
- A Google-authenticated applicant may save, submit, withdraw, and request an email change
  exactly as an email-authenticated applicant; authorization depends only on the resulting
  `Application.id` session.
- A pending email change remains visible after either sign-in method. Google sign-in neither
  confirms nor cancels it.
- Expired local sessions, Google consent revocation, Google-account deletion, and Google outages
  fall back to email access. Revoking Google consent does not retroactively revoke an already issued
  Penta browser session; Penta sign-out, sign-out-all-devices, expiry, withdrawal, and retention
  rules still govern that session.
- A provider-wide email suppression may prevent email recovery or email-change confirmation;
  Google access does not bypass confirmation of a new contact address. Tech Support remains the
  recovery route.
- Multiple tabs follow the existing working-revision and pending-copy rules. A Google round trip
  cannot overwrite newer server answers, publish a guest copy, or bypass explicit reconciliation.
- Google sign-in does not prefill the applicant's legal name or any application answer. The Google
  email initializes only the primary email for a genuinely new application.
- Google sign-in must not reveal whether an arbitrary typed address has an application. The only
  address involved is the verified address returned for the Google account the visitor controlled.
- Applicant Google use remains identity-only. It does not restore Google Forms, Sheets, Picker,
  Drive scopes, imports, or synchronization.

## Vacancy Email Tone And Content

- Notices describe the published opening's unit size, housing charge, move-in date, and deadline.
- A matching vacancy notice consumes the whole one-notice subscription after provider acceptance,
  regardless of whether the recipient also has an application. It invites resubscription.
- An existing application is never enrolled automatically: the applicant must review and submit it
  for the new opening. Retention alone never authorizes consideration for another opening.
- Retention is anchored to committee decisions as specified under Intake data boundary; notice copy
  must not invent a new expiry or imply that every application expires one year after submission.
- Penta has no waitlist. Notices are warm, concise, co-operative, and signed by the Membership Committee.

## Product Concept

The product proceeds in phases:

1. Collect, save, version, and normalize submitted applications.
2. Apply deterministic hard filters without AI.
3. Use AI to flag data-integrity concerns and discover the dimensions the pool varies on.
4. Let the committee weight those dimensions (a tier-list), re-sorting the ranked pool instantly.
5. Produce a MOMI-ready report with recommended interview candidates and justifications.

The screener supports multiple MOMI committee members running their own screening sessions independently (see "Multi-Member MOMI Workflow"). Each member may value different criteria; the app preserves and summarizes each member's criteria, ranked candidate view, and rationale so MOMI can compare both applicant recommendations and the values behind them.

Candidate saving has two deliberately separate meanings. **My favourites** remains a private
bookmark for one member's broader list. **Shared shortlist** is one committee-visible, reversible
working set for the households the committee currently wants to keep on its shortlist. Either may be
changed from Applications, Ranking, or applicant detail; each view can show All, My favourites, or
Shared shortlist, and printing Ranking follows that active view. Neither marker changes eligibility,
AI output, rank order, or the final opening-selection outcome. Removing a household from the shared
shortlist never removes any member's private favourite.

## Screening Scope

Each opening configures its own unit size, move-in date, housing charge, and eligibility policy.
The screener has no hard-coded current search or unit size.

The application form is responsible for collecting complete applications. The screener focuses on what happens after applications have been submitted.

## Dashboard

The app provides a dashboard summarizing the current application pool and screening state: total submitted applications, eligible applications after deterministic hard filters, filtered-out applications with reasons, applications ready for AI review, currently qualified applications, and the ranked shortlist. Every submitted application remains visible somewhere; deterministically disqualified applicants are excluded from AI review but remain accessible in a filtered-out view with their reasons.

## Intake And Analysis Records

Submitted applications are immediately available to the committee. Screening results are cached
against application content, prompt, model identity, and applicable reasoning level. A new or
edited submission therefore makes only affected work stale. Each Rank analysis records the pool
fingerprint and the exact AI configuration it used; immutable opening-specific application
snapshots are not required because dated `ApplicationVersion` rows preserve submission history.

## Deterministic Eligibility Rules

### Rules Engine Architecture

The screening rules system is a configurable rules engine. Each rule is a discrete, named validation that produces a binary outcome: the application is either `eligible` or `ineligible`.

The pure domain evaluator calls a failed result `filtered_out`; committee APIs expose the
corresponding effective status as `ineligible`.

Each rule has:

- **ID**: machine-readable slug (e.g. `owns_real_estate`, `child_age_over_max`)
- **Display name**: human-readable label shown in the admin UI
- **Description**: explains what the rule checks and why
- **Outcome**: `ineligible` (the only outcome — any rule that fires disqualifies)
- **Parameters**: configurable thresholds or values (e.g. income min/max, min/max children, max child age, max pets). Not all rules have parameters.
- **Enabled**: toggle on/off per screening configuration. The employment requirement is controlled
  only by its dedicated dropdown.

Eligibility Settings owns the selected opening's per-member rules and admin-editable committee default. It shows the rule list, toggles, and parameters. Disabled rules do not run during screening.

Adding a new rule requires code (a rule function that takes normalized application data and returns pass/fail with a reason). Once the code exists, the rule appears in the admin UI and can be configured. The rule logic is simple enough to add, and the admin controls which rules are active and what thresholds apply without code changes.

Rules run in a defined order. An application that fails any enabled rule is `ineligible`. An application that passes all enabled rules is `eligible` and proceeds to AI screening. The pure logic lives in `app/domain/hard_filters.py`, separate from HTTP/ORM/Google concerns.

### Rule Catalog

**Household composition rules:**

| Rule ID | Description |
|---------|-------------|
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

**Employment rules:**

| Rule ID | Description |
|---------|-------------|
| `employment_requirement_not_met` | The household does not meet the member's configured employment requirement: none, at least one adult working, or every adult working. Employed and self-employed adults count as working; a missing co-applicant is not counted. Legacy applications without explicit employment status are not inferred or flagged. |

**Property rules:**

| Rule ID | Description |
|---------|-------------|
| `owns_real_estate` | Applicant owns real estate. |

### Rule Behavior Notes

- Moving within the two-year residence-history period is not disqualifying.
- Applicants outside Vancouver, BC, or Canada are eligible.
- Applications should be complete at submission time. The screener does not create applicant follow-up workflows.
- Applicants with an application already on file are not treated differently.
- Email-list signup date and notification history must not influence screening.
- Applicant, co-applicant, and child ages are calculated from their dates of birth as of the
  application's last submitted edit.
- The built-in form derives child count and household income, requires a complete co-applicant when
  one is present, rejects negative income, and rejects future birth and employment start dates.
  These are submission constraints rather than eligibility decisions.

### Application Status Model

Each member sees one effective **status** for an application in the selected opening, with
exactly two values. Status is computed from current findings and that member's optional
`MemberEligibility` override; it is not a mutable status stored on `Application`:

- `eligible`: in the running, proceeds through screening
- `ineligible`: not in the running

Status is set by an actor, recorded in **`status_source`**:

- `untouched`: no actor has acted on it — it passed the rules and either AI has not run or AI did not flag it. The default for a clean eligible application.
- `rules`: the deterministic filters set it `ineligible` (high trust)
- `ai`: the AI screening pass set it `ineligible` (lower trust — the "needs review" bucket)
- `human`: a person set the status, in either direction

A clean automatic verdict is `eligible / untouched`. Rule reasons take precedence; a pet-only
reason or an active integrity flag is attributed to `ai`. Automatic status can change when its
findings change. A human override takes precedence in either direction until explicitly cleared.

There is no third status. The UI surfaces the `status_source = ai` group as an "AI Flagged" view, composed client-side as a filter over the derived response fields. This keeps status binary while distinguishing high-trust deterministic exclusions from AI exclusions. The labeling is deliberately factual ("AI Flagged" — what happened), not prescriptive. The backend returns derived status/source counts and filters, faceted so impossible combinations
read zero; these are response fields rather than `Application` columns.

**Findings are separate from human decisions.** Members do not edit machine evidence:

- deterministic **filter reasons** (e.g. `Household gross income ($164,000) is above $150,000.`)
- **AI screening flags** (category, summary, evidence)

A human flipping the status never deletes these records — an applicant can be `eligible / human` while still showing the AI flags a reviewer chose to accept. This preserves the audit trail.

**Stickiness:** a machine actor (rules or AI) must never overwrite a `human` status. When submitted fields or AI findings change, machine actors refresh the reason/flag records but leave a human-set status untouched.

**Clearing an override:** a human override can be removed, handing the decision back to the machine. Clearing recomputes the status from the *current* findings (rules then AI) and resets `status_source` to the machine source. The detail view models this as source ownership: a segmented **Decided by** control over `Automatic | Eligible | Ineligible`, where "Automatic" is selected whenever `status_source != human` and selecting it clears the override. The detail payload carries `autoStatus`/`autoStatusSource` (what the machine would decide right now). Clearing is idempotent.

**Staleness nudge:** because human decisions are sticky, a re-run can surface new findings on an application a human already cleared. When the machine records change after a human's review, the application is marked stale ("new findings since last review") so the reviewer can re-decide. Status does not move; staleness compares the current finding reason codes and flag categories with the fingerprint recorded when the human reviewed them.

An eligibility override carries the fingerprint from the displayed detail, so a save cannot silently
record unseen findings as reviewed. The member's decision still saves when newer findings exist;
it remains stale, and the detail refreshes in the background without delaying acknowledgement or
mixing newer reasons into older answers. A failed refresh preserves the decision and stale nudge.
Members can explicitly reaffirm the same Eligible/Ineligible decision after reviewing current
findings. The nudge says **New findings**, covering deterministic rules as well as AI flags.

### AI Screening (Integrity Flags)

Separately from eligibility, AI makes a screening/integrity pass over eligible applications to flag suspicious patterns too subjective or contextual for deterministic rules. When the AI pass flags an eligible application, it sets the status to `ineligible` with `status_source = ai` (the low-trust AI-excluded group) rather than excluding it outright. A human reviews these and either confirms the exclusion or restores the applicant to `eligible`. The flags are kept as immutable records regardless.

The pass also re-analyzes applications a *previous AI pass* marked ineligible, so a revised prompt can change the verdict in either direction. Applications the deterministic rules disqualified are excluded (rules outrank AI). Human-set statuses remain sticky.

Known patterns to detect (intentionally incomplete; grows over time):

- Child names that look like placeholders ("Baby", "TBD", "N/A", "Test")
- Applicant or child names that appear fake or nonsensical
- An essay set with no substantive response anywhere; one or several short or blank answers do not
  trigger this when any other essay is substantive, and a blank optional essay is ignored
- Essay responses that appear to be advertising or spam
- Essay responses that appear to be AI-generated boilerplate with no personal detail
- Responses copy-pasted across multiple essay fields
- Internal inconsistencies between essays and other fields
- Phone numbers or emails that appear fake beyond format validation

The pass also extracts neutral pet counts and other-pet descriptions. Deterministic per-member hard
filters judge those facts against the applicable pet limits. AI screening flags are stored
per-application and shown in the candidate detail view as informational notices, not filter reasons.
Implementation depth: [docs/ai-screening.md](docs/ai-screening.md).

## AI-Assisted Screening

AI review runs only for candidates who pass deterministic hard filters (or are resolved eligible by a human). The full pipeline and file layout are in [docs/ai-screening.md](docs/ai-screening.md); the significant decisions are in [docs/adr/](docs/adr/). This section is the product-level current state.

### Provider And Cost Controls

The AI architecture is provider-adaptable behind an internal `AIProvider` interface, with a deterministic `MockProvider` backing tests. The Strands implementation supports Claude and GPT through Amazon Bedrock plus direct Anthropic and OpenAI routes. One exact model catalog owns routing, capabilities, and the shared provider-neutral model identity for equivalent routes. Provider-native model IDs remain in settings, traces, evals, and cost rows for provenance and route-specific pricing; caches and freshness use the model identity, so moving the same pinned model between Bedrock and its direct API preserves valid work. Credentials are deployment secrets, while admins choose configured routes per pass in the UI. Default routes use Claude on Bedrock. Every Bedrock route uses a `global.` inference profile from the `us-east-1` source region: Claude retains Strands' Bedrock/Converse adapter, while GPT retains Strands' OpenAI Responses adapter pointed at Bedrock Runtime and authenticated with fresh short-lived tokens signed from the AWS credential chain. Bedrock may process a request in any supported commercial AWS Region while keeping traffic on AWS's network. This accepts worldwide processing of applicant prompts and outputs in exchange for the global profiles' lower price and broader capacity; the public privacy policy discloses that service-provider processing may occur outside British Columbia or Canada. See ADRs 0010 and 0014–0016.

Cost control is a core requirement. The app prefers: cached AI analysis per application and per run; smaller/cheaper models for high-volume passes and frontier models only for cross-document synthesis; short structured outputs; a visible AI cost estimate before running; and a configurable per-run spending cap (default `$2.00`, enforced against the estimate before any model call — an over-cap run fails fast with 402). Hard filters are computed from submitted application fields; AI review starts only after the user sees the estimate and confirms.

### Interactive Screening And Ranking

The screener discovers the differentiating dimensions of *this* pool rather than starting from a fixed rubric, then lets the committee weight them. It is a screening assistant for a human, not an autonomous filter.

**The assistant does not "cut" candidates.** At ~300 applicants, hard removal is the wrong model. Instead it **stack-ranks the entire qualified pool with a per-row rationale**, and the committee's weighting re-sorts that list. Re-weighting adjusts standing (soft ranking), never removes anyone; the committee reads the stack rank top-down with no fixed cut line. Re-weighting is freely reversible.

**The committee expresses what matters with a tier-list maker** (`@dnd-kit`; see ADR 0006): the discovered dimensions are draggable chips sorted into self-defined importance tiers (Critical/Important/Minor by default, plus an Ignore zone), and the ranking re-sorts instantly as deterministic math over the cached scores — **no model call per change**. A future "Criteria Coach" may *ask* questions to help the committee reflect on the weighting they built (not to elicit it).

**The defining architectural decision (ADR 0005): the LLM extracts scored features; ranking is deterministic math on top.** The model scores each candidate on the discovered dimensions and never opines on importance. Criteria start at zero weight in Ignore. Until a member places at least one criterion in a working tier, applicants are unranked: rank numbers, aggregate fit, and fit bands are absent. The Ranking tab keeps the criteria controls and a persistent notice directing members to choose priorities; it hides the applicant list, View selector, and Print buttons. Applicants remain available in Applications. Moving every criterion back to Ignore restores this unranked state. Each member chooses their own priorities; a weighting change re-runs only the math over cached scores and makes no model call.

An applicant enters the merit-ranked list only after every positively weighted criterion has a
returned score. Missing scoring work is unknown, distinct from an actual neutral score of zero;
partial results remain stored for reuse and recovery. Missing unweighted criteria do not delay
ranking. Bands and contribution means use the rankable shared pool before member-view filtering.

The Rank chain is exposed as a **single button** — the committee never runs the sub-passes individually. In order:

1. **Pattern discovery** (synthesis model, ×K in parallel): reads the whole eligible pool (facts + raw essays) and discovers the dimensions it varies on — name, definition, why-it-differentiates. K blind fresh-context calls; their cross-call disagreement is diversity the next step needs. Committee proposals seed one worker. Targets 5–25 dimensions (empirically ~14–16), biased to split, anti-padding. Dimensions are **oriented so more-is-better fit** (no direction flag — see ADR 0004); "goldilocks" axes reframe to a monotonic concept or split into two more-is-better dimensions.
2. **Decomposition** (synthesis model): settles the K overlapping reports into one finest, non-overlapping set — collapses re-carvings of one concept, keeps genuinely distinct axes apart, protects committee-requested axes (a `from_committee_request` axis has a higher bar to merge away, with a deterministic backstop). See ADR 0007.
3. **Identity matching** (synthesis model): maps this run's dimensions onto *all prior runs'* by meaning, so a re-discovered concept re-adopts its old key and carries its tier placement + cached scores forward. A high bar (a wrong match corrupts a reused score), erring toward "new."
4. **Dimension scoring** (first-pass model, per candidate): scores each applicant on the signed **−1..+1** scale per dimension, with rationale, grounding evidence, and a confidence label. Silence scores 0 (never negative) — see ADR 0009. The per-dimension rationale + evidence is this pass's observability (no separate call-level narrative). Cached per (candidate, dimension) under `dimension_scoring:<dimension_key>`, so matched dimensions reuse scores by key across re-ranks and only new/unmatched ones are re-scored.
5. **Consolidation** (synthesis model): post-score cleanup — near-identical score vectors *nominate* suspected duplicates the definition-only match pass missed (Pearson ≥ 0.8), and one confirm call merges genuine ones by definition (aliasing the newer key to the older, so the key space converges). Distinct axes that merely correlate are kept apart. `dimension_aliases` is the durable merge-truth.

Then the ranked list is **pure deterministic math** (`app/domain/ranking.py`): fit is the weight-normalized average of a candidate's dimension scores, `Σ(weight·score) / Σ(weight)`; weights are derived from the tier layout (never stored); qualitative bands ("Strong fit" … "Limited") are relative to the pool (rank position), not absolute thresholds; confidence is surfaced next to each score but never folded into fit. The candidate detail page selects/orders per-dimension contributions by `abs(impact)` where `impact = weight × (score − pool_mean)`, so a heavy strike surfaces as readily as a strength.

**Two Rank modes.** *Discover new criteria* runs the full chain and may replace the criteria set. *Score missing applicants* runs only scoring, for eligible applicants missing a current-dimension result — preserving the run's dimensions and tier layout, independently cap-gated. Complete score coverage makes the retained criteria current for the changed pool.

**Cost gating and readiness.** Screen is ready when its in-scope applicants have valid cached screening results. Rank is ready when every eligible applicant has valid scores for every current criterion, with no pending proposed criteria for that member. Answer, scoring-model, effective reasoning, scoring-prompt or criterion changes can cause real cache gaps and amber the step. Ignored existing criteria are not pending proposals. Discovery remains optional even with complete scores and always requires cost confirmation. `Analysis.rank_inputs_fingerprint` records the inputs captured before explicit AI work for provenance; it does not determine button colour. Discovery-only model, prompt or strategy changes do not invalidate scores for retained criteria. Switching between certified-equivalent routes preserves cached work. Rank streams phase-aware progress and model reasoning for its pool-level calls, then opens the ranked view.

### Cache evidence and cost projections

AI cache identity includes canonical answer content and the frozen submitted facts consumed
by each pass. Birthdays between submissions cause no miss. A resubmission that refreshes an
age invalidates only passes that consume that changed evidence. The evidence-key migration
retains outputs, selected-result references and cost history, rekeying provably unchanged
inputs; ambiguous historical age projections remain history and are not claimed as cache hits.
Rank fingerprints include discovery fan-out and consolidation correlation threshold; worker
count and spending limits do not invalidate semantic freshness. New Rank analyses capture the
AI settings and all five prompt/model/reasoning identities in their discovery audit, available
through the existing fan-out audit endpoint. Analyses without the expanded fingerprint remain
reviewable; only current cache gaps or pending proposed criteria make Rank amber. New AI work requires an explicit run.

Cached-result retention: `ApplicationAIResult.producer_application_id` preserves the original
producer identity without a cascading FK. Output remains while the producer or a selected
consumer has current legal retention. Purge and selected-reference replacement prune affected
unowned output; restore upgrades the schema before replaying deletions. Result IDs, cache keys,
provider provenance and cost history are preserved.

Full-Rank cost projections remain expected costs, not upper bounds. Compatible historical token
usage is repriced for the selected route; discovery usage is normalized by provider replies and
the current discovery count. Matching uses global criterion history consistently with execution.
Unknown/incompatible history uses the existing fallback, without guessing ledger/analysis links.
Cost tables compare cached result units with attempted uncached units (including failed attempts);
provider reply counts are separate. No eval spending cap or automatic paid retry is introduced.

### Ranking And Outputs

The primary output is a ranked list. It is explainable and preserves evidence behind each recommendation. AI produces qualitative labels for user-facing screening; hidden internal scores support ranking, but the UI explains rankings in plain language rather than centering numeric scores. AI summaries use a neutral committee tone and stay transparent enough to detect bias or unsupported claims. Direct essay excerpts are used sparingly; entire essays are never reproduced in summaries or reports.

Candidate detail exposes source answers and per-candidate AI evidence to committee members.
Observability, Evals, and historical pool-level audit traces require an administrator. Each screening run is saved with its criteria, prompts, model outputs, ranking outputs, and shortlist. AI output schemas are defined in `app/ai/schemas.py`, shared by prompt, storage, API, UI, and evals.

### Essay Judgment

Strong negative essay signals include (not limited to): the applicant appears unaware of co-op obligations; treats the unit mainly as cheap rent without understanding shared work; expresses hostility or resistance to shared work; has an unclear or inconsistent household situation. Essay concerns may justify a "do not interview" recommendation — essay review is central, not a low-priority flag. Brief, awkward, translated, or non-native English answers are **not** penalized for writing polish; the AI judges evidence of co-op fit, participation commitment, and relevant signals rather than style or fluency. Differentiating criteria are *discovered* against the pool at Rank time rather than pre-committed (ADR 0001).

### Observability And Evals

The pipeline makes real, non-deterministic model judgments, so it is instrumented across four pillars (build history in CHANGELOG M13; grader design in ADR 0008 and [docs/ai-evals.md](docs/ai-evals.md)):

- **Cost** — an Observability "Cost" subtab: cumulative and last-run AI spend, per pass, with a token (in→out) + model breakdown and estimate-vs-actual reconciliation. All cost accounting flows through one `PassCost` value object into `run_cost_ledger` + `run_pass_cost`, which both Screen and Rank write and both surfaces read.
- **Per-pass AI trace viewer** — each pass's raw output is legible: per-application (screening flags, scoring rationale/evidence) on the candidate detail page; per-run (discovery, decomposition, matching, consolidation audits) on the Observability subtabs.
- **Operational metrics** — an Observability "Trends" subtab: per-run/per-pass cost, tokens, wall-clock latency, cache-hit rate, failure count, and dimension count over time.
  Final dimension counts are captured with completed Rank ledgers. Historical runs without that
  measurement show unknown; counts are never inferred from unrelated analysis order.
- **Evals** — run in-app from the **Evals** tab, never gating a commit:
  - **Invariants** (deterministic, the only CI gate): things always a bug — every dimension has distinct high/low poles; no criterion keys on a protected class. "Re-baseline from current Rank" records the blessed fixture.
  - **Live per-pass evals** — each pass's golden cases fed through the *real* production prompt and graded by a grader matched to the output shape (categorical → exact-match; scoring → a band; screening → per-category), with a `?mode=stability` K-repeat run measuring verdict flips. See ADR 0008.
  - **Judge** — a blind label-auditor: an independent model reproduces each pass's output from an editable per-pass brief + the case's input, blind to the label; the harness grades it against the human label with that pass's own grader. Decisive-case agreement and separate contested counts summarize the corpus; a consistent disagreement flags the *label*. Run occasionally, not per-run. See ADR 0002.

Applicant-facing eval exports require verified captured synthetic provenance and a wholly synthetic
actual export cohort. The assurance is captured before provider work and includes inherited criterion
history. Later arrivals are checked by both harvesters and baseline capture; unknown historical
sources fail closed. A baseline refusal reports Synthetic evidence required and preserves the file.
Fixtures use opaque applicant columns and omit top-level narrative and pool justifications; nested
prose is committable only behind the same synthetic boundary. Golden sets are grown with the harvest scripts under `backend/scripts/` (co-authored, then labelled by hand).

### Operator access and versioned eval data

**Operator tools and versioned eval data:** Evals and Observability, including the four ranking
audit endpoints, require an administrator. Ordinary member Screen/Rank/current-board access
remains available, with historical operator narrative omitted from ordinary member responses.
Eval runs deliberately have no spending cap; application AI caps do not
apply to them. Existing call-count and real-spend confirmation remains visible.

Case editing, judge-brief editing and baseline recording are local admin operations. The
backend exposes this runtime capability and refuses hosted writes; the UI shows hosted cases,
briefs, invariants and paid run controls without edit/re-baseline controls. Local fixture edits
are committed/pushed in Git and included in the next manually deployed image. Git push alone
does not update the hosted app. The versioned corpus stays out of the runtime database/volume.

Eval fixture readers and writers share nested family contracts and UTF-8 encoding. File
publication replaces a complete JSON file atomically. Missing scoring output is null, with
its failure reason retained; an all-missing stability run has no numeric range. Stability
measures consistency separately from correctness. Baseline vectors are scoped to the source
analysis's current opening cohort and criteria. Provenance uses captured pool configuration
and selected score producers; unavailable or mixed history is unknown rather than guessed.

Fixture family identity comes from its owning endpoint/file; conflicting metadata is rejected.
Screening expectations validate category names and strict raw pet-count types. Ordinary eval
batches retain completed case evidence alongside explicit operational errors; invalid output
cannot pass through contested handling, and cancellation remains distinct. Stability bounds
nested concurrency under the request's worker setting without dropping repetitions. Golden
comparisons capture inputs once and retain known usage after errors; incomplete repetitions
have no stability verdict. Copied Rank experiments use SQLite-consistent snapshots, require
an explicit opening, apply effective pass settings and accept only that attempt's new results.

Same-analysis trace refresh preserves expanded content and offers retry after failure. A changed
opening or analysis resets the displayed trace. Interrupted Screen streams reconcile committed
partial results without claiming successful completion or waiting for all derived views. Network
failures, timeouts and server 5xx responses are uncertain outcomes for Screen and both Rank modes;
these trigger scoped recovery reads. Definite 4xx rejection and caller cancellation remain separate.

### Agent Workflow

The application is *designed as* a multi-agent system, but the agents are a conceptual decomposition, not a mandate to build orchestrated LLM loops everywhere. **The realized architecture is a pipeline of single-purpose passes + human gating.** Each "agent" is a named, user-visible pass — deterministic code (hard filters, ranking math) or one structured-output call (screening, discovery, decomposition, matching, scoring, consolidation). State lives in the database between passes; orchestration is the human clicking gated workflow steps plus deterministic control flow. No LLM decides what runs next. This is deliberate: pre-run cost estimates + a cap, per-(candidate, kind, prompt-version) caching, auditability, eval-replayability, and reproducible structured output all depend on the call graph being known in advance.

Genuine multi-agent coordination is reserved for spots with a feedback/revision loop that a fixed pipeline can't express, added surgically and kept **bounded** (generate→critique→retry-N, not open-ended): a future `Evidence Auditor` (checks recommendations are grounded, sends weakly-supported ones back), the `Criteria Coach` (reflects on the committee's weighting), and a `Screener-Evaluator` (evaluates the system across runs and proposes human-approved, versioned improvements — schemas/prompts are never self-modified at runtime). A `Coordination Agent` becomes worthwhile only once two or more such loops run in one session. (The fan-out discovery redesign considered a multi-agent merger↔splitter loop and rejected it on measurement — ADR 0007.)

Every AI recommendation is reviewable and overrideable, and explains why a candidate advanced rather than only providing a numeric score.

### Privacy, Auditability, And Evals

It is acceptable to send full application context, including names/contact context, to the AI model. Redaction is not required. Applicant data is still treated as sensitive: deterministic filtering stays separate from AI judgment; prompts, model outputs, filter decisions, ranking rationales, and overrides are auditable. The eval-oriented design (fixtures, schema-consistency checks, grounding/evidence-quality tracking, enough trace data to debug regressions) is built and described above.

## Multi-Member MOMI Workflow

Each of the ~5 committee members screens independently — their own eligibility rules, eligibility overrides, dimension tiering, ranking, and notes — layered on a **shared, compute-once substrate within the selected opening**: its applicant pool and AI-discovered dimension set, plus globally reusable per-(applicant × dimension) scores. Members bring their own lists to a meeting and debate live; the app does **not** merge, compare, or reconcile them. There is no merge formula, disagreement flag, criteria-comparison surface, or visibility into
another member's private ranking. Committee notes and the Shared shortlist are explicitly shared.

### Opening workspace boundaries

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

### Shared and personal state

**Shared / per-member boundary:**

| State | Scope | Notes |
|---|---|---|
| Submitted applicant pool | per-opening, shared by members | one source of truth for the selected opening |
| Discovered dimension set | **per-opening, shared by members** | rebuilt from that opening's pool; matched through global canonical history + `dimension_aliases` |
| Per-(app, dim) AI scores | **global cache** | content-addressed cache key has no member or opening id — sharing is automatic when inputs match |
| Cost ledger / traces / evals | committee-wide | run costs carry opening attribution; aggregate Observability crosses openings |
| Eligibility **rules** (income/age/children/pet thresholds, `disabled_checks`) | **per-opening, per-member** | each opening owns a committee default; a member's row is copy-on-write for that opening |
| Eligibility **overrides** (per applicant) | **per-opening, per-member** | |
| Tier placement + ranking + new/revived/requested badges | **per-opening, per-member** | weights stay **derived** from tiers, so per-member re-weighting is free math |
| Private notes | application-wide, per-member | personal context follows the applicant across openings |
| Committee notes | application-wide, shared by members | attributed entries follow the applicant across openings |
| AI model/cap settings | shared | infra config, not judgment — split out of the eligibility-rules blob |

**Union eligible pool.** Within the selected opening, an applicant is in the **committee-eligible union** if they pass *any* member's effective screen (that member's rules *or* an explicit override) — a derived predicate over the per-member views, not new stored state. Discovery and scoring operate on this union floor; applicants whom no member passes are never scored — preserving "don't score applicants who won't clear the screen." A member's ranked list is the opening's shared analysis **filtered to their eligible view and weighted by their tiers** — pure math, instant, free.

**Selected AI evidence.** Screening findings, candidate scores, detail provenance, and
consolidation vectors read the result last consumed for each applicant and kind, including
cache hits. `ApplicationAISelection` references the existing result ID; it never copies
outputs or changes the original producer, model, prompt, reasoning, or usage. Scores stay
shared across members and openings by canonical dimension key. Cache references update in
one batch after inputs are captured; fresh references commit with their result. Historical
rows are migrated to their previously displayed newest result because earlier cache choices
were not recorded.

Score-only execution captures the current analysis, eligible pool, effective reasoning,
cache choices, model inputs, and estimate after acquiring the run lease. Estimate and
execution consume the same plan. The pass refreshes references for the whole pool while
making model calls only for cache misses. Valid matching saved scores are applied automatically
without a cache-reuse prompt or AI spend. The criteria and tier layout stay unchanged.
Completed replies retain their known token usage and cost even if missing scores remain
after retries or a later call fails. Incomplete candidate scores are never cached. Progress
counts attempted applicants; the completion summary counts successfully scored applicants.
Timeout billing without returned usage is unknown and is not inferred. New scoring ledgers
count completed structured-output replies, including retries, separately from dimension
cache units. Historical scoring call counts can reflect dimension units because those
replies were not recorded separately. The live run total uses whole-call usage and price;
per-dimension token allocation cannot reduce its reported cost.

A candidate's complete fresh score vector and consumed references publish in one transaction.
Storage failure rolls that vector back; other successfully saved candidates remain available.

Failed Rank phases preserve known completed replies from earlier passes and the failing pass,
including processing errors after a reply. The ledger records the failed stage and error type;
Insights labels failed attempts and cumulative known spending, and failed attempts do not train
normal rerun cost estimates. Best-effort consolidation errors retain their known cost and warn
that cleanup was skipped while the usable ranking completes.
Cache-hit rates use explicit fresh/cache dimension units, not provider-call counts. Historical
rows without recorded units remain unknown; the additive migration preserves their costs,
attribution, and completed status without guessing a cache percentage.

Screening and score-current failures follow the same known-usage rule, including storage errors
after a reply. HTTP interruption rolls back pending results and releases the run lease, then
records already-returned usage as an interrupted attempt in a separate expense transaction.
It neither publishes cancelled results nor duplicates a completed ledger. Cache-unit and
latency measurements for those receipts remain unknown. Calls still running at cleanup and
billing without returned usage require provider reconciliation; cleanup does not await providers.
Failure logs retain operation and exception class without provider traceback text or criterion keys.

**Sharing and readiness:** caches have no member or opening ID; identical submitted evidence,
canonical criterion, model identity, reasoning and prompt reuse the same result. Pool discovery
remains opening-specific. New criteria enter each member's Ignore zone at zero weight. Screening
uses the union of deterministic rules plus forced-eligible overrides, with one reusable integrity
and pet-fact result. Rule thresholds do not enter its prompt/version. The readiness and reuse
rules above determine amber/green; analysis membership alone does not establish currentness.

**Dimension survival on re-rank:** an opening's shared set keeps any dimension in **any** member's working tier for that opening; a dimension drops only when no member has it working-tiered there.

**Committee-proposed seeds** feed the selected opening's shared discovery. The resulting axis
and Requested provenance are shared; each member may dismiss that badge independently. There
is no deterministic proposal-to-requester attribution.

**Out of scope:** merged ranking, disagreement flags, criteria comparison, and visibility into
another member's private ranking or favourites. The Shared shortlist is a single explicit
committee working set, not a merge or exposure of those private views. Private notes remain visible
only to their author. Committee notes are a separate attributed stream visible to all members; only
the author may edit or delete an entry. Neither kind of note enters AI inputs or applicant-facing
responses. Candidate-detail printing includes the current member's private note and the attributed
committee notes.

Committee-note creation carries one browser-generated key per publishing attempt. A lost
acknowledgement retries that same attempt without appending a duplicate; deliberately
publishing the same text again uses a new key. The composer confirms an uncertain attempt
before publishing a newer draft, retaining text typed while the request was pending.
Deleting a keyed committee note clears its text and retains only its existing scoped
creation/deletion receipt until the application is purged. Retrying that creation cannot
restore the deleted note, and editing a deleted note is rejected.
Permanent opening decisions with uncertain acknowledgements refresh openings in the
background and require review before another choice is offered.

Private-note drafts and their ordered autosave queue belong to the authenticated committee
workspace. Internal tab, applicant, opening, and browser-history navigation preserve unsent text
without waiting for the network. The editor subscribes to its applicant's draft so typing does
not rerender the workspace; confirmed, unobserved drafts are released for fresh detail reads.
Failed saves retain the draft and offer **Retry save**; reopening
it through another opening lets an explicit retry use that opening's authority checks. Drafts
stay in memory only. Leaving the page warns while work is unconfirmed, and explicit sign-out
asks before discarding it. Sign-out fences queued writes before credentials change; a failed
sign-out resumes saving under the original account. Switching accounts clears private drafts.

Committee browser history records the tab, opening, applicant, and retained/read-only review
mode. Back and Forward restore that recorded opening through the normal list-selection workflow
before displaying its applicant. Detail and list reads may run in parallel, but a superseded
navigation cannot change the opening or reopen an applicant. An unavailable opening reports a
load failure rather than substituting another opening's pool. Opening the same applicant in an
editable opening after a retained review creates the appropriate history entry and clears the
read-only mode.

The per-member-pool/shared-content-cache decision is recorded in
[ADR 0011](docs/adr/0011-per-member-eligible-pool-shared-content-cache.md).

### Ranking reconciliation and confirmations

Proposal edits persist individual Add/Remove intent against the current member state under
the shared run/member guards. The composer retains text until a successful acknowledgement,
clears only the exact submitted draft, and permits typing the next draft while a save is pending.
Live full Rank continues to reject edits whose inputs it has already captured.

**Displayed ranking refresh:** the workspace's visible-page intake interval and focus events
reconcile a displayed ranking through the board endpoint, including scores and eligibility
changes within the same analysis. A hidden ranking receives only the lightweight analysis
check on focus. New analysis IDs keep the Reload notice; pending edits and this member's live
AI work retain ownership of their displayed state. Refresh failures preserve the last board.
Settings saves trigger free cache adoption and background application/dashboard refreshes.

**Automatic cache reuse:** the account/opening-scoped workspace adopts valid saved screening
findings and scores in the background on entry and intake/focus refresh. This does not delay
initial reads, call a provider, claim a run, or record spend. References are rechecked under a
short writer; active AI runs and finalized openings are left alone. A miss preserves the last
consumed result until explicit analysis. Readiness follows current cache coverage and pending
proposals, independently of discovery provenance or fingerprint format. Ignored criteria are not
pending proposals. Discovery-only changes leave retained scores ready; screening/scoring model,
effective reasoning, or prompt changes require a matching cache. Certified-equivalent routes
reuse valid work; AI never runs automatically.

**Confirmations:** both Rank modes use **Run ranking?**, brief action/cost copy, and the discovery
tier-retention sentence in the same paragraph. The workflow indicator owns freshness; the
confirmation adds no blanket freshness verdict or redundant coverage summary. Keep scoring missing
applicants and discovering criteria as distinct paid actions, with visible cost caps. Cache-only
Screen shows **Screening is up to date.** and a dismiss button. Active workflow buttons omit generic
staleness hover text; disabled/archived buttons explain why they are unavailable.

**Consolidation and personal history:** new analyses offer Reload. Merges preserve each member's
priorities on keys still owned by their report, including intermediate alias survivors. Existing
and first-after member views restore the same personal history and presence-gap flags, preserving
explicit acknowledgements and later Ignore choices. Personal priorities and report are read as one
snapshot. Proven reusable survivor scores are adopted atomically with report changes; incomplete
or stale survivors defer the merge. The audit distinguishes model confirmation from application.

## Users, Roles, And Authentication

Committee members may sign in with an allowlisted email magic link or identity-only Google sign-in.
Applicants may use identity-only Google sign-in, email links, or guest access. Committee access is
allowlist-based. Roles:

- `Admin`: manages committee access, shared settings, opening defaults, and administrative audit surfaces.
- `Member`: a MOMI committee screener — screens independently (own eligibility rules, overrides, tiering, ranking, notes) over the shared cached AI substrate; there is no merged comparison surface.

Every committee member is a trusted screener with access to the core Screen/Rank workflow, submitted source answers, and per-candidate AI evidence. Historical operator narratives and Observability/Evals require an administrator. Within the committee, each member's eligibility rules, overrides, tiering, and ranking are **private per member** — shared artifacts stay open to all, personal judgment does not. Admission is by an **email allowlist** whose entry role becomes the `User`'s role, and `require_admin` gates the genuinely admin-only capabilities — editing an opening's committee default, the allowlist, Admin Settings, and the Observability/Evals tabs. Adding a new entry sends that person a role-specific invitation with a magic sign-in link; changing an existing role does not. Admins persisted by the startup seed are permanent administrators: they cannot be demoted or removed, even by another admin, and removing an address from the seed file does not clear that protection. The Access subtab shows an account's name, email, role, first activity, and latest authenticated app activity. It stores only those two timestamps per user, refreshing the latest at most once every five minutes; it does not retain activity history or collect pages, IP addresses, devices, or OAuth tokens. Below it, a separate denied-attempts table aggregates unallowlisted Google login attempts by account and retains them for one year. The engineering default remains `require_current_user`; a role gate is added only for a genuinely admin-only capability, as a deliberate decision.

AI screening results are shared across users and cached per application content, model, and prompt version. Any logged-in member may run the checks; the cost concern is uncached work, not which member initiates a shared run.

### Browser request identity

Browser API work carries `X-Penta-Identity` for its captured committee user or applicant
application ID, including explicit signed-out state for applicable guest operations. The
server compares it with the credential before protected reads, writes, paid work or logout.
Committee auth state and the initial applicant application GET are deliberate bootstrap reads;
manual non-browser test clients may omit the header. API factories bind a captured request
client so queued work never inherits a later account's cookie authority. Session changes are
rechecked on focus and cross-tab signals. Committee actions pause while the old account's
unsaved private drafts remain copyable; continuing discards them only with explicit confirmation.
Applicant lifecycle refresh checks identity as well as revision and preserves browser answers.
Email-only return-link requests have no base revision and cannot save into a current cookie's
application. Credential exchanges use browser locks when available; ordinary requests remain
parallel. Only Google OAuth transitions read/write the short-lived Authlib state cookie.
Removed members retain personal history for readmission but cannot contribute rules, overrides,
kept dimensions or proposals to shared AI inputs.

Protected committee API modules expose explicit request-client factories; workspace hooks require
a captured identity provider. Applicant flow owners receive a required bound API. Public
bootstrap/email-delivery advisory calls are explicit exceptions; manual harnesses construct
their own clients. Administrative writes recheck active admin authority under the SQLite writer
before shared mutation or side-effect staging, with ordinary reads/provider I/O outside that guard.

Applicant API modules export only the public/bootstrap calls as unbound functions. Protected
operations require an explicitly constructed client for the captured applicant identity.

## Data Storage

- The application database is the source of truth for working copies, submitted applications, versions, opening participation, screening, notes, rankings, and reports.
- Production uses SQLite on a persistent volume (ADR 0012). At the expected ~5-member committee
  with light concurrency, WAL and a run lease provide sufficient serialization. The relational
  model stays portable to Postgres if real growth or an atomic shared budget later warrants it.

Core data model:

- An `Application` represents one household with a private working document and one current committee-visible submitted projection. `ApplicationVersion` preserves each dated submission; `ApplicationParticipation` links that durable applicant to selected openings.
- Primary application identity is the normalized primary applicant email plus an internal DB ID. An unauthenticated collision can never overwrite the existing working or submitted copy, and records are never automatically merged.
- Normalized fields computed on submission include ages as of the submission date, adult and child counts, household income, real-estate ownership, employment state, and other deterministic screening facts.
- **Age/cache invariant:** ages are calculated at the latest submission time and stay frozen until another submission. A birthday or calendar passage alone does not change stored ages or invalidate AI work. Resubmission recalculates ages and may cause a cache miss when evidence consumed by a pass changes, even if the answers are identical. A newer submission timestamp alone does not cause a miss. Keep display, eligibility, and AI evidence explicit about the submission-time reference; preserve valid existing caches and historical result provenance. Genuine answer, model, or prompt changes retain their existing invalidation behavior. AI work runs only through the committee's explicit analysis workflow. After resubmission, valid matching cached findings become active automatically. When fresh AI work is needed, the last consumed findings remain active until the committee runs Screen again. The amber workflow indicator communicates outdated work; individual applicants do not receive stale-result labels.
- An opening-scoped `Analysis` (one current per opening, `get_current_analysis(db, opening_id)`) holds a Rank's discovered dimensions (`dimension_report`) and the `rank_inputs_fingerprint`; its 1:1 `analysis_audit` child holds the AI-legibility trail (discovery narrative + match/fan-out/decompose/consolidate audits) so the hot read path stays lean. The committee's mutable view is **per-member** in `MemberRanking` (member × analysis: `run_state` = tiers + new/revived/requested flags + pending proposals; weights are **derived** from the tiers, never stored). Per-member eligibility overrides live in `MemberEligibility` (opening × member × applicant); a member's diverged eligibility rules live in a copy-on-write `member_rules` row over that opening's `opening_rules` default. `dimension_aliases` is the sole merge-truth. Per-run/per-pass cost lives in `run_cost_ledger` (+ a nullable `triggered_by_user_id` attributing each shared run) + `run_pass_cost`; eval runs in `eval_runs`. See [docs/app-architecture.md](docs/app-architecture.md) for the schema layout.

Settings live in the database, not `.env`, split by scope: **Admin Settings** holds global infrastructure and administration; **Eligibility Settings** holds the selected opening's `My rules` plus its admin-editable `Committee default`. Local `.env.local` holds secrets and runtime safety controls; `.env.example` holds safe placeholders. Never committed: `.env` files, OAuth credentials, SQLite DB files, applicant exports, AI traces, and raw prompts/outputs containing applicant data. Existing databases change through Alembic migrations rather than resets.

## Reports

**The report format is the browser's print-to-PDF of the ranked view.** The committee opens the ranking and clicks **Print**; the print stylesheet hides interactive chrome (`no-print`) and renders a clean artifact: the ranked shortlist with each candidate's band and rationale, plus a text **importance-tiers summary** (`TierSummaryForPrint`) so a reader sees which dimensions sat in which tier. The candidate detail page is independently printable.

Print-to-PDF needs no Docs/Drive scopes, second OAuth consent, or generated-file storage, and the document stays current because it is a live render. A Google Docs export is out of scope unless the committee needs an editable, collaboratively-commentable artifact.

## MVP Shape And Tech Stack

The MVP is a web app with a **Python/FastAPI** backend, a **Vite + React/TypeScript** frontend,
**SQLite** (SQLAlchemy + Alembic), revocable server-side sessions, SocketLabs transactional email,
optional identity-only Google authentication for applicants and committee members, and
provider-neutral AI routing across Bedrock or direct APIs. Python deps use `uv`; frontend uses
`npm`; backend tests use `pytest`.

Google setup uses only `openid`, `email`, and `profile` for optional applicant and committee
identity. It requests no Google data scope and stores no provider access or refresh token. Setup is
documented in [docs/google-cloud-oauth-setup.md](docs/google-cloud-oauth-setup.md).

The settings surfaces: **Eligibility Settings** covers the selected opening's per-member rules, with an admin-only `Committee default` subtab; **Admin Settings** covers global AI configuration, access, openings, vacancy notifications, email delivery, and feedback. Observability and Evals are separate admin-only views.

Each Admin Settings section loads its own resources. Loading or failing to load global AI
configuration affects only the Configuration section, which offers a retry; the admin section
navigation, openings, notifications, delivery, access, and feedback remain available.

Feedback carries nullable opening and retained-review context. Submission returns only an
acknowledgement; inaccessible or mismatched references are omitted without rejecting the text.
Admin applicant links and names use current ordinary/retained visibility, never private draft
identities. Contextless records do not broaden retained access.

Implementation defaults:

- Readability first; avoid redundancy; prefer elegant, boring solutions over clever abstractions.
- Shared business rules, thresholds, field mappings, prompts, and schema definitions have a single clear home.
- Abstractions are added only when they reduce real duplication or clarify an important boundary.
- Clean changes over backward compatibility for internal APIs, local schemas, fixtures, and UI shapes; backward compatibility is added only when real users or real applicant data require it.
- Relational tables for workflow data, JSON columns for raw rows, flexible payloads, AI outputs, and debug traces; the relational model stays portable to Postgres.

**Milestones 1–24 are complete** and proven end-to-end against real models (screen → discover fact-aware dimensions → score the pool → rank with tier-list weighting → print a committee-ready PDF), now with first-party application intake, vacancy notifications, optional applicant Google sign-in, and opening-specific per-member screening on a shared compute-once substrate, **hosted live at [screener.pentacoop.com](https://screener.pentacoop.com)** for the real committee. Per-milestone detail and every resolved decision/reversal are in [CHANGELOG.md](CHANGELOG.md).

## Operations and deliberate limits

Production is one Fly Machine with persistent-volume SQLite, WAL, a five-second busy timeout,
and suspend-to-zero. Each surface calls its own origin; the public website uses explicit CORS for
vacancy signup. A global database run lease serializes Screen and both Rank modes. Its 15-minute
lease is renewed every minute during provider waits and checked before guarded commits; expired
owners cannot publish over or release their successors. Full Rank blocks tier/proposal changes
whose inputs it has captured. See [deployment guidance](docs/deploy.md) and
[watchdog operations](ops/fly-watchdog/README.md).

Production deployment is an explicit `fly deploy --remote-only` operator action; pushing Git does
not release. The watchdog observes Fly's Machines API without waking the website. It restarts a
started Machine only for an explicitly critical service check, confirms host/lookup outages across
observations, persists notification/recovery state, and honours its pause switch. A single Machine
is not highly available; host loss still requires operational recovery. The archived M19 record
retains the full decision table and historical verification.

The following remain deliberate limits, not unfinished milestones:

- No combined or merged committee ranking, comparison of private rankings, automatic application
  merging, co-applicant sign-in, general-purpose form builder, or multi-tenant onboarding.
- No committee-wide spending budget or optimistic concurrency for shared AI settings; trusted-admin
  edits remain last-write-wins. Per-run caps gate expected cost, not actual provider billing.
- Reports remain browser print-to-PDF. Google Docs export, filtered-out report details, near-miss
  reports, and a separate “why not selected” feature need demonstrated committee demand.
- Criteria Coach, Evidence Auditor, and bounded model feedback loops remain optional future ideas.
- Whether administrators should review upcoming one-year purges remains an open product decision;
  there is no implemented advance warning or purge-confirmation gate.
- Frozen Google cutover forms/sheets were to remain until historical opening 1 closeout; their
  deletion is a separate operator task whose current completion has not been verified here.

Delivered milestones, migration evidence, bake-off measurements, and superseded delivery checklists
are preserved in [the completed milestone archive](docs/archive/spec-milestones.md). The current
provider catalog and configured runtime settings take precedence over historical model availability.

## Ponytail audit — November 24, 2026

**Status: implementation authorized November 24, 2026.** Jeff approved all 13 recommendations
and local commits. He also approved conservative deletion of affected pool-level narratives and
applicant-specific justifications at the first contributing applicant purge, retaining numeric
costs and demonstrably non-identifying criteria. All 13 findings are implemented and locally verified; the completion record below distinguishes
automated checks from real-provider observations and bounded Chrome verification.
The findings below preserve the pre-fix audit evidence. Application baseline:
`220a3b60c72f8438b48d3c18f8e60ec986963dc5`. All passes used unchanged application code.

**What this repo does:** Penta collects and retains housing applications, manages opening outcomes
and mail, and helps committee members screen and rank candidates using shared AI evidence and
personal priorities. Expected load is one Fly process, approximately five committee members,
300 applications, and 1,500 vacancy subscriptions. Overlapping applicant requests, committee work,
and background email/maintenance are normal; the public intake boundary must also withstand abuse.

### Passes and stopping evidence

| Pass | Perspective and result |
| --- | --- |
| 1 — user journeys | Traced guest/email/Google access, saved vs submitted answers, opening publication/decisions, notices and applicant recovery. Found unthrottled public intake, broken frontend verification, and the native income widget (4, 8, 11). |
| 2 — data transformations | Compared eligibility consumers and traced criterion identity, cache reuse, export provenance and aggregate deletion. Confirmed the three larger privacy/identity findings (1–3); the 24 list/detail comparisons and union/Screen/Rank scope checks agreed. |
| 3 — adverse sequences | Challenged partial discovery failure, a later ordinary applicant entering a synthetic analysis's opening, corrupted browser storage, leases/disconnects, selection/purge overlap and email consent generations. Added proposal loss, recovery failure and missing failure counts (5, 6, 9); strengthened finding 1 with a second reproduction. |
| 4 — simplification and contracts | Reviewed actual call sites, schema/prompt meanings, nested editor shapes, deployment/build/scripts and the watchdog. Added only smaller prompt/editor/dead-helper recommendations (10, 12, 13); no new high-impact defect. |
| 5 — request-lifetime challenge | Repeated a guest collision using a separate session for each HTTP request. Found a real rollback hidden by the existing test's shared session (7). Followed the shared mail helper through both collision consumers. |
| 6 — closing challenge | Checked every magic-link sender caller and the alternate sent/failed/coalesced branches; ordinary draft/access saves explicitly commit their suppressed-mail paths. Rechecked all findings against consumers, existing success tests and documented limits; revisited every coverage row. No further material issue remained unexamined within this bounded coverage. |

Returns diminished after the broad passes: pass 4 added only small contract/tooling cleanup,
pass 5 found one substantive transaction defect, and the focused follow-through/final challenge
added none. That late defect was followed to closure in the audit rather than ignored to meet a
stopping target. Stopping also depends on the coverage map and explicit gaps, not a finding count. This is a bounded audit, not a claim that every line or defect was found.

### Coverage and evidence

For each row, review covered correctness, failure/concurrency, supported value shapes, consumer
agreement, unnecessary work and readability. `Read` means source tracing; `Test` means existing
checks actually executed; `Probe` means a separate synthetic reproduction. Tests are not treated
as proof of model judgment, browser gestures, production state, or the absence of other bugs.
Backend paths in this table are relative to `backend/app/`.

| Area | Source and scenario coverage | Executed evidence and limits |
| --- | --- | --- |
| Applicant intake | Read `api/applicant/{guest,application,google}.py`, `services/applications/{intake,drafts,access}.py`, answer/submission schemas and frontend save/review/lifecycle/storage owners. Followed collisions, incomplete drafts, stale revisions, closed/archived choices and primary-email authority. | Test: applicant, submission, identity and copy-concurrency suites. Probe: 12 same-source unique submissions plus 12 same-address draft saves; corrupted stored record; corrected-selector copy of guest-review tests; repeated collision with separate request sessions. Found 4, 6, 7, 8, 11. No live mailbox, Google round trip or browser date-entry test. |
| Identity and authority | Read dependencies, cookie identity binding, passwordless/applicant/committee resolvers, admin writer guard, browser API factories and session refresh. Checked host-only cookie policy, active allowlist, revocation and queued-work identity capture; kept one session model. | Test: auth/passwordless, identity concurrency, admin-write authority, operator access, frontend identity/client/session tests. No live OAuth configuration or dependency-advisory check; no claim about external provider availability. |
| Openings and mail | Read catalog, participation, selection, protection, notice/audience/subscription ownership, delivery reservation/outbox/sender and admin opening workflows. Traced preparing → publication → decision, whole-consent consumption, failure/retry, current recipient and ambiguous acknowledgement. | Test: opening edit/write/selection concurrency, decision outbox, notice eligibility, email and vacancy-consent suites; frontend opening/decision tests. Reviewed acceptance-before-consumption and absence of provider I/O under the send writer. No actual messages or 1,500-recipient load run. |
| Retention and recovery | Read retention clauses, purge, result ownership, maintenance, backup service and root backup/restore wrappers. Checked Pacific expiry, legal hold/selection, WAL-safe restore, deletion bounds, allocation high-water marks and restored authority. | Test: retention transitions/purge/protection/schema, result retention, migrations, backup and maintenance suites. Probe: a purged participant's marker remains in its opening's analysis/audit prose (2). No local real DB reset/restore and no production snapshot rehearsal. |
| Eligibility and pool consistency | Read pure filters/status, per-member rules/union, list/detail presentation, opening scope, submitted facts and ranking assembly. Examined income/age/child/pet/employment/property boundaries, muted flags, an override, selection and missing-score semantics. | Probe: identical 12 synthetic households under two policies; all 24 list/detail comparisons matched, individual eligibility matched list output, union matched scoring, and pre-screen scope matched its rule union. Existing ranking/age/cache tests also passed. No claim of statistical fairness or model accuracy. |
| AI and ranking | Read cached/fresh publication, provider adapter, discovery/decomposition/matching/scoring/consolidation, selected-result references, cost meters, rank persistence/member history and run lease/stream lifetime. Checked no-priority and partial-score behavior, timeout/storage failure, aliases and tier ownership. | Test: AI/scoring/identity/tier/pool/cost/metrics, lease-renewal, cancellation and HTTP-disconnect suites; frontend ranking/run tests. Probe: same label/different definition with a model returning no match (3); seeded-worker failure/proposal clearing and zero persisted failure count (5, 8). No paid calls; prompt judgment and latency remain unmeasured. |
| Evals and observability | Read fixture export/synthetic guard, both applicant harvesters, categorical/stability/Judge collectors, history/result presentation and nested editor. Traced errors vs contested cases, attempted repetitions, local-write/admin gates, nullable values and provenance. | Test: eval completion/experiments/history/cases, stability/Judge and editor suites. Probe: non-synthetic baseline would publish nested marker prose; later non-synthetic applicant passes historical analysis guard (1); nested scalar/object/list controls and null-to-string editing (11). File write was intercepted; committed eval data was not changed. |
| Browser and operations | Read API deadlines/stream parser, request scopes, navigation, note queues, settings/board refresh, applicant persistence, print/report ownership, Docker/Fly config, backup wrappers and all three watchdog source modules. Checked acknowledgement ordering, scope changes, cancellation, watchdog restart/host/lookup recovery and pause. | Test: frontend suite/build/lint; watchdog tests/type check; backend deployment/stream/backup tests. The current workflow already uses short writes, shared helpers and bounded worker pools. No full visual/accessibility/print walkthrough, gesture test, deployed watchdog check or production load profile. |

Verification results against the unchanged baseline:

- Backend: **1,330 passed, 1 skipped**; complete Ruff check passed. The first sandboxed pytest run
  hit the established temporary-directory permissions issue; the successful run used the same
  configured directory outside the sandbox. No application failure was attributed to that run.
- Frontend: **474 passed, 2 failed** across 54 files; build passed. Lint failed on the unused
  `preview` in `OpeningsPanel.test.tsx:58`. Both failed tests stop at the obsolete date-field query
  in `ApplicantReviewAdmission.test.tsx:157`, before reaching their intended adverse sequence.
- Temporary probes: **13 frontend checks passed** in the copied guest-review/shape probes, plus
  **1 storage reproduction passed**. The copied review suite passes with label-based field lookup;
  its original file remains unchanged. Python boundary/privacy/failure and separate-request-session probes reproduced the
  documented outcomes using isolated in-memory SQLite and captured providers/mail only.
- Watchdog: **43 tests passed** and TypeScript check passed. All temporary probe files were removed.

### Must fix

1. **Exports can label ordinary applicant evidence as safe synthetic data.**
   - **What this is:** `evals/fixture.py:168` writes the baseline; `_harvest_common.py:33` trusts an
     analysis stamp before the scoring/screening harvesters read today's candidates.
   - **Problem:** Baseline recording accepts a non-synthetic analysis and retains nested prose.
     A later non-synthetic applicant can also enter an originally synthetic opening and be harvested
     under its old stamp. Both synthetic-marker probes reproduced the unsafe boundary; no real leak
     was inspected or claimed. `docs/ai-evals.md` already warns about these limits.
   - **Fix:** Enforce the synthetic boundary at every export over the actual exported inputs and
     source analysis/history; preserve provenance from the pool captured before calls, rather than
     recomputing it later. Refuse unknown/mixed evidence before publishing a file or printing cases.
   - **If we skip it:** An operator can follow the advertised harvesting/re-baseline workflow and
     put real applicant text into a Git-tracked fixture.
   - **Owner/check/cost:** `services/ranking/{pipeline,analysis}.py`, `evals/{fixture,synthetic_guard}.py`
     and both harvesters. Check non-synthetic baseline refusal, late arrival, withdrawal during
     discovery, inherited non-synthetic criterion prose and unchanged destination on refusal. Reuse
     existing provenance/guards; remove duplicate weaker assumptions. Only bounded local reads;
     no extra provider call or waiting on the applicant path.

2. **Applicant purge leaves pool-level AI text behind.**
   - **What this is:** `services/applications/purge.py:155` erases application aggregates; an opening's
     `Analysis`/`AnalysisAudit` owns separate narratives and pool justifications.
   - **Problem:** Purging a participant leaves its synthetic identifying marker in discovery
     narrative, fan-out prose and `why_it_differentiates`. These free-text fields can quote applicants;
     their lifetime is not tied to the source applicant. Hiding an opening does not erase its rows.
   - **Fix:** Include applicant-bearing pool text in the retention boundary. Prefer conservative
     cleanup by the existing opening/participation scope over a paragraph-level tracking system;
     retain only demonstrably non-identifying criterion identity and numeric expense facts.
   - **If we skip it:** The stated aggregate-deletion guarantee is incomplete even when direct
     applicant rows, credentials and per-applicant cache results disappear correctly.
   - **Owner/check/cost:** Purge/result-retention owners plus ranking audit/report persistence.
     Before implementation, agree what historical prose must be removed when source lifetimes differ.
     Seed markers in every copied/nested prose destination, purge through normal and restore paths,
     and check that unrelated retained applicants and numeric costs survive. Consolidate cleanup in
     aggregate erasure; no new live-read polling or provider cost. Historical trace detail may shrink.

3. **A fresh criterion can silently become an unrelated old criterion.**
   - **What this is:** `ai/dimension_matching.py:158` forces every shared key to self-match;
     `services/ranking/identity.py:8` then restores the prior criterion wholesale.
   - **Problem:** Fresh discovery also invents snake-case keys. Two different definitions called
     `community_skills` are therefore forced together even when the matching model explicitly
     returns no match. The probe replaced conflict-resolution skill with the older gardening skill.
   - **Fix:** Distinguish proven carried-forward keys from fresh model labels. Rename a colliding
     fresh key before matching, and reserve forced self-matches for established input identity.
     Preserve frozen wording/scores once a genuine identity match has been established.
   - **If we skip it:** New concepts disappear, and the committee sees old tiers and scores instead
     of the distinct criterion discovery found.
   - **Owner/check/cost:** Discovery/criteria/matching and key adoption; trace cache/tier/audit consumers
     together. Check same label/different meaning/no match, proven kept-key survival, equivalent
     renamed match and cached-score reuse. Replace the overbroad self-match assumption; no schema
     rewrite or automatic history rewrite. Correctly distinct criteria may require fresh scoring.

4. **Public intake can create records and send mail without a source-level limit.**
   - **What this is:** `api/applicant/guest.py:155,201,273` accepts anonymous draft, submission and
     access requests. Existing mail throttling largely follows the recipient address.
   - **Problem:** One synthetic client submitted 12 different addresses and received 12 successes
     and 12 captured confirmations; it also created 12 drafts for one address despite email coalescing.
     There is no equivalent of the public vacancy-signup source limiter on these paths.
   - **Fix:** Reuse `PublicRateLimiter` and the existing trusted ingress-key rule before anonymous
     record creation/mail staging, covering submission checks, drafts, submissions and access requests.
     Keep mailbox coalescing as well; authenticated revision saves must retain their normal behavior.
   - **If we skip it:** A single source can fill the live pool/draft store and consume the shared
     email allowance. Changing recipient addresses bypasses the present mailbox limits.
   - **Owner/check/cost:** Applicant public boundary, `services/auth/rate_limit.py` and the existing
     vacancy ingress-key owner. Check rotating addresses, repeated drafts, forged forwarding headers,
     ordinary retries and authenticated saves. Share the ingress policy rather than copy it. Constant
     in-memory work, no extra network call; use a threshold that accommodates shared household access.

5. **A failed proposal-seeded discovery worker consumes unevaluated proposals.**
   - **What this is:** Only worker 0 receives proposals (`ai/dimension_discovery.py:223`);
     `services/ranking/analysis.py:98` starts the next member view with no pending proposals.
   - **Problem:** If worker 0 fails and a blind worker succeeds, the run can publish successfully.
     The proposal guard sees no proposed axes in the surviving reports and the new view clears the
     original request. The synthetic “Conflict mediation” request vanished in this exact sequence.
   - **Fix:** Do not publish new criteria when the sole proposal-bearing worker fails. Use the
     existing failed-run path to keep the prior board/proposals; retain tolerance for blind-worker
     failures. A deliberate model decision to skip a non-varying proposal remains valid.
   - **If we skip it:** Human input looks consumed even though the model never assessed it.
   - **Owner/check/cost:** Discovery/criteria pipeline, new-analysis creation and proposal UI refresh.
     Check seeded failure with blind success, the reverse order, no proposals and valid deliberate
     omission. Remove the claim that downstream guards recover failed seed input. No automatic paid
     retry; a failed attempt retains known spend and a user may choose another run.

6. **Malformed browser recovery data can block valid server answers.**
   - **What this is:** `frontend/src/applicant/draftStorage.ts:67,217` casts parsed storage to the
     draft type; `useApplicantPersistence.ts:315` loads it before applying server answers.
   - **Problem:** Valid JSON with a current timestamp and `draft: null` throws `TypeError` in
     `loadApplicationDraft`. Nested malformed fields can also escape into rendering; parsing JSON
     successfully is not proof of a usable draft.
   - **Fix:** Treat an invalid individual remembered record as unavailable and continue restoring
     the server copy. Validate the used record's structure and clear only that captured bad record
     under the existing storage lock, preserving another tab's newer copy.
   - **If we skip it:** A returning applicant can be stuck during restoration until site data is
     cleared, despite a healthy saved application on the server.
   - **Owner/check/cost:** Browser draft storage and restore flow. Check null/missing/nested malformed
     data, invalid opening IDs/revision, valid sibling drafts and concurrent replacement, through
     actual restore. Reuse existing storage fencing; no compatibility framework or dependency.
     Local validation only; never delay server recovery on provider work.

7. **Email coalescing rolls back the latest guest collision answers.**
   - **What this is:** `api/applicant/guest.py:123` saves a comparison copy and delegates delivery
     to `services/email/transactional.py:67`. Both pre-review checks and submission collisions use it.
   - **Problem:** `send_magic_link` returns `RECENT` before committing when a prior email is still
     recent or its request quota is reached. The caller also returns/raises without committing the
     new copy, so request-session close rolls it back. With realistic per-request sessions, the
     first response was `sent`, the second `recent`, and stored answers remained the first copy.
   - **Fix:** Make the collision owner explicitly commit the preserved copy independently of whether
     another email is sent. Keep the existing mailbox coalescing and authenticate before any change
     to the applicant's saved working/submitted application.
   - **If we skip it:** Returning through the already-sent link can present older guest answers while
     the applicant believes the latest answers were preserved for comparison.
   - **Owner/check/cost:** Shared collision helper, both HTTP consumers and
     `tests/applicant/test_guest.py:171`. That existing regression shares one Session across requests
     via `tests/applicant/support.py:41`, allowing a later link-open to commit the previous request's
     pending update. Give the regression real request-session lifetimes; test sent, coalesced,
     quota-limited and failed delivery and the 409 submission path. Reuse the existing transaction;
     no extra provider call, duplicated draft store or network wait is needed.

### Should fix

8. **Frontend verification is already red.**
   - **What this is:** Guest-review admission tests and the opening-panel test fixture.
   - **Problem:** Two tests query native date controls as textboxes; lint also rejects a never-used
     `preview` fixture. The concurrency assertions are not reached by the failing tests.
   - **Fix:** Use accessible label queries for the date fields and delete the unused preview/import.
     The temporary copied review suite already passes with label lookup.
   - **If we skip it:** Routine frontend checks remain noisy and those review races lack a working test.
   - **Owner/check/cost:** `ApplicantReviewAdmission.test.tsx:157`, `OpeningsPanel.test.tsx:58`.
     Full frontend suite/lint/build must pass after repair. Delete the obsolete fixture; no runtime
     code, dependency or latency change is needed.

9. **Degraded discovery records zero failed calls.**
   - **What this is:** `ai/dimension_discovery.py:280` tracks `failed_count` separately from `PassCost`;
     criteria persistence, the run ledger and `services/metrics.py` consume the latter.
   - **Problem:** One failed worker plus one successful worker produces a visible degradation
     warning but `discovery_cost.failed_calls == 0`. The normal ledger loses that failure fact.
   - **Fix:** Carry failed worker counts into the existing pass accounting, without guessing token
     usage or billing for responses never returned. Keep successful replies and failed attempts distinct.
   - **If we skip it:** Failure trends and the warning describe different versions of the same run.
   - **Owner/check/cost:** Fan-out result accounting → criteria → ledger → metrics/UI. Test partial
     success, all-fail and all-success and inspect the persisted pass row, not only the warning.
     Consolidate counts in the existing result/cost objects; no provider call or extra hot-path query.

10. **Discovery defines a different score scale from the scorer.**
   - **What this is:** `ai/schemas.py:107,357` defines the low pole as near zero; discovery instructions
     (`ai/dimension_discovery.py:72`) still describe a 0..1 score.
   - **Problem:** Scoring and ranking use −1..+1, with zero reserved for neutral/no evidence. The
     producer of the pole definition and its consumer assign different meanings to the same zero.
     This is a confirmed contract contradiction, not a measured claim of model error frequency.
   - **Fix:** Align both dimension schemas and discovery instructions with the signed scale and
     neutral-zero rule. Keep one clear meaning for the low pole in production and eval inputs.
   - **If we skip it:** The model receives conflicting instructions at the point where criteria
     definitions become scores and committee explanations.
   - **Owner/check/cost:** Shared AI schemas, discovery/decomposition, prompt versions and eval corpus.
     Remove unsigned-scale wording; test prompt/schema consistency, then run bounded real-model
     scoring/stability checks before shipping. Prompt changes rederive versions; no new pass or
     workflow wait, though explicit rediscovery may produce different criteria.

11. **Applicant income bypasses the shared safe number control.**
    - **What this is:** `frontend/src/applicant/ApplicantFormFields.tsx:222` has a separate native
      number input; the established `NumberInput` avoids accidental wheel changes.
    - **Problem:** Income is an eligibility input on a long scrolling form, but this is the one
      production numeric entry still using the widget the project explicitly excludes. Source and
      rendering confirm it is native; its wheel gesture was not tested in a real browser here.
    - **Fix:** Use the existing shared control, preserving blank vs zero and whole-dollar validation.
    - **If we skip it:** The form retains the known risk of silently changing an income while scrolling.
    - **Owner/check/cost:** MoneyField, draft conversion, validation and guest-review tests. Check blank,
      zero, negative/fractional refusal and wheel behavior in Chrome. Delete the parallel widget;
      no dependency or request/latency change.

### Nice to have

12. **The generic case editor cannot create or restore JSON null.**
    - **What this is:** `frontend/src/components/evals/StructuredFields.tsx:9,49` supports nullable
      fixture values but renders null as empty text and offers no null field type.
    - **Problem:** Editing a null value to `2` produces the string `"2"`; clearing it produces `""`.
      The scalar/list/object probe confirmed that ordinary shapes work, but null cannot be restored
      through those controls. Missing, empty text and null can mean different things to a prompt.
    - **Fix:** If editing such a case, provide an explicit null choice through the existing scalar
      controls rather than adding a schema-driven editor. Preserve null on blank display alone.
    - **If we skip it:** Operators must edit the JSON file directly for a null-valued case.
    - **Owner/check/cost:** StructuredFields and case-save contract tests. Exercise null → text/number
      → null, including inside lists, and verify the saved JSON type. No new dependency, provider
      cost or network wait; optional ergonomics, not a production screening blocker.

13. **A published-opening helper has no production caller.**
    - **What this is:** `services/openings/catalog.py:60` duplicates a small published-opening query;
      its only function reference outside its definition is one assertion/import in
      `tests/test_preparing_openings.py`. The loader's same-named local variable is unrelated.
    - **Problem:** It preserves and tests a query contract no route or service uses.
    - **Fix:** Delete the helper and replace that one assertion with the real applicant-visible
      opening projection; preserve the rest of the protection/publication test.
    - **If we skip it:** A small amount of dead production surface remains to maintain.
    - **Owner/check/cost:** Catalog and preparing-opening tests; whole-tree reference search already
      checked imports, tests, scripts and docs. Recheck consumers, then run focused opening tests.
      About 15 production lines can go, with zero runtime/dependency cost.

### Proportionality, rejected rewrites and remaining gaps

Recommended discussion order: **export safety and retention (1–2), criterion identity (3), public
intake abuse (4), then proposal/recovery correctness (5–7)**. Restore green frontend checks (8)
before implementing frontend fixes. Accounting and scale wording (9–10) are bounded follow-ups;
11–13 are small shared-component/tooling cleanup. Implementation is complete; the findings above describe the audited baseline.

Keep the current FastAPI/SQLite/React architecture, the explicit pipeline, shared cached evidence,
short write transactions and human priorities. The audit found no justification at this load for
Postgres, a distributed job system, a new agent orchestrator, a generic provenance framework,
another numeric component, or replacing the nested editor. The 1,151-line ORM model catalog stays
cohesive as the schema map; splitting it merely to meet a line threshold would not fix these bugs.
Do not add a committee-wide budget, automatic paid retries, cross-member ranking comparison or a
new account model. Preserve the run lease, selected-result references, writer guards and synthetic
boundary rather than deleting them as apparent abstraction overhead.

Rejected suspected issues: editor typing does not invalidate captured write ownership
(`useRequestScope.invalidate` affects ordered reads, and the existing acknowledgement test passes);
unknown scores are not treated as neutral by the ranker; failed/contested eval outcomes are retained
and use distinct summary rules; per-applicant shared-result deletion already waits for the last
retained producer/consumer. None is an additional recommendation.

**Audit verdict at discovery:** the core consumer/transaction design was well defended by tests,
but privacy/export and identity gaps required correction before broad cleanup. **Lean:** about 15 production lines and
the unused preview fixture can be deleted; **0 dependencies** need adding or replacing.

**Not checked:** live provider quality/prices/terms, dependency vulnerability advisories, public
website code in the sibling repository, production mail/OAuth/Fly state, real-data load/latency,
full browser accessibility/visual/print/drag behavior, and every migration/script/stylesheet line.
Existing migration/script checks passed; that does not substitute for a production rehearsal.
These are explicit limits, not silent green checks. Only synthetic inputs were used; real local
or production applicant records were not inspected, changed, restored, emailed or exported.


### Implementation and verification closeout

Jeff authorized all findings and local commits, including conservative pool-text deletion, on
November 24, 2026. Existing application/result/cost data was preserved; the additive migration
`b69f7e31d425` adds captured source IDs and the text-purge marker. Local SQLite is verified at that
revision, with 104 applications, 21 analyses, 18,611 AI results and 79 cost runs unchanged by the
schema check/upgrade, and valid foreign keys. Production deployment remains an operator action.

| Finding | Implemented behavior and verification |
| --- | --- |
| 1 | Baseline and both actual harvest paths require captured and current synthetic inputs. Unknown/mixed history is refused; a withdrawal cannot rewrite captured assurance. Regression tests cover stale stamps, inherited unknown history, late arrivals, expired sources and unchanged destination files. |
| 2 | Source-aware purge removes whole affected audits and copied pool explanations, preserves generic criteria/retained applicants/costs, and fences late consolidation text. Normal purge, legacy scope, cross-opening inheritance and SQLite restore are covered, including a restore without the source row. |
| 3 | A fresh colliding key with different frozen meaning receives a distinct key before matching. Proven kept keys and identical frozen definitions retain identity; semantic matching may still adopt an established concept. Production criteria-path regressions cover refusal and kept identity. |
| 4 | One 30-per-15-minute anonymous quota runs before records/mail for all four public intake paths. The shared ingress helper rejects forged forwarding identities. Endpoint tests use rotating mailboxes, shared quota and saturated-quota authenticated saves. |
| 5 | Failure of a worker carrying proposals aborts criteria publication and leaves prior proposals/board intact. Blind-worker degradation remains tolerated. HTTP run tests inspect terminal events, unchanged member state and persisted known spend. |
| 6 | Remembered records are shape-checked before use; malformed copies fall back to server answers. Clearing uses the captured record and existing browser lock. Tests cover nested malformed data, invalid revision/opening IDs, valid siblings and a newer concurrent replacement. |
| 7 | The collision owner commits the latest comparison copy independently of mail delivery. Its existing repeated-collision regression now uses real per-request sessions; submission-collision and delivery-failure paths remain covered. |
| 8 | Date controls use accessible label queries and the unused preview fixture/import is deleted. Frontend suite, lint and build are green. |
| 9 | Degraded discovery carries failed workers into the pass ledger/metrics without invented usage. HTTP regressions verify failed/successful call counts for degraded completion and proposal failure. |
| 10 | Both dimension schemas and discovery instructions define −1..+1 with neutral zero. Discovery/decomposition versions include their static output schemas. Retained scores remain valid; rediscovery stays explicit. Real-provider checks exercise the revised producers and signed-score boundaries. |
| 11 | Applicant income uses the shared NumberInput. Tests preserve blank/zero and reject negative/fractional amounts at review; no native number widget remains in production entry code. |
| 12 | Existing scalar controls offer explicit null/text/number/Boolean choices; new fields and copied null list entries preserve JSON null. A nested case round-trip verifies the saved JSON, not only the displayed control. |
| 13 | The unused published_openings helper is deleted. The preparing-opening test now checks the real applicant projection and preserves its retention/publication checks. |

Automated verification: **1,356 backend tests passed, 1 skipped**, complete Ruff check passed;
**486 frontend tests passed**, frontend lint and production build passed. The watchdog code was
unchanged; its audit baseline had 43 passing tests plus a passing TypeScript check.

Real-provider evidence is preserved in
[the synthetic validation snapshot](docs/archive/ponytail-audit-validation-2026-11-24.json).
The successful direct Terra-low/Haiku run screened three fictional households, completed discovery,
decomposition, scoring and consolidation with **19 criteria, 3 scored applicants and 0 failures**,
and passed deterministic invariant checks. Rank's ledger recorded **$0.2633**; the retained full
probe including Screen recorded **$0.291312** known usage at application prices. No production
model setting was changed.

The direct Sonnet attempt timed out during decomposition at the normal 90-second idle policy;
the earlier shorter probe also timed out. The initial restricted process did not discover AWS
credentials. In the normal Windows user context the default shared-credentials-file profile resolved
and **Bedrock Haiku/Sonnet completed the full run: 24 criteria, 3 scored applicants, 0 failures**,
with **$0.4577** recorded Rank cost and **$0.577205** known probe usage including Screen and scoring
stability checks. Invariants passed. The existing bounded missing-dimension re-asks recovered one
omitted dimension for each applicant without losing returned usage or complete-vector publication.
No credential or production model configuration was changed.

Both Haiku routes measured the same two sensitive goldens over five repetitions per case: absence
confidence passed 4/5 and the modest-evidence band passed 3/5. The other four goldens were stable.
Absence scored zero every time; the high and demonstrated-negative boundaries held 5/5. The scoring
prompt and golden labels were unchanged. These observed sensitivities remain visible; neither labels
nor unrelated instructions were weakened to make a clean sweep. Provider billing without returned
usage is unknown; the evidence notes the first in-memory probe's missing durable usage receipt.

After Jeff restarted the Chrome integration, signed-in local Evals and the applicant form were
reachable. Actual applicant income controls rendered as text inputs with decimal input mode. In a
separate preview tab, the real shared components were exercised using isolated fictional state:
blank/zero/negative/fractional income validity, ArrowUp without changing 80000, number → text → null,
and copying null list entries. At desktop width the editor was 980 px wide; at a 390 px mobile
viewport it was 366 px wide, with controls contained and an 8 px label-row gap. The mobile screenshot
was visually inspected. No applicant answer or fixture was saved by those checks, and the scratch
tab was closed. Physical mouse-wheel, drag, complete application and print journeys remain outside
this verification. No dev server was started and no production deployment performed.
