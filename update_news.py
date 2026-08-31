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


# ============================================================
# RADARKARET.CZ
# Automatický sběr TCG novinek
# ============================================================


# ------------------------------------------------------------
# NASTAVENÍ
# ------------------------------------------------------------

MAX_PER_SOURCE = 12
MAX_AGE_DAYS = 180
MAX_TOTAL_ARTICLES = 80

OUTPUT_FILE = Path("data/news.json")


SOURCES = [

    {
        "game": "Pokémon",
        "category": "pokemon",
        "query": 'site:pokemon.com "Trading Card Game"',
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

    {
        "game": "Magic",
        "category": "magic",
        "query": "site:magic.wizards.com",
    },

    {
        "game": "Yu-Gi-Oh!",
        "category": "yugioh",
        "query": "site:yugioh-card.com",
    },

    {
        "game": "Star Wars Unlimited",
        "category": "starwars",
        "query": "site:starwarsunlimited.com",
    },

]


HEADERS = {

    "User-Agent":
        "Mozilla/5.0 "
        "(Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36 "
        "RadarKaret/1.0",

    "Accept-Language":
        "en-US,en;q=0.9",

}


translator = GoogleTranslator(
    source="auto",
    target="cs"
)


# ------------------------------------------------------------
# GOOGLE NEWS RSS
# ------------------------------------------------------------

def google_news_feed(query):

    encoded = quote_plus(query)

    return (
        "https://news.google.com/rss/search"
        f"?q={encoded}"
        "&hl=en-US"
        "&gl=US"
        "&ceid=US:en"
    )


# ------------------------------------------------------------
# DATUM
# ------------------------------------------------------------

def parse_entry_date(entry):

    try:

        published = getattr(
            entry,
            "published",
            None
        )

        if published:

            dt = parsedate_to_datetime(
                published
            )

            if dt.tzinfo is None:

                dt = dt.replace(
                    tzinfo=timezone.utc
                )

            return dt.astimezone(
                timezone.utc
            )

    except Exception as error:

        print(
            "Chyba při čtení data:",
            error
        )

    return datetime.now(
        timezone.utc
    )


# ------------------------------------------------------------
# ČIŠTĚNÍ TEXTU
# ------------------------------------------------------------

def clean_text(text):

    if not text:
        return ""

    text = re.sub(
        r"\s+",
        " ",
        text
    )

    return text.strip()


def clean_title(text):

    text = clean_text(text)

    if not text:
        return ""

    patterns = [

        r"\s*-\s*Pokemon\.com$",

        r"\s*-\s*Pokémon.*$",

        r"\s*-\s*ONE PIECE CARD GAME.*$",

        r"\s*-\s*Disney Lorcana.*$",

        r"\s*\|\s*Disney Lorcana.*$",

        r"\s*-\s*Magic.*$",

        r"\s*-\s*Wizards of the Coast.*$",

        r"\s*-\s*Yu-Gi-Oh!.*$",

        r"\s*-\s*Star Wars Unlimited.*$",

    ]

    for pattern in patterns:

        text = re.sub(
            pattern,
            "",
            text,
            flags=re.IGNORECASE
        )

    return text.strip()


# ------------------------------------------------------------
# DEKÓDOVÁNÍ GOOGLE NEWS URL
# ------------------------------------------------------------

def resolve_original_url(url):

    if not url:
        return ""

    if "news.google.com" not in url:
        return url

    try:

        result = gnewsdecoder(
            url,
            interval=0.5
        )

        if isinstance(result, dict):

            decoded = (
                result.get("decoded_url")
                or
                result.get("url")
            )

            if decoded:
                return decoded

    except Exception as error:

        print(
            "Nepodařilo se dekódovat Google News URL:",
            error
        )

    return url


# ------------------------------------------------------------
# META DATA ORIGINÁLNÍHO ČLÁNKU
# ------------------------------------------------------------

def get_article_metadata(url):

    result = {

        "url": url,

        "title": "",

        "description": "",

        "image": "",

    }

    if not url:
        return result

    if "news.google.com" in url:
        return result

    try:

        response = requests.get(

            url,

            headers=HEADERS,

            timeout=20,

            allow_redirects=True,

        )

        response.raise_for_status()

        result["url"] = response.url

        soup = BeautifulSoup(
            response.text,
            "html.parser"
        )


        # ----------------------------------------------------
        # Pomocná funkce pro meta tag
        # ----------------------------------------------------

        def meta_content(selectors):

            for selector in selectors:

                tag = soup.select_one(
                    selector
                )

                if not tag:
                    continue

                content = tag.get(
                    "content"
                )

                if content:

                    return clean_text(
                        content
                    )

            return ""


        # ----------------------------------------------------
        # TITULEK
        # ----------------------------------------------------

        result["title"] = meta_content([

            'meta[property="og:title"]',

            'meta[name="twitter:title"]',

        ])


        if (
            not result["title"]
            and
            soup.title
        ):

            result["title"] = clean_text(

                soup.title.get_text(
                    " ",
                    strip=True
                )

            )


        # ----------------------------------------------------
        # POPIS
        # ----------------------------------------------------

        result["description"] = meta_content([

            'meta[property="og:description"]',

            'meta[name="description"]',

            'meta[name="twitter:description"]',

        ])


        # ----------------------------------------------------
        # OBRÁZEK
        # ----------------------------------------------------

        result["image"] = meta_content([

            'meta[property="og:image"]',

            'meta[property="og:image:secure_url"]',

            'meta[name="twitter:image"]',

            'meta[property="twitter:image"]',

        ])


        if result["image"]:

            result["image"] = urljoin(

                response.url,

                result["image"]

            )


        # ----------------------------------------------------
        # CANONICAL URL
        # ----------------------------------------------------

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

                canonical.get("href")

            )

    except Exception as error:

        print(
            "Nepodařilo se načíst článek:",
            url,
            error
        )

    return result


# ------------------------------------------------------------
# PŘEKLAD DO ČEŠTINY
# ------------------------------------------------------------

def translate_to_czech(
    text,
    max_length=1000
):

    text = clean_text(text)

    if not text:
        return ""

    text = text[:max_length]

    try:

        translated = translator.translate(
            text
        )

        if translated:

            return clean_text(
                translated
            )

    except Exception as error:

        print(
            "Překlad selhal:",
            error
        )

    # pokud bezplatný překlad selže,
    # necháme původní text

    return text


# ------------------------------------------------------------
# NAČTENÍ STARÉHO NEWS.JSON
# ------------------------------------------------------------

def load_old_data():

    if not OUTPUT_FILE.exists():

        return []

    try:

        return json.loads(

            OUTPUT_FILE.read_text(
                encoding="utf-8"
            )

        )

    except Exception:

        return []


# ------------------------------------------------------------
# CACHE
# ------------------------------------------------------------

def build_cache(old_items):

    cache = {}

    for item in old_items:

        original_title = (

            item.get("title_original")
            or
            item.get("title")
            or
            ""

        )

        original_title = clean_text(
            original_title
        ).lower()

        category = item.get(
            "category",
            ""
        )

        if original_title:

            cache[
                (
                    category,
                    original_title
                )
            ] = item

    return cache


old_items = load_old_data()

cache = build_cache(
    old_items
)


# ------------------------------------------------------------
# ČASOVÁ HRANICE
# ------------------------------------------------------------

cutoff = (

    datetime.now(
        timezone.utc
    )

    -

    timedelta(
        days=MAX_AGE_DAYS
    )

)


# ------------------------------------------------------------
# SBĚR DAT
# ------------------------------------------------------------

items = []


for source in SOURCES:

    print(
        "\nSleduji:",
        source["game"]
    )

    rss_url = google_news_feed(
        source["query"]
    )

    feed = feedparser.parse(
        rss_url
    )

    accepted = 0


    for entry in feed.entries:

        if accepted >= MAX_PER_SOURCE:
            break


        # ----------------------------------------------------
        # DATUM
        # ----------------------------------------------------

        published = parse_entry_date(
            entry
        )


        if published < cutoff:
            continue


        # ----------------------------------------------------
        # RSS TITULEK
        # ----------------------------------------------------

        rss_title = clean_title(

            entry.get(
                "title",
                ""
            )

        )


        if not rss_title:
            continue


        # ----------------------------------------------------
        # ZKONTROLUJ CACHE
        # ----------------------------------------------------

        cache_key = (

            source["category"],

            rss_title.lower(),

        )


        cached = cache.get(
            cache_key
        )


        if cached:

            # už jsme zprávu zpracovali dříve

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


        # ----------------------------------------------------
        # GOOGLE NEWS ODKAZ
        # ----------------------------------------------------

        google_url = entry.get(
            "link",
            ""
        )


        # ----------------------------------------------------
        # PŮVODNÍ ODKAZ
        # ----------------------------------------------------

        original_url = resolve_original_url(
            google_url
        )


        # ----------------------------------------------------
        # DATA ORIGINÁLNÍHO ČLÁNKU
        # ----------------------------------------------------

        meta = get_article_metadata(
            original_url
        )


        # ----------------------------------------------------
        # PŮVODNÍ TITULEK
        # ----------------------------------------------------

        original_title = clean_title(

            meta.get("title")
            or
            rss_title

        )


        if not original_title:

            original_title = (
                rss_title
            )


        # ----------------------------------------------------
        # POPIS
        # ----------------------------------------------------

        original_description = clean_text(

            meta.get(
                "description",
                ""
            )

        )


        # ----------------------------------------------------
        # ČESKÝ TITULEK
        # ----------------------------------------------------

        title_cs = translate_to_czech(

            original_title,

            max_length=350

        )


        # ----------------------------------------------------
        # ČESKÝ POPIS
        # ----------------------------------------------------

        if original_description:

            summary_cs = translate_to_czech(

                original_description,

                max_length=900

            )

        else:

            summary_cs = (

                "Aktuální informace "
                "ze světa "
                f"{source['game']}."

            )


        # ----------------------------------------------------
        # OBRÁZEK
        # ----------------------------------------------------

        image = meta.get(
            "image",
            ""
        )


        # ----------------------------------------------------
        # KONEČNÁ URL
        # ----------------------------------------------------

        final_url = (

            meta.get("url")
            or
            original_url
            or
            google_url

        )


        # ----------------------------------------------------
        # VYTVOŘ ZÁZNAM
        # ----------------------------------------------------

        item = {

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

            "summary_original":
                original_description,

            "image":
                image,

            "url":
                final_url,

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

        }


        items.append(
            item
        )


        accepted += 1


        print(
            " +",
            source["game"],
            "-",
            title_cs[:80]
        )


        # malá pauza, abychom weby
        # zbytečně nezatěžovali

        time.sleep(
            0.4
        )


# ------------------------------------------------------------
# ODSTRANĚNÍ DUPLICIT
# ------------------------------------------------------------

unique = {}


for item in items:

    title_key = (

        item.get(
            "title_original"
        )

        or

        item.get(
            "title"
        )

        or ""

    )


    title_key = clean_text(
        title_key
    ).lower()


    key = (

        item.get(
            "category",
            ""
        ),

        title_key

    )


    if not title_key:
        continue


    existing = unique.get(
        key
    )


    # pokud už máme stejný článek,
    # necháme verzi s obrázkem

    if existing:

        if (
            not existing.get("image")
            and
            item.get("image")
        ):

            unique[key] = item

    else:

        unique[key] = item


items = list(
    unique.values()
)


# ------------------------------------------------------------
# ŘAZENÍ PODLE DATA
# ------------------------------------------------------------

items.sort(

    key=lambda item:
        item.get(
            "published",
            ""
        ),

    reverse=True

)


# ------------------------------------------------------------
# LIMIT
# ------------------------------------------------------------

items = items[
    :MAX_TOTAL_ARTICLES
]


# ------------------------------------------------------------
# ULOŽENÍ
# ------------------------------------------------------------

OUTPUT_FILE.parent.mkdir(

    parents=True,

    exist_ok=True

)


OUTPUT_FILE.write_text(

    json.dumps(

        items,

        ensure_ascii=False,

        indent=2

    ),

    encoding="utf-8"

)


# ------------------------------------------------------------
# STATISTIKA
# ------------------------------------------------------------

counts = {}

for item in items:

    game = item.get(
        "game",
        "Ostatní"
    )

    counts[game] = (
        counts.get(
            game,
            0
        )
        +
        1
    )


print("\n==============================")

print(
    "RADARKARET HOTOVO"
)

print(
    "Celkem zpráv:",
    len(items)
)

print(
    "Zapsáno do:",
    OUTPUT_FILE
)

print(
    "Kategorie:"
)

for game, count in counts.items():

    print(
        f" - {game}: {count}"
    )

print("==============================")
