#!/usr/bin/env python3
"""Builds Helga’s Morning Paper as an EPUB (docs/morgenzeitung.epub) plus a start page (docs/index.html)."""
import datetime as dt
import html
import io
import json
import os
import random
import re
import socket
import sys
import urllib.request
import zoneinfo

from PIL import Image, ImageDraw, ImageFont

socket.setdefaulttimeout(25)

PAPER_NAME = "Helga’s Morning Paper"
TOTAL_BUDGET = 28000   # characters of article text; with the extras this is roughly 20 pages on a 6-inch Kobo
MIN_PER_ARTICLE = 700
MAX_PER_ARTICLE = 2600

# Weather places: (name, latitude, longitude)
WEATHER_PLACES = [
    ("Vienna", 48.21, 16.37),
    ("Istria", 45.24, 13.93),
]

# ---------------------------------------------------------------------------
# CHANGE HERE: sections and sources.
# Each source: (name, feed address) or (name, feed address, number of articles)
# "per_feed" = default articles per source, "max" = maximum articles in the section.
# Later sources are a fallback if earlier ones fail.
# ---------------------------------------------------------------------------
SECTIONS = [
    {"title": "World", "per_feed": 1, "max": 2, "feeds": [
        ("BBC News", "https://feeds.bbci.co.uk/news/world/rss.xml"),
        ("NPR", "https://feeds.npr.org/1001/rss.xml"),
    ]},
    {"title": "Austria", "per_feed": 1, "max": 2, "feeds": [
        ("The Local Austria", "https://feeds.thelocal.com/rss/at"),
        ("Vindobona", "https://www.vindobona.org/feed"),
        # German-language sources, to be translated in the AI step later:
        # ("ORF", "https://rss.orf.at/news.xml"),
        # ("Der Standard", "https://www.derstandard.at/rss"),
    ]},
    {"title": "Israel", "per_feed": 1, "max": 2, "feeds": [
        ("Jerusalem Post", "https://www.jpost.com/rss/rssfeedsfrontpage.aspx"),
        ("Israel Hayom", "https://www.israelhayom.com/feed/"),
        ("JNS", "https://www.jns.org/feed/"),
    ]},
    {"title": "Croatia", "per_feed": 1, "max": 2, "feeds": [
        ("Croatia Week", "https://www.croatiaweek.com/feed/"),
        ("Index.hr", "https://www.index.hr/rss"),
        ("Jutarnji list", "https://www.jutarnji.hr/feed"),
    ]},
    {"title": "Music", "per_feed": 1, "max": 2, "feeds": [
        ("Slipped Disc", "https://slippedisc.com/feed/"),
        ("Gramophone", "https://www.gramophone.co.uk/feed"),
    ]},
    {"title": "Early Music", "per_feed": 1, "max": 2, "feeds": [
        ("Early Music America", "https://www.earlymusicamerica.org/feed/"),
        # (the daily Early Music Sources video is added automatically, see ems_video)
    ]},
    {"title": "Technology", "per_feed": 1, "max": 2, "feeds": [
        ("Ars Technica", "https://feeds.arstechnica.com/arstechnica/index"),
        ("The Verge", "https://www.theverge.com/rss/index.xml"),
    ]},
    {"title": "Good News", "per_feed": 1, "max": 1, "feeds": [
        ("Good News Network", "https://www.goodnewsnetwork.org/feed/"),
        ("Positive News", "https://www.positive.news/feed/"),
    ]},
    {"title": "Travel", "per_feed": 1, "max": 1, "feeds": [
        ("Condé Nast Traveler", "https://www.cntraveler.com/feed/rss"),
        ("Atlas Obscura", "https://www.atlasobscura.com/feeds/latest"),
    ]},
    {"title": "Japan & South Korea", "per_feed": 1, "max": 2, "feeds": [
        ("Japan Today", "https://japantoday.com/feed"),
        ("Tokyo Cheapo", "https://tokyocheapo.com/feed/"),
        ("Korea Herald", "http://www.koreaherald.com/common/rss_xml.php?ct=102"),
    ]},
    {"title": "Beauty", "per_feed": 1, "max": 1, "feeds": [
        ("Allure", "https://www.allure.com/feed/rss"),
        ("Into The Gloss", "https://intothegloss.com/feed/"),
    ]},
    {"title": "Knitting & Home", "per_feed": 1, "max": 1, "feeds": [
        ("Knitty", "https://knitty.com/feed/"),
        ("Apartment Therapy", "https://www.apartmenttherapy.com/main.rss"),
    ]},
]

UA = "Mozilla/5.0 (compatible; MorningPaper/1.0)"
WIKI_UA = "MorningPaper/1.0 (personal e-paper; https://github.com/HKorbar/morgenzeitung)"
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
li { margin: 0.2em 0; }
table.sudoku { border-collapse: collapse; margin: 1em auto; border: 3px solid #000; }
table.sudoku td { width: 1.7em; height: 1.7em; text-align: center; border: 1px solid #000;
                  padding: 0; font-size: 1.1em; }
table.sudoku td.br { border-right: 3px solid #000; }
table.sudoku td.bb { border-bottom: 3px solid #000; }
table.small td { font-size: 0.7em; }
"""


# ------------------------------ helpers ------------------------------------

def http_get(url, ua=UA, timeout=25):
    req = urllib.request.Request(url, headers={"User-Agent": ua})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def http_json(url, ua=UA):
    return json.loads(http_get(url, ua=ua))


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
    cap = section.get("max", 99)
    for feed_def in section["feeds"]:
        if len(articles) >= cap:
            break
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
            if taken >= count or len(articles) >= cap:
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


# ----------------------- Early Music Sources (YouTube) -----------------------
# One video from the "Early Music Sources" channel per day (rotating through the latest ones).
EMS_FEED = "https://www.youtube.com/feeds/videos.xml?channel_id=UCJOiqToQ7kiakqTLE7Hdd5g"
EMS_TRANSCRIPT_CHARS = 4500   # length of the transcript excerpt (about 2-3 pages)


def fetch_transcript(video_id):
    """English transcript text of a YouTube video (may fail: YouTube often blocks cloud servers)."""
    from youtube_transcript_api import YouTubeTranscriptApi
    try:
        fetched = YouTubeTranscriptApi().fetch(video_id, languages=["en"])
        parts = [getattr(sn, "text", None) or (sn.get("text", "") if isinstance(sn, dict) else "")
                 for sn in fetched]
    except (AttributeError, TypeError):  # older versions of the library
        parts = [x["text"] for x in YouTubeTranscriptApi.get_transcript(video_id, languages=["en"])]
    return " ".join(parts)


def transcript_paragraphs(raw):
    """Turn caption text into readable paragraphs."""
    text = re.sub(r"\[[^\]]{1,30}\]", " ", raw)          # [Music], [Applause] ...
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return []
    sentences = re.split(r"(?<=[.!?])\s+", text)
    paras, cur = [], ""
    if len(sentences) > 8 and len(text) / len(sentences) < 400:   # captions with punctuation
        for sent in sentences:
            cur = (cur + " " + sent).strip()
            if len(cur) > 450:
                paras.append(cur)
                cur = ""
    else:                                                          # no punctuation: cut at word boundaries
        words = text.split(" ")
        for w in words:
            cur = (cur + " " + w).strip()
            if len(cur) > 450:
                paras.append(cur)
                cur = ""
    if cur:
        paras.append(cur)
    return paras


def ems_video(now):
    import feedparser
    try:
        parsed = feedparser.parse(EMS_FEED, agent=UA)
        entries = [e for e in parsed.entries if e.get("title")]
        if not entries:
            raise ValueError("no videos found")
        e = entries[now.timetuple().tm_yday % len(entries)]
        raw = e.get("summary") or e.get("media_description") or ""
        lines = [ln.strip() for ln in strip_tags(raw).replace("\r", "").split("\n") if ln.strip()]
        lines = [ln for ln in lines if "http" not in ln]
        title = strip_tags(e.get("title", ""))
        link = e.get("link", "")
        video_id = e.get("yt_videoid") or (link.split("v=")[-1].split("&")[0] if "v=" in link else "")
        article = {"title": title, "source": "Early Music Sources (video)", "link": link,
                   "text": "\n".join(lines) if lines else f"Video: {title}",
                   "note": "Watch: " + (link or "earlymusicsources.com")}
        if video_id:
            try:
                paras = transcript_paragraphs(fetch_transcript(video_id))
                if paras:
                    article["text"] = "\n".join(paras)
                    article["note"] = "Transcript excerpt. Watch: " + (link or "earlymusicsources.com")
                    article["max_chars"] = EMS_TRANSCRIPT_CHARS
            except Exception as exc:  # noqa: BLE001
                problems.append(f"Early Music Sources transcript not available (showing description): {exc}")
        return article
    except Exception as exc:  # noqa: BLE001
        problems.append(f"Early Music Sources video: {exc}")
        return None


# ------------------------------- weather -----------------------------------

WMO = {0: "clear", 1: "mostly clear", 2: "partly cloudy", 3: "overcast", 45: "fog", 48: "fog",
       51: "light drizzle", 53: "drizzle", 55: "heavy drizzle", 56: "freezing drizzle",
       57: "freezing drizzle", 61: "light rain", 63: "rain", 65: "heavy rain",
       66: "freezing rain", 67: "freezing rain", 71: "light snow", 73: "snow", 75: "heavy snow",
       77: "snow grains", 80: "light showers", 81: "showers", 82: "heavy showers",
       85: "snow showers", 86: "heavy snow showers", 95: "thunderstorm",
       96: "thunderstorm with hail", 99: "thunderstorm with hail"}


def what_to_wear(tmax, rain):
    if tmax <= 3:
        wear = "heavy coat, hat and gloves"
    elif tmax <= 10:
        wear = "warm coat"
    elif tmax <= 17:
        wear = "light jacket"
    elif tmax <= 24:
        wear = "light layers"
    else:
        wear = "summer clothes and sun protection"
    if rain >= 50:
        wear += ", and take an umbrella"
    return wear


def weather_line(name, lat, lon):
    url = (f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
           "&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max"
           "&timezone=Europe%2FVienna&forecast_days=1")
    d = http_json(url)["daily"]
    code = d["weather_code"][0]
    tmax, tmin = round(d["temperature_2m_max"][0]), round(d["temperature_2m_min"][0])
    rain = d["precipitation_probability_max"][0] or 0
    return (f"{name}: {WMO.get(code, 'changeable')}, {tmin}° to {tmax}°C, "
            f"chance of rain {rain}%. Wear: {what_to_wear(tmax, rain)}.")


def weather_html():
    lines = []
    for name, lat, lon in WEATHER_PLACES:
        try:
            lines.append(weather_line(name, lat, lon))
        except Exception as exc:  # noqa: BLE001
            problems.append(f"Weather {name}: {exc}")
    if not lines:
        return "", 0
    body = "<h3>Weather</h3>" + "".join(f'<p class="first">{html.escape(l)}</p>' for l in lines)
    return body, sum(len(l) for l in lines)


# ----------------------------- on this day ---------------------------------

MUSIC_WORDS = ("composer", "pianist", "violinist", "cellist", "violist", "organist", "conductor",
               "singer", "soprano", "tenor", "baritone", "countertenor", "lutenist", "harpsichordist",
               "guitarist", "musician", "oboist", "flautist", "flutist", "music theorist",
               "musicologist", "opera", "recorder player", "violist da gamba", "madrigal")


def on_this_day_items(now):
    items = []
    for kind, label, take in (("births", "Born", 3), ("deaths", "Died", 2)):
        url = (f"https://en.wikipedia.org/api/rest_v1/feed/onthisday/{kind}/"
               f"{now.month:02d}/{now.day:02d}")
        try:
            data = http_json(url, ua=WIKI_UA)
        except Exception as exc:  # noqa: BLE001
            problems.append(f"On this day ({kind}): {exc}")
            continue
        matches = []
        for it in data.get(kind, []):
            blob = (it.get("text", "") + " " + " ".join(
                p.get("description", "") for p in it.get("pages", []))).lower()
            if any(w in blob for w in MUSIC_WORDS):
                matches.append(it)
        # early music first: older years before newer ones
        matches.sort(key=lambda it: (0 if it.get("year", 9999) < 1800 else 1, it.get("year", 9999)))
        for it in matches[:take]:
            text = it.get("text", "")
            if len(text) > 170:
                text = text[:170].rsplit(" ", 1)[0] + " …"
            items.append(f"{label} {it.get('year', '')}: {text}")
    return items


def on_this_day_html(now):
    items = on_this_day_items(now)
    if not items:
        return "", 0
    title = f"On this day, {now.day} {MONTHS[now.month - 1]}"
    body = (f"<h1>{html.escape(title)}</h1><p class=\"center\"><i>Musicians born and died on this date</i></p><ul>"
            + "".join(f"<li>{html.escape(i)}</li>" for i in items) + "</ul>")
    return body, sum(len(i) for i in items)


# -------------------------------- sudoku -----------------------------------

def _solve_count(grid, limit=2):
    """Count solutions of a sudoku (stops at `limit`)."""
    count = 0

    def candidates(i):
        r, c = divmod(i, 9)
        used = set(grid[r * 9:(r + 1) * 9]) | {grid[k * 9 + c] for k in range(9)}
        br, bc = r // 3 * 3, c // 3 * 3
        for rr in range(br, br + 3):
            for cc in range(bc, bc + 3):
                used.add(grid[rr * 9 + cc])
        return [v for v in range(1, 10) if v not in used]

    def rec():
        nonlocal count
        best, best_c = None, None
        for i in range(81):
            if grid[i] == 0:
                cands = candidates(i)
                if not cands:
                    return
                if best is None or len(cands) < len(best_c):
                    best, best_c = i, cands
                    if len(cands) == 1:
                        break
        if best is None:
            count += 1
            return
        for v in best_c:
            grid[best] = v
            rec()
            grid[best] = 0
            if count >= limit:
                return

    rec()
    return count


def sudoku_solution(rng):
    def pattern(r, c):
        return (3 * (r % 3) + r // 3 + c) % 9
    groups = list(range(3))
    rows = [g * 3 + r for g in rng.sample(groups, 3) for r in rng.sample(groups, 3)]
    cols = [g * 3 + c for g in rng.sample(groups, 3) for c in rng.sample(groups, 3)]
    nums = rng.sample(range(1, 10), 9)
    return [nums[pattern(r, c)] for r in rows for c in cols]


def sudoku_puzzle(rng, givens=34):
    solution = sudoku_solution(rng)
    puzzle = solution[:]
    cells = list(range(81))
    rng.shuffle(cells)
    filled = 81
    for i in cells:
        if filled <= givens:
            break
        keep = puzzle[i]
        puzzle[i] = 0
        if _solve_count(puzzle[:], 2) == 1:
            filled -= 1
        else:
            puzzle[i] = keep
    return puzzle, solution


def sudoku_table(grid, small=False):
    rows = []
    for r in range(9):
        tds = []
        for c in range(9):
            cls = []
            if c % 3 == 2 and c < 8:
                cls.append("br")
            if r % 3 == 2 and r < 8:
                cls.append("bb")
            v = grid[r * 9 + c]
            tds.append(f'<td class="{" ".join(cls)}">{v if v else "&#160;"}</td>')
        rows.append("<tr>" + "".join(tds) + "</tr>")
    klass = "sudoku small" if small else "sudoku"
    return f'<table class="{klass}">' + "".join(rows) + "</table>"


def sudoku_html(now):
    rng = random.Random(int(now.strftime("%Y%m%d")))
    puzzle, solution = sudoku_puzzle(rng)
    return ("<h1>Coffee Break</h1><p class=\"center\"><i>Today’s sudoku</i></p>"
            + sudoku_table(puzzle)
            + "<h3>Solution</h3>" + sudoku_table(solution, small=True))


# ----------------------- private sections (calendar, villa) -----------------
# These are only built when the repository is PRIVATE and the secret links exist.

def get_ics_events(url, start, end):
    import icalendar
    import recurring_ical_events
    cal = icalendar.Calendar.from_ical(http_get(url))
    out = []
    for ev in recurring_ical_events.of(cal).between(start, end):
        s = ev["DTSTART"].dt
        e = ev["DTEND"].dt if "DTEND" in ev else s
        all_day = not isinstance(s, dt.datetime)
        if not all_day:
            s = s.astimezone(TZ) if s.tzinfo else s.replace(tzinfo=TZ)
        out.append({"start": s, "end": e, "all_day": all_day,
                    "summary": str(ev.get("SUMMARY", "")), "location": str(ev.get("LOCATION", "")),
                    "description": str(ev.get("DESCRIPTION", ""))})
    out.sort(key=lambda x: dt.datetime.combine(x["start"], dt.time.min, tzinfo=TZ)
             if x["all_day"] else x["start"])
    return out


def week_html(events, now):
    days = {}
    for ev in events:
        d = ev["start"] if ev["all_day"] else ev["start"].date()
        days.setdefault(d, []).append(ev)
    parts = []
    if not days:
        parts.append('<p class="center">Nothing in your calendar for the next 7 days.</p>')
    for d in sorted(days):
        label = "Today" if d == now.date() else f"{WEEKDAYS[d.weekday()]} {d.day} {MONTHS[d.month - 1][:3]}"
        parts.append(f"<h3>{html.escape(label)}</h3><ul>")
        for ev in days[d]:
            when = "all day" if ev["all_day"] else ev["start"].strftime("%H:%M")
            line = f"{when} – {ev['summary']}"
            if ev["location"]:
                line += f" ({ev['location']})"
            item = html.escape(line)
            prog = [ln.strip() for ln in ev["description"].splitlines() if ln.strip()][:4]
            if prog:
                item += "<br/>" + "<br/>".join(html.escape(ln) for ln in prog)
            parts.append(f"<li>{item}</li>")
        parts.append("</ul>")
    return "".join(parts)


def villa_html(events, now):
    """Arrivals and departures only: dates, no guest names."""
    def fmt(d):
        return f"{WEEKDAYS[d.weekday()][:3]} {d.day} {MONTHS[d.month - 1][:3]}"
    lines = []
    for ev in events:
        s = ev["start"] if ev["all_day"] else ev["start"].date()
        e = ev["end"]
        e = e if not isinstance(e, dt.datetime) else e.date()
        if s <= now.date() < e:
            lines.append(f"Guests in the house until {fmt(e)}")
        elif s > now.date():
            lines.append(f"Arrival {fmt(s)}, departure {fmt(e)}")
    if not lines:
        lines = ["No bookings in the next 3 weeks."]
    return "<h3>Villa Kinkeli</h3><ul>" + "".join(f"<li>{html.escape(x)}</li>" for x in lines) + "</ul>"


def private_html(now):
    cal_url = os.environ.get("CALENDAR_ICS_URL", "").strip()
    villa_url = os.environ.get("VILLA_ICS_URL", "").strip()
    if not (cal_url or villa_url):
        return ""
    if os.environ.get("REPO_PRIVATE", "").lower() != "true":
        problems.append("Personal sections skipped: the repository is public. They are only built in a private repository.")
        return ""
    start = dt.datetime.combine(now.date(), dt.time.min, tzinfo=TZ)
    body = ""
    if cal_url:
        try:
            body += week_html(get_ics_events(cal_url, start, start + dt.timedelta(days=7)), now)
        except Exception as exc:  # noqa: BLE001
            problems.append(f"Calendar: {exc}")
    if villa_url:
        try:
            body += villa_html(get_ics_events(villa_url, start, start + dt.timedelta(days=21)), now)
        except Exception as exc:  # noqa: BLE001
            problems.append(f"Villa calendar: {exc}")
    return f"<h1>Your Week</h1>{body}" if body else ""


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


def make_cover(date_label, section_titles):
    W, H = 1200, 1600
    img = Image.new("L", (W, H), 255)
    d = ImageDraw.Draw(img)
    d.rectangle([36, 36, W - 36, H - 36], outline=0, width=8)
    d.rectangle([56, 56, W - 56, H - 56], outline=0, width=2)
    margin = 110
    inner = W - 2 * margin

    centered(d, 100, "VIENNA  ·  MORNING EDITION", load_font(34, bold=False), W)
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
    y += bar_h + 60

    centered(d, y, "IN THIS ISSUE", load_font(36), W)
    y += 62
    d.rectangle([W / 2 - 60, y, W / 2 + 60, y + 3], fill=0)
    y += 34

    f_s = load_font(38, bold=False)
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
        y += 66

    for cx in (W / 2 - 90, W / 2, W / 2 + 90):  # three small diamonds
        cy = H - 205
        d.polygon([(cx, cy - 22), (cx + 22, cy), (cx, cy + 22), (cx - 22, cy)], fill=0)
    centered(d, H - 150, "Freshly printed for you, every morning", load_font(32, bold=False), W)

    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=88)
    return buf.getvalue()


# ------------------------------ book pages ---------------------------------

def article_html(a):
    paras = []
    for i, p in enumerate(a["paras"]):
        cls = ' class="first"' if i == 0 else ""
        paras.append(f"<p{cls}>{html.escape(p)}</p>")
    note = f'<p class="first"><i>{html.escape(a["note"])}</i></p>' if a.get("note") else ""
    return (f"<h2>{html.escape(a['title'])}</h2>"
            f"<p class=\"byline\">{html.escape(a['source'])}</p>" + note + "".join(paras))


def main():
    import feedparser  # noqa: F401  (fails early with a clear message if missing)
    from ebooklib import epub

    now = dt.datetime.now(TZ)
    date_label = f"{WEEKDAYS[now.weekday()]}, {now.day} {MONTHS[now.month - 1]} {now.year}"

    collected = []
    for section in SECTIONS:
        articles = collect_section(section)
        if section["title"] == "Early Music":
            video = ems_video(now)
            if video:
                articles = [video] + articles[:1]
        if articles:
            collected.append((section["title"], articles))

    total = sum(len(a) for _, a in collected)
    if total == 0:
        print("No articles found. Problems:", *problems, sep="\n- ")
        sys.exit(1)

    fixed = [a for _, arts in collected for a in arts if a.get("max_chars")]
    normal_count = max(1, total - len(fixed))
    share = (TOTAL_BUDGET - sum(a["max_chars"] for a in fixed)) // normal_count
    per_article = max(MIN_PER_ARTICLE, min(MAX_PER_ARTICLE, share))
    chars = 0
    for _, articles in collected:
        for a in articles:
            a["paras"] = shorten(a["text"], a.get("max_chars") or per_article)
            chars += sum(len(p) for p in a["paras"])

    weather_body, weather_chars = weather_html()
    private_body = private_html(now)
    otd_body, otd_chars = on_this_day_html(now)
    sudoku_body = sudoku_html(now)
    extra_chars = weather_chars + otd_chars + len(re.sub(r"<[^>]+>", "", private_body))
    est_pages = max(1, round((chars + extra_chars) / 1700) + 3)

    cover_titles = [t for t, _ in collected]
    if private_body:
        cover_titles.insert(0, "Your Week")
    if otd_body:
        cover_titles.append("On This Day")
    cover_titles.append("Coffee Break")

    book = epub.EpubBook()
    book.set_identifier(f"morningpaper-{now:%Y%m%d%H%M}")
    book.set_title(f"{PAPER_NAME} – {date_label}")
    book.set_language("en")
    book.add_author(PAPER_NAME)
    book.set_cover("cover.jpg", make_cover(date_label, cover_titles))

    css = epub.EpubItem(uid="style", file_name="style/paper.css", media_type="text/css", content=CSS)
    book.add_item(css)

    def add_chapter(title, file_name, body):
        ch = epub.EpubHtml(title=title, file_name=file_name, lang="en")
        ch.content = body
        ch.add_item(css)
        book.add_item(ch)
        return ch

    # front page: weather and headlines of the whole issue
    front = [f"<h1>{html.escape(PAPER_NAME)}</h1>",
             f'<p class="date">{html.escape(date_label)}</p>', weather_body,
             '<p class="center"><b>In this issue</b></p>']
    for title, articles in collected:
        front.append(f"<h3>{html.escape(title)}</h3><ul>")
        front += [f"<li>{html.escape(a['title'])}</li>" for a in articles]
        front.append("</ul>")
    chapters = [add_chapter("Front page", "front.xhtml", "".join(front))]

    if private_body:
        chapters.append(add_chapter("Your Week", "week.xhtml", private_body))
    for i, (title, articles) in enumerate(collected, start=1):
        body = f"<h1>{html.escape(title)}</h1>" + "".join(article_html(a) for a in articles)
        chapters.append(add_chapter(title, f"section{i}.xhtml", body))
    if otd_body:
        chapters.append(add_chapter("On This Day", "onthisday.xhtml", otd_body))
    chapters.append(add_chapter("Coffee Break", "sudoku.xhtml", sudoku_body))

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
