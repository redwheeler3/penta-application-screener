import tomllib
from pathlib import Path
from urllib.parse import urlparse


def test_fly_config_has_distinct_https_committee_and_applicant_origins() -> None:
    config_path = Path(__file__).resolve().parents[2] / "fly.toml"
    environment = tomllib.loads(config_path.read_text(encoding="utf-8"))["env"]

    committee = urlparse(environment["FRONTEND_URL"])
    applicant = urlparse(environment["APPLICANT_FRONTEND_URL"])

    assert committee.scheme == "https"
    assert committee.hostname == "screener.pentacoop.com"
    assert applicant.scheme == "https"
    assert applicant.hostname == "applications.pentacoop.com"
    assert applicant.geturl() != committee.geturl()
    assert environment["GOOGLE_REDIRECT_URI"].startswith(f"{committee.geturl()}/")
