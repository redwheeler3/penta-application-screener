"""Shared Pydantic bases that put the snake_case ↔ camelCase boundary in one place.

The wire contract is camelCase; our Python is snake_case. Rather than hand-alias
every field, these bases drive the conversion from one ``to_camel`` generator. Two
bases, split by direction, so the contract is *enforced*, not merely tolerated:

- ``ResponseModel`` — serializes to camelCase (``serialization_alias``). Built
  internally with snake_case field names; never validated from the wire.
- ``RequestModel`` — accepts ONLY camelCase (``validation_alias``,
  ``populate_by_name`` off), so a snake_case body is rejected. Field *access* in
  Python stays snake_case (``body.dimension_keys``); only the accepted wire key
  changes.

``BridgeModel`` is the deliberate exception (see ``AppSettings``): a model that is
both a wire shape AND reconstructed from snake_case JSON we store, so it must
accept both. Use it only when a model genuinely bridges the store and the wire —
not as a migration shortcut.

Renaming a *field* (``dimension_key`` → ``dimensionKey``) is the generator's job;
snake_case *values* (a dimension key like ``participation_commitment``, enum
values) are data and pass through untouched — which is exactly why this is typed
per-field aliasing rather than a recursive response camelizer.
"""

from pydantic import AliasGenerator, BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class ResponseModel(BaseModel):
    """Base for response bodies: snake_case in Python, camelCase on the wire."""

    model_config = ConfigDict(
        alias_generator=AliasGenerator(serialization_alias=to_camel),
    )


class RequestModel(BaseModel):
    """Base for request bodies: the wire MUST be camelCase (snake_case rejected)."""

    model_config = ConfigDict(
        alias_generator=AliasGenerator(validation_alias=to_camel),
        populate_by_name=False,
    )


class BridgeModel(BaseModel):
    """Base for a model that is both a wire shape and reconstructed from stored
    snake_case JSON, so it must accept either casing on input and emit camelCase.
    Deliberate exception — see ``AppSettings``; not a migration crutch.
    """

    model_config = ConfigDict(
        alias_generator=AliasGenerator(
            validation_alias=to_camel, serialization_alias=to_camel
        ),
        populate_by_name=True,
    )
