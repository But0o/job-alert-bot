# Job Alert Bot (Telegram)

Te avisa por Telegram cuando aparece una oferta nueva (pasantía / junior) en backend,
networking o ciberseguridad en Argentina. No postula solo — te manda el link para
que vos apretes "postularme".

## PASO 1 — Crear tu bot de Telegram (2 minutos, gratis para siempre, sin cuentas de negocio)

1. Abrí Telegram (la app, instalala si no la tenés — está en cualquier tienda de apps).
2. Buscá el usuario **@BotFather** (es el bot oficial de Telegram para crear bots).
3. Escribile `/newbot`.
4. Te va a pedir un nombre (cualquiera, ej: "Mis Alertas Laborales") y un usuario que
   termine en "bot" (ej: `martin_jobs_bot`).
5. Te va a devolver un mensaje con un **token**, algo así:
   `123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw`
   **Guardá ese token, es el `TELEGRAM_BOT_TOKEN`.**

## PASO 2 — Conseguir tu chat_id (1 minuto)

1. Buscá en Telegram tu bot recién creado (por el nombre de usuario que le pusiste)
   y mandale cualquier mensaje, por ejemplo "hola".
2. Abrí esta URL en el navegador (reemplazando `TU_TOKEN` por el token del paso 1):
   `https://api.telegram.org/botTU_TOKEN/getUpdates`
3. Vas a ver un texto con `"chat":{"id":123456789,...`
   **Ese número es tu `TELEGRAM_CHAT_ID`.**

## PASO 3 — Probarlo en tu compu

```bash
pip install -r requirements.txt

export TELEGRAM_BOT_TOKEN="8923393273:AAGjv4U_JhylAxOcJYiFX7bvINj3x1EhNY4"
export TELEGRAM_CHAT_ID=5508133021

python job_alert_bot.py
```

Si aparecen ofertas nuevas que matcheen tu perfil, te van a llegar como mensajes de
Telegram de tu propio bot. Si no aparece nada, probá correrlo de nuevo (a veces
Indeed tarda o no hay ofertas nuevas ese día — es normal, no rompiste nada).

## PASO 4 (opcional) — Que corra solo todos los días sin que prendas la compu

1. Subí esta carpeta completa a un repositorio de GitHub (puede ser privado).
2. En el repo: `Settings` → `Secrets and variables` → `Actions` → `New repository secret`.
   Cargá 2 secrets:
   - `TELEGRAM_BOT_TOKEN` (el del paso 1)
   - `TELEGRAM_CHAT_ID` (el del paso 2)
3. Listo. El archivo `.github/workflows/job_alert.yml` corre solo todos los días
   a las 9am y 18pm (hora Argentina).
4. Para probarlo manualmente sin esperar: pestaña "Actions" del repo → "Job Alert Bot"
   → botón "Run workflow".

## ¿Qué es lo único que quizás quieras tocar?

Adentro de `job_alert_bot.py`, arriba de todo, están estas 3 listas — podés editarlas
libremente, no rompés nada:

- `SEARCHES`: qué se busca y en qué ubicación.
- `KEYWORDS`: palabras que tienen que aparecer para que te llegue el aviso.
- `EXCLUDE_KEYWORDS`: palabras que descartan una oferta (ej: "senior").

Todo lo demás del archivo (las funciones) no hace falta que lo toques.

## Nota sobre las fuentes

El bot usa el feed RSS público de Indeed Argentina. LinkedIn, Bumeran, Zonajobs y
Computrabajo no ofrecen un feed público equivalente — automatizarlos violaría sus
términos de servicio y puede banearte la cuenta, así que no están incluidos. La vía
correcta ahí es crear una alerta de empleo manual en cada portal (te llega por mail).

## Sobre WhatsApp

Dejamos ese camino en pausa por la fricción de Meta (cuenta desactivada durante la
configuración, revisión pendiente). Cuando te llegue la resolución de esa revisión,
avisame y migramos este mismo bot a WhatsApp en minutos — la función ya está probada,
solo hay que volver a activarla.
