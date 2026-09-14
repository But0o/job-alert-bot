# Job Alert Bot (GitHub Actions, con comandos)

Corre por cron cada 15 minutos (gratis, sin servidor 24/7). Busca ofertas en
Indeed, revisa mail de alertas de otros portales (opcional), y responde
comandos que le escribas por Telegram — con hasta ~15 minutos de demora,
porque no queda escuchando todo el tiempo como una app 24/7.

## Comandos disponibles

- `/buscar` — busca ofertas ya mismo (las 23 búsquedas rápidas)
- `/escaneo` — escaneo profundo: ~47 búsquedas extra generadas automáticamente + paginación (trae más volumen, tarda varios minutos)
- `/mail` — revisa alertas nuevas por mail
- `/agregar <palabra>` — suma una palabra clave a buscar
- `/sacar <palabra>` — excluye ofertas con esa palabra
- `/keywords` — ver palabras clave actuales
- `/excluidas` — ver palabras excluidas actuales
- `/estado` — última corrida, cuántas ofertas encontró
- `/start` o `/ayuda` — ver esta lista

## Cómo funciona la cobertura ampliada (búsquedas automáticas + paginación)

Para cubrir no solo ofertas nuevas sino también las ya publicadas, sin
saturar a Indeed de pedidos cada 5 minutos, el bot trabaja en dos velocidades:

1. **Búsqueda rápida** (`SEARCHES`, 23 frases escritas a mano): corre en
   *cada* ejecución del cron dentro del horario 9am-18pm ART. Es la que te
   avisa apenas aparece algo nuevo.

2. **Escaneo profundo** (`DEEP_SEARCHES_EXTRA`, generadas automáticamente
   combinando `NIVELES` × `AREAS`): corre solo 2 veces por día (9am y 18pm
   ART), y además pide varias "páginas" de resultados por búsqueda usando
   el parámetro `&start=` del RSS de Indeed (25 resultados por página).
   Esto multiplica la cobertura sin generar tráfico excesivo todo el día.

**Para agregar más variantes de búsqueda sin escribir frases a mano:**
editá las listas `NIVELES` o `AREAS` en `bot.py` — cualquier palabra que
agregues ahí se combina automáticamente con todas las demás.

**Nota sobre la paginación:** el parámetro `&start=` no es parte de una API
oficial y documentada de Indeed — es un remanente de una versión vieja de su
feed que hoy en día sigue funcionando, pero puede dejar de hacerlo sin
aviso. Si en algún momento notás que el escaneo profundo deja de traer más
resultados que antes, puede ser por eso — no significa que el bot esté roto,
simplemente Indeed le sacó soporte a ese parámetro.

**Nota sobre el volumen de pedidos:** con este diseño, el bot hace
aproximadamente ~2.700 consultas/día a Indeed en horario laboral (búsqueda
rápida) más ~280 consultas 2 veces al día (escaneo profundo). Es tráfico
considerable — si en algún momento Indeed empieza a bloquear o devolver
menos resultados de lo esperado, puede ser una señal de rate-limiting. Se
puede bajar reduciendo `DEEP_SCAN_PAGES` (menos páginas por búsqueda) o
achicando las listas `NIVELES`/`AREAS`.

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
