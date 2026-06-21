# Test Data

The CSV in this directory contains completely synthetic application data generated for local development and testing.

It is intentionally realistic enough to exercise import logic, hard filters, search/sort behavior, and AI quality checks. Names, emails, phone numbers, addresses, employers, essays, household details, income values, and references are fictional test values and should not be treated as real applicant data.

## Identity assumptions

- **Email is the unique key for an applicant.** Every row has a distinct email address, and there will never be duplicate emails. Treat email as the stable identifier when importing or deduplicating.
- **Applicant names are not unique by guarantee.** Two distinct applicants can legitimately share the same first and last name (possible but unlikely), so name must not be used as an identity key. The current fixture happens to have all-unique names, but import logic should not depend on that.

Do not add real application exports, applicant records, AI traces, local databases, OAuth files, or other private data to this directory.
