# Google Form Field Reference

Complete field-by-field reference for the Penta Co-operative Housing Application form. This documents field types, validation rules, and required status as configured in Google Forms.

Form ID: `1fxl3CP_DIK05I_HwTSQBQ_M7j7gNh2nCBZzl16aUTWg`

## Validation Patterns Used

- **Phone regex**: `^[2-9]\d{2}-\d{3}-\d{4}$` (North American format xxx-xxx-xxxx, no leading 0 or 1)
- **Number → Whole number**: Google Forms rejects anything that isn't a clean integer
- **Text → Email**: Google Forms validates email format
- **Date picker**: Google Forms native date input (Month, day, year)

## Section 1: Application Introduction and Consent

| Field | Type | Validation | Required |
|-------|------|-----------|----------|
| Email (form-level collection) | Email | Valid email | Yes |

The section also contains the privacy/consent declaration text and mailing list link. No other input fields.

## Section 2: Applicant and Co-applicant Details

### Applicant

| Field | Type | Validation | Required |
|-------|------|-----------|----------|
| First name | Short answer | None | Yes |
| Last name | Short answer | None | Yes |
| Age | Short answer | Number → Whole number | Yes |
| Phone number (xxx-xxx-xxxx) | Short answer | Phone regex | Yes |
| Email address | Short answer | Text → Email | Yes |

### Co-applicant (all optional)

| Field | Type | Validation | Required |
|-------|------|-----------|----------|
| First name | Short answer | None | No |
| Last name | Short answer | None | No |
| Age | Short answer | Number → Whole number | No |
| Relationship to applicant | Short answer | None | No |
| Phone number (xxx-xxx-xxxx) | Short answer | Phone regex | No |
| Email address | Short answer | Text → Email | No |

### Household

| Field | Type | Validation | Required |
|-------|------|-----------|----------|
| How many children (under 18) will be living in the unit on the move in date? | Dropdown | Options: 0, 1, 2, 3, 4, More than 4 | Yes |

The children count dropdown controls form branching. Selecting "0" or "More than 4" routes to Section 3 (ineligible).

## Section 3: Sorry (Ineligible Branch)

No input fields. Display-only rejection message. Routes to form submit (ends form).

## Section 4: Children

Four child blocks, all optional. Each block:

| Field | Type | Validation | Required |
|-------|------|-----------|----------|
| First name | Short answer | None | No |
| Last name | Short answer | None | No |
| Age | Short answer | Number → Whole number | No |

Blocks are labeled Child #1 (oldest) through Child #4 (fourth oldest).

## Section 5: Current Housing Situation

### Address

| Field | Type | Validation | Required |
|-------|------|-----------|----------|
| Street address | Short answer | None | Yes |
| Street address 2 | Short answer | None | No |
| City | Short answer | None | Yes |
| Province / State | Short answer | None | Yes |
| Postal / Zip Code | Short answer | None | Yes |
| Country | Short answer | None | Yes |

### Residency and Ownership

| Field | Type | Validation | Required |
|-------|------|-----------|----------|
| Have you lived at your current address for 2 years or more? | Multiple choice (radio) | Yes / No | Yes |
| Do you own real estate (land, house, condominium, etc.)? | Multiple choice (radio) | Yes / No | Yes |

### Current Landlord (required)

| Field | Type | Validation | Required |
|-------|------|-----------|----------|
| Current landlord name | Short answer | None | Yes |
| Current landlord email address | Short answer | Text → Email | Yes |
| Current landlord phone number (xxx-xxx-xxxx) | Short answer | Phone regex | Yes |

### Previous Landlord (optional)

| Field | Type | Validation | Required |
|-------|------|-----------|----------|
| Previous landlord name | Short answer | None | No |
| Previous landlord email address | Short answer | Text → Email | No |
| Previous landlord phone number (xxx-xxx-xxxx) | Short answer | Phone regex | No |

## Section 6: Tell Us More About You

### Required Essays

| Field | Type | Validation | Required |
|-------|------|-----------|----------|
| Please introduce yourself and your family, including your employment background, interests, and values. | Long answer | None | Yes |
| Please tell us about any skills you and the co-applicant could actively contribute to the running and maintenance of the co-op. | Long answer | None | Yes |
| Please tell us about any previous co-op experience you or the co-applicant may have. | Long answer | None | Yes |
| Describe why you want to live in a co-op and in what ways you would be a valuable member to the co-op. | Long answer | None | Yes |

### Optional Questions

| Field | Type | Validation | Required |
|-------|------|-----------|----------|
| If you have a link to a photo of yourself and the members of your household, please include it here. | Short answer | None | No |
| If you have any pets, please describe them here. | Long answer | None | No |

The pets field description states: "The Co-op has a pet policy allowing a household to own one dog and one cat, of a size and type subject to approval by the Board."

## Section 7: Employment Information

### Applicant (required)

| Field | Type | Validation | Required |
|-------|------|-----------|----------|
| Job title | Short answer | None | Yes |
| Company name | Short answer | None | Yes |
| Start date at this company | Date picker | Date format | Yes |
| Name of current manager | Short answer | None | Yes |
| Phone number (xxx-xxx-xxxx) of current manager | Short answer | Phone regex | Yes |
| Email address of current manager | Short answer | Text → Email | Yes |

### Co-applicant (optional)

| Field | Type | Validation | Required |
|-------|------|-----------|----------|
| Job title | Short answer | None | No |
| Company name | Short answer | None | No |
| Start date at this company | Date picker | Date format | No |
| Name of current manager | Short answer | None | No |
| Phone number (xxx-xxx-xxxx) of current manager | Short answer | Phone regex | No |
| Email address of current manager | Short answer | Text → Email | No |

## Section 8: Household Income

| Field | Type | Validation | Required |
|-------|------|-----------|----------|
| Total yearly gross income for applicant | Short answer | Number → Whole number | Yes |
| Total yearly gross income for co-applicant | Short answer | Number → Whole number | No |
| Total yearly gross income for your household (add up all the numbers above) | Short answer | Number → Whole number | Yes |

## Section 9: Declaration

| Field | Type | Validation | Required |
|-------|------|-----------|----------|
| Declaration | Checkbox | Single option: "I / We have read and agree to be bound by the conditions outlined above" | Yes |

## Parsing Implications for Screener

Fields used by deterministic hard filters and their parsing risk:

| Filter Input | Source Field | Parsing Risk |
|-------------|-------------|-------------|
| Adult count | Inferred from applicant/co-applicant name presence | Low — names are always present for applicant |
| Child count | Dropdown (0-4, "More than 4") | None — structured |
| Real estate ownership | Radio Yes/No | None — structured |
| Household income | Number → Whole number validated | None for new submissions; legacy data may need parse_money |
| Pets | Free text (long answer, optional) | Medium — only field requiring AI triage |

All other fields (essays, address, employment, landlord info) are not used for hard filter decisions and do not need deterministic parsing.
