"""Reconexión de Google (Calendar/Tasks) sin SSH, pegando una URL en el chat.

El flujo "Desktop app" redirige a `http://localhost`, que en el celular no carga
(no hay nada escuchando) — pero la URL con el `code` queda en la barra de direcciones.
El usuario la copia y la pega al bot, que canjea el código por el token. Funciona con
cualquier scope y sin exponer nada del servidor. (El device flow de Google, RFC 8628,
no sirve: rechaza clientes "Desktop app" y no admite los scopes de Calendar/Tasks.)
"""

import json
import secrets
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import httpx
from google.oauth2.credentials import Credentials

from lia.integrations.google_calendar import SCOPES

_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN_URL = "https://oauth2.googleapis.com/token"
REDIRECT_URI = "http://localhost"
PENDING_TTL_SECONDS = 15 * 60


class OAuthError(Exception):
    """El código no se pudo canjear, o la URL pegada no sirve."""


@dataclass
class PendingAuth:
    state: str
    created_at: float = field(default_factory=time.monotonic)

    def expired(self) -> bool:
        return time.monotonic() - self.created_at > PENDING_TTL_SECONDS


def _client_config(credentials_path: Path) -> tuple[str, str]:
    raw = json.loads(credentials_path.read_text())
    data = raw.get("installed") or raw.get("web") or {}
    return data["client_id"], data["client_secret"]


def start_auth(credentials_path: Path) -> tuple[str, PendingAuth]:
    client_id, _ = _client_config(credentials_path)
    pending = PendingAuth(state=secrets.token_urlsafe(16))
    query = urlencode(
        {
            "client_id": client_id,
            "redirect_uri": REDIRECT_URI,
            "response_type": "code",
            "scope": " ".join(SCOPES),
            "access_type": "offline",
            # Sin esto Google puede no reemitir refresh_token si ya hay uno vigente.
            "prompt": "consent",
            "state": pending.state,
        }
    )
    return f"{_AUTH_URL}?{query}", pending


def looks_like_auth_response(text: str) -> bool:
    """La URL de redirección, o un código pegado a mano (siempre empiezan con `4/`)."""
    text = text.strip()
    return "code=" in text or text.startswith(("http://localhost", "4/"))


def extract_code(text: str, pending: PendingAuth) -> str:
    """Acepta la URL completa de redirección, o solo el `code` pegado a mano."""
    text = text.strip()
    if "code=" not in text and "://" not in text:
        return text
    params = parse_qs(urlparse(text).query)
    if "error" in params:
        raise OAuthError(f"Google devolvió un error: {params['error'][0]}")
    if "code" not in params:
        raise OAuthError("La URL no trae el parámetro `code`.")
    if params.get("state", [pending.state])[0] != pending.state:
        raise OAuthError("La URL es de otro intento de reconexión. Pide un enlace nuevo con /reconectar.")
    return params["code"][0]


async def exchange_code(credentials_path: Path, code: str) -> Credentials:
    client_id, client_secret = _client_config(credentials_path)
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            _TOKEN_URL,
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "code": code,
                "redirect_uri": REDIRECT_URI,
                "grant_type": "authorization_code",
            },
        )
    payload = resp.json()
    if resp.status_code != 200:
        raise OAuthError(payload.get("error_description") or payload.get("error") or "error desconocido")
    if not payload.get("refresh_token"):
        raise OAuthError(
            "Google no entregó refresh_token. Revoca el acceso de LIA en "
            "myaccount.google.com/permissions y vuelve a intentar con /reconectar."
        )
    return Credentials(
        token=payload["access_token"],
        refresh_token=payload["refresh_token"],
        token_uri=_TOKEN_URL,
        client_id=client_id,
        client_secret=client_secret,
        scopes=SCOPES,
    )
