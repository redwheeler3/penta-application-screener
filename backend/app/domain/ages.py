"""Calendar-date age calculations shared by intake and screening."""

from datetime import date


def age_on(birth_date: date, on_date: date) -> int:
    before_birthday = (on_date.month, on_date.day) < (birth_date.month, birth_date.day)
    return on_date.year - birth_date.year - int(before_birthday)
