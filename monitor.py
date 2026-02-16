import os, re, csv, json, hashlib, time, base64
from datetime import datetime, timedelta, timezone
import pytz
import requests
import feedparser
from bs4 import BeautifulSoup
from dateutil import parser as dateparser
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders

TZ = pytz.timezone(os.getenv("TZ", "Europe/Madrid"))
RUN_AT = os.getenv("RUN_AT", "08:00")
WINDOW_HOURS = int(os.getenv("WINDOW_HOURS", "24"))
OVERLAP_MIN = int(os.getenv("OVERLAP_MIN", "120"))
RECIPIENTS = [e.strip() for e in os.getenv("RECIPIENTS", "").split(",") if e.strip()]
SENDER = os.getenv("SENDER", "monitor@example.com")
SUBJECT_TPL = os.getenv("SUBJECT_TPL", "[LALIGA | Javier Tebas] Monitor diario — {date}")

# === Config SMTP (funciona con Gmail o Brevo) ===
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "465"))  # 465=SSL, 587=STARTTLS
SMTP_SECURE = os.getenv("SMTP_SECURE", "ssl").lower()  # "ssl" o "starttls"
SMTP_USER = os.getenv("SMTP_USER")  # Gmail: tu@gmail.com | Brevo: tu usuario SMTP
SMTP_PASS = os.getenv("SMTP_PASS")  # Gmail: App Password | Brevo: SMTP key

QUERIES = {
  "LALIGA": ["LALIGA", "LaLiga", "La Liga", "Liga de Fútbol Profesional", "LFP"],
  "JAVIER_TEBAS": ["Javier Tebas", "Tebas Medrano"],
}

RSS_FEEDS = [
  "https://e00-marca.uecdn.es/rss/futbol/laliga.xml",
  "https://as.com/rss/tags/e/l/laliga/a/",
  "https://www.relevo.com/rss",
  "https://feeds.elpais.com/mrss-s/pages/ep/site/elpais.com/section/deportes/portada",
  "https://e00-elmundo.uecdn.es/elmundo/rss/deportes.xml",
   "https://www.abc.es/rss/feeds/abc_Deportes.xml",
  "https://www.rtve.es/api/rss/deportes",
  "https://www.europapress.es/rss/rss.aspx?ch=273",
  "https://www.efe.com/efe/espana/deportes/123/rss",
]

BING_NEWS_ENDPOINT = "https://api.bing.microsoft.com/v7.0/news/search"
BING_API_KEY = os.getenv("BING_NEWS_KEY")
NEWSAPI_ENDPOINT = "https://newsapi.org/v2/everything"
NEWSAPI_KEY = os.getenv("NEWSAPI_KEY")
GDELT_ENDPOINT = "https://api.gdeltproject.org/api/v2/doc/doc"


def now_local():
    return datetime.now(TZ)

def in_window(dt_utc):
    end = now_local().replace(hour=0, minute=0, second=0, microsecond=0)
    start = end - timedelta(hours=24)
    dt_local = dt_utc.astimezone(TZ)
    return start <= dt_local < end + timedelta(hours=24)


def normalize_url(url):
    if not url:
        return url
    url = re.sub(r"[?#].*$", "", url)
    return url

def hash_item(url, title):
    base = (normalize_url(url) or "") + "|" + (title or "")
    return hashlib.sha256(base.encode("utf-8")).hexdigest()


def fetch_rss():
    items = []
    for feed in RSS_FEEDS:
        d = feedparser.parse(feed)
        for e in d.entries:
            url = e.link
            title = e.title
            published = None
            if hasattr(e, 'published'):
                try:
                    published = dateparser.parse(e.published)
                except: pass
            if not published:
                published = now_local()
            if published.tzinfo is None:
                published = TZ.localize(published)
            items.append({
                'source': 'rss', 'feed': feed,
                'title': title, 'url': url,
                'published': published.astimezone(timezone.utc)
            })
    return items


def fetch_bing(query):
    if not BING_API_KEY: return []
    headers = {"Ocp-Apim-Subscription-Key": BING_API_KEY}
    params = {"q": query, "mkt": "es-ES", "freshness": "Day", "count": 50}
    r = requests.get(BING_NEWS_ENDPOINT, headers=headers, params=params, timeout=20)
    r.raise_for_status()
    data = r.json()
    items = []
    for v in data.get('value', []):
        dt = dateparser.parse(v.get('datePublished'))
        if dt.tzinfo is None: dt = dt.replace(tzinfo=timezone.utc)
        items.append({
            'source': 'bing', 'title': v.get('name'), 'url': v.get('url'), 'published': dt
        })
    return items


def fetch_newsapi(query):
    if not NEWSAPI_KEY: return []
    params = {
        'q': query,
        'language': 'es',
        'sortBy': 'publishedAt',
        'pageSize': 100,
        'from': (now_local() - timedelta(hours=24+2)).astimezone(timezone.utc).isoformat(),
        'to': now_local().astimezone(timezone.utc).isoformat()
    }
    r = requests.get(NEWSAPI_ENDPOINT, params=params, headers={'X-Api-Key': NEWSAPI_KEY}, timeout=20)
    r.raise_for_status()
    data = r.json()
    items = []
    for a in data.get('articles', []):
        dt = dateparser.parse(a.get('publishedAt'))
        if dt.tzinfo is None: dt = dt.replace(tzinfo=timezone.utc)
        items.append({
            'source': 'newsapi',
           'title': a.get('title'),
            'url': a.get('url'),
            'published': dt
        })
    return items


def fetch_gdelt(query):
    params = {
        'query': query + ' sourcecountry:SPAIN',
        'mode': 'ArtList',
        'maxrecords': 250,
        'timespan': '24h',
        'format': 'json'
    }
    r = requests.get(GDELT_ENDPOINT, params=params, timeout=20)
    r.raise_for_status()
    data = r.json()
    items = []
    for a in data.get('articles', []):
        dt = dateparser.parse(a.get('seendate'))
        if dt.tzinfo is None: dt = dt.replace(tzinfo=timezone.utc)
        items.append({
            'source': 'gdelt',
            'title': a.get('title'),
            'url': a.get('url'),
            'published': dt
        })
    return items


def classify_category(title):
    t = (title or '').lower()
    if 'tebas' in t: return 'JAVIER_TEBAS'
    if 'laliga' in t or 'la liga' in t or 'liga de fútbol profesional' in t or 'lfp' in t:
        return 'LALIGA'
    return 'LALIGA'


def near_dedupe(items, threshold=0.88):
    if not items:
        return []
    texts = [i["title"] for i in items]
    vec = TfidfVectorizer(min_df=1).fit_transform(texts)
    sim = cosine_similarity(vec)
    n = len(items)
    removed = set()
    for i in range(n):
        if i in removed:
            continue
        for j in range(i + 1, n):
            if j in removed:
                continue
            if sim[i, j] >= threshold:
                removed.add(j)
    return [it for k, it in enumerate(items) if k not in removed]


def gather():
    all_items = []
    # RSS capa
    all_items += fetch_rss()

    # Consultas agregadores
    q_laliga = "(LALIGA OR \"LaLiga\" OR \"La Liga\" OR \"Liga de Fútbol Profesional\" OR LFP)"
    q_tebas = "(\"Javier Tebas\" OR \"Tebas Medrano\")"

    for q in (q_laliga, q_tebas):
        all_items += fetch_bing(q)
        all_items += fetch_newsapi(q)
        all_items += fetch_gdelt(q)

    # Normalizar, filtrar por ventana, dedupe exacto
    norm = []
    seen = set()
    for it in all_items:
        url = normalize_url(it.get('url'))
        title = it.get('title')
        if not url or not title: continue
        h = hash_item(url, title)
        if h in seen: continue
        seen.add(h)
        dt = it.get('published')
        if isinstance(dt, str):
            dt = dateparser.parse(dt)
            if dt.tzinfo is None: dt = dt.replace(tzinfo=timezone.utc)
        if not in_window(dt):
            continue
        norm.append({
            'title': title,
            'url': url,
            'published': dt,
            'medio': '',
            'categoria': classify_category(title),
            'hash': h
        })

    # Near-duplicate
    deduped = near_dedupe(norm, threshold=float(os.getenv('NEAR_DUP_T', '0.88')))
    return deduped


def build_email_payload(items):
    date_str = now_local().strftime('%Y-%m-%d')
    laliga = [i for i in items if i['categoria'] == 'LALIGA']
    tebas  = [i for i in items if i['categoria'] == 'JAVIER_TEBAS']

    def fmt_line(i):
        tloc = i['published'].astimezone(TZ).strftime('%H:%M')
        return f"- {i['title']} — {i['url']} — {tloc}"

    lines = []
    lines.append(f"[LALIGA | Javier Tebas] Monitor diario — {date_str}")
    lines.append("Ventana: 00:00 -> 23:59 (Europe/Madrid)")
    lines.append("")
    lines.append(f"LALIGA ({len(laliga)})")
    lines.extend(fmt_line(i) for i in laliga)
    lines.append("")
    lines.append(f"Javier Tebas ({len(tebas)})")
    lines.extend(fmt_line(i) for i in tebas)
    lines.append("")
    lines.append(f"Totales: {len(items)} | Fuentes: RSS/Agregadores")
    text_body = "\n".join(lines)

    def list_html(lst):
        return "".join(
            f"<li><a href='{x['url']}'>{x['title']}</a> "
            f"<em>{x['published'].astimezone(TZ).strftime('%H:%M')}</em></li>"
            for x in lst
        )

    html_body = (
        f"<h2>[LALIGA | Javier Tebas] Monitor diario — {date_str}</h2>"
        f"<p>Ventana: 00:00 - 23:59 (Europe/Madrid)</p>"
        f"<h3>LALIGA ({len(laliga)})</h3><ol>{list_html(laliga)}</ol>"
        f"<h3>Javier Tebas ({len(tebas)})</h3><ol>{list_html(tebas)}</ol>"
        f"<p>Totales: {len(items)} | Fuentes: RSS/Agregadores</p>"
    )

    return text_body, html_body


def send_email(items):
   if not (SMTP_HOST and SMTP_PORT and SMTP_USER and SMTP_PASS):
        raise RuntimeError("Faltan variables SMTP: SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS")

    text_body, html_body = build_email_payload(items)

    msg = MIMEMultipart('mixed')
    msg['Subject'] = SUBJECT_TPL.format(date=now_local().strftime('%Y-%m-%d'))
    msg['From'] = SENDER or SMTP_USER
    msg['To'] = ", ".join(RECIPIENTS)

    alt = MIMEMultipart('alternative')
    alt.attach(MIMEText(text_body, 'plain', 'utf-8'))
    alt.attach(MIMEText(html_body, 'html', 'utf-8'))
    msg.attach(alt)

    # Adjuntar JSON con items
    payload = json.dumps(items, default=str, ensure_ascii=False, indent=2).encode('utf-8')
    part = MIMEBase('application', 'json')
    part.set_payload(payload)
    encoders.encode_base64(part)
    part.add_header('Content-Disposition', 'attachment', filename='items.json')
    msg.attach(part)

    if SMTP_SECURE == 'ssl':
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as server:
            server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(msg['From'], RECIPIENTS, msg.as_string())
    else:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.ehlo()
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(msg['From'], RECIPIENTS, msg.as_string())


def main():
    items = gather()
    send_email(items)
    print(f"Enviadas {len(items)} referencias")

if __name__ == "__main__":
    main()
