"""Shared value objects for transactional email composition."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ApplicationOpeningTimeline:
    unit_size: str
    close_date: str
    move_in_date: str
