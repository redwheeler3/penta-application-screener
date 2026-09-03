# Case study: the scope you don't ask for — designing auth for the light verification path

> **Historical implementation:** This case study covers the former Google Sheet intake flow.
> The current product uses first-party application intake; Google is now an optional identity
> provider only, with no access to Sheets, Drive, or the Picker API.

*A permission you never request can't scare a user, can't fail a security review, and
can't leak. Narrowing the app's Google scope from "read all your Sheets" to "the one
file an admin picks" turned a months-long restricted-scope gauntlet into an automated
branding check — and then two verification rejections taught me that a reviewer is just
a crawler that doesn't run your JavaScript.*

At this stage, the screener signed committee members in with Google and read applications from a
Google Sheet. Going from "works on my laptop with my personal Google login" to "hosted, used by
other people, and verified by Google" is where auth stops being a checkbox and becomes a design
problem. The transferable part isn't the OAuth mechanics. It's four moves:

1. **Pick the scope that changes the *verification class*, not just the permission.**
   `drive.file` vs. `spreadsheets.readonly` isn't a small security nicety — it's the
   difference between a non-sensitive scope (automated branding check) and a restricted
   one (security assessment, demo video, category eligibility).
2. **Make bad output impossible over asking a human to be careful.** The narrowest
   working scope is a structural guarantee; a broad scope with a promise to behave is
   not.
3. **A verification reviewer is a crawler that doesn't run JavaScript.** Every page
   Google needs to read — policy, home page — must be real HTML at a real URL, or it's
   invisible no matter how good the content is.
4. **When a fix "works," check whether the *original* would have worked too.** I rebuilt
   a subsystem to fix a bug whose real cause was one missing line. Shipping the rebuild
   was right; believing my diagnosis was wrong.

## Background (one paragraph)

For local development, the app used `spreadsheets.readonly` — the whole login asked for
"see all your Google Sheets." Fine when the only user is me and my manager has blessed it.
The moment I let the rest of the co-op committee in, two things broke at once: I could no
longer justify a broad Drive scope on other people's accounts, and every member would see
a scary "this app wants to read all your spreadsheets" consent screen from an unverified
app. The fix had to solve *both* the consent-screen fright and the eventual Google
verification — and ideally make verification cheap rather than a multi-week ordeal.

## Move 1 — the scope that changes the verification *class*

The instinct is to treat scope reduction as a nice-to-have: "ask for less, it's tidier."
It's much bigger than that, and the lever is a classification most people meet only when
they hit the wall.

Google sorts OAuth scopes into three buckets, and the bucket — not the app — sets the
verification burden:

- **Non-sensitive** (identity; `drive.file`, per-file access to files the user explicitly
  picks) → **basic verification**, essentially an automated branding check.
- **Sensitive** (`spreadsheets.readonly`, `drive.readonly`) → manual review, a written
  per-scope justification, and an **unlisted demo video** walking the consent flow.
- **Restricted** (`drive`, full Gmail) → all of the above **plus a third-party security
  assessment (CASA)** that can run into real money and weeks, plus app-category
  eligibility limits.

`spreadsheets.readonly` — what the app already used — is **sensitive**. `drive.file` is
**non-sensitive**. So the choice wasn't "read one sheet vs. read all sheets" as a security
detail; it was "automated check that clears in minutes vs. a manual review with a demo
video." Same feature, a whole tier of process difference, decided entirely by which scope
string you send.

That reframed the work. The design target became: *get the entire app onto non-sensitive
scopes.* Members sign in with identity only (`openid`/`email`/`profile` — all
non-sensitive). The sheet gets connected with `drive.file` through the Google Picker,
which grants access to exactly the one file an admin picks and nothing else. No scope in
the app is sensitive or restricted. The verification path collapses to branding.

## Move 2 — inert-by-default beats a careful promise

`drive.file` is stronger than "a smaller Drive scope." It's a *structural* guarantee: the
app is granted access to a specific file the user pointed at, and it is technically
incapable of reaching any other file in that Drive. Compare the alternative — hold
`drive.readonly` and promise, in a privacy policy, to only ever open the one sheet. Both
"work." Only one of them is true when nobody's watching.

This is the same principle the ranking pipeline is built on (a discovered dimension has
*weight 0* until a human tiers it, so junk is harmless by default), applied to auth: prefer
the design where the bad outcome is impossible over the one where it's merely discouraged.
A reviewer can verify a structural guarantee by reading the scope; they can't verify a
promise, which is exactly why the promise-based scopes cost more to verify.

There was a real split to honor, and `drive.file` honored it cleanly. Only *I* (an admin)
need to connect the sheet; the other members just need to sign in and sync. So members get
identity-only, and the one privileged act — linking the source file — is a separate,
admin-only Picker flow whose token becomes the designated reader for everyone's syncs. The
committee never sees a Drive consent at all.

## Move 3 — the bug I "fixed" by rebuilding the wrong thing

Here's the wrong turn, because it's the instructive part. With the Picker wired up, linking
my *original* sheet worked. The first time I tried linking a *different* sheet:
**"Couldn't read that sheet with your Google access."**

I theorized a story about token *provenance* — that a server-refreshed token had somehow
lost the authorization for a freshly-picked file — and rebuilt the whole flow around the
GIS **code model**: an interactive popup that hands back an auth code, exchanged
server-side for a token I was sure would be "properly" authorized. It worked. I was pleased.

Jeff, reasonably, asked the question that should always follow a rebuild:

> *now that we know what the problem was, are there any simplifications you would want to
> make? I'm guessing your first version would have worked, too.*

He was right, and my diagnosis was wrong. The real cause was one missing call: the Google
Picker requires **`setAppId(<cloud project number>)`** for a `drive.file`-picked file to be
authorized to the app. Without it, the picked file simply isn't granted — which presents,
misleadingly, as "couldn't read that sheet." My original token-based version would have
worked fine with that one line added. The elaborate code-model rebuild wasn't the fix; the
one line was.

I kept the rebuild (its popup UX is genuinely better and it earns a refresh token for
durable sync), so shipping it wasn't a mistake. But *believing the rebuild was what fixed
the bug* was — and it's a seductive error: a big change that makes a symptom disappear
feels like a diagnosis, even when a small change hiding inside it did the actual work. The
tell I should have heeded: I couldn't state, crisply, *why* the old version failed. When
you can't name the mechanism, you haven't found the cause — you've found a coincidence you
like.

## Move 4 — a verification reviewer is a crawler that doesn't run your JavaScript

Scopes sorted, the app deployed and members happy, I submitted for verification. It came
back with two automated failures:

> Your home page does not explain the purpose of your app.
> The app name … does not match the app name on your home page.

Both were the *same* root cause wearing two hats, and it's a cause worth internalizing: **the
things Google reads, it reads without running JavaScript.** Three surfaces got bitten by
one fact.

- The **privacy policy** lived at `pentacoop.com/#/privacy` — a hash-routed single-page app.
  Everything after `#` is a fragment the server never sees; a crawler that doesn't execute JS
  gets the empty app shell. The policy was excellent and completely invisible.
- I then pointed the home page at the **app itself**, `screener.pentacoop.com`. That's a
  React SPA that serves `<div id="root"></div>` and fills in the text at runtime — so the
  crawler saw a blank shell (no purpose explained) — *and* it's a login wall, which Google
  independently forbids as a home page ("publicly accessible, not just to logged-in users").
- The app's visible heading, had the crawler even run the JS, said "Application Screener,"
  not the consent screen's "Penta Application Screener." Name mismatch.

The fix was to stop making a crawler do work it won't do: **plain static HTML at real
URLs.** A `privacy.html`, a `terms.html`, and a dedicated `screener.html` home page — each
one real markup a crawler reads on first byte, each `<h1>` matching the consent-screen app
name character-for-character, the home page publicly reachable and describing the app. The
policy content already existed; it just had to live somewhere a non-JS fetch could see it.
Re-submitted, and the branding verified — green check, no "unverified app" warning on the
consent screen.

The transferable line: **an SPA is a promise to render, and a verification crawler doesn't
wait for promises.** Any content a machine must read to approve you — policy, home page,
ownership proof — belongs in server-delivered HTML, not behind a client-side router or a
login.

## What shipped in this iteration

Identity-only member login; an admin-only Google Picker flow (`drive.file` +
`setAppId`) that designates a sheet-reader token used for every sync; the whole app on
non-sensitive scopes. On the co-op's static site (a hash-routed SPA), standalone
`privacy.html`, `terms.html`, and `screener.html` — crawler-readable, cross-linked, names
matched. The result: Google branding verification cleared on the automated path — no
security assessment, no demo video, no category review — and members sign in through a
consent screen that shows verified branding and asks for nothing but their identity.

## The transferable core

The cheapest verification is the one your *scope choice* qualifies you for before you write
a word of justification — so choose the scope that changes the verification *class*, not
just the permission (1), and prefer the scope whose safety is structural over the one you'd
have to promise to honor (2). When a machine has to read your work to approve it, give it
real HTML, because a reviewer is a crawler and a crawler doesn't run your JavaScript (3).
And keep the discipline that a symptom disappearing is not a diagnosis: if you can't name
why the old code failed, the new code probably isn't why it works (4). The connective
thread across all four is the same one the rest of this project keeps landing on — the best
way to pass a review, human or automated, is to design so there's nothing left to argue
about: a scope that can't overreach, a page that can't be blank, a claim you don't have to
be trusted on.
