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

Fase 6 (Endurecimiento) **verificada en vivo en la Pi** (`docker-compose`, no Docker Compose v2 — la Pi tiene Docker/buildx viejos de `apt`, ver nota abajo):
- **Error handler global** (`bot/handlers.py::error_handler`, registrado vía `app.add_error_handler`): cualquier excepción no capturada en un handler (p. ej. un 503 de Gemini, o un `CalendarNotConnected` mientras faltaba `token.json`) avisa al usuario por Telegram en vez de fallar en silencio. Confirmado en vivo en la Pi.
- **Healthcheck de Docker** (`Dockerfile`): job `_heartbeat` (cada `HEARTBEAT_INTERVAL_MINUTES`) toca `HEARTBEAT_PATH`; `HEALTHCHECK` del contenedor falla si el archivo tiene más de 3 minutos sin tocarse. Nota: Docker Compose (sin Swarm) no reinicia automáticamente un contenedor solo por estar "unhealthy" — el valor es de observabilidad (`docker ps`), no de auto-recuperación.
- **Logging rotativo**: delegado al driver `json-file` de Docker (`docker-compose.yml`, `max-size: 10m`, `max-file: 3`) en vez de manejar rotación desde Python — el bot sigue logueando a stdout.
- **Backup de SQLite** (`services/backup.py`): job `_backup_database` cada `BACKUP_INTERVAL_HOURS` usa la API `.backup()` de `sqlite3` (segura con el proceso escribiendo en simultáneo) hacia `BACKUP_DIR`, y `prune_old_backups` borra los más viejos que `BACKUP_RETENTION_DAYS`. Corrió bien en la primera ejecución en la Pi.
- **Alerta de presupuesto del LLM** (`services/budget.py` + job `_check_llm_budget`): suma `llm_usage.cost_usd` del mes en curso; si supera `LLM_BUDGET_USD * LLM_BUDGET_ALERT_THRESHOLD` avisa una sola vez por mes (dedup vía tabla `preferences`, reutilizada de antes).
- **Refresh token de Google expirado/revocado** (`integrations/google_calendar.py::load_credentials`): un `RefreshError` de `google-auth` se traduce a `CalendarNotConnected` con instrucciones claras. Además, si el refresh sí funciona pero no se puede persistir el token nuevo en disco (el `token.json` montado en Docker es de solo lectura, a propósito), se loguea un warning y se sigue con las credenciales frescas en memoria en vez de crashear — bug real encontrado en el primer deploy a la Pi.

**Gotchas del deploy real en la Pi** (Raspberry Pi OS + Docker vía `apt`, todo descubierto en el primer despliegue):
- El `Dockerfile` necesita `COPY README.md ./` antes del segundo `uv sync` — `uv_build` lo exige porque `pyproject.toml` declara `readme = "README.md"`.
- El buildx de la Pi es viejo (<0.17): hay que buildear con `DOCKER_BUILDKIT=0 docker-compose build` (el `Dockerfile` no usa sintaxis exclusiva de BuildKit, así que es seguro).
- Bind mount de `./data` con el contenedor corriendo como usuario no-root (`lia`, UID 1000): si la carpeta no existe en el host, Docker la crea como `root` y el contenedor no puede escribir ahí — hay que `sudo chown -R 1000:1000 data/` una vez.
- `scripts/deploy.sh` (nuevo) automatiza el resto del flujo: SSH a la Pi, `git pull`, rebuild y restart, ver README § Desplegar a producción.

Fase 7 (Google Tasks + tipos de entrada + colores) con código completo y tests, **pendiente de probar en vivo** — necesita que el usuario rehaga el OAuth (el scope de Google cambió):
- **Nuevo scope `tasks`** en `integrations/google_calendar.py::SCOPES`, sumado a `calendar.events`. **El `token.json` existente NO tiene este permiso** — hay que borrar `token.json`, correr `uv run python scripts/google_auth.py` de nuevo (concede ambos scopes en un solo consentimiento) y recopiar el `token.json` nuevo a la Pi, si no `crear_tarea`/`crear_cumpleanos` van a fallar con un error de permisos de Google.
- **`integrations/google_tasks.py`** (nuevo): cliente de Google Tasks API (`build("tasks", "v1", ...)`), reutiliza `load_credentials` de `google_calendar.py` (mismo token, mismo refresh). `insert_task` crea una tarea en la tasklist `@default`. La API de Tasks solo guarda la fecha del `due`, nunca la hora (aunque se le mande una, Google la descarta).
- **Tres tipos de entrada, tres tools distintas** (`llm/tools.py`, enseñado en `llm/prompts.py`): `crear_evento` (horario concreto, sin cambios de fondo), `crear_tarea` (pendiente sin horario, va a Google Tasks), `crear_cumpleanos` (usa `eventType: "birthday"` de la API de Calendar — todo el día, recurrencia anual automática, **forzado al calendario `primary`** porque la API de Google no permite crear eventos de tipo cumpleaños en otro calendario). Las tres requieren confirmación, igual que `crear_evento` ya la requería.
- **Colores por categoría**: `crear_evento` ahora acepta `categoria` opcional (`academico`, `personal`, `social`, `salud`, `viajes`), mapeada a un `colorId` de la paleta fija de 11 colores de Google Calendar (`CATEGORY_COLORS` en `google_calendar.py`). Sin categoría, el evento queda con el color por defecto del calendario.
- Nota: los cumpleaños son eventos de todo el día, y `services/reminders.py::is_important` excluye a propósito los eventos de todo el día — así que hoy no disparan el recordatorio pre-evento genérico. Queda anotado en el backlog de `docs/main-plan.md`.
- **`eliminar_evento`/`editar_evento`** (`llm/tools.py`, apoyados en `delete_event`/`update_event` de `google_calendar.py`): ambos requieren confirmación. `update_event` hace un *patch* parcial — solo manda a Google los campos que el LLM indicó que cambian, el resto queda intacto. `_event_to_dict` ahora expone `id` y `calendario` de cada evento (antes no viajaban) para que el LLM pueda referenciar un evento concreto después de un `listar_eventos`.
- ⚠️ **El SDK de `google-genai` NO reintenta por defecto.** `retry_args(None)` devuelve `stop_after_attempt(1)`, así que cada 503 de "high demand" (transitorio por definición) llegaba al usuario como error a la primera. `GeminiProvider` ahora pasa `HttpOptions(retry_options=…)` con backoff exponencial sobre **408/500/502/503/504** y sobre `httpx.ConnectError` (que cubre los cortes de DNS de la Pi). **429 queda fuera a propósito**: en un bot de un solo usuario casi nunca es "muchas peticiones por minuto" sino crédito agotado o cuota del proyecto, y reintentarlo solo agrega ~30 s de espera antes de dar el mismo error.
- ⚠️ **`gemini-2.5-flash-lite` aparece en `models.list()` pero NO se puede usar**: devuelve `404 NOT_FOUND — "no longer available to new users"`. Que un modelo esté listado no significa que la key pueda invocarlo — hay que probarlo en vivo antes de cambiar `GEMINI_MODEL`.
- **`bot/handlers.py::describe_error`**: un único traductor de errores usado por el `error_handler` global y por `confirmar_accion`. Devuelve explicación en castellano **más el código y el mensaje reales** (`🔧 Gemini 503 UNAVAILABLE …`). Antes todo mostraba el mismo texto genérico y eso ocultó tres fallas distintas en producción: 503 de Gemini, `Temporary failure in name resolution` (DNS de la Pi, nada que ver con Gemini) y `429 … prepayment credits are depleted` (crédito agotado). El 429 por crédito tiene su propio mensaje, porque la acción a tomar es recargar, no esperar.
- ⚠️ **El historial NO guarda resultados de herramientas** (`services/conversation.py::load_recent_history` devuelve solo `Conversation.content`; el `tool_calls` que se guarda no se relee). Consecuencia real, detectada en vivo: el LLM listaba eventos, resumía en prose (sin ids), y en el turno siguiente —al pedirle borrar— **inventaba UUIDs** que daban 404. Mitigado por prompt: `listar_eventos` es obligatorio *en el mismo turno* justo antes de `eliminar_evento`/`editar_evento`, nunca reusar un id de mensajes anteriores. Si algún día se quiere resolver de raíz hay que persistir los resultados de tools en el historial, pero eso cuesta tokens y choca con el presupuesto de <$1/mes.
- **`confirmar_accion` registra en el historial lo que realmente pasó** (`[Aplicado <tool>]` / `[Falló <tool>, no se aplicó nada: …]`). Antes escribía siempre `"Evento creado: …"` sin importar la herramienta, así que tras borrar un evento el historial decía que se había creado, con `None - None` en las fechas; y los fallos no quedaban registrados, por lo que un "continúa" hacía que el LLM reintentara a ciegas.
- **Ignorar curso de Canvas** (por curso completo, no por tarea puntual — Canvas no expone un id estable por assignment en el código, solo `course_name` + `title`): tabla `IgnoredCanvasCourse` en `db.py`, `services/canvas_ignore.py` (`ignore_course`/`unignore_course`/`list_ignored_courses` — tabla dedicada, no `Preference`, que es solo get/set de un valor escalar sin semántica de lista). Filtra tanto el watcher (`canvas_watcher.find_new_items`, los ítems ignorados igual se marcan como vistos para no reaparecer si se deja de ignorar el curso después) como el tool `canvas_tareas_pendientes`. Tools `ignorar_curso_canvas`, `dejar_de_ignorar_curso_canvas`, `listar_cursos_ignorados_canvas`, sin confirmación (reversible).
