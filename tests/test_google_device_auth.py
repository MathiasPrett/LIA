import json

import httpx
import pytest

from lia.integrations import google_device_auth as auth

pytestmark = pytest.mark.asyncio


@pytest.fixture
def credentials_file(tmp_path):
    path = tmp_path / "credentials.json"
    path.write_text(json.dumps({"installed": {"client_id": "cid", "client_secret": "secret"}}))
    return path


class _FakeAsyncClient:
    def __init__(self, responses):
        self._responses = list(responses)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, data):
        status, payload = self._responses.pop(0)
        request = httpx.Request("POST", url)
        return httpx.Response(status, json=payload, request=request)


def _patch_client(monkeypatch, responses):
    monkeypatch.setattr(auth.httpx, "AsyncClient", lambda timeout=15: _FakeAsyncClient(responses))


async def test_request_device_code_returns_payload(monkeypatch, credentials_file):
    _patch_client(monkeypatch, [(200, {"device_code": "d", "user_code": "ABC-123", "interval": 0, "expires_in": 5})])
    result = await auth.request_device_code(credentials_file)
    assert result["user_code"] == "ABC-123"


async def test_poll_keeps_trying_while_pending_then_succeeds(monkeypatch, credentials_file):
    device = {"device_code": "d", "interval": 0, "expires_in": 5}
    _patch_client(
        monkeypatch,
        [
            (400, {"error": "authorization_pending"}),
            (200, {"access_token": "tok", "refresh_token": "rt"}),
        ],
    )
    creds = await auth.poll_for_credentials(credentials_file, device)
    assert creds.token == "tok"
    assert creds.refresh_token == "rt"


async def test_poll_raises_on_access_denied(monkeypatch, credentials_file):
    device = {"device_code": "d", "interval": 0, "expires_in": 5}
    _patch_client(monkeypatch, [(400, {"error": "access_denied", "error_description": "denegado"})])
    with pytest.raises(auth.DeviceAuthError, match="denegado"):
        await auth.poll_for_credentials(credentials_file, device)


async def test_poll_raises_on_timeout(monkeypatch, credentials_file):
    device = {"device_code": "d", "interval": 0, "expires_in": 0}
    _patch_client(monkeypatch, [])
    with pytest.raises(auth.DeviceAuthError, match="expiró"):
        await auth.poll_for_credentials(credentials_file, device)
