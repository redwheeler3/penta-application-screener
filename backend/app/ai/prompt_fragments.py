"""Guardrail language shared across the AI prompts.

Defined once so a policy change updates every pass that embeds it — and, because a
cached pass derives its cache version from its own prompt text (see
``derive_prompt_version`` in ``analysis.py``), editing a fragment here automatically
re-runs exactly the cached passes that use it. Only genuinely cross-cutting language
lives here; a fragment specific to one pass (e.g. the facts note that describes the
fact keys) stays co-located with that pass.
"""

from __future__ import annotations

# The neutrality / anti-bias floor every pass shares. Each pass may add its own
# domain-specific clause around it (e.g. discovery forbids polish *as a dimension*).
PROTECTED_CHARACTERISTICS_NOTE = (
    "Stay neutral and evidence-based; never base a judgment on protected "
    "characteristics, family structure, or national origin."
)

# Used by every pass that reads applicants' free-text essays. Many applicants are
# not native English speakers; substance, not prose, is what the committee cares about.
ENGLISH_POLISH_NOTE = (
    "Do not penalize brief, awkward, translated, or non-native English answers for "
    "writing polish — judge the substance, not the prose."
)
