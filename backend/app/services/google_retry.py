import time
from collections.abc import Callable
from typing import TypeVar

from google.auth.exceptions import TransportError
from googleapiclient.errors import HttpError
from httplib2 import HttpLib2Error

Result = TypeVar("Result")

GOOGLE_RETRY_DELAY_SECONDS = 0.5
GOOGLE_REQUEST_ATTEMPTS = 2


def retry_google_request(operation: Callable[[], Result]) -> Result:
    """Retry one safe Google request after a transient transport or service failure."""
    for attempt in range(GOOGLE_REQUEST_ATTEMPTS):
        try:
            return operation()
        except (TimeoutError, TransportError, HttpLib2Error):
            if attempt == GOOGLE_REQUEST_ATTEMPTS - 1:
                raise
            time.sleep(GOOGLE_RETRY_DELAY_SECONDS)
        except HttpError as exc:
            if not _is_retryable_http_status(exc) or attempt == GOOGLE_REQUEST_ATTEMPTS - 1:
                raise
            time.sleep(GOOGLE_RETRY_DELAY_SECONDS)

    raise AssertionError("Google request retry loop exhausted without returning or raising")


def _is_retryable_http_status(error: HttpError) -> bool:
    status = error.resp.status
    return status == 429 or 500 <= status < 600
