# LIA

Bot de Telegram privado (un solo usuario) que actúa como secretaria personal: resumen diario/semanal, recordatorios pre-evento y ad-hoc, gestión de Google Calendar por lenguaje natural, notificaciones de novedades de Canvas, clima, y notas de voz. Corre 24/7 en una Raspberry Pi doméstica, dockerizado, detrás de NAT.

Plan completo y roadmap por fases: [docs/main-plan.md](docs/main-plan.md). El resto de `docs/` guarda notas de diseño, quirks de APIs externas descubiertas en el camino, y skills de Claude Code específicas del proyecto.

## Restricciones duras

- **Un solo usuario.** Todo mensaje que no venga del `owner_user_id` configurado se ignora (`bot/handlers.py::OwnerFilter`).
- **Presupuesto de LLM: <$1 USD/mes.** El modelo en uso es `gemini-3.1-flash-lite` (~$0.77/mes estimado, con poco margen — ver `docs/main-plan.md` § Presupuesto). Gemini 2.5 Flash-Lite, el modelo originalmente planeado, dejó de estar disponible para API keys nuevas antes de su retiro oficial. No usar modelos más caros (Haiku 4.5+, Sonnet, Gemini 3.5 Flash-Lite) sin que el usuario lo pida explícitamente — se salen del presupuesto.
- **Raspberry Pi (arm64), sin IP pública.** Por eso el bot usa long-polling, nunca webhooks.
- **Ninguna escritura al calendario sin confirmación humana** vía teclado inline (`✅ Confirmar / ✏️ Editar / ❌ Cancelar`). El LLM propone, el usuario confirma.

## Stack y convenciones

- **Gestión de paquetes: `uv`.** `uv add <paquete>` para dependencias, `uv add --dev <paquete>` para dev, `uv run <comando>` para ejecutar dentro del entorno. No usar `pip` directo ni editar `pyproject.toml` a mano para dependencias — dejar que `uv` mantenga `uv.lock`.
- Python 3.12, `python-telegram-bot` v21+ (async), SQLite + SQLAlchemy 2.x, `pydantic-settings` para config vía `.env`.
- LLM detrás de una interfaz propia (`llm/base.py`) — nunca llamar al SDK de Gemini directo desde el resto del código. Esto es lo que permitió migrar de `gemini-2.5-flash-lite` a `gemini-3.1-flash-lite` cambiando solo una variable de entorno cuando el primero dejó de estar disponible.
- El LLM responde siempre en **español neutro latinoamericano** ("tú", nunca "vos"/"vosotros", sin modismos regionales) y en formato Markdown legado de Telegram (un solo asterisco para negrita, viñetas con "•") — ver `llm/prompts.py`. Los envíos usan `bot/ui.py` (`reply_formatted`/`send_formatted`/`edit_formatted`), que intentan `parse_mode=MARKDOWN` y caen a texto plano si el Markdown viene mal formado — nunca uses `update.message.reply_text` directo para contenido dinámico o generado por el LLM.
- Arquitectura de IA: **tool-calling**. El LLM recibe funciones registradas (`llm/tools.py`) y decide cuáles invocar; el código nunca intenta parsear intención a mano.

## Comandos útiles

```bash
uv sync                 # instalar/actualizar dependencias según uv.lock
uv run python -m lia   # correr el bot localmente
uv run pytest            # correr tests
docker compose up --build    # correr dockerizado (como en la Pi)
```

## Estado

Fases 0-3 completas y verificadas en vivo (calendario + resumen diario, LLM con tool-calling y confirmación inline, Canvas con dedup y backfill silencioso). Fase 4 (Proactividad) con código completo, parcialmente verificado en vivo:
- Resumen semanal automático domingo 20:00 (`_send_weekly_briefing`), igual que el diario: redactado por el LLM con fallback a texto plano, ahora incluye entregas de Canvas de la semana agrupadas por día.
- Recordatorios pre-evento (`services/reminders.py::is_important`): heurística por duración/asistentes/palabras clave/calendario de origen, todo configurable por `.env`. Dedup vía `seen_items` con `source="event_reminder"` (mismo patrón que Canvas). Los eventos de todo el día quedan excluidos a propósito (no tienen una hora concreta contra la cual avisar).
- `services/planner.py::find_free_slots` + tool `buscar_huecos_libres`: probado en vivo, el LLM ya usa esta tool para responder "¿cuándo tengo tiempo libre para estudiar?" con bloques reales, respetando el horario configurado (`PLANNER_DAY_START_HOUR`/`PLANNER_DAY_END_HOUR`) y bloqueando días con eventos de todo el día.
- `CalendarEvent` ahora incluye `id`, `calendar_id` y `attendees_count` (antes no se guardaban).

El resumen semanal y el chequeo de recordatorios pre-evento ya se probaron en vivo (invocando los jobs directo, sin esperar al domingo).

Fase 5 completa, **sin Gmail** (queda pendiente para más adelante por decisión del usuario — no urge). Verificado en vivo:
- `crear_recordatorio` (recordatorio ad-hoc por lenguaje natural, tabla `reminders` que ya existía desde la Fase 0): se aplica directo sin confirmación (es reversible), un job cada `ADHOC_REMINDER_POLL_INTERVAL_MINUTES` (1 min) revisa vencidos. Probado: "recuérdame llamar al dentista mañana a las 10am" guardó la hora en UTC correctamente convertida.
- `clima` (`integrations/weather.py`, Open-Meteo, sin API key) y **notas de voz** (`integrations/transcribe.py`, Groq Whisper): ambas son **opcionales** — si falta `WEATHER_LATITUDE`/`WEATHER_LONGITUDE` o `GROQ_API_KEY`, el resto del bot arranca y funciona igual; solo esa función puntual avisa que falta configurarla. Probado en vivo el degradado sin ubicación configurada (pide la ubicación en vez de inventar el clima); falta configurar coordenadas y la key de Groq para probar el camino feliz de ambas.

Fase 6 (Endurecimiento) con código completo, pendiente de probar en la Pi real (Docker no está disponible en este entorno de desarrollo):
- **Error handler global** (`bot/handlers.py::error_handler`, registrado vía `app.add_error_handler`): cualquier excepción no capturada en un handler (p. ej. un 503 de Gemini por alta demanda) ahora avisa al usuario por Telegram en vez de fallar en silencio — antes solo se logueaba y el usuario se quedaba sin respuesta. Motivado por un bug real detectado en vivo.
- **Healthcheck de Docker** (`Dockerfile`): job `_heartbeat` (cada `HEARTBEAT_INTERVAL_MINUTES`) toca `HEARTBEAT_PATH`; `HEALTHCHECK` del contenedor falla si el archivo tiene más de 3 minutos sin tocarse. Nota: Docker Compose (sin Swarm) no reinicia automáticamente un contenedor solo por estar "unhealthy" — el valor es de observabilidad (`docker ps`), no de auto-recuperación.
- **Logging rotativo**: delegado al driver `json-file` de Docker (`docker-compose.yml`, `max-size: 10m`, `max-file: 3`) en vez de manejar rotación desde Python — el bot sigue logueando a stdout.
- **Backup de SQLite** (`services/backup.py`): job `_backup_database` cada `BACKUP_INTERVAL_HOURS` usa la API `.backup()` de `sqlite3` (segura con el proceso escribiendo en simultáneo) hacia `BACKUP_DIR`, y `prune_old_backups` borra los más viejos que `BACKUP_RETENTION_DAYS`.
- **Alerta de presupuesto del LLM** (`services/budget.py` + job `_check_llm_budget`): suma `llm_usage.cost_usd` del mes en curso; si supera `LLM_BUDGET_USD * LLM_BUDGET_ALERT_THRESHOLD` avisa una sola vez por mes (dedup vía tabla `preferences`, reutilizada de antes).
- **Refresh token de Google expirado/revocado** (`integrations/google_calendar.py::load_credentials`): antes un `RefreshError` de `google-auth` se propagaba sin capturar; ahora se traduce a `CalendarNotConnected` con instrucciones claras. El scheduler (`_send_daily_briefing`/`_send_weekly_briefing`/`_check_important_events`) avisa por Telegram una sola vez cuando esto pasa (dedup vía `preferences`) y avisa de nuevo cuando se reconecta.
- Todo esto es nuevo código sin ejecución real en producción todavía — pendiente probarlo en la Pi con `docker compose up --build`.
