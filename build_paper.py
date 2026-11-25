#!/usr/bin/env python3
"""Baut die Morgenzeitung als EPUB (docs/morgenzeitung.epub) plus Startseite (docs/index.html)."""
import datetime as dt
import html
import os
import re
import socket
import sys
import zoneinfo

import feedparser
import trafilatura
from ebooklib import epub

socket.setdefaulttimeout(25)

# ---------------------------------------------------------------------------
# HIER AENDERN: Rubriken und Quellen.
# Jede Quelle: (Name, Feed-Adresse) oder (Name, Feed-Adresse, Anzahl Artikel)
# "per_feed" ist die Standard-Anzahl Artikel pro Quelle.
# ---------------------------------------------------------------------------
SECTIONS = [
    {"title": "Welt", "per_feed": 1, "feeds": [
        ("BBC News", "https://feeds.bbci.co.uk/news/world/rss.xml"),
        ("Tagesschau", "https://www.tagesschau.de/index~rss2.xml"),
    ]},
    {"title": "Österreich", "per_feed": 2, "feeds": [
        ("ORF", "https://rss.orf.at/news.xml"),
        ("Der Standard", "https://www.derstandard.at/rss", 1),
    ]},
    {"title": "Israel", "per_feed": 1, "feeds": [
        ("Jerusalem Post", "https://www.jpost.com/rss/rssfeedsfrontpage.aspx"),
        ("Israel Hayom", "https://www.israelhayom.com/feed/"),
        ("JNS", "https://www.jns.org/feed/"),
    ]},
    {"title": "Kroatien", "per_feed": 1, "feeds": [
        ("Croatia Week", "https://www.croatiaweek.com/feed/"),
        ("Index.hr", "https://www.index.hr/rss"),
        ("Jutarnji list", "https://www.jutarnji.hr/feed"),
    ]},
    {"title": "Technik", "per_feed": 1, "feeds": [
        ("Heise", "https://www.heise.de/rss/heise-atom.xml"),
        ("Ars Technica", "https://feeds.arstechnica.com/arstechnica/index"),
    ]},
    {"title": "Gute Nachrichten", "per_feed": 1, "feeds": [
        ("Good News Network", "https://www.goodnewsnetwork.org/feed/"),
        ("Positive News", "https://www.positive.news/feed/"),
    ]},
    {"title": "Reisen", "per_feed": 1, "feeds": [
        ("Condé Nast Traveler", "https://www.cntraveler.com/feed/rss"),
        ("Atlas Obscura", "https://www.atlasobscura.com/feeds/latest"),
    ]},
    {"title": "Japan & Südkorea", "per_feed": 1, "feeds": [
        ("Japan Today", "https://japantoday.com/feed"),
        ("Tokyo Cheapo", "https://tokyocheapo.com/feed/"),
        ("Korea Herald", "http://www.koreaherald.com/common/rss_xml.php?ct=102"),
    ]},
    {"title": "Beauty", "per_feed": 1, "feeds": [
        ("Allure", "https://www.allure.com/feed/rss"),
        ("Into The Gloss", "https://intothegloss.com/feed/"),
    ]},
    {"title": "Stricken & Putzen", "per_feed": 1, "feeds": [
        ("Knitty", "https://knitty.com/feed/"),
        ("Apartment Therapy", "https://www.apartmenttherapy.com/main.rss"),
    ]},
]

MAX_CHARS = 4500  # maximale Textlänge pro Artikel
UA = "Mozilla/5.0 (compatible; Morgenzeitung/1.0)"
TZ = zoneinfo.ZoneInfo("Europe/Vienna")
WEEKDAYS = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]

problems = []


def strip_tags(text):
    return html.unescape(re.sub(r"<[^>]+>", " ", text or "")).strip()


def get_text(entry):
    """Volltext der Seite holen; wenn das nicht klappt, die Kurzfassung aus dem Feed."""
    link = entry.get("link")
    text = None
    if link:
        try:
            downloaded = trafilatura.fetch_url(link)
            if downloaded:
                text = trafilatura.extract(downloaded, include_comments=False, include_tables=False)
        except Exception:
            text = None
    if not text:
        text = strip_tags(entry.get("summary", ""))
    return text or ""


def trim(text):
    paras = [p.strip() for p in text.split("\n") if p.strip()]
    out, total = [], 0
    for p in paras:
        if out and total + len(p) > MAX_CHARS:
            out.append("…")
            break
        out.append(p)
        total += len(p)
    return out


def collect_section(section):
    articles, seen = [], set()
    for feed_def in section["feeds"]:
        name, url = feed_def[0], feed_def[1]
        count = feed_def[2] if len(feed_def) > 2 else section["per_feed"]
        try:
            parsed = feedparser.parse(url, agent=UA)
        except Exception as exc:  # noqa: BLE001
            problems.append(f"{name}: {exc}")
            continue
        if not parsed.entries:
            problems.append(f"{name}: keine Artikel gefunden ({url})")
            continue
        taken = 0
        for entry in parsed.entries:
            if taken >= count:
                break
            link = entry.get("link", "")
            title = strip_tags(entry.get("title", ""))
            if not title or link in seen:
                continue
            paras = trim(get_text(entry))
            if not paras:
                continue
            seen.add(link)
            articles.append({"title": title, "source": name, "link": link, "paras": paras})
            taken += 1
    return articles


def article_html(a):
    paras = "".join(f"<p>{html.escape(p)}</p>" for p in a["paras"])
    return (f"<h2>{html.escape(a['title'])}</h2>"
            f"<p><i>{html.escape(a['source'])}</i></p>{paras}")


def main():
    now = dt.datetime.now(TZ)
    date_label = f"{WEEKDAYS[now.weekday()]}, {now.day}.{now.month}.{now.year}"

    book = epub.EpubBook()
    book.set_identifier(f"morgenzeitung-{now:%Y%m%d%H%M}")
    book.set_title(f"Morgenzeitung – {date_label}")
    book.set_language("de")
    book.add_author("Morgenzeitung")

    chapters, total = [], 0
    for i, section in enumerate(SECTIONS, start=1):
        articles = collect_section(section)
        if not articles:
            continue
        total += len(articles)
        body = f"<h1>{html.escape(section['title'])}</h1>" + "".join(article_html(a) for a in articles)
        chapter = epub.EpubHtml(title=section["title"], file_name=f"sektion{i}.xhtml", lang="de")
        chapter.content = body
        book.add_item(chapter)
        chapters.append(chapter)

    if total == 0:
        print("Keine Artikel gefunden. Probleme:", *problems, sep="\n- ")
        sys.exit(1)

    book.toc = tuple(chapters)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav"] + chapters

    os.makedirs("docs", exist_ok=True)
    epub.write_epub("docs/morgenzeitung.epub", book)

    problem_html = ""
    if problems:
        items = "".join(f"<li>{html.escape(p)}</li>" for p in problems)
        problem_html = f"<h3>Nicht geladen</h3><ul>{items}</ul>"
    page = f"""<!doctype html>
<html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Morgenzeitung</title>
<style>body{{font-family:sans-serif;max-width:32rem;margin:2rem auto;padding:0 1rem}}
a.big{{display:block;padding:1.2rem;background:#222;color:#fff;text-align:center;
font-size:1.4rem;text-decoration:none;border-radius:.5rem}}</style></head>
<body><h1>Morgenzeitung</h1>
<p>{date_label}, erstellt um {now:%H:%M} Uhr ({total} Artikel)</p>
<a class="big" href="morgenzeitung.epub">Zeitung laden</a>
{problem_html}</body></html>"""
    with open("docs/index.html", "w", encoding="utf-8") as f:
        f.write(page)
    print(f"Fertig: {total} Artikel, {len(problems)} Probleme.")
    for p in problems:
        print(" -", p)


if __name__ == "__main__":
    main()
