from __future__ import annotations

import io
import json
from urllib.error import HTTPError, URLError

import pytest

from cli_anything.cheat_engine.utils import udl_client


class FakeResponse:
    def __init__(self, payload, status=200):
        self.payload = json.dumps(payload).encode("utf-8")
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, _type, _value, _traceback):
        return False

    def read(self):
        return self.payload


def test_client_sends_bearer_token_and_load_path(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout):
        captured.update(request=request, timeout=timeout)
        return FakeResponse({"ok": True, "service_name": "Sample"})

    monkeypatch.setattr(udl_client, "urlopen", fake_urlopen)
    client = udl_client.UDLClient(token="secret", timeout=4.5)

    payload = client.load(r"C:\drivers\sample.sys")

    request = captured["request"]
    assert payload["ok"] is True
    assert request.full_url == "http://127.0.0.1:8765/api/load"
    assert request.method == "POST"
    assert request.get_header("Authorization") == "Bearer secret"
    assert json.loads(request.data) == {"path": r"C:\drivers\sample.sys"}
    assert captured["timeout"] == 4.5


def test_client_unload_uses_service_name_field(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout):
        captured.update(request=request, timeout=timeout)
        return FakeResponse({"ok": True})

    monkeypatch.setattr(udl_client, "urlopen", fake_urlopen)
    udl_client.UDLClient().unload("SampleService")

    assert json.loads(captured["request"].data) == {"service_name": "SampleService"}


def test_client_surfaces_api_error_payload(monkeypatch):
    def fake_urlopen(_request, timeout):
        raise HTTPError(
            "http://127.0.0.1:8765/api/load",
            400,
            "Bad Request",
            {},
            io.BytesIO(b'{"ok":false,"status":400,"error":"field path is required"}'),
        )

    monkeypatch.setattr(udl_client, "urlopen", fake_urlopen)

    with pytest.raises(udl_client.UDLAPIError, match="field path is required") as error:
        udl_client.UDLClient().load("")

    assert error.value.status == 400


def test_client_surfaces_connection_error(monkeypatch):
    monkeypatch.setattr(
        udl_client,
        "urlopen",
        lambda _request, timeout: (_ for _ in ()).throw(URLError("connection refused")),
    )

    with pytest.raises(udl_client.UDLConnectionError, match="UDL API unavailable"):
        udl_client.UDLClient().health()


@pytest.mark.parametrize(
    "url",
    [
        "http://192.168.1.10:8765",
        "https://127.0.0.1:8765",
        "http://127.0.0.1:8765/api",
    ],
)
def test_client_rejects_nonlocal_or_ambiguous_urls(url):
    with pytest.raises(ValueError):
        udl_client.UDLClient(base_url=url)


def test_launcher_environment_enables_auto_http_and_token(monkeypatch):
    monkeypatch.setenv("UDL_API_TOKEN", "old")

    environment = udl_client._launcher_environment("http://127.0.0.1:9876", "new")

    assert environment["UDL_AUTO_HTTP"] == "1"
    assert environment["UDL_API_PORT"] == "9876"
    assert environment["UDL_API_TOKEN"] == "new"
