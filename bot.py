#!/usr/bin/env python3
"""
bot.py — versión GitHub Actions (sin servidor 24/7)

No queda escuchando todo el tiempo: corre como una tarea programada (cron).
Cada vez que se ejecuta:
  1. Revisa si llegaron comandos nuevos por Telegram desde la última corrida
     y los responde. Como no es 24/7, hay demora: si el cron corre cada 15
     minutos, en el peor caso esperás 15 minutos la respuesta a un comando.
  2. Busca ofertas nuevas en Indeed (solo en horario 9am-18pm hora Argentina).
  3. Revisa mail de alertas de otros portales, si configuraste Gmail.

Comandos disponibles (mismos que la versión anterior):
    /buscar            -> busca ofertas ya mismo
    /mail              -> revisa mail de alertas ahora
    /agregar <palabra> -> suma palabra clave
    /sacar <palabra>   -> excluye ofertas con esa palabra
    /keywords          -> ver palabras clave actuales
    /excluidas         -> ver palabras excluidas actuales
    /estado            -> última corrida, cuántas ofertas encontró
    /start /ayuda      -> lista de comandos

Requiere:
    pip install feedparser requests

Variables de entorno:
    TELEGRAM_BOT_TOKEN
    TELEGRAM_CHAT_ID
    EMAIL_ADDRESS       (opcional, para revisar mail)
    EMAIL_APP_PASSWORD  (opcional, para revisar mail)
"""

import os
import json
import re
import time
import imaplib
import email
from email.header import decode_header
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote_plus

import feedparser
import requests

# ---------------------------------------------------------------------------
# CONFIGURACIÓN BASE
# ---------------------------------------------------------------------------

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
    ("pasantia desarrollo de software", "Argentina"),
    ("trainee sistemas", "Argentina"),
    ("junior soporte tecnico", "Argentina"),
]

# ---------------------------------------------------------------------------
# BÚSQUEDA "PROFUNDA" GENERADA AUTOMÁTICAMENTE (más cobertura, pero más lenta)
#
# Combina "niveles" x "áreas" para armar muchas más variantes de búsqueda sin
# tener que escribirlas a mano. Agregar una palabra a NIVELES o AREAS genera
# automáticamente todas las combinaciones nuevas.
#
# OJO: por volumen (más consultas a Indeed + páginas adicionales por
# paginación), esto NO corre en cada ejecución del cron (cada 5 min sería
# demasiados pedidos seguidos y arriesga que Indeed bloquee el IP). Corre
# solo 2 veces por día, en las mismas horas que ya usábamos para el aviso de
# "sin ofertas" (9am y 18pm ART) — ver DEEP_SCAN_HOURS_UTC más abajo.
# ---------------------------------------------------------------------------
import itertools

NIVELES = ["pasantia", "junior", "trainee", "practicante"]

AREAS = [
    "backend", "ciberseguridad", "sistemas", "IT", "desarrollo",
    "soporte tecnico", "redes", "devops", "cloud security", "pentester",
    "python", "linux", "sysadmin", "soc", "seguridad informatica",
]

_auto_searches = [(f"{n} {a}", "Argentina") for n, a in itertools.product(NIVELES, AREAS)]

_vistos = {(q.lower(), l.lower()) for q, l in SEARCHES}
DEEP_SEARCHES_EXTRA = [
    (q, l) for q, l in _auto_searches if (q.lower(), l.lower()) not in _vistos
]

# Cuántas "páginas" adicionales de 25 resultados pedir por búsqueda en el
# escaneo profundo (0 = solo la primera tanda, sin paginación extra).
DEEP_SCAN_PAGES = 2

DEEP_SCAN_HOURS_UTC = {12, 21}  # 9am y 18pm hora Argentina


DEFAULT_KEYWORDS = [
    "pasant", "junior", "jr.", "jr ", "trainee", "practicante", "primer empleo",
    "backend", "back-end", "back end", "fullstack", "full stack",
    "ciberseguridad", "cybersecurity", "seguridad informatica", "seguridad de la informacion",
    "networking", "redes", "soc", "pentest", "pentester", "red team", "blue team",
    "devsecops", "devops", "cloud security", "seguridad en la nube",
    "python", "linux", "fastapi", "sysadmin", "administrador de sistemas",
    "ethical hacking", "hacking etico", "vulnerabilidades", "ciso",
]

DEFAULT_EXCLUDE_KEYWORDS = [
    "senior", "ssr.", "ssr ", "semi senior", "semi-senior", "sr.", "sr ",
    "lead ", "gerente", "manager", "director", "jefe de",
]

# Horas UTC en las que corre la búsqueda. Argentina es UTC-3, así que esto
# corresponde a 9am-18pm hora Argentina.
SCHEDULED_HOURS_UTC = set(range(12, 22))  # 12..21 inclusive

EMAIL_SOURCES = {
    "linkedin.com": "LinkedIn",
    "bumeran.com.ar": "Bumeran",
    "zonajobs.com.ar": "Zonajobs",
    "computrabajo.com": "Computrabajo",
    "computrabajo.com.ar": "Computrabajo",
    "getonbrd.com": "GetOnBoard",
}

STATE_FILE = Path(__file__).parent / "state.json"
SEEN_FILE = Path(__file__).parent / "seen_jobs.json"
SEEN_EMAILS_FILE = Path(__file__).parent / "seen_emails.json"

# ---------------------------------------------------------------------------
# PERSISTENCIA (archivos JSON, commiteados al repo por el workflow)
# ---------------------------------------------------------------------------

def load_json_set(path):
    if path.exists():
        return set(json.loads(path.read_text()))
    return set()


def save_json_set(path, data):
    path.write_text(json.dumps(list(data)))


def load_state():
    if STATE_FILE.exists():
        data = json.loads(STATE_FILE.read_text())
    else:
        data = {}
    data.setdefault("keywords", DEFAULT_KEYWORDS.copy())
    data.setdefault("exclude_keywords", DEFAULT_EXCLUDE_KEYWORDS.copy())
    data.setdefault("last_run", None)
    data.setdefault("last_run_found", 0)
    data.setdefault("last_update_id", 0)  # para no reprocesar comandos ya vistos
    return data


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2))


STATE = load_state()
SEEN = load_json_set(SEEN_FILE)
SEEN_EMAILS = load_json_set(SEEN_EMAILS_FILE)

# ---------------------------------------------------------------------------
# TELEGRAM (HTTP directo, sin librería extra)
# ---------------------------------------------------------------------------

def tg_url(method):
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    return f"https://api.telegram.org/bot{token}/{method}"


def send_message(text, chat_id=None):
    chat_id = chat_id or os.environ["TELEGRAM_CHAT_ID"]
    resp = requests.post(tg_url("sendMessage"), data={
        "chat_id": chat_id, "text": text, "parse_mode": "Markdown",
    }, timeout=15)
    if resp.status_code >= 400:
        print(f"Error enviando mensaje: {resp.text[:200]}")


def get_updates(offset):
    resp = requests.get(tg_url("getUpdates"), params={
        "offset": offset, "timeout": 0,
    }, timeout=15)
    resp.raise_for_status()
    return resp.json().get("result", [])

# ---------------------------------------------------------------------------
# BÚSQUEDA EN INDEED
# ---------------------------------------------------------------------------

FEED_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}


def build_rss_url(query, location, start=0):
    url = f"https://ar.indeed.com/rss?q={quote_plus(query)}&l={quote_plus(location)}"
    if start:
        url += f"&start={start}"
    return url


def clean_html(raw_html):
    text = re.sub(r"<[^>]+>", " ", raw_html or "")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def matches_profile(title, summary):
    text = f"{title} {summary}".lower()
    if any(bad in text for bad in STATE["exclude_keywords"]):
        return False
    return any(kw in text for kw in STATE["keywords"])


def fetch_new_jobs(searches=None, pages=0):
    """
    Busca en Indeed. `searches` permite pasar una lista custom (si no, usa la
    lista rápida SEARCHES). `pages` es cuántas páginas extra de 25 resultados
    pedir por búsqueda con &start= (0 = solo la primera tanda).
    """
    searches = searches if searches is not None else SEARCHES
    new_jobs = []
    for query, location in searches:
        for page in range(pages + 1):
            start = page * 25
            url = build_rss_url(query, location, start=start)
            try:
                feed = feedparser.parse(url, request_headers=FEED_HEADERS)
            except Exception as e:
                print(f"Error consultando '{query}' (start={start}): {e}")
                continue
            if not feed.entries:
                break  # no hay más páginas para esta búsqueda, no seguimos pidiendo de más
            for entry in feed.entries:
                job_id = entry.get("id") or entry.get("link")
                if job_id in SEEN:
                    continue
                title = entry.get("title", "Puesto sin título")
                summary = clean_html(entry.get("summary", ""))
                link = entry.get("link", "")
                if not matches_profile(title, summary):
                    continue
                new_jobs.append({"id": job_id, "title": title, "summary": summary[:280], "link": link})
                SEEN.add(job_id)
    return new_jobs


REMOTE_KEYWORDS = [
    "remoto", "remota", "remote", "home office", "teletrabajo",
    "trabajo desde casa", "100% remoto", "full remoto",
]

HYBRID_KEYWORDS = [
    "hibrido", "híbrido", "hybrid", "semi presencial", "semi-presencial",
    "mixta", "modalidad mixta",
]


def get_modality_tag(title, summary):
    text = f"{title} {summary}".lower()
    if any(kw in text for kw in REMOTE_KEYWORDS):
        return "🏠 *REMOTO*\n"
    if any(kw in text for kw in HYBRID_KEYWORDS):
        return "🔀 *HÍBRIDO*\n"
    return "🏢 *Presencial/no especificado*\n"


def format_job_message(job):
    tag = get_modality_tag(job["title"], job.get("summary", ""))
    return f"🔔 *Nueva oferta:* {job['title']}\n{tag}\n📝 {job['summary']}\n\n🔗 Postularme: {job['link']}"

# ---------------------------------------------------------------------------
# MAIL DE ALERTAS (LinkedIn, Bumeran, Zonajobs, Computrabajo, GetOnBoard)
# ---------------------------------------------------------------------------

def decode_mime(value):
    if not value:
        return ""
    parts = decode_header(value)
    out = ""
    for text, enc in parts:
        out += text.decode(enc or "utf-8", errors="ignore") if isinstance(text, bytes) else text
    return out


def extract_body_text(msg):
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            if ctype in ("text/plain", "text/html"):
                try:
                    payload = part.get_payload(decode=True).decode(
                        part.get_content_charset() or "utf-8", errors="ignore"
                    )
                except Exception:
                    continue
                return clean_html(payload) if ctype == "text/html" else payload
    else:
        try:
            payload = msg.get_payload(decode=True).decode(msg.get_content_charset() or "utf-8", errors="ignore")
            return clean_html(payload) if msg.get_content_type() == "text/html" else payload
        except Exception:
            return ""
    return ""


def extract_links(text, sender_domain):
    urls = re.findall(r'https?://[^\s"<>]+', text)
    relevant = [u for u in urls if sender_domain.split(".")[0] in u]
    seen, out = set(), []
    for u in relevant:
        short = u.split("?")[0]
        if short not in seen:
            seen.add(short)
            out.append(short)
    return out[:5]


def check_email_alerts():
    address = os.environ.get("EMAIL_ADDRESS")
    app_password = os.environ.get("EMAIL_APP_PASSWORD")
    if not address or not app_password:
        return []

    results = []
    imap = imaplib.IMAP4_SSL("imap.gmail.com")
    try:
        imap.login(address, app_password)
        imap.select("INBOX")
        status, data = imap.search(None, "UNSEEN")
        if status != "OK":
            return []
        ids = data[0].split()
        for eid in ids[-50:]:
            status, msg_data = imap.fetch(eid, "(RFC822)")
            if status != "OK":
                continue
            msg = email.message_from_bytes(msg_data[0][1])
            from_header = decode_mime(msg.get("From", ""))
            match = re.search(r"@([\w.-]+)", from_header)
            sender_domain = match.group(1).lower() if match else ""

            portal = next((name for frag, name in EMAIL_SOURCES.items() if frag in sender_domain), None)
            if not portal:
                continue

            msg_id = msg.get("Message-ID", str(eid))
            if msg_id in SEEN_EMAILS:
                continue

            subject = decode_mime(msg.get("Subject", "(sin asunto)"))
            body = extract_body_text(msg)
            links = extract_links(body, sender_domain)
            results.append({"portal": portal, "subject": subject, "links": links, "body": body[:1000]})
            SEEN_EMAILS.add(msg_id)
        imap.close()
    finally:
        imap.logout()
    return results


def format_email_alert_message(item):
    tag = get_modality_tag(item["subject"], item.get("body", ""))
    links_txt = "\n".join(item["links"]) if item["links"] else "(sin link detectado, revisá el mail original)"
    return f"📧 *{item['portal']}:* {item['subject']}\n{tag}\n{links_txt}"

# ---------------------------------------------------------------------------
# COMANDOS
# ---------------------------------------------------------------------------

def cmd_start():
    msg_text = (
        "🤖 Job Alert Bot activo (versión GitHub Actions).\n\n"
        "Comandos disponibles:\n"
        "/buscar - buscar ofertas ahora (búsqueda rápida, Indeed)\n"
        "/escaneo - escaneo profundo, más búsquedas + paginación (tarda más)\n"
        "/mail - revisar alertas nuevas por mail\n"
        "/agregar <palabra> - sumar palabra clave\n"
        "/sacar <palabra> - excluir palabra\n"
        "/keywords - ver palabras clave actuales\n"
        "/excluidas - ver palabras excluidas\n"
        "/estado - ver última corrida\n\n"
        "⏱️ Nota: como corre por cron y no 24/7, los comandos tardan hasta "
        "el intervalo configurado en responder (no es instantáneo)."
    )
    send_message(msg_text)


def cmd_buscar():
    new_jobs = fetch_new_jobs()
    STATE["last_run"] = datetime.now(timezone.utc).isoformat()
    STATE["last_run_found"] = len(new_jobs)
    if not new_jobs:
        send_message("No encontré ofertas nuevas que matcheen tu perfil.")
        return
    for job in new_jobs:
        send_message(format_job_message(job))
        time.sleep(1)


def cmd_escaneo():
    send_message(
        f"🔎 Iniciando escaneo profundo ({len(DEEP_SEARCHES_EXTRA)} búsquedas extra, "
        f"{DEEP_SCAN_PAGES + 1} páginas c/u). Puede tardar varios minutos..."
    )
    new_jobs = fetch_new_jobs(searches=DEEP_SEARCHES_EXTRA, pages=DEEP_SCAN_PAGES)
    STATE["last_run"] = datetime.now(timezone.utc).isoformat()
    STATE["last_run_found"] = len(new_jobs)
    if not new_jobs:
        send_message("Escaneo profundo terminado: no encontré ofertas nuevas.")
        return
    for job in new_jobs:
        send_message(format_job_message(job))
        time.sleep(1)


def cmd_mail():
    if not os.environ.get("EMAIL_ADDRESS"):
        send_message("Todavía no configuraste EMAIL_ADDRESS / EMAIL_APP_PASSWORD.")
        return
    items = check_email_alerts()
    if not items:
        send_message("No hay mails nuevos de los portales configurados.")
        return
    for item in items:
        send_message(format_email_alert_message(item))
        time.sleep(1)


def cmd_agregar(args):
    if not args:
        send_message("Usá: /agregar palabra clave")
        return
    palabra = args.strip().lower()
    if palabra in STATE["keywords"]:
        send_message(f'"{palabra}" ya estaba en la lista.')
        return
    STATE["keywords"].append(palabra)
    send_message(f'✅ Agregada "{palabra}" a las palabras clave.')


def cmd_sacar(args):
    if not args:
        send_message("Usá: /sacar palabra a excluir")
        return
    palabra = args.strip().lower()
    if palabra in STATE["exclude_keywords"]:
        send_message(f'"{palabra}" ya estaba excluida.')
        return
    STATE["exclude_keywords"].append(palabra)
    send_message(f'🚫 A partir de ahora excluyo ofertas con "{palabra}".')


def cmd_keywords():
    send_message("Palabras clave actuales:\n" + ", ".join(STATE["keywords"]))


def cmd_excluidas():
    send_message("Palabras excluidas actuales:\n" + ", ".join(STATE["exclude_keywords"]))


def cmd_estado():
    last_run = STATE.get("last_run")
    last_run_txt = last_run.replace("T", " ").split(".")[0] + " UTC" if last_run else "todavía no corrió"
    send_message(
        f"📊 Estado del bot\n\n"
        f"Última corrida: {last_run_txt}\n"
        f"Ofertas encontradas esa vez: {STATE.get('last_run_found', 0)}\n"
        f"Búsquedas rápidas (cada corrida): {len(SEARCHES)}\n"
        f"Búsquedas del escaneo profundo (9am/18pm): {len(DEEP_SEARCHES_EXTRA)}\n"
        f"Palabras clave: {len(STATE['keywords'])}\n"
        f"Palabras excluidas: {len(STATE['exclude_keywords'])}"
    )


COMMANDS = {
    "/start": lambda args: cmd_start(),
    "/ayuda": lambda args: cmd_start(),
    "/buscar": lambda args: cmd_buscar(),
    "/escaneo": lambda args: cmd_escaneo(),
    "/mail": lambda args: cmd_mail(),
    "/agregar": cmd_agregar,
    "/sacar": cmd_sacar,
    "/keywords": lambda args: cmd_keywords(),
    "/excluidas": lambda args: cmd_excluidas(),
    "/estado": lambda args: cmd_estado(),
}


def process_pending_commands():
    """Revisa mensajes de Telegram recibidos desde la última corrida y los ejecuta."""
    my_chat_id = str(os.environ["TELEGRAM_CHAT_ID"])
    offset = STATE.get("last_update_id", 0) + 1
    updates = get_updates(offset)

    for update in updates:
        STATE["last_update_id"] = update["update_id"]
        message = update.get("message", {})
        chat_id = str(message.get("chat", {}).get("id", ""))
        text = message.get("text", "")

        if chat_id != my_chat_id or not text.startswith("/"):
            continue  # ignora mensajes de otros o que no son comandos

        parts = text.strip().split(maxsplit=1)
        cmd = parts[0].split("@")[0]  # soporta "/buscar@tu_bot" también
        args = parts[1] if len(parts) > 1 else ""

        handler = COMMANDS.get(cmd)
        if handler:
            try:
                handler(args)
            except Exception as e:
                send_message(f"Error ejecutando {cmd}: {e}")

# ---------------------------------------------------------------------------
# BÚSQUEDA PROGRAMADA
# ---------------------------------------------------------------------------

def run_scheduled_search():
    now_hour = datetime.now(timezone.utc).hour
    if now_hour not in SCHEDULED_HOURS_UTC:
        print("Fuera de horario (9am-18pm ART), no busco.")
        return

    new_jobs = fetch_new_jobs()

    # Escaneo profundo: solo 2 veces por día (9am y 18pm ART), con las
    # búsquedas extra generadas automáticamente + paginación. El objetivo es
    # cubrir también ofertas ya publicadas que las 22 búsquedas rápidas no
    # hayan encontrado, sin golpear a Indeed con esas ~60 búsquedas extra en
    # cada corrida de 5 minutos.
    if now_hour in DEEP_SCAN_HOURS_UTC:
        deep_jobs = fetch_new_jobs(searches=DEEP_SEARCHES_EXTRA, pages=DEEP_SCAN_PAGES)
        new_jobs += deep_jobs

    STATE["last_run"] = datetime.now(timezone.utc).isoformat()
    STATE["last_run_found"] = len(new_jobs)

    if new_jobs:
        for job in new_jobs:
            send_message(format_job_message(job))
            time.sleep(1)
    elif now_hour in (12, 21):
        send_message("🔍 Revisé las búsquedas y no encontré ofertas nuevas que matcheen tu perfil.")

    if os.environ.get("EMAIL_ADDRESS"):
        try:
            for item in check_email_alerts():
                send_message(format_email_alert_message(item))
                time.sleep(1)
        except Exception as e:
            print(f"Error revisando mail: {e}")

# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

def main():
    process_pending_commands()
    run_scheduled_search()

    save_state(STATE)
    save_json_set(SEEN_FILE, SEEN)
    save_json_set(SEEN_EMAILS_FILE, SEEN_EMAILS)
    print("Corrida terminada.")


if __name__ == "__main__":
    main()