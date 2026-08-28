"""Flujo de OAuth de Google, para correr una sola vez en una máquina con navegador.

Requiere `credentials.json` (OAuth Client ID de tipo "Desktop app", descargado desde
Google Cloud Console) en la raíz del proyecto. Al terminar, deja `token.json` con el
refresh token — ese es el archivo que se monta en el contenedor de Docker.

Uso:
    uv run python scripts/google_auth.py
"""

from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

from lia.integrations.google_calendar import SCOPES

CREDENTIALS_PATH = Path("credentials.json")
TOKEN_PATH = Path("token.json")


def main() -> None:
    if not CREDENTIALS_PATH.exists():
        raise SystemExit(
            f"No se encontró {CREDENTIALS_PATH}. Descargalo desde Google Cloud Console "
            "(credenciales OAuth de tipo 'Desktop app') y dejalo en la raíz del proyecto."
        )

    flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_PATH), SCOPES)
    creds = flow.run_local_server(port=0)

    TOKEN_PATH.write_text(creds.to_json())
    print(f"Listo. Se guardó {TOKEN_PATH}.")


if __name__ == "__main__":
    main()
