"""Response shape for the sync router."""

from app.schemas.base import ResponseModel


class SyncResponse(ResponseModel):
    """POST /sync/applications — counts from one sync run.

    A sync is an idempotent upsert-by-email reconcile (it tracks
    updated/unchanged/duplicate counts), not a one-shot load — hence "sync".
    Bare typed object (no wrapper): the result is an aggregate of one operation,
    not a stored entity the client holds onto.
    """

    id: int
    row_count: int
    duplicate_count: int
    imported_count: int
    updated_count: int
    unchanged_count: int
    eligible_count: int
    filtered_out_count: int
