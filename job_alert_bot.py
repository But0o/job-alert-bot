#!/usr/bin/env python3
"""
job_alert_bot.py

Revisa feeds públicos de ofertas laborales (Indeed RSS), filtra por
palabras clave de tu perfil (backend / networking / ciberseguridad / junior / pasantía),
y manda un mensaje de TELEGRAM por cada oferta nueva con:
  - Puesto
  - Breve descripción / requisitos
  - Link directo a la postulación

No postula automáticamente en ningún lado. Vos hacés el último clic.

Requiere:
    pip install feedparser requests

Variables de entorno necesarias (definilas antes de correr el script) — ver README.md:
    TELEGRAM_BOT_TOKEN  -> el token que te da BotFather
    TELEGRAM_CHAT_ID    -> tu chat_id

Cómo se programa para que corra solo (elegí una opción):
    A) Cron en tu propia PC/servidor Linux (corre mientras la máquina esté prendida):
       crontab -e
       0 9,18 * * * /usr/bin/python3 /ruta/completa/job_alert_bot.py >> /ruta/completa/log.txt 2>&1

    B) GitHub Actions (corre en la nube, gratis, no depende de tu PC prendida):
       Ver el archivo .github/workflows/job_alert.yml incluido más abajo.
"""

import os
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote_plus

import feedparser
import requests

# ---------------------------------------------------------------------------
# CONFIGURACIÓN — ajustá esto a tu gusto
# ---------------------------------------------------------------------------

# Horas UTC en las que, si no hay ofertas nuevas, SÍ se manda el aviso de
# "no encontré nada". Argentina es UTC-3, así que 12 UTC = 9am ART y
# 21 UTC = 18pm ART (tienen que coincidir con el cron de job_alert.yml).
NO_JOBS_ALERT_HOURS_UTC = {12, 21}

# Búsquedas a correr. Cada tupla es (query, ubicación).
SEARCHES = [
    ("pasantia ciberseguridad", "Argentina"),
    ("pasantia backend", "Argentina"),
    ("pasantia IT", "Argentina"),
    ("pasantia desarrollo", "Argentina"),
    ("pasantia sistemas", "Argentina"),
    ("junior ciberseguridad", "Argentina"),
    ("junior backend python", "Argentina"),
    ("junior devops", "Argentina"),
    ("junior cloud security", "Argentina"),
    ("junior pentester", "Argentina"),
    ("trainee ciberseguridad", "Argentina"),
    ("trainee desarrollador", "Argentina"),
    ("practicante desarrollo", "Argentina"),
    ("analista soc junior", "Argentina"),
    ("analista ciberseguridad junior", "Argentina"),
    ("networking junior", "Argentina"),
    ("soporte tecnico linux", "Argentina"),
    ("administrador linux junior", "Argentina"),
    ("desarrollador python junior", "Argentina"),
    ("devsecops junior", "Argentina"),
]

# Palabras clave que tienen que aparecer en título o descripción para que te llegue.
# (case-insensitive, basta con que matchee una)
KEYWORDS = [
    "pasant", "junior", "jr.", "jr ", "trainee", "practicante", "primer empleo",
    "backend", "back-end", "back end", "fullstack", "full stack",
    "ciberseguridad", "cybersecurity", "seguridad informatica", "seguridad de la informacion",
    "networking", "redes", "soc", "pentest", "pentester", "red team", "blue team",
    "devsecops", "devops", "cloud security", "seguridad en la nube",
    "python", "linux", "fastapi", "sysadmin", "administrador de sistemas",
    "ethical hacking", "hacking etico", "vulnerabilidades", "ciso",
]

# Palabras que si aparecen, descartan la oferta (para filtrar ruido)
EXCLUDE_KEYWORDS = [
    "senior", "ssr.", "ssr ", "semi senior", "semi-senior", "sr.", "sr ",
    "lead ", "gerente", "manager", "director", "jefe de",
]

STATE_FILE = Path(__file__).parent / "seen_jobs.json"

# ---------------------------------------------------------------------------
# LÓGICA
# ---------------------------------------------------------------------------

def load_seen():
    if STATE_FILE.exists():
        return set(json.loads(STATE_FILE.read_text()))
    return set()


def save_seen(seen):
    STATE_FILE.write_text(json.dumps(list(seen)))


def build_rss_url(query, location):
    return f"https://ar.indeed.com/rss?q={quote_plus(query)}&l={quote_plus(location)}"


# Indeed a veces devuelve 403 a pedidos sin User-Agent de navegador.
FEED_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}


def matches_profile(title, summary):
    text = f"{title} {summary}".lower()
    if any(bad in text for bad in EXCLUDE_KEYWORDS):
        return False
    return any(kw in text for kw in KEYWORDS)


def clean_html(raw_html):
    text = re.sub(r"<[^>]+>", " ", raw_html or "")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def fetch_new_jobs(seen):
    new_jobs = []
    for query, location in SEARCHES:
        url = build_rss_url(query, location)
        feed = feedparser.parse(url, request_headers=FEED_HEADERS)
        for entry in feed.entries:
            job_id = entry.get("id") or entry.get("link")
            if job_id in seen:
                continue
            title = entry.get("title", "Puesto sin título")
            summary = clean_html(entry.get("summary", ""))
            link = entry.get("link", "")

            if not matches_profile(title, summary):
                continue

            new_jobs.append({
                "id": job_id,
                "title": title,
                "summary": summary[:280],  # recorte breve para el mensaje
                "link": link,
                "query": query,
            })
            seen.add(job_id)
        time.sleep(1)  # buena práctica, no golpear el feed muy rápido
    return new_jobs


def format_message(job):
    return (
        f"🔔 *Nueva oferta:* {job['title']}\n\n"
        f"📝 {job['summary']}\n\n"
        f"🔗 Postularme: {job['link']}"
    )


def send_telegram(body):
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    resp = requests.post(url, data={
        "chat_id": chat_id,
        "text": body,
        "parse_mode": "Markdown",
        "disable_web_page_preview": False,
    }, timeout=15)
    resp.raise_for_status()


def main():
    seen = load_seen()
    new_jobs = fetch_new_jobs(seen)

    if not new_jobs:
        print("Sin ofertas nuevas que matcheen el perfil.")
        current_hour_utc = datetime.now(timezone.utc).hour
        force_test = os.environ.get("FORCE_NO_JOBS_ALERT", "false").lower() == "true"
        if current_hour_utc in NO_JOBS_ALERT_HOURS_UTC or force_test:
            try:
                send_telegram("🔍 Revisé las búsquedas y no encontré ofertas nuevas que matcheen tu perfil.")
            except Exception as e:
                print(f"Error enviando aviso de 'sin ofertas': {e}")
        else:
            print("(No es horario de aviso de 'sin ofertas' — se manda solo a las 9am y 18pm ART)")
        return

    for job in new_jobs:
        msg = format_message(job)
        try:
            send_telegram(msg)
            print(f"Enviado: {job['title']}")
        except Exception as e:
            print(f"Error enviando '{job['title']}': {e}")
        time.sleep(1)

    save_seen(seen)


if __name__ == "__main__":
    main()