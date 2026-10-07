"""Credential-free JSON contracts shared by email producers and the retry worker."""

from typing import Literal, NotRequired, TypedDict


class MagicLinkRetryIntent(TypedDict):
    type: Literal["magic_link"]
    purpose: str
    remember_device: NotRequired[bool]
    initiating_session_id: NotRequired[int | None]
    committee_invitation: NotRequired[bool]


class VacancyOpeningRetryIntent(TypedDict):
    type: Literal["vacancy_opening"]
    opening_id: int
    subscription_id: int
    # Set only when this delivery reserves that one-time consent generation.
    subscription_consented_at: NotRequired[str]


class ApplicationConfirmationRetryIntent(TypedDict):
    type: Literal["application_confirmation"]
    submitted: bool


class EmailChangeNoticeRetryIntent(TypedDict):
    type: Literal["email_change_notice"]
    old_email: str


class ApplicationUnavailableRetryIntent(TypedDict):
    type: Literal["application_unavailable"]


class SelectedApplicationRetryIntent(TypedDict):
    type: Literal["application_selected_locked"]


class UnsuccessfulApplicationRetryIntent(TypedDict):
    type: Literal["application_unsuccessful"]
    opening_labels: list[str]


class ApplicationOpeningRetryIntent(TypedDict):
    type: Literal["application_opening"]
    opening_id: int
    subscription_id: NotRequired[int]
    subscription_consented_at: NotRequired[str]


RetryIntent = (
    MagicLinkRetryIntent
    | VacancyOpeningRetryIntent
    | ApplicationConfirmationRetryIntent
    | EmailChangeNoticeRetryIntent
    | ApplicationUnavailableRetryIntent
    | SelectedApplicationRetryIntent
    | UnsuccessfulApplicationRetryIntent
    | ApplicationOpeningRetryIntent
)
