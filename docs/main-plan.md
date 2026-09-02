# LIA — Bot de Telegram como secretaria personal

## Contexto

Este plan define la arquitectura, el stack, el roadmap por fases y el presupuesto de un asistente personal privado. (Nota histórica: este documento se escribió antes de que existiera código, cuando el proyecto vivía en una carpeta vacía sin repo git.)

**Problema que resuelve:** información dispersa entre Google Calendar, Canvas y correo. Hoy hay que ir a buscarla a tres lugares y nadie avisa proactivamente. LIA centraliza eso en Telegram, empuja la información en vez de esperar a que la pidas, y acepta lenguaje natural en vez de comandos.

**Restricciones duras:**
- Un solo usuario (privado). Todo lo que no sea tu `user_id` se rechaza.
- Corre 24/7 en una Raspberry Pi en casa, dockerizado, detrás de NAT (sin IP pública).
- Presupuesto de LLM: **< $1 USD/mes**.

**Decisiones ya tomadas** (respondidas por el usuario):
- LLM: **Gemini 2.5 Flash-Lite** como modelo base.
- Arquitectura IA: **tool-calling** — el LLM tiene herramientas registradas y decide cuáles llamar.
- Integraciones extra en roadmap: **Gmail + Clima + recordatorios ad-hoc**, y **notas de voz (audio → texto)**.

---

## Stack

| Capa | Elección | Por qué |
|---|---|---|
| Lenguaje | Python 3.12 (`slim`, no 3.14 — ruedas precompiladas para arm64) | Ecosistema de las APIs que necesitas |
| Bot | `python-telegram-bot` v21+ (async) | Trae `JobQueue` (APScheduler) integrado; long-polling funciona detrás de NAT sin abrir puertos |
| Scheduler | APScheduler vía `JobQueue` + `SQLAlchemyJobStore` | Los jobs sobreviven reinicios de la Pi |
| Persistencia | SQLite + SQLAlchemy 2.x | Un archivo en un volumen; suficiente para un usuario |
| Config | `pydantic-settings` + `.env` | Validación al arrancar: falla rápido si falta un token |
| LLM | `google-genai` (Gemini), detrás de una interfaz propia | Cambiar de proveedor = cambiar una variable de entorno |
| HTTP | `httpx` async | Canvas, Open-Meteo, Groq |
| Deploy | Docker + docker-compose, `linux/arm64` | Objetivo: Raspberry Pi |

**Long-polling, no webhooks.** La Pi está detrás de NAT. Los webhooks exigirían IP pública + TLS + túnel. Polling no necesita nada de eso y para un usuario el costo es irrelevante.

---

## Arquitectura

```
src/lia/
├── __main__.py              # bootstrap: config → db → integraciones → bot → scheduler
├── config.py                # pydantic-settings; valida todos los tokens al arrancar
├── db.py                    # engine + modelos SQLAlchemy
├── bot/
│   ├── app.py               # Application PTB + filtro de autorización (allowlist)
│   ├── handlers.py          # /hoy /semana /agenda, texto libre, voz, callbacks
│   └── ui.py                # teclados inline, formateo MarkdownV2
├── llm/
│   ├── base.py              # interfaz LLMProvider: .chat(messages, tools) -> respuesta|tool_calls
│   ├── gemini.py            # implementación Gemini
│   ├── registry.py          # decorador @tool: función Python → JSON schema automático
│   ├── tools.py             # las herramientas concretas
│   └── prompts.py           # system prompt + persona de LIA
├── integrations/
│   ├── google_calendar.py   # OAuth desktop flow, refresh token persistido
│   ├── gmail.py             # scope readonly
│   ├── canvas.py            # REST + token personal
│   ├── weather.py           # Open-Meteo (sin API key)
│   └── transcribe.py        # Groq Whisper para notas de voz
├── services/
│   ├── briefing.py          # resumen diario / semanal
│   ├── reminders.py         # recordatorios ad-hoc y pre-evento
│   ├── canvas_watcher.py    # polling + deduplicación
│   └── planner.py           # "organiza mi semana"
└── scheduler.py             # registro de jobs recurrentes
```

### Modelo de datos (SQLite)

| Tabla | Campos clave | Para qué |
|---|---|---|
| `seen_items` | `source`, `external_id`, `content_hash`, `first_seen_at` | Deduplicación del polling de Canvas/Gmail. **El corazón de "no me notifiques dos veces"** |
| `reminders` | `text`, `fire_at`, `status`, `source_event_id` | Recordatorios ad-hoc y pre-evento |
| `conversations` | `role`, `content`, `tool_calls`, `created_at` | Memoria de chat con ventana deslizante (últimos ~15 turnos) |
| `llm_usage` | `model`, `tokens_in`, `tokens_out`, `cost_usd`, `called_at` | Control de presupuesto — sin esto no sabes si te pasaste de $1 |
| `preferences` | `key`, `value` | Hora del resumen, umbral de "evento importante", tono |

### Tool-calling: las herramientas

El LLM recibe el schema de estas funciones y decide cuáles llamar. Las de **lectura** se ejecutan directo; las de **escritura** pasan por confirmación humana.

| Herramienta | Tipo | Nota |
|---|---|---|
| `listar_eventos(desde, hasta)` | lectura | |
| `crear_evento(titulo, inicio, fin, ...)` | **escritura** | Confirmación inline obligatoria |
| `mover_evento` / `borrar_evento` | **escritura** | Confirmación inline obligatoria |
| `buscar_huecos_libres(rango, duracion)` | lectura | Base del planificador semanal |
| `canvas_tareas_pendientes()` | lectura | |
| `canvas_novedades(desde)` | lectura | |
| `correos_importantes(desde)` | lectura | |
| `clima(fecha)` | lectura | |
| `crear_recordatorio(texto, cuando)` | escritura local | Sin confirmación: es reversible y barato |

**Regla de seguridad del agente:** ninguna herramienta de escritura sobre un sistema externo (Calendar) se ejecuta sin que muestres antes al usuario exactamente qué se va a crear, con botones `✅ Confirmar / ✏️ Editar / ❌ Cancelar`. El LLM propone; tú confirmas.

### Autenticación de cada integración

- **Telegram:** `TELEGRAM_BOT_TOKEN` de @BotFather. Allowlist con tu `user_id` numérico aplicada como filtro global — cualquier otro chat recibe silencio o un "no autorizado".
- **Google (Calendar + Tasks):** OAuth 2.0 *desktop flow*, ejecutado **una vez en tu laptop** (necesita navegador). Genera `token.json` con refresh token; ese archivo se monta en el contenedor como volumen read-only. *Una service account NO sirve* para un Google personal sin Workspace. Scopes: `calendar.events` (lectura/escritura) y `tasks` (Fase 7). Gmail quedó descartado (ver Fase 5), así que ese scope nunca se agregó.
- **Canvas:** token de acceso personal generado desde `Cuenta → Configuración → Nuevo token de acceso`. Header `Authorization: Bearer <token>`. Sin OAuth.
- **Groq (Whisper):** API key gratuita, tier gratis generoso.
- **Open-Meteo:** sin API key.

### Canvas: cómo detectar novedades

Canvas **no ofrece webhooks** para cuentas de estudiante → polling cada 15–30 min.

Endpoint principal: `GET /api/v1/users/self/activity_stream` — agrega en una sola llamada anuncios, mensajes del inbox, entregas calificadas y mensajes de conversación. Complementar con:
- `GET /api/v1/users/self/todo` — tareas por entregar
- `GET /api/v1/users/self/upcoming_events` — próximos eventos/deadlines
- `GET /api/v1/courses/:id/assignments?bucket=upcoming` — detalle por curso

Cada ítem se hashea y se guarda en `seen_items`; solo lo nuevo dispara notificación. El LLM clasifica la urgencia (`urgente` → push inmediato, `normal` → se acumula para el resumen diario) para no convertirse en spam.

---

## Roadmap iterativo

Cada fase termina en algo que **funciona y se usa**. Docker desde la Fase 0 para no descubrir problemas de arm64 al final.

### Fase 0 — Esqueleto desplegable
Estructura del proyecto, `config.py`, `db.py`, Dockerfile multi-arch, `docker-compose.yml`, bot que responde `/start` y `/ping` solo a tu `user_id`.
**Criterio de término:** el contenedor corre en la Pi y te responde `/ping`.

### Fase 1 — Calendario y resumen diario
`google_calendar.py` con OAuth, `services/briefing.py`, job diario a las 07:00, comandos `/hoy` y `/semana`. Texto plano generado por código (todavía sin LLM).
**Criterio de término:** cada mañana llega un mensaje con la agenda del día.

### Fase 2 — LLM con tool-calling
`llm/base.py` + `gemini.py` + `registry.py`, system prompt, memoria conversacional, herramientas de lectura de calendario, y `crear_evento` con confirmación inline. Contador de tokens en `llm_usage`.
**Criterio de término:** escribes "agéndame almuerzo con Javi el viernes a la 1" y aparece el evento tras confirmar. El resumen diario pasa a estar redactado por el LLM.

### Fase 3 — Canvas
Cliente Canvas, `canvas_watcher.py` con `seen_items`, job de polling, clasificación de urgencia, herramientas `canvas_*` expuestas al LLM. Canvas entra al resumen diario.
**Criterio de término:** te avisa de un anuncio nuevo sin repetirlo, y `/hoy` incluye tus entregas.

### Fase 4 — Proactividad
Resumen semanal (domingo 20:00), recordatorios pre-evento con heurística de "importante" (duración, asistentes, palabras clave, calendario de origen) ajustable por ti, y `planner.py` para "organiza mi semana" usando `buscar_huecos_libres`.
**Criterio de término:** te avisa 1h antes de algo importante y te propone un plan semanal editable.

### Fase 5 — El resto de integraciones
Open-Meteo, recordatorios ad-hoc por lenguaje natural, y notas de voz: Telegram voice → OGG → Groq Whisper → mismo pipeline que un mensaje de texto.
**Criterio de término:** le mandas un audio y hace lo que le pediste.

**Gmail: descartado** — decisión del usuario, no se retoma salvo que lo pida explícitamente (antes decía "pendiente para más adelante"; ya no es un "después", es un "no, a menos que se pida").

### Fase 6 — Endurecimiento
Healthcheck en compose + `restart: unless-stopped`, logging rotativo, backup del SQLite a cron, alerta a ti mismo si el presupuesto de tokens supera un umbral, manejo de expiración del refresh token de Google.

**Estado: código completo, pendiente de probar en la Pi real** (sin Docker en el entorno de desarrollo). Detalle de qué se implementó y por qué en `CLAUDE.md` § Estado.

### Fase 7 — Google Tasks, tipos de entrada y colores por categoría
Se agregó el scope `tasks` (Google Tasks API) junto al de Calendar en el mismo `token.json` — **requiere rehacer el OAuth una vez** (`uv run python scripts/google_auth.py` de nuevo, y recopiar `token.json` a la Pi) para que el token tenga el permiso nuevo.

El LLM ahora distingue tres tipos de cosas para guardar, cada una con su propia herramienta:
- **Evento** (`crear_evento`): horario concreto, como antes.
- **Tarea** (`crear_tarea`): pendiente sin horario fijo, va a Google Tasks (aparece en la lista de tareas de Calendar), no al calendario de eventos.
- **Cumpleaños** (`crear_cumpleanos`): entrada `eventType: birthday` de la API de Calendar — todo el día, recurrencia anual automática, forzada al calendario `primary` (restricción de la propia API de Google, no se puede elegir otro calendario).

Los eventos normales (`crear_evento`/`editar_evento`) ahora aceptan una `categoria` opcional que colorea el evento automáticamente en Calendar (`colorId`), usando la paleta fija de 11 colores de Google:
- académico → Peacock (7)
- personal → Sage (2)
- social → Tangerine (6)
- salud → Tomato (11)
- viajes → Blueberry (9)

También se agregaron, del backlog que había quedado pendiente:
- **`eliminar_evento`/`editar_evento`**: ambos requieren confirmación igual que `crear_evento`. `listar_eventos` ahora expone `id`/`calendario` de cada evento para que el LLM pueda referenciarlo. `editar_evento` es un patch parcial — solo toca los campos que el usuario pidió cambiar.
- **Ignorar curso de Canvas** (por curso completo): `ignorar_curso_canvas`, `dejar_de_ignorar_curso_canvas`, `listar_cursos_ignorados_canvas`, sin confirmación (reversible). Filtra tanto las notificaciones automáticas (`canvas_watcher`) como el tool `canvas_tareas_pendientes`.

**Estado: implementado y con tests, pendiente de probar en vivo** (necesita que el usuario rehaga el OAuth con el scope nuevo antes de que `crear_tarea`/`crear_cumpleanos` funcionen).

### Fase 8 — Finanzas personales
Registro de gastos sin fricción: el usuario cuenta lo que gastó (escrito o por nota de voz) y LIA lo persiste con monto, descripción, fecha y categoría. Después puede pedir resúmenes, fijar topes mensuales por categoría, y exportar un CSV al chat.

Decisiones que vale la pena recordar:
- **Categorías fijas** (16), no inventadas por el LLM: sin lista fija los totales dejan de sumar por variantes del mismo nombre.
- **`spent_at` en hora local de Chile**, excepción deliberada a la convención UTC del proyecto — ver `CLAUDE.md`.
- **3 tools en vez de 7**, por restricción de tokens: los schemas viajan en cada llamada al LLM. Costo final medido: **+570 tokens/llamada ≈ +$0.17/mes**, sobre los ~$0.77 previos.
- Sin confirmación inline (a diferencia del calendario): es de alta frecuencia y reversible, mismo criterio que `crear_recordatorio`. Por eso corregir/borrar el último gasto es parte del núcleo, no un extra.
- `ahorro` no cuenta como consumo (es un traspaso), así que el resumen devuelve dos totales.

**Estado: implementado y con tests, pendiente de probar en vivo.**

---

## Presupuesto del LLM

Estimación con uso realista (resumen diario, resumen semanal, ~10 mensajes de chat al día con tool-calling — que son ~2 llamadas por mensaje — y clasificación de novedades de Canvas):

**≈ 2.1M tokens de entrada + 165K de salida al mes.**

| Modelo | Precio IN/OUT (por 1M) | Costo mensual estimado | ¿Cabe en $1? |
|---|---|---|---|
| ~~Gemini 2.5 Flash-Lite~~ | $0.10 / $0.40 | ~$0.28 | **No disponible** — ver nota abajo |
| **Gemini 3.1 Flash-Lite** (modelo real en uso) | $0.25 / $1.50 | **~$0.77** | Sí, pero con poco margen |
| Gemini 3.5 Flash-Lite | $0.30 / $2.50 | ~$1.04 | No — se pasa del techo |
| DeepSeek V4 | $0.14 / $0.28 | ~$0.34 | Sí |
| Claude Haiku 4.5 | $1.00 / $5.00 | ~$2.93 | **No** |
| Claude Sonnet 5 | $3.00 / $15.00 | ~$8.80 | No |

**Actualización (27-ago-2026, verificado en vivo):** al generar la API key real, Gemini 2.5 Flash-Lite devolvió `404 NOT_FOUND — "no longer available to new users"` — Google lo sacó para keys nuevas *antes* de la fecha de retiro anunciada (16-oct-2026). El modelo en uso es **`gemini-3.1-flash-lite`** (estable, no preview), configurado en `GEMINI_MODEL`. El presupuesto de ~$0.77/mes sigue por debajo de $1, pero con bastante menos margen que la estimación original — vale la pena vigilar `llm_usage` los primeros días de uso real.

**Dos advertencias importantes:**

1. **El tier gratis de Gemini (~15 RPM, 1000–1500 req/día) te cubriría entero — pero Google usa esos datos para mejorar sus productos.** Vas a mandarle tu calendario, tus correos y tus ramos. Recomendación: **activa facturación** (tier de pago) — el costo sigue siendo bajo y tus datos quedan fuera del entrenamiento.
2. **`llm/base.py` es una interfaz y no llamadas directas** justamente por esto: migrar de modelo (como ya tuvimos que hacer) es cambiar una variable de entorno (`GEMINI_MODEL`), no reescribir código.

**Whisper (notas de voz):** Groq tiene tier gratis; en modo pago, `whisper-large-v3-turbo` ronda $0.04/hora de audio. 10 min diarios ≈ $0.20/mes.

**Total esperado: ~$0.77–$0.97/mes** (LLM + Whisper), dentro del presupuesto pero sin el margen amplio que había en la estimación original.

**Palancas de control de costo, ordenadas por impacto:**
1. Ventana deslizante de conversación (últimos ~15 turnos), no todo el historial.
2. Prompts de sistema cortos y estables; las herramientas ya llevan su descripción en el schema.
3. Nada de LLM donde basta código: formatear fechas, ordenar eventos, calcular huecos libres.
4. Cortafuegos duro: si `llm_usage` del mes supera un umbral configurable, el bot cae a modo sin-LLM y te avisa.

---

## Ideas adicionales de integración (backlog, no comprometidas)

- **Transporte:** Google Maps Directions con tráfico en vivo → "sal ahora, hay 20 min de atraso".
- **Cumpleaños/contactos:** Google People API → aviso el día anterior. *(Parcialmente cubierto en Fase 7: ya se puede guardar un cumpleaños a pedido vía `crear_cumpleanos`. Lo que falta es la parte proactiva — detectarlos automáticamente desde People API y avisar el día anterior; además, los cumpleaños son eventos de todo el día y `is_important`/`services/reminders.py` excluye a propósito los eventos de todo el día, así que ni siquiera el recordatorio pre-evento genérico los agarra hoy.)*
- **Hábitos:** tracking simple en SQLite, pregunta al final del día ("¿estudiaste hoy?"), gráfico semanal.
- **Finanzas locales:** `mindicador.cl` (UF, dólar, UTM) — gratis, sin key.
- **RSS/newsletters:** resumen de 3 bullets de tus fuentes en el brief matutino.
- **Home Assistant:** si algún día domotizas la Pi, control por lenguaje natural desde el mismo bot.
- **Modo "no molestar":** silenciar pushes según el calendario (si estás en clase o en una reunión, se acumulan).
- **Retro semanal:** cuánto de lo planificado se cumplió, comparando el plan de la semana con lo que quedó en el calendario.
- **Radar de vencimientos cruzado:** una sola vista que une Canvas + Calendar + GitHub (issues con due date) — "¿qué se me vence esta semana, en todo?" en vez de mirar tres lugares por separado.
- **Reparto de horas por deadline:** dado un conjunto de entregas próximas, sugerir cuántas horas por día conviene destinarle a cada una según lo que falta. Extensión natural de `planner.py` (Fase 4).
- **Check-in diario liviano:** a la mañana pregunta "¿en qué vas a avanzar hoy?", a la noche pregunta si se cumplió — historial simple de foco/cumplimiento (se cruza bien con la "Retro semanal" de arriba).
- **Salud de la propia infraestructura:** como el bot corre 24/7 en la Raspberry Pi, avisar si se queda sin espacio en disco, se cae el contenedor, o el refresh token de Google expira — para no descubrirlo recién cuando deja de mandar el resumen diario. Natural para la Fase 6 (Endurecimiento).
- ~~`eliminar_evento`~~ y ~~editar evento~~ — **implementados** (Fase 7): `eliminar_evento`/`editar_evento` en `llm/tools.py`, apoyados en `delete_event`/`update_event` (patch parcial) de `google_calendar.py`. `_event_to_dict` ahora expone `id` y `calendario` para que el LLM pueda referenciar un evento después de `listar_eventos`. Ambos requieren confirmación, igual que `crear_evento`.
- ~~Ignorar curso de Canvas~~ — **implementado** (Fase 7), por curso completo como estaba decidido: tabla `IgnoredCanvasCourse` en `db.py`, `services/canvas_ignore.py` (ignore/unignore/list), filtrado en `canvas_watcher.find_new_items` y en el tool `canvas_tareas_pendientes`. Tools `ignorar_curso_canvas`, `dejar_de_ignorar_curso_canvas` y `listar_cursos_ignorados_canvas`, sin confirmación (reversible).

---

## Verificación

**Por fase, antes de dar por cerrada:**
- Fase 0: `docker compose up` en la Pi; `/ping` responde. Desde otra cuenta de Telegram, el bot ignora los mensajes.
- Fase 1: `/hoy` contra un calendario con eventos de prueba, incluyendo eventos de día completo y eventos que cruzan medianoche. Adelantar el reloj del job para verificar el disparo diario.
- Fase 2: batería de frases ambiguas en español ("el próximo martes", "mañana en la tarde", "en dos semanas") verificando la fecha resuelta. Confirmar que cancelar en el teclado inline **no** crea el evento.
- Fase 3: correr el watcher dos veces seguidas y confirmar cero notificaciones duplicadas (es el bug más probable de todo el proyecto).
- Fase 5: mandar un audio real y verificar que el pipeline completo funciona.

**Transversal:**
- Tests unitarios con `pytest` + `respx` para mockear las APIs HTTP. La lógica de fechas/zonas horarias (`America/Santiago`, con cambio de hora) y la deduplicación son lo que más necesita tests.
- Prueba de resiliencia: matar el contenedor y levantarlo; los jobs programados y los recordatorios pendientes deben sobrevivir.
- Prueba de costo: tras una semana de uso real, consultar `llm_usage` y extrapolar al mes.

---

## Primeros pasos concretos

Antes de escribir código necesitas tener a mano:
1. `TELEGRAM_BOT_TOKEN` de @BotFather y tu `user_id` numérico (de @userinfobot).
2. Un proyecto en Google Cloud Console con Calendar API habilitada y credenciales OAuth de tipo *Desktop app*.
3. Token de acceso personal de Canvas y la URL base de tu institución.
4. API key de Groq (para la Fase 5).
