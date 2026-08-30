import re
from datetime import UTC, date, datetime, timedelta

from httpx2 import AsyncClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import (
    Base,
    Opening,
)
from app.db.session import get_db
from app.services.email_sender import CapturedEmailSender, get_email_sender
from tests.app_support import shared_test_app


class FailingEmailSender:
    def send(self, _message) -> str:
        raise TimeoutError("synthetic provider timeout")


def app_and_db() -> tuple:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    test_session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = test_session()
    today = date.today()
    db.add(
        Opening(
            unit_size_bedrooms=2,
            housing_charge_cents=100_000,
            application_open_date=today - timedelta(days=1),
            application_close_date=today + timedelta(days=10),
            move_in_date=today + timedelta(days=30),
            published_at=datetime.now(UTC),
        )
    )
    db.commit()
    app = shared_test_app()
    sender = CapturedEmailSender()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_email_sender] = lambda: sender
    return app, db, sender


def sample_answers(email: str = "avery@example.com", introduction: str = "Synthetic introduction") -> dict:
    reference = {
        "name": "Synthetic Reference",
        "email": "reference@example.com",
        "phone": "(604) 555-0101",
    }
    return {
        "applicant": {
            "firstName": "Avery",
            "lastName": "Ng",
            "birthDate": "1990-04-12",
            "phone": "(604) 555-0102",
            "email": email,
        },
        "coApplicant": None,
        "children": [],
        "currentAddress": {
            "street": "123 Synthetic Street",
            "street2": None,
            "city": "Vancouver",
            "provinceOrState": "BC",
            "postalOrZipCode": "V6R 1A1",
            "country": "Canada",
        },
        "livedAtCurrentAddressTwoYears": True,
        "ownsCurrentHome": False,
        "ownsOtherRealEstate": False,
        "currentLandlord": reference,
        "previousLandlord": None,
        "essays": {
            "householdIntroduction": introduction,
            "skillsToContribute": "Synthetic maintenance and organizing skills.",
            "previousCoopExperience": "No previous co-op experience.",
            "whyCoop": "Synthetic interest in community living.",
            "additionalInformation": "Synthetic additional context.",
        },
        "pets": None,
        "householdPhotoLink": "https://example.com/synthetic-household-photo",
        "applicantEmployment": {
            "status": "employed",
            "jobTitle": "Synthetic role",
            "companyName": "Synthetic employer",
            "startDate": "2020-01-02",
            "manager": reference,
        },
        "coApplicantEmployment": None,
        "applicantIncome": 80000,
        "coApplicantIncome": None,
    }


def link_from_email(sender: CapturedEmailSender) -> str:
    match = re.search(r"#applicant-link=([^\s]+)", sender.messages[-1].text_body)
    assert match is not None
    return match.group(1)


async def save_draft(client: AsyncClient, *, email: str = "avery@example.com", intent: str = "save"):
    return await client.post(
        "/applicant/drafts",
        json={"answers": sample_answers(email), "intent": intent},
    )
