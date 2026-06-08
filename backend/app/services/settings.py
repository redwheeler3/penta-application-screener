from typing import Final

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import AdminSetting
from app.schemas.settings import AppSettings

APP_SETTINGS_KEY: Final = "app_settings"


def get_app_settings(db: Session) -> AppSettings:
    record = db.scalar(select(AdminSetting).where(AdminSetting.key == APP_SETTINGS_KEY))
    if record is None:
        return AppSettings()
    return AppSettings.model_validate(record.value)


def save_app_settings(db: Session, settings: AppSettings) -> AppSettings:
    record = db.scalar(select(AdminSetting).where(AdminSetting.key == APP_SETTINGS_KEY))
    payload = settings.model_dump(mode="json")

    if record is None:
        record = AdminSetting(key=APP_SETTINGS_KEY, value=payload)
        db.add(record)
    else:
        record.value = payload

    db.commit()
    return settings

