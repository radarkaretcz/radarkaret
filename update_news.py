import json
import re
import time

from pathlib import Path
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus, urljoin

import feedparser
import requests

from bs4 import BeautifulSoup
from deep_translator import GoogleTranslator
from googlenewsdecoder import gnewsdecoder


# =========================================================
# NASTAVENÍ
# =========================================================

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


MAX_AGE_DAYS = 180

MAX_PER_SOURCE = 10


HEADERS = {

    "User-Agent":
        "Mozilla/5.0 "
        "(Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 "
        "Chrome/124 Safari/537.36 "
        "RadarKaret/1.0",

    "Accept-Language":
        "en-US,en;q=0.9",

}


translator = GoogleTranslator(
    source="auto",
    target="cs"
)


# =========================================================
# GOOGLE NEWS
# =========================================================

def google_news_feed(query):

    q = quote_plus(query)

    return (
        "https://news.google.com/rss/search"
        f"?q={q}"
        "&hl=en-US"
        "&gl=US"
        "&ceid=US:en"
    )


# =========================================================
# DATUM
# =========================================================

def parse_date(entry):

    try:

        if getattr(
            entry,
            "published",
            None
        ):

            dt = parsedate_to_datetime(
                entry.published
            )

            if dt.tzinfo is None:

                dt = dt.replace(
                    tzinfo=timezone.utc
                )

            return dt.astimezone(
                timezone.utc
            )

    except Exception:
        pass

    return datetime.now(
        timezone.utc
    )


# =========================================================
# ČIŠTĚNÍ TITULKU
# =========================================================

def clean_title(text):

    if not text:
        return ""

    text = re.sub(
        r"\s+",
        " ",
        text
    ).strip()


    suffixes = [

        r"\s*-\s*Pokemon\.com$",

        r"\s*-\s*ONE PIECE CARD GAME\s*-\s*Official Web Site$",

        r"\s*-\s*disneylorcana\.com$",

        r"\s*\|\s*Disney Lorcana TCG by Ravensburger\s*-\s*disneylorcana\.com$",

    ]


    for pattern in suffixes:

        text = re.sub(
            pattern,
            "",
            text,
            flags=re.I
        )


    return text.strip()


# =========================================================
# PŮVODNÍ URL ČLÁNKU
# =========================================================

def resolve_original_url(
    google_url
):

    if (
        not google_url
        or
        "news.google.com"
        not in google_url
    ):
        return google_url


    try:

        result = gnewsdecoder(
            google_url,
            interval=0.3
        )


        if (
            isinstance(
                result,
                dict
            )
            and
            result.get("status")
        ):

            return (
                result.get(
                    "decoded_url"
                )
                or google_url
            )


    except Exception as exc:

        print(
            "Google News URL "
            f"se nepodařilo rozbalit: {exc}"
        )


    return google_url


# =========================================================
# DATA Z ORIGINÁLNÍHO ČLÁNKU
# =========================================================

def get_article_meta(url):

    result = {

        "title": "",

        "description": "",

        "image": "",

        "url": url,

    }


    if (
        not url
        or
        "news.google.com"
        in url
    ):
        return result


    try:

        response = requests.get(

            url,

            headers=HEADERS,

            timeout=15,

            allow_redirects=True,

        )


        response.raise_for_status()


        result["url"] = (
            response.url
        )


        soup = BeautifulSoup(
            response.text,
            "html.parser"
        )


        def meta_value(
            *selectors
        ):

            for selector in selectors:

                tag = soup.select_one(
                    selector
                )

                if tag:

                    value = tag.get(
                        "content"
                    )

                    if value:
                        return value.strip()

            return ""


        # TITULEK

        result["title"] = meta_value(

            'meta[property="og:title"]',

            'meta[name="twitter:title"]',

        )


        if (
            not result["title"]
            and soup.title
        ):

            result["title"] = (
                soup.title.get_text(
                    " ",
                    strip=True
                )
            )


        # POPIS

        result["description"] = (
            meta_value(

                'meta[property="og:description"]',

                'meta[name="description"]',

                'meta[name="twitter:description"]',

            )
        )


        # ORIGINÁLNÍ OBRÁZEK

        result["image"] = (
            meta_value(

                'meta[property="og:image"]',

                'meta[name="twitter:image"]',

                'meta[property="twitter:image"]',

            )
        )


        if result["image"]:

            result["image"] = (
                urljoin(
                    response.url,
                    result["image"]
                )
            )


        # CANONICAL URL

        canonical = soup.select_one(
            'link[rel="canonical"]'
        )


        if (
            canonical
            and
            canonical.get("href")
        ):

            result["url"] = urljoin(

                response.url,

                canonical["href"]

            )


    except Exception as exc:

        print(
            "Metadata článku "
            f"se nepodařila načíst: "
            f"{url} -> {exc}"
        )


    return result


# =========================================================
# PŘEKLAD DO ČEŠTINY
# =========================================================

def translate_cs(
    text,
    max_chars=1200
):

    text = (
        text or ""
    ).strip()


    if not text:
        return ""


    text = text[
        :max_chars
    ]


    try:

        translated = (
            translator.translate(
                text
            )
        )


        return (
            translated
            or text
        ).strip()


    except Exception as exc:

        print(
            f"Překlad selhal: {exc}"
        )

        return text


# =========================================================
# CACHE
# =========================================================

def load_cache():

    path = Path(
        "data/news.json"
    )


    if not path.exists():
        return {}


    try:

        old_items = json.loads(

            path.read_text(
                encoding="utf-8"
            )

        )

    except Exception:
        return {}


    cache = {}


    for item in old_items:

        original = (

            item.get(
                "title_original"
            )

            or

            item.get(
                "title"
            )

            or ""

        ).lower().strip()


        category = item.get(
            "category",
            ""
        )


        if original:

            cache[
                (
                    category,
                    original
                )
            ] = item


    return cache


# =========================================================
# SBĚR ZPRÁV
# =========================================================

cache = load_cache()


cutoff = (

    datetime.now(
        timezone.utc
    )

    -

    timedelta(
        days=MAX_AGE_DAYS
    )

)


items = []


for source in SOURCES:


    feed = feedparser.parse(

        google_news_feed(
            source["query"]
        )

    )


    accepted = 0


    for entry in feed.entries:


        if accepted >= MAX_PER_SOURCE:
            break


        published = parse_date(
            entry
        )


        # ignoruj příliš staré výsledky

        if published < cutoff:
            continue


        rss_title = clean_title(

            entry.get(
                "title",
                ""
            )

        )


        if not rss_title:
            continue


        key = (

            source["category"],

            rss_title.lower(),

        )


        cached = cache.get(
            key
        )


        # pokud už máme obrázek i překlad,
        # nemusíme všechno zpracovávat znovu

        if (
            cached
            and
            cached.get("image")
            and
            cached.get("title")
        ):

            item = dict(
                cached
            )


            item["published"] = (
                published.isoformat()
            )


            item["date"] = (
                published.strftime(
                    "%d.%m.%Y"
                )
            )


            items.append(
                item
            )


            accepted += 1

            continue


        google_url = entry.get(
            "link",
            ""
        )


        original_url = (
            resolve_original_url(
                google_url
            )
        )


        meta = get_article_meta(
            original_url
        )


        original_title = clean_title(

            meta["title"]
            or
            rss_title

        )


        original_description = (

            meta["description"]
            or ""

        ).strip()


        # ČESKÝ TITULEK

        title_cs = translate_cs(

            original_title,

            350

        )


        # ČESKÝ POPIS

        if original_description:

            summary_cs = translate_cs(

                original_description,

                850

            )

        else:

            summary_cs = (
                "Aktuální informace "
                "z oficiálního zdroje."
            )


        items.append({

            "game":
                source["game"],

            "category":
                source["category"],

            "title":
                title_cs,

            "title_original":
                original_title,

            "summary":
                summary_cs,

            "image":
                meta["image"],

            "url":
                meta["url"]
                or
                original_url,

            "google_news_url":
                google_url,

            "published":
                published.isoformat(),

            "date":
                published.strftime(
                    "%d.%m.%Y"
                ),

            "source_type":
                "official-monitor",

        })


        accepted += 1


        time.sleep(
            0.25
        )


# =========================================================
# DUPLICITY
# =========================================================

unique = {}


for item in items:

    key = (

        item["category"],

        (
            item.get(
                "title_original"
            )
            or
            item["title"]
        ).lower(),

    )


    unique[key] = item


items = list(
    unique.values()
)


# =========================================================
# NEJNOVĚJŠÍ NAHORU
# =========================================================

items.sort(

    key=lambda item:
        item["published"],

    reverse=True

)


items = items[:60]


# =========================================================
# ULOŽIT
# =========================================================

output = Path(
    "data/news.json"
)


output.parent.mkdir(

    parents=True,

    exist_ok=True

)


output.write_text(

    json.dumps(

        items,

        ensure_ascii=False,

        indent=2

    ),

    encoding="utf-8"

)


print(

    "RadarKaret: "
    f"uloženo {len(items)} "
    "zpráv v češtině."

)
