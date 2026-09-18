#!/usr/bin/env python3
"""
bot.py — versión 24/7 (para correr en una VM propia, ej. Oracle Cloud Always Free)

A diferencia de la versión de GitHub Actions, este proceso queda corriendo
sin parar (python-telegram-bot con long polling), así que:
  - Los comandos responden AL INSTANTE, sin esperar a un cron.
  - La búsqueda programada corre sola por dentro (job_queue), sin depender
    de que nada externo la dispare.
  - El estado (palabras clave, ofertas ya vistas) se guarda en archivos
    locales en el disco de la VM — no hace falta comitear nada a git.
  - Tiene un teclado de botones en Telegram para los comandos más usados.
  - Verifica que cada oferta siga aceptando postulaciones antes de mandarla.

Comandos:
    /buscar            -> busca ofertas ya mismo (Indeed, búsqueda rápida)
    /escaneo           -> escaneo profundo (más búsquedas + paginación)
    /mail              -> revisa mail de alertas ahora
    /agregar <palabra> -> suma palabra clave
    /sacar <palabra>   -> excluye ofertas con esa palabra
    /keywords          -> ver palabras clave actuales
    /excluidas         -> ver palabras excluidas actuales
    /estado            -> última corrida, cuántas ofertas encontró
    /start /ayuda      -> lista de comandos + activa el teclado de botones

Requiere:
    pip install "python-telegram-bot[job-queue]" feedparser requests

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
import calendar
import itertools
import imaplib
import email
from email.header import decode_header
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote_plus

import feedparser
import requests
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, BotCommand
from telegram.ext import Application, CommandHandler, ContextTypes

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

NIVELES = ["pasantia", "junior", "trainee", "practicante"]
AREAS = [
    "backend",
    "ciberseguridad",
    "sistemas",
    "IT",
    "desarrollo",
    "soporte tecnico",
    "redes",
    "devops",
    "cloud security",
    "pentester",
    "python",
    "linux",
    "sysadmin",
    "soc",
    "seguridad informatica",
]
_auto_searches = [
    (f"{n} {a}", "Argentina") for n, a in itertools.product(NIVELES, AREAS)
]
_vistos = {(q.lower(), l.lower()) for q, l in SEARCHES}
DEEP_SEARCHES_EXTRA = [
    (q, l) for q, l in _auto_searches if (q.lower(), l.lower()) not in _vistos
]

DEEP_SCAN_PAGES = 2
DEEP_SCAN_HOURS_UTC = {12, 21}  # 9am y 18pm hora Argentina
SCHEDULED_HOURS_UTC = set(range(12, 22))  # 9am-18pm ART

DEFAULT_KEYWORDS = [
    "pasant",
    "junior",
    "jr.",
    "jr ",
    "trainee",
    "practicante",
    "primer empleo",
    "backend",
    "back-end",
    "back end",
    "fullstack",
    "full stack",
    "ciberseguridad",
    "cybersecurity",
    "seguridad informatica",
    "seguridad de la informacion",
    "networking",
    "redes",
    "soc",
    "pentest",
    "pentester",
    "red team",
    "blue team",
    "devsecops",
    "devops",
    "cloud security",
    "seguridad en la nube",
    "python",
    "linux",
    "fastapi",
    "sysadmin",
    "administrador de sistemas",
    "ethical hacking",
    "hacking etico",
    "vulnerabilidades",
    "ciso",
]

DEFAULT_EXCLUDE_KEYWORDS = [
    "senior",
    "ssr.",
    "ssr ",
    "ssr/",
    "/ssr",
    "semi senior",
    "semi-senior",
    "sr.",
    "sr ",
    "sr/",
    "/sr",
    "lead ",
    "team lead",
    "tech lead",
    "gerente",
    "manager",
    "director",
    "jefe de",
    "coordinador",
    "coordinadora",
    "responsable de",
    "head of",
    "principal ",
    "staff engineer",
    "arquitecto",
    "amplia experiencia",
    "experiencia comprobada",
    "experiencia sólida",
    "experiencia solida",
]

_ANIOS_EXPERIENCIA_RE = re.compile(
    r"(\d+)\s*\+?\s*(?:años?|years?)\s*(?:de\s+)?(?:experiencia|experience)"
)

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
# PERSISTENCIA (archivos locales en el disco de la VM)
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
    return data


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2))


STATE = load_state()
SEEN = load_json_set(SEEN_FILE)
SEEN_EMAILS = load_json_set(SEEN_EMAILS_FILE)

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


# Avisos publicados hace más de esta cantidad de días se descartan: Indeed no
# informa si un aviso sigue aceptando postulaciones, pero cuanto más viejo,
# más probable que ya esté cerrado. Ajustable si te parece muy corto/largo.
MAX_JOB_AGE_DAYS = 15


def is_too_old(entry, max_days=MAX_JOB_AGE_DAYS):
    published = entry.get("published_parsed") or entry.get("updated_parsed")
    if not published:
        return False  # si no sabemos la fecha, no lo descartamos por las dudas
    entry_ts = calendar.timegm(published)  # timestamp UTC
    age_days = (time.time() - entry_ts) / 86400
    return age_days > max_days


# Frases que indican que una oferta ya no acepta postulaciones, buscadas
# directo en el texto de la página del aviso (no solo en el RSS, que no
# informa esto).
CLOSED_PHRASES = [
    "ya no acepta postulaciones",
    "ya no acepta solicitudes",
    "posición cerrada",
    "posicion cerrada",
    "vacante cerrada",
    "empleo no disponible",
    "oferta no disponible",
    "no longer accepting applications",
    "position has been filled",
    "this job is no longer available",
    "job posting has expired",
    "esta oferta ha expirado",
    "esta vacante ha finalizado",
    "ya no está disponible",
    "ya no esta disponible",
]


def is_job_still_open(link):
    """Abre el link real de la oferta y revisa si la página dice que ya
    cerró. Si falla la verificación (timeout, bloqueo, etc.) NO se descarta
    la oferta por las dudas — mejor mostrar una de más que perderte una real."""
    try:
        resp = requests.get(link, headers=FEED_HEADERS, timeout=10)
        if resp.status_code == 404:
            return False
        text = resp.text.lower()
        return not any(phrase in text for phrase in CLOSED_PHRASES)
    except Exception as e:
        print(f"No se pudo verificar si sigue abierta ({link}): {e}")
        return True


def matches_profile(title, summary, require_keyword=True):
    text = f"{title} {summary}".lower()
    if any(bad in text for bad in STATE["exclude_keywords"]):
        return False
    for match in _ANIOS_EXPERIENCIA_RE.finditer(text):
        try:
            if int(match.group(1)) >= 3:
                return False
        except ValueError:
            pass
    if not require_keyword:
        return True
    return any(kw in text for kw in STATE["keywords"])


def fetch_new_jobs(searches=None, pages=0):
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
                break
            for entry in feed.entries:
                job_id = entry.get("id") or entry.get("link")
                if job_id in SEEN:
                    continue
                if is_too_old(entry):
                    SEEN.add(job_id)  # no lo volvemos a evaluar en corridas futuras
                    continue
                title = entry.get("title", "Puesto sin título")
                summary = clean_html(entry.get("summary", ""))
                link = entry.get("link", "")
                if not matches_profile(title, summary):
                    continue
                if not is_job_still_open(link):
                    SEEN.add(job_id)  # ya sabemos que está cerrada, no la re-chequeamos
                    continue
                new_jobs.append(
                    {
                        "id": job_id,
                        "title": title,
                        "summary": summary[:280],
                        "link": link,
                    }
                )
                SEEN.add(job_id)
    return new_jobs


REMOTE_KEYWORDS = [
    "remoto",
    "remota",
    "remote",
    "home office",
    "teletrabajo",
    "trabajo desde casa",
    "100% remoto",
    "full remoto",
]
HYBRID_KEYWORDS = [
    "hibrido",
    "híbrido",
    "hybrid",
    "semi presencial",
    "semi-presencial",
    "mixta",
    "modalidad mixta",
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
        out += (
            text.decode(enc or "utf-8", errors="ignore")
            if isinstance(text, bytes)
            else text
        )
    return out


def extract_raw_html(msg):
    parts = msg.walk() if msg.is_multipart() else [msg]
    for part in parts:
        if part.get_content_type() == "text/html":
            try:
                return part.get_payload(decode=True).decode(
                    part.get_content_charset() or "utf-8", errors="ignore"
                )
            except Exception:
                continue
    return None


JOB_URL_PATTERNS = {
    "LinkedIn": re.compile(r"/jobs/view/\d+"),
    "Bumeran": re.compile(r"/empleos?/[^/?#\"']+-\d{4,}"),
    "Zonajobs": re.compile(r"/empleos?/[^/?#\"']+-\d{4,}"),
    "Computrabajo": re.compile(r"/(ofertas-de-trabajo|trabajo-de)/"),
    "GetOnBoard": re.compile(r"/jobs/[^/?#\"']+/[^/?#\"']+"),
}

JUNK_LINK_RE = re.compile(
    r"(unsubscribe|opt-?out|preferences|settings|privacy|legal|terms|"
    r"help\b|support|notification|manage-alert|email-setting|feed\?|"
    r"/search\?|/search/)",
    re.I,
)

GENERIC_ANCHOR_TEXTS = {
    "ver oferta",
    "ver empleo",
    "aplicar",
    "postularme",
    "postular",
    "ver más",
    "ver mas",
    "click aquí",
    "click aqui",
    "apply now",
    "view job",
    "see job",
    "ver todas las ofertas",
    "ver todos los empleos",
}


def extract_job_links(html, portal):
    if not html:
        return []
    pattern = JOB_URL_PATTERNS.get(portal)
    if not pattern:
        return []

    anchor_re = re.compile(
        r'<a\s+[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', re.I | re.S
    )
    seen_urls, out = set(), []
    for url, inner_html in anchor_re.findall(html):
        if JUNK_LINK_RE.search(url):
            continue
        if not pattern.search(url):
            continue
        short_url = url.split("?")[0]
        if short_url in seen_urls:
            continue
        seen_urls.add(short_url)

        title = clean_html(inner_html).strip()
        if not title or len(title) < 10 or title.lower() in GENERIC_ANCHOR_TEXTS:
            title = None
        out.append({"link": short_url, "title": title})
        if len(out) >= 15:
            break
    return out


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

            portal = next(
                (name for frag, name in EMAIL_SOURCES.items() if frag in sender_domain),
                None,
            )
            if not portal:
                continue

            msg_id = msg.get("Message-ID", str(eid))
            if msg_id in SEEN_EMAILS:
                continue
            SEEN_EMAILS.add(msg_id)

            raw_html = extract_raw_html(msg)
            job_links = extract_job_links(raw_html, portal)

            for job in job_links:
                if job["link"] in SEEN:
                    continue
                title = job["title"] or f"Nueva oferta en {portal}"
                if not matches_profile(title, "", require_keyword=False):
                    SEEN.add(job["link"])
                    continue
                SEEN.add(job["link"])
                results.append({"portal": portal, "title": title, "link": job["link"]})
        imap.close()
    finally:
        imap.logout()
    return results


def format_email_alert_message(item):
    tag = get_modality_tag(item["title"], "")
    return f"📧 *{item['portal']}:* {item['title']}\n{tag}\n🔗 {item['link']}"


# ---------------------------------------------------------------------------
# SEGURIDAD: solo responder a tu chat
# ---------------------------------------------------------------------------


def is_authorized(update: Update) -> bool:
    return str(update.effective_chat.id) == str(os.environ["TELEGRAM_CHAT_ID"])


# Teclado de botones que reemplaza al teclado normal en Telegram
REPLY_KEYBOARD = ReplyKeyboardMarkup(
    [
        [KeyboardButton("/buscar"), KeyboardButton("/escaneo")],
        [KeyboardButton("/mail"), KeyboardButton("/estado")],
        [KeyboardButton("/keywords"), KeyboardButton("/excluidas")],
    ],
    resize_keyboard=True,  # botones más chicos, no ocupan toda la pantalla
    is_persistent=True,  # se queda fijo, no hay que volver a pedirlo
)

# ---------------------------------------------------------------------------
# COMANDOS
# ---------------------------------------------------------------------------


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    await update.message.reply_text(
        "🤖 Job Alert Bot activo 24/7 (Oracle Cloud).\n\n"
        "Comandos disponibles:\n"
        "/buscar - buscar ofertas ahora (Indeed, rápida)\n"
        "/escaneo - escaneo profundo (más búsquedas + paginación)\n"
        "/mail - revisar alertas nuevas por mail\n"
        "/agregar <palabra> - sumar palabra clave\n"
        "/sacar <palabra> - excluir palabra\n"
        "/keywords - ver palabras clave actuales\n"
        "/excluidas - ver palabras excluidas\n"
        "/estado - ver última corrida\n\n"
        "👇 Usá los botones de abajo para los comandos más comunes.",
        reply_markup=REPLY_KEYBOARD,
    )


async def cmd_buscar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    await update.message.reply_text("🔍 Buscando en Indeed ahora, un momento...")
    new_jobs = fetch_new_jobs()
    STATE["last_run"] = datetime.now(timezone.utc).isoformat()
    STATE["last_run_found"] = len(new_jobs)
    save_state(STATE)
    save_json_set(SEEN_FILE, SEEN)

    if not new_jobs:
        await update.message.reply_text(
            "No encontré ofertas nuevas en Indeed que matcheen tu perfil."
        )
        return
    for job in new_jobs:
        await update.message.reply_text(format_job_message(job), parse_mode="Markdown")
        time.sleep(1)


async def cmd_escaneo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    await update.message.reply_text(
        f"🔎 Iniciando escaneo profundo ({len(DEEP_SEARCHES_EXTRA)} búsquedas extra, "
        f"{DEEP_SCAN_PAGES + 1} páginas c/u). Puede tardar varios minutos..."
    )
    new_jobs = fetch_new_jobs(searches=DEEP_SEARCHES_EXTRA, pages=DEEP_SCAN_PAGES)
    STATE["last_run"] = datetime.now(timezone.utc).isoformat()
    STATE["last_run_found"] = len(new_jobs)
    save_state(STATE)
    save_json_set(SEEN_FILE, SEEN)

    if not new_jobs:
        await update.message.reply_text(
            "Escaneo profundo terminado (Indeed): no encontré ofertas nuevas."
        )
        return
    for job in new_jobs:
        await update.message.reply_text(format_job_message(job), parse_mode="Markdown")
        time.sleep(1)


async def cmd_mail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    if not os.environ.get("EMAIL_ADDRESS"):
        await update.message.reply_text(
            "Todavía no configuraste EMAIL_ADDRESS / EMAIL_APP_PASSWORD."
        )
        return
    await update.message.reply_text("📬 Revisando tu bandeja de entrada...")
    items = check_email_alerts()
    save_json_set(SEEN_EMAILS_FILE, SEEN_EMAILS)
    save_json_set(SEEN_FILE, SEEN)
    if not items:
        await update.message.reply_text(
            "No hay mails nuevos de los portales configurados."
        )
        return
    for item in items:
        await update.message.reply_text(
            format_email_alert_message(item), parse_mode="Markdown"
        )
        time.sleep(1)


async def cmd_agregar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    if not context.args:
        await update.message.reply_text("Usá: /agregar palabra clave")
        return
    palabra = " ".join(context.args).lower().strip()
    if palabra in STATE["keywords"]:
        await update.message.reply_text(f'"{palabra}" ya estaba en la lista.')
        return
    STATE["keywords"].append(palabra)
    save_state(STATE)
    await update.message.reply_text(f'✅ Agregada "{palabra}" a las palabras clave.')


async def cmd_sacar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    if not context.args:
        await update.message.reply_text("Usá: /sacar palabra a excluir")
        return
    palabra = " ".join(context.args).lower().strip()
    if palabra in STATE["exclude_keywords"]:
        await update.message.reply_text(f'"{palabra}" ya estaba excluida.')
        return
    STATE["exclude_keywords"].append(palabra)
    save_state(STATE)
    await update.message.reply_text(
        f'🚫 A partir de ahora excluyo ofertas con "{palabra}".'
    )


async def cmd_keywords(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    await update.message.reply_text(
        "Palabras clave actuales:\n" + ", ".join(STATE["keywords"])
    )


async def cmd_excluidas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    await update.message.reply_text(
        "Palabras excluidas actuales:\n" + ", ".join(STATE["exclude_keywords"])
    )


async def cmd_estado(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    last_run = STATE.get("last_run")
    last_run_txt = (
        last_run.replace("T", " ").split(".")[0] + " UTC"
        if last_run
        else "todavía no corrió"
    )
    await update.message.reply_text(
        f"📊 Estado del bot (24/7)\n\n"
        f"Última corrida: {last_run_txt}\n"
        f"Ofertas encontradas esa vez: {STATE.get('last_run_found', 0)}\n"
        f"Búsquedas rápidas: {len(SEARCHES)}\n"
        f"Búsquedas del escaneo profundo: {len(DEEP_SEARCHES_EXTRA)}\n"
        f"Palabras clave: {len(STATE['keywords'])}\n"
        f"Palabras excluidas: {len(STATE['exclude_keywords'])}"
    )


# ---------------------------------------------------------------------------
# BÚSQUEDA PROGRAMADA (corre sola, sin cron externo)
# ---------------------------------------------------------------------------


async def scheduled_search(context: ContextTypes.DEFAULT_TYPE):
    now_hour = datetime.now(timezone.utc).hour
    if now_hour not in SCHEDULED_HOURS_UTC:
        return

    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    new_jobs = fetch_new_jobs()

    if now_hour in DEEP_SCAN_HOURS_UTC:
        new_jobs += fetch_new_jobs(searches=DEEP_SEARCHES_EXTRA, pages=DEEP_SCAN_PAGES)

    STATE["last_run"] = datetime.now(timezone.utc).isoformat()
    STATE["last_run_found"] = len(new_jobs)
    save_state(STATE)
    save_json_set(SEEN_FILE, SEEN)

    if new_jobs:
        for job in new_jobs:
            await context.bot.send_message(
                chat_id=chat_id, text=format_job_message(job), parse_mode="Markdown"
            )
            time.sleep(1)
    elif now_hour in (12, 21):
        await context.bot.send_message(
            chat_id=chat_id,
            text="🔍 Revisé las búsquedas en Indeed y no encontré ofertas nuevas que matcheen tu perfil.",
        )

    if os.environ.get("EMAIL_ADDRESS"):
        try:
            email_items = check_email_alerts()
            save_json_set(SEEN_EMAILS_FILE, SEEN_EMAILS)
            save_json_set(SEEN_FILE, SEEN)
            for item in email_items:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=format_email_alert_message(item),
                    parse_mode="Markdown",
                )
                time.sleep(1)
        except Exception as e:
            print(f"Error revisando mail: {e}")


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------


async def _post_init(app: Application):
    """Configura el menú nativo de comandos de Telegram (el ícono '/' al lado del teclado)."""
    await app.bot.set_my_commands(
        [
            BotCommand("buscar", "Buscar ofertas ahora (rápida)"),
            BotCommand("escaneo", "Escaneo profundo (más búsquedas)"),
            BotCommand("mail", "Revisar alertas por mail"),
            BotCommand("agregar", "Sumar palabra clave"),
            BotCommand("sacar", "Excluir palabra"),
            BotCommand("keywords", "Ver palabras clave"),
            BotCommand("excluidas", "Ver palabras excluidas"),
            BotCommand("estado", "Ver última corrida"),
            BotCommand("ayuda", "Ver esta lista y mostrar botones"),
        ]
    )


def main():
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    app = Application.builder().token(token).post_init(_post_init).build()

    app.add_handler(CommandHandler(["start", "ayuda"], cmd_start))
    app.add_handler(CommandHandler("buscar", cmd_buscar))
    app.add_handler(CommandHandler("escaneo", cmd_escaneo))
    app.add_handler(CommandHandler("mail", cmd_mail))
    app.add_handler(CommandHandler("agregar", cmd_agregar))
    app.add_handler(CommandHandler("sacar", cmd_sacar))
    app.add_handler(CommandHandler("keywords", cmd_keywords))
    app.add_handler(CommandHandler("excluidas", cmd_excluidas))
    app.add_handler(CommandHandler("estado", cmd_estado))

    # corre cada 5 minutos; la propia función decide si es horario laboral o no
    app.job_queue.run_repeating(scheduled_search, interval=300, first=10)

    print("Bot 24/7 corriendo. Esperando comandos y corriendo búsquedas programadas...")
    app.run_polling()


if __name__ == "__main__":
    main()
