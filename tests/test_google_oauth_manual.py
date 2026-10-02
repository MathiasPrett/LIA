import json

import httpx
import pytest
import respx

from lia.integrations import google_oauth_manual as oauth


@pytest.fixture
def credentials_file(tmp_path):
    path = tmp_path / "credentials.json"
    path.write_text(json.dumps({"installed": {"client_id": "cid", "client_secret": "secret"}}))
    return path


def test_start_auth_pide_refresh_token_y_ambos_scopes(credentials_file):
    url, pending = oauth.start_auth(credentials_file)
    assert "access_type=offline" in url
    assert "prompt=consent" in url
    assert "client_id=cid" in url
    assert f"state={pending.state}" in url
    assert "calendar.events" in url and "tasks" in url


def test_extract_code_desde_url_completa(credentials_file):
    _, pending = oauth.start_auth(credentials_file)
    text = f"http://localhost/?state={pending.state}&code=4/abc&scope=x"
    assert oauth.extract_code(text, pending) == "4/abc"


def test_extract_code_acepta_codigo_suelto(credentials_file):
    _, pending = oauth.start_auth(credentials_file)
    assert oauth.extract_code("4/abc", pending) == "4/abc"


def test_extract_code_rechaza_state_ajeno(credentials_file):
    _, pending = oauth.start_auth(credentials_file)
    with pytest.raises(oauth.OAuthError):
        oauth.extract_code("http://localhost/?state=otro&code=4/abc", pending)


def test_extract_code_reporta_error_de_google(credentials_file):
    _, pending = oauth.start_auth(credentials_file)
    with pytest.raises(oauth.OAuthError, match="access_denied"):
        oauth.extract_code(f"http://localhost/?state={pending.state}&error=access_denied", pending)


def test_looks_like_auth_response():
    assert oauth.looks_like_auth_response("http://localhost/?code=4/abc")
    assert oauth.looks_like_auth_response("4/abc")
    assert not oauth.looks_like_auth_response("qué tengo hoy")


@pytest.mark.asyncio
async def test_exchange_code_devuelve_credenciales(credentials_file):
    with respx.mock:
        respx.post("https://oauth2.googleapis.com/token").mock(
            return_value=httpx.Response(200, json={"access_token": "at", "refresh_token": "rt"})
        )
        creds = await oauth.exchange_code(credentials_file, "4/abc")
    assert creds.refresh_token == "rt"


@pytest.mark.asyncio
async def test_exchange_code_sin_refresh_token_falla(credentials_file):
    with respx.mock:
        respx.post("https://oauth2.googleapis.com/token").mock(
            return_value=httpx.Response(200, json={"access_token": "at"})
        )
        with pytest.raises(oauth.OAuthError, match="refresh_token"):
            await oauth.exchange_code(credentials_file, "4/abc")


@pytest.mark.asyncio
async def test_exchange_code_error_de_google(credentials_file):
    with respx.mock:
        respx.post("https://oauth2.googleapis.com/token").mock(
            return_value=httpx.Response(400, json={"error": "invalid_grant", "error_description": "Bad code"})
        )
        with pytest.raises(oauth.OAuthError, match="Bad code"):
            await oauth.exchange_code(credentials_file, "4/abc")
