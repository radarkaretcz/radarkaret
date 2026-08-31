import json
from pathlib import Path
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus

import feedparser


# -------------------------------------------
# ZDROJE RADARU
# -------------------------------------------

SOURCES = [
    {
        "game": "Pokémon",
        "category": "pokemon",
        "query": 'site:pokemon.com/us/pokemon-news "Trading Card Game"',
    },
    {
        "game": "One Piece",
        "category": "onepiece",
        "query": "site:en.onepiece-cardgame.com",
    },
    {
        "game": "Disney Lorcana",
        "category": "lorcana",
        "query": "site:disneylorcana.com",
    },
]


def google_news_feed(query):
    q = quote_plus(query)

    return (
        "https://news.google.com/rss/search"
        f"?q={q}"
        "&hl=en-US"
        "&gl=US"
        "&ceid=US:en"
    )


def parse_date(entry):

    try:
        if getattr(entry, "published", None):
            dt = parsedate_to_datetime(entry.published)

            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)

            return dt

    except Exception:
        pass

    return datetime.now(timezone.utc)


items = []


for source in SOURCES:

    url = google_news_feed(source["query"])

    feed = feedparser.parse(url)

    for entry in feed.entries[:15]:

        published = parse_date(entry)

        items.append({
            "game": source["game"],
            "category": source["category"],
            "title": entry.get("title", "").strip(),
            "url": entry.get("link", ""),
            "published": published.isoformat(),
            "date": published.strftime("%d.%m.%Y"),
            "source_type": "official-monitor",
        })


# -------------------------------------------
# ODSTRANĚNÍ DUPLICIT
# -------------------------------------------

unique = {}

for item in items:

    key = (
        item["category"],
        item["title"].lower()
    )

    unique[key] = item


items = list(unique.values())


# -------------------------------------------
# NEJNOVĚJŠÍ NAHORU
# -------------------------------------------

items.sort(
    key=lambda item: item["published"],
    reverse=True
)


# maximálně posledních 60 zpráv
items = items[:60]


# -------------------------------------------
# ULOŽENÍ JSON
# -------------------------------------------

output = Path("data/news.json")

output.parent.mkdir(
    parents=True,
    exist_ok=True
)


with output.open(
    "w",
    encoding="utf-8"
) as f:

    json.dump(
        items,
        f,
        ensure_ascii=False,
        indent=2
    )


print(
    f"RadarKaret: uloženo {len(items)} zpráv."
)
