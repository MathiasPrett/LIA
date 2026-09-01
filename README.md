# LIA

Bot de Telegram privado que actúa como secretaria personal. Ver [CLAUDE.md](CLAUDE.md) para el resumen del proyecto y [docs/main-plan.md](docs/main-plan.md) para el plan completo.

## Desarrollo local

```bash
cp .env.example .env   # completar TELEGRAM_BOT_TOKEN y OWNER_USER_ID
uv sync
uv run python -m lia
```

## Tests

```bash
uv run pytest
```

## Docker

```bash
docker compose up --build
```

## Desplegar a producción (Raspberry Pi)

Después de pushear los cambios:

```bash
git push
./scripts/deploy.sh
```

El script se conecta por SSH a la Pi, hace `git pull`, reconstruye la imagen y reinicia el contenedor. Usa `PI_HOST`/`PI_PATH` como variables de entorno si la IP o la ruta cambian (por defecto `mathias@192.168.100.251` y `~/Docker/LIA`).
