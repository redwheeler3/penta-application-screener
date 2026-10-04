from typing import Final

from sqlalchemy import func, select
from sqlalchemy.dialects.sqlite import insert
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
    payload = settings.model_dump(mode="json")
    db.execute(insert(AdminSetting).values(key=APP_SETTINGS_KEY, value=payload)
        .on_conflict_do_update(index_elements=[AdminSetting.key],
            set_={"value": payload, "updated_at": func.now()}))
    db.commit()
    return settings
