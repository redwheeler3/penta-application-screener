# Test Data

The CSV in this directory contains completely synthetic application data generated for local development and testing. Its dotted column names mirror the built-in application schema; nested children are stored as JSON in `children_json`. The local-only loader reads this shape without coupling fixture data to form labels. Naive `submitted_at` values are interpreted as UTC.

It is intentionally realistic enough to exercise hard filters, search/sort behavior, and AI quality checks. Names, emails, phone numbers, addresses, employers, essays, household details, income values, and references are fictional test values and should not be treated as real applicant data.

The loader stamps applications from this committed fixture as synthetic. The runtime never infers that status from a filename or email domain, and production form submissions remain non-synthetic by default.

From `backend/`, after publishing a local opening and setting
`APPLICATION_DATA_IS_SYNTHETIC=true`:

```sh
uv run python -m scripts.load_synthetic_applications --opening-id 1 --opening-id 2
```

Repeat `--opening-id` to connect every fixture applicant to multiple local openings. The loader is
idempotent, sends no email, accepts SQLite only, and refuses to replace an existing application
that is not already stamped synthetic.

## Identity assumptions

- **Email is the unique key for an applicant.** Every row has a distinct email address, and there will never be duplicate emails. The loader uses the normalized primary email as its stable identifier.
- **Applicant names are not unique by guarantee.** Two distinct applicants can legitimately share the same first and last name (possible but unlikely), so name must not be used as an identity key. The current fixture happens to have all-unique names, but import logic should not depend on that.

Do not add real application exports, applicant records, AI traces, local databases, OAuth files, or other private data to this directory. The CSV is a fixture, not a production intake path.
