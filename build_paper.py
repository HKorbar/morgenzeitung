#!/usr/bin/env python3
"""Builds Helga’s Morning Paper as an EPUB (docs/morgenzeitung.epub) plus a start page (docs/index.html)."""
import datetime as dt
import html
import io
import os
import re
import socket
import sys
import zoneinfo

from PIL import Image, ImageDraw, ImageFont

socket.setdefaulttimeout(25)

PAPER_NAME = "Helga’s Morning Paper"
TOTAL_BUDGET = 26000   # total characters of article text; roughly 15 pages on a 6-inch Kobo
MIN_PER_ARTICLE = 700
MAX_PER_ARTICLE = 2600

# ---------------------------------------------------------------------------
# CHANGE HERE: sections and sources.
# Each source: (name, feed address) or (name, feed address, number of articles)
# "per_feed" is the default number of articles per source.
# ---------------------------------------------------------------------------
SECTIONS = [
    {"title": "World", "per_feed": 1, "feeds": [
        ("BBC News", "https://feeds.bbci.co.uk/news/world/rss.xml"),
        ("NPR", "https://feeds.npr.org/1001/rss.xml"),
    ]},
    {"title": "Austria", "per_feed": 1, "feeds": [
        ("The Local Austria", "https://feeds.thelocal.com/rss/at"),
        ("Vindobona", "https://www.vindobona.org/feed"),
        # German-language sources, to be translated in the AI step later:
        # ("ORF", "https://rss.orf.at/news.xml"),
        # ("Der Standard", "https://www.derstandard.at/rss"),
    ]},
    {"title": "Israel", "per_feed": 1, "feeds": [
        ("Jerusalem Post", "https://www.jpost.com/rss/rssfeedsfrontpage.aspx"),
        ("Israel Hayom", "https://www.israelhayom.com/feed/"),
        ("JNS", "https://www.jns.org/feed/"),
    ]},
    {"title": "Croatia", "per_feed": 1, "feeds": [
        ("Croatia Week", "https://www.croatiaweek.com/feed/"),
        ("Index.hr", "https://www.index.hr/rss"),
        ("Jutarnji list", "https://www.jutarnji.hr/feed"),
    ]},
    {"title": "Technology", "per_feed": 1, "feeds": [
        ("Ars Technica", "https://feeds.arstechnica.com/arstechnica/index"),
        ("The Verge", "https://www.theverge.com/rss/index.xml"),
    ]},
    {"title": "Good News", "per_feed": 1, "feeds": [
        ("Good News Network", "https://www.goodnewsnetwork.org/feed/"),
        ("Positive News", "https://www.positive.news/feed/"),
    ]},
    {"title": "Travel", "per_feed": 1, "feeds": [
        ("Condé Nast Traveler", "https://www.cntraveler.com/feed/rss"),
        ("Atlas Obscura", "https://www.atlasobscura.com/feeds/latest"),
    ]},
    {"title": "Japan & South Korea", "per_feed": 1, "feeds": [
        ("Japan Today", "https://japantoday.com/feed"),
        ("Tokyo Cheapo", "https://tokyocheapo.com/feed/"),
        ("Korea Herald", "http://www.koreaherald.com/common/rss_xml.php?ct=102"),
    ]},
    {"title": "Beauty", "per_feed": 1, "feeds": [
        ("Allure", "https://www.allure.com/feed/rss"),
        ("Into The Gloss", "https://intothegloss.com/feed/"),
    ]},
    {"title": "Knitting & Home", "per_feed": 1, "feeds": [
        ("Knitty", "https://knitty.com/feed/"),
        ("Apartment Therapy", "https://www.apartmenttherapy.com/main.rss"),
    ]},
]

UA = "Mozilla/5.0 (compatible; MorningPaper/1.0)"
TZ = zoneinfo.ZoneInfo("Europe/Vienna")
WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
MONTHS = ["January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]

problems = []

CSS = """
body { font-family: serif; line-height: 1.35; margin: 0 0.4em; }
h1 { text-align: center; font-size: 1.7em; border-top: 3px double #000;
     border-bottom: 3px double #000; padding: 0.3em 0; margin: 0.3em 0 1em 0;
     text-transform: uppercase; letter-spacing: 0.08em; }
h2 { font-size: 1.25em; margin: 1.3em 0 0.1em 0; line-height: 1.2; }
p { text-align: justify; margin: 0; text-indent: 1.2em; }
p.byline { text-indent: 0; font-size: 0.8em; font-style: italic; margin-bottom: 0.5em;
           border-bottom: 1px solid #000; padding-bottom: 0.2em; }
p.first { text-indent: 0; }
p.center { text-align: center; text-indent: 0; }
p.date { text-align: center; text-indent: 0; font-style: italic; margin-bottom: 1em; }
h3 { font-size: 1em; margin: 1em 0 0.2em 0; text-transform: uppercase; letter-spacing: 0.05em;
     border-bottom: 1px solid #000; }
ul { margin: 0.2em 0 0.6em 1.2em; padding: 0; }
li { margin: 0.1em 0; }
"""


def strip_tags(text):
    return html.unescape(re.sub(r"<[^>]+>", " ", text or "")).strip()


def get_text(entry):
    """Full article text if possible, otherwise the short summary from the feed."""
    import trafilatura
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


def shorten(text, limit):
    """Cut text to roughly `limit` characters, ending at a sentence if possible."""
    paras = [p.strip() for p in text.split("\n") if p.strip()]
    out, used = [], 0
    for p in paras:
        room = limit - used
        if room <= 60:
            break
        if len(p) <= room:
            out.append(p)
            used += len(p)
        else:
            cut = p[:room]
            idx = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
            if idx > room * 0.5:
                out.append(cut[: idx + 1])
            else:
                out.append(cut.rsplit(" ", 1)[0] + " …")
            break
    return out


def collect_section(section):
    import feedparser
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
            problems.append(f"{name}: no articles found ({url})")
            continue
        taken = 0
        for entry in parsed.entries:
            if taken >= count:
                break
            link = entry.get("link", "")
            title = strip_tags(entry.get("title", ""))
            if not title or link in seen:
                continue
            text = get_text(entry)
            if len(text) < 150:
                continue
            seen.add(link)
            articles.append({"title": title, "source": name, "link": link, "text": text})
            taken += 1
    return articles


# ----------------------------- cover image ---------------------------------

def load_font(size, bold=True):
    names = (["DejaVuSerif-Bold.ttf", "LiberationSerif-Bold.ttf"] if bold
             else ["DejaVuSerif.ttf", "LiberationSerif-Regular.ttf"])
    dirs = ["/usr/share/fonts/truetype/dejavu/", "/usr/share/fonts/truetype/liberation/",
            "/usr/share/fonts/dejavu/", "/Library/Fonts/", "/System/Library/Fonts/Supplemental/"]
    for d in dirs:
        for n in names:
            try:
                return ImageFont.truetype(d + n, size)
            except OSError:
                continue
    try:
        return ImageFont.load_default(size)
    except TypeError:
        return ImageFont.load_default()


def fit_font(draw, text, max_width, start, bold=True):
    size = start
    while size > 12:
        font = load_font(size, bold)
        if draw.textlength(text, font=font) <= max_width:
            return font
        size -= 4
    return load_font(12, bold)


def centered(draw, y, text, font, width, fill=0):
    w = draw.textlength(text, font=font)
    draw.text(((width - w) / 2, y), text, font=font, fill=fill)
    return font.size


def make_cover(date_label, section_titles):
    W, H = 1200, 1600
    img = Image.new("L", (W, H), 255)
    d = ImageDraw.Draw(img)
    d.rectangle([36, 36, W - 36, H - 36], outline=0, width=8)
    d.rectangle([56, 56, W - 56, H - 56], outline=0, width=2)
    margin = 110
    inner = W - 2 * margin

    f = load_font(34, bold=False)
    centered(d, 100, "VIENNA  ·  MORNING EDITION", f, W)
    d.rectangle([margin, 160, W - margin, 168], fill=0)
    d.rectangle([margin, 176, W - margin, 178], fill=0)

    f1 = fit_font(d, "Helga’s", inner, 190)
    centered(d, 215, "Helga’s", f1, W)
    f2 = fit_font(d, "Morning Paper", inner, 150)
    centered(d, 215 + f1.size + 30, "Morning Paper", f2, W)

    y = 215 + f1.size + 30 + f2.size + 70
    d.rectangle([margin, y, W - margin, y + 2], fill=0)
    d.rectangle([margin, y + 10, W - margin, y + 18], fill=0)
    y += 50
    bar_h = 86
    d.rectangle([margin, y, W - margin, y + bar_h], fill=0)
    fd = fit_font(d, date_label, inner - 40, 42, bold=True)
    w = d.textlength(date_label, font=fd)
    d.text(((W - w) / 2, y + (bar_h - fd.size) / 2 - 4), date_label, font=fd, fill=255)
    y += bar_h + 70

    centered(d, y, "IN THIS ISSUE", load_font(38), W)
    y += 70
    d.rectangle([W / 2 - 60, y, W / 2 + 60, y + 3], fill=0)
    y += 40

    f_s = load_font(44, bold=False)
    lines, cur = [], ""
    for t in section_titles:
        trial = t if not cur else cur + "   ·   " + t
        if d.textlength(trial, font=f_s) <= inner:
            cur = trial
        else:
            lines.append(cur)
            cur = t
    if cur:
        lines.append(cur)
    for line in lines:
        centered(d, y, line, f_s, W)
        y += 84

    for cx in (W / 2 - 90, W / 2, W / 2 + 90):  # three small diamonds
        cy = H - 225
        d.polygon([(cx, cy - 22), (cx + 22, cy), (cx, cy + 22), (cx - 22, cy)], fill=0)
    centered(d, H - 170, "Freshly printed for you, every morning", load_font(32, bold=False), W)

    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=88)
    return buf.getvalue()


# ------------------------------ book pages ---------------------------------

def article_html(a):
    paras = []
    for i, p in enumerate(a["paras"]):
        cls = ' class="first"' if i == 0 else ""
        paras.append(f"<p{cls}>{html.escape(p)}</p>")
    return (f"<h2>{html.escape(a['title'])}</h2>"
            f"<p class=\"byline\">{html.escape(a['source'])}</p>" + "".join(paras))


def main():
    import feedparser  # noqa: F401  (fails early with a clear message if missing)
    from ebooklib import epub

    now = dt.datetime.now(TZ)
    date_label = f"{WEEKDAYS[now.weekday()]}, {now.day} {MONTHS[now.month - 1]} {now.year}"

    collected = []
    for section in SECTIONS:
        articles = collect_section(section)
        if articles:
            collected.append((section["title"], articles))

    total = sum(len(a) for _, a in collected)
    if total == 0:
        print("No articles found. Problems:", *problems, sep="\n- ")
        sys.exit(1)

    per_article = max(MIN_PER_ARTICLE, min(MAX_PER_ARTICLE, TOTAL_BUDGET // total))
    chars = 0
    for _, articles in collected:
        for a in articles:
            a["paras"] = shorten(a["text"], per_article)
            chars += sum(len(p) for p in a["paras"])
    est_pages = max(1, round(chars / 1700) + 2)

    book = epub.EpubBook()
    book.set_identifier(f"morningpaper-{now:%Y%m%d%H%M}")
    book.set_title(f"{PAPER_NAME} – {date_label}")
    book.set_language("en")
    book.add_author(PAPER_NAME)
    book.set_cover("cover.jpg", make_cover(date_label, [t for t, _ in collected]))

    css = epub.EpubItem(uid="style", file_name="style/paper.css", media_type="text/css", content=CSS)
    book.add_item(css)

    # front page: headlines of the whole issue
    front = [f"<h1>{html.escape(PAPER_NAME)}</h1>",
             f'<p class="date">{html.escape(date_label)}</p>',
             '<p class="center"><b>In this issue</b></p>']
    for title, articles in collected:
        front.append(f"<h3>{html.escape(title)}</h3><ul>")
        front += [f"<li>{html.escape(a['title'])}</li>" for a in articles]
        front.append("</ul>")
    front_ch = epub.EpubHtml(title="Front page", file_name="front.xhtml", lang="en")
    front_ch.content = "".join(front)
    front_ch.add_item(css)
    book.add_item(front_ch)

    chapters = [front_ch]
    for i, (title, articles) in enumerate(collected, start=1):
        body = f"<h1>{html.escape(title)}</h1>" + "".join(article_html(a) for a in articles)
        ch = epub.EpubHtml(title=title, file_name=f"section{i}.xhtml", lang="en")
        ch.content = body
        ch.add_item(css)
        book.add_item(ch)
        chapters.append(ch)

    book.toc = tuple(chapters)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["cover", "nav"] + chapters

    os.makedirs("docs", exist_ok=True)
    epub.write_epub("docs/morgenzeitung.epub", book)

    problem_html = ""
    if problems:
        items = "".join(f"<li>{html.escape(p)}</li>" for p in problems)
        problem_html = f"<h3>Not loaded</h3><ul>{items}</ul>"
    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{PAPER_NAME}</title>
<style>body{{font-family:Georgia,serif;max-width:32rem;margin:2rem auto;padding:0 1rem}}
h1{{text-align:center;border-top:4px double #000;border-bottom:4px double #000;padding:.4rem 0}}
a.big{{display:block;padding:1.2rem;background:#000;color:#fff;text-align:center;
font-size:1.4rem;text-decoration:none}}</style></head>
<body><h1>{PAPER_NAME}</h1>
<p style="text-align:center"><i>{date_label}</i><br>{total} articles, about {est_pages} pages · built {now:%H:%M}</p>
<a class="big" href="morgenzeitung.epub">Download today’s paper</a>
{problem_html}</body></html>"""
    with open("docs/index.html", "w", encoding="utf-8") as f:
        f.write(page)
    print(f"Done: {total} articles, about {est_pages} pages, {len(problems)} problems.")
    for p in problems:
        print(" -", p)


if __name__ == "__main__":
    main()
