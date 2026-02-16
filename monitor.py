# -*- coding: utf-8 -*-
import os
import re
import json
import hashlib
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
SUBJECT_TPL = os.getenv("SUBJECT_TPL", "[LALIGA | Javier Tebas] Monitor diario - {date}")

# SMTP (Gmail o Brevo)
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "465"))  # 465=SSL, 587=STARTTLS
SMTP_SECURE = os.getenv("SMTP_SECURE", "ssl").lower()  # "ssl" o "starttls"
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASS = os.getenv("SMTP_PASS")

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
            url = getattr(e, "link", None)
            title = getattr(e, "title", None)
            if not url or not title:
                continue
            published = None
            if hasattr(e, "published"):
                try:
                    published = dateparser.parse(e.published)
                except Exception:
                    published = None
            if not published:
    main()
