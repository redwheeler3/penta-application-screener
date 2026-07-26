from app.services.google_sheets import GOOGLE_HTTP_TIMEOUT_SECONDS, sheets_service


def test_sheets_service_uses_a_bounded_http_client(monkeypatch) -> None:
    seen: dict[str, object] = {}

    class Http:
        def __init__(self, *, timeout):
            seen["timeout"] = timeout

    class Authorized:
        def __init__(self, credentials, *, http):
            seen["credentials"] = credentials
            seen["http"] = http
            seen["authorized"] = self

    def build(*args, **kwargs):
        seen["build_args"] = args
        seen["build_kwargs"] = kwargs
        return "service"

    monkeypatch.setattr("app.services.google_sheets.httplib2.Http", Http)
    monkeypatch.setattr("app.services.google_sheets.AuthorizedHttp", Authorized)
    monkeypatch.setattr("app.services.google_sheets.build", build)
    credentials = object()

    assert sheets_service(credentials) == "service"
    assert seen["timeout"] == GOOGLE_HTTP_TIMEOUT_SECONDS
    assert seen["credentials"] is credentials
    assert seen["build_args"] == ("sheets", "v4")
    assert seen["build_kwargs"] == {"http": seen["authorized"], "cache_discovery": False}
