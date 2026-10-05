"""Content identity includes the submitted facts a cacheable pass actually consumes."""

import hashlib
import json

from app.ai.applicant_facts import facts_from_normalized, screening_fields


def input_fingerprint(raw_hash: str, normalized: dict, kind: str) -> str:
    facts = (screening_fields(normalized) if kind == "screening"
             else facts_from_normalized(normalized))
    basis = json.dumps({"raw_hash": raw_hash, "facts": facts}, sort_keys=True, default=str)
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()
