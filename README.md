# Job Alert Bot (GitHub Actions, con comandos)

Corre por cron cada 15 minutos (gratis, sin servidor 24/7). Busca ofertas en
Indeed, revisa mail de alertas de otros portales (opcional), y responde
comandos que le escribas por Telegram — con hasta ~15 minutos de demora,
porque no queda escuchando todo el tiempo como una app 24/7.

## Comandos disponibles

- `/buscar` — busca ofertas ya mismo
- `/mail` — revisa alertas nuevas por mail
- `/agregar <palabra>` — suma una palabra clave a buscar
- `/sacar <palabra>` — excluye ofertas con esa palabra
- `/keywords` — ver palabras clave actuales
- `/excluidas` — ver palabras excluidas actuales
- `/estado` — última corrida, cuántas ofertas encontró
- `/start` o `/ayuda` — ver esta lista

## PASO 1 — Probarlo en tu compu

```bash
python -m venv venv
source venv/bin/activate        # o "activate.fish" si usás fish
pip install -r requirements.txt

export TELEGRAM_BOT_TOKEN="tu token"
export TELEGRAM_CHAT_ID="tu chat id"

python bot.py
```

Como esta versión corre una vez y termina (no queda escuchando), para probar
un comando: primero mandale el comando por Telegram (ej: `/estado`), después
corré `python bot.py` — ahí sí lo va a ver y contestar.

## PASO 2 — Subir a GitHub

```bash
git add .
git commit -m "Version GitHub Actions con comandos"
git push
```

## PASO 3 — Cargar los secrets

En tu repo: `Settings` → `Secrets and variables` → `Actions` → `New repository secret`.

Obligatorios:
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

Opcionales (solo si configuraste la revisión de mail):
- `EMAIL_ADDRESS`
- `EMAIL_APP_PASSWORD`

## PASO 4 — Probarlo ya corriendo en la nube

Pestaña **Actions** del repo → "Job Alert Bot" → botón **"Run workflow"**.
Esperá un minuto y revisá Telegram.

## Cómo persiste el estado

Este bot no tiene servidor propio, así que guarda todo en 3 archivos JSON
(`state.json`, `seen_jobs.json`, `seen_emails.json`) que el propio workflow
**commitea de vuelta al repo** al final de cada corrida (ver el paso
"Guardar el estado" en `.github/workflows/job_alert.yml`). Por eso vas a ver
commits automáticos del bot en el historial del repo — es esperado, es cómo
recuerda qué ofertas ya te mandó y qué palabras clave agregaste.

## Ajustar la frecuencia de los comandos

Si 15 minutos de demora te resulta mucho, podés bajar el intervalo del cron
en `.github/workflows/job_alert.yml` (ej: `*/5 * * * *` para cada 5 minutos).
GitHub no garantiza que corra exactamente en ese minuto —en la práctica puede
haber algunos minutos extra de atraso—, pero sí sigue siendo gratis sin
importar la frecuencia que seas uses (dentro de límites razonables).

## Ajustar qué se busca

En `bot.py`, arriba de todo:
- `SEARCHES` — qué se busca y en qué ubicación (Indeed).
- `DEFAULT_KEYWORDS` — palabras que activan el aviso.
- `DEFAULT_EXCLUDE_KEYWORDS` — palabras que descartan una oferta.
- `EMAIL_SOURCES` — dominios de mail que se reenvían por Telegram.

## Mail de alertas de otros portales (opcional)

Mismo procedimiento que antes: activá la alerta por mail en cada portal
(LinkedIn, Bumeran, Zonajobs, Computrabajo, GetOnBoard), generá una
contraseña de aplicación de Gmail en myaccount.google.com/apppasswords, y
cargá `EMAIL_ADDRESS` / `EMAIL_APP_PASSWORD` como secrets.
