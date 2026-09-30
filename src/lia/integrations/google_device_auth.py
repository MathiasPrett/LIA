"""Reconexión de Google (Calendar/Tasks) sin SSH ni navegador en el servidor.

El script original (`scripts/google_auth.py`) usa `run_local_server()`, que abre un
puerto local y un navegador en la MISMA máquina — imposible en un servidor headless
(Render, la Pi). El flujo "OAuth para dispositivos" (RFC 8628) resuelve justo esto:
el servidor pide un código, el usuario lo confirma desde cualquier navegador (el
celular sirve perfecto) sin que el servidor necesite exponer nada.
"""

import asyncio
import json
import time
from pathlib import Path

import httpx
from google.oauth2.credentials import Credentials

from lia.integrations.google_calendar import SCOPES

_DEVICE_CODE_URL = "https://oauth2.googleapis.com/device/code"
_TOKEN_URL = "https://oauth2.googleapis.com/token"


class DeviceAuthError(Exception):
    """El usuario negó el acceso, o el código expiró antes de confirmarlo."""


def _client_config(credentials_path: Path) -> tuple[str, str]:
    raw = json.loads(credentials_path.read_text())
    data = raw.get("installed") or raw.get("web") or {}
    return data["client_id"], data["client_secret"]


async def request_device_code(credentials_path: Path) -> dict:
    client_id, _ = _client_config(credentials_path)
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            _DEVICE_CODE_URL, data={"client_id": client_id, "scope": " ".join(SCOPES)}
        )
        resp.raise_for_status()
        return resp.json()


async def poll_for_credentials(credentials_path: Path, device: dict) -> Credentials:
    """Espera la confirmación del usuario. `asyncio.sleep` entre intentos, así que
    no bloquea el resto del bot mientras espera los minutos que tarde el usuario."""
    client_id, client_secret = _client_config(credentials_path)
    interval = device.get("interval", 5)
    deadline = time.monotonic() + device.get("expires_in", 1800)

    async with httpx.AsyncClient(timeout=15) as client:
        while time.monotonic() < deadline:
            await asyncio.sleep(interval)
            resp = await client.post(
                _TOKEN_URL,
                data={
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "device_code": device["device_code"],
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                },
            )
            payload = resp.json()
            if resp.status_code == 200:
                return Credentials(
                    token=payload["access_token"],
                    refresh_token=payload.get("refresh_token"),
                    token_uri=_TOKEN_URL,
                    client_id=client_id,
                    client_secret=client_secret,
                    scopes=SCOPES,
                )
            error = payload.get("error")
            if error == "authorization_pending":
                continue
            if error == "slow_down":
                interval += 5
                continue
            raise DeviceAuthError(payload.get("error_description") or error or "error desconocido")

    raise DeviceAuthError("El código expiró antes de que confirmaras el acceso. Pide uno nuevo con /reconectar.")
