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
