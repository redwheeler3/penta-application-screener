"""Pure intake-copy operations shared by the future applicant API and retention jobs."""

import hashlib
import json
from datetime import datetime
from typing import Any

from app.db.models import Application
from app.schemas.intake import CanonicalApplicationAnswers


def canonical_answers(answers: CanonicalApplicationAnswers) -> dict[str, Any]:
    return answers.model_dump(mode="json")


def content_hash(answers: dict[str, Any]) -> str:
    serialized = json.dumps(answers, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def save_working_copy(
    application: Application,
    answers: CanonicalApplicationAnswers,
    *,
    saved_at: datetime,
) -> None:
    stored = canonical_answers(answers)
    application.working_answers = stored
    application.working_content_hash = content_hash(stored)
    application.working_saved_at = saved_at
