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

## Desplegar en Render

`render.yaml` ya declara el worker, el disco y las rutas. En el dashboard:

1. **New → Blueprint**, apunta al repo. Render lee `render.yaml`.
2. Rellena los secretos que pide (los marcados `sync: false`) con los valores de tu `.env`.
3. **Environment → Secret Files**: sube `token.json` con ese nombre exacto. Queda en `/etc/secrets/token.json` (solo lectura — el código ya lo maneja).
4. Deploy. De ahí en adelante, cada `git push` a `main` redespliega solo.

Para llevarte la base de datos actual en vez de partir de cero, con el servicio ya corriendo:

```bash
scp data/lia.db <servicio>@ssh.oregon.render.com:/data/lia.db   # SSH viene con el plan pago
```

## Desplegar a producción (Raspberry Pi)

Después de pushear los cambios:

```bash
git push
./scripts/deploy.sh
```

El script se conecta por SSH a la Pi, hace `git pull`, reconstruye la imagen y reinicia el contenedor. Usa `PI_HOST`/`PI_PATH` como variables de entorno si la IP o la ruta cambian (por defecto `mathias@192.168.100.251` y `~/Docker/LIA`).
