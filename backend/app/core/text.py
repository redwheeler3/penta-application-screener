"""Cross-cutting text canonicalization.

One definition of "the canonical form of an email" so identity comparisons agree
everywhere it matters — application import, the access allowlist, the User record,
and the denied-sign-in log all key off the SAME normalized string. A second spelling
here is a latent identity bug (an allowlist entry that silently fails to match a user),
not just duplication.
"""

from __future__ import annotations

from typing import Any


def normalize_email(value: Any) -> str:
    """An email in its canonical comparison form: trimmed and lowercased. Accepts any
    value (spreadsheet cells may be None or non-string) and coerces to str first, so
    ``None`` becomes ``""`` rather than raising."""
    return str(value or "").strip().lower()
