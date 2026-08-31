import json
import re
import time
from pathlib import Path
from datetime import datetime, timezone, timedelta
from urllib.parse import urljoin, urlparse, urldefrag

import requests
from bs4 import BeautifulSoup
from deep_translator import GoogleTranslator


# ============================================================
# RADARKARET.CZ
# ČISTÝ SBĚR OFICIÁLNÍCH TCG NOVINEK
# ============================================================

OUTPUT = Path("data/news.json")

MAX_PER_SOURCE = 10
MAX_TOTAL = 60
MAX_AGE_DAYS = 180

PIPELINE_VERSION = 4


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36 RadarKaret/1.0"
    ),
    "Accept-Language": "en-US,en;q=0.9"
}


SOURCES = [
    {
        "game": "Pokémon",
        "category": "pokemon",
        "url": "https://www.pokemon.com/us/pokemon-news/",
        "domain": "pokemon.com"
    },
    {
        "game": "One Piece",
        "category": "onepiece",
        "url": "https://en.onepiece-cardgame.com/news/",
        "domain": "en.onepiece-cardgame.com"
    },
    {
        "game": "Disney Lorcana",
        "category": "lorcana",
        "url": "https://www.disneylorcana.com/en-US/news/",
        "domain": "disneylorcana.com"
    },
    {
        "game": "Magic",
        "category": "magic",
        "url": "https://magic.wizards.com/en/news",
        "domain": "magic.wizards.com"
    },
    {
        "game": "Yu-Gi-Oh!",
        "category": "yugioh",
        "url": "https://www.yugioh-card.com/eu/news/?view=all",
        "domain": "yugioh-card.com"
    },
    {
        "game": "Star Wars Unlimited",
        "category": "starwars",
        "url": "https://starwarsunlimited.com/articles",
        "domain": "starwarsunlimited.com"
    }
]


session = requests.Session()
session.headers.update(HEADERS)

translator = GoogleTranslator(
    source="auto",
    target="cs"
)


# ============================================================
# ZÁKLADNÍ FUNKCE
# ============================================================

def clean(text):
    if not text:
        return ""

    return re.sub(
        r"\s+",
        " ",
        str(text)
    ).strip()


def normalize_url(url):
    if not url:
        return ""

    url, _ = urldefrag(url)

    return url.rstrip("/")


def same_domain(url, domain):
    try:
        hostname = (
            urlparse(url).hostname
            or ""
        ).lower()

        return (
            hostname == domain
            or hostname.endswith("." + domain)
        )

    except Exception:
        return False


def fetch(url):
    response = session.get(
        url,
        timeout=25,
        allow_redirects=True
    )

    response.raise_for_status()

    return (
        response.text,
        BeautifulSoup(
            response.text,
            "html.parser"
        ),
        response.url
    )


# ============================================================
# ČIŠTĚNÍ TITULKŮ
# ============================================================

def clean_title(text):
    text = clean(text)

    suffixes = [
        r"\s*\|\s*ONE PIECE CARD GAME.*$",
        r"\s*-\s*Official Web Site.*$",
        r"\s*\|\s*Magic: The Gathering.*$",
        r"\s*-\s*Yu-Gi-Oh!.*$",
        r"\s*\|\s*Disney Lorcana.*$",
        r"\s*-\s*Disney Lorcana.*$",
        r"\s*\|\s*Pokemon\.com.*$",
        r"\s*-\s*Pokemon\.com.*$"
    ]

    for pattern in suffixes:
        text = re.sub(
            pattern,
            "",
            text,
            flags=re.I
        )

    return clean(text)


JUNK_TITLES = {
    "products",
    "all products",
    "card list",
    "cards",
    "getting started",
    "for stores",
    "for beginners",
    "rules",
    "faq",
    "shop",
    "events",
    "news",
    "archive",
    "article archive",
    "latest releases",
    "booster packs",
    "structure decks",
    "starter decks",
    "accessories",
    "more articles",
    "view all",
    "learn to play",
    "digital",
    "arena direct | terms and conditions",
    "terms and conditions"
}


def title_is_junk(text):
    value = clean(text).lower()

    if not value:
        return True

    if value in JUNK_TITLES:
        return True

    if "error 500" in value:
        return True

    if "server error" in value:
        return True

    if value.startswith("product category:"):
        return True

    if value.startswith("article archive"):
        return True

    return False


# ============================================================
# PŘEKLAD
# ============================================================

def translate_cs(text, limit=1000):
    text = clean(text)[:limit]

    if not text:
        return ""

    try:
        result = translator.translate(text)

        if result:
            time.sleep(0.15)
            return clean(result)

    except Exception as exc:
        print("  Překlad selhal:", exc)

    return text


# ============================================================
# DATUM
# ============================================================

MONTH_PATTERN = (
    r"January|February|March|April|May|June|July|"
    r"August|September|October|November|December|"
    r"Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec"
)

DATE_REGEXES = [
    re.compile(
        rf"\b(?:{MONTH_PATTERN})\s+\d{{1,2}},\s+\d{{4}}\b",
        re.I
    ),
    re.compile(
        rf"\b\d{{1,2}}\s+(?:{MONTH_PATTERN})\s+\d{{4}}\b",
        re.I
    )
]

DATE_FORMATS = [
    "%B %d, %Y",
    "%b %d, %Y",
    "%d %B %Y",
    "%d %b %Y"
]


def parse_human_date(text):
    text = clean(text)

    for regex in DATE_REGEXES:
        match = regex.search(text)

        if not match:
            continue

        value = match.group(0)

        for fmt in DATE_FORMATS:
            try:
                return datetime.strptime(
                    value,
                    fmt
                ).replace(
                    tzinfo=timezone.utc
                )

            except ValueError:
                pass

    return None


def parse_iso_date(value):
    value = clean(value)

    if not value:
        return None

    try:
        value = value.replace(
            "Z",
            "+00:00"
        )

        date = datetime.fromisoformat(
            value
        )

        if date.tzinfo is None:
            date = date.replace(
                tzinfo=timezone.utc
            )

        return date.astimezone(
            timezone.utc
        )

    except Exception:
        return None


# ============================================================
# META DATA
# ============================================================

def meta_content(soup, selectors):
    for selector in selectors:
        tag = soup.select_one(selector)

        if not tag:
            continue

        value = tag.get("content")

        if value:
            return clean(value)

    return ""


def first_good_paragraph(soup):
    for p in soup.select(
        "article p, main p, .article p, .content p"
    ):
        text = clean(
            p.get_text(" ", strip=True)
        )

        if len(text) < 70:
            continue

        lower = text.lower()

        if any(
            word in lower
            for word in [
                "cookie",
                "privacy policy",
                "javascript",
                "all rights reserved"
            ]
        ):
            continue

        return text[:1200]

    return ""


def fallback_image(soup, base_url):
    for img in soup.select(
        "article img[src], main img[src], .article img[src]"
    ):
        src = (
            img.get("src")
            or img.get("data-src")
            or ""
        )

        if not src:
            continue

        src = urljoin(
            base_url,
            src
        )

        lower = src.lower()

        if any(
            word in lower
            for word in [
                "logo",
                "icon",
                "cookie",
                "avatar"
            ]
        ):
            continue

        return src

    return ""


# ============================================================
# ZÍSKÁNÍ DETAILU ČLÁNKU
# ============================================================

def get_article(url, fallback_date=None):
    try:
        html, soup, final_url = fetch(url)

    except Exception as exc:
        print(
            "  Nelze načíst:",
            url,
            exc
        )
        return None


    title = meta_content(
        soup,
        [
            'meta[property="og:title"]',
            'meta[name="twitter:title"]'
        ]
    )

    if not title:
        h1 = soup.select_one("h1")

        if h1:
            title = clean(
                h1.get_text(
                    " ",
                    strip=True
                )
            )

    if not title and soup.title:
        title = clean(
            soup.title.get_text(
                " ",
                strip=True
            )
        )


    title = clean_title(title)

    if title_is_junk(title):
        return None


    description = meta_content(
        soup,
        [
            'meta[property="og:description"]',
            'meta[name="description"]',
            'meta[name="twitter:description"]'
        ]
    )

    if not description:
        description = first_good_paragraph(
            soup
        )


    image = meta_content(
        soup,
        [
            'meta[property="og:image"]',
            'meta[property="og:image:secure_url"]',
            'meta[name="twitter:image"]'
        ]
    )

    if image:
        image = urljoin(
            final_url,
            image
        )

    else:
        image = fallback_image(
            soup,
            final_url
        )


    published = parse_iso_date(
        meta_content(
            soup,
            [
                'meta[property="article:published_time"]',
                'meta[name="date"]',
                'meta[name="publish-date"]'
            ]
        )
    )


    if not published:
        page_text = clean(
            soup.get_text(
                " ",
                strip=True
            )
        )

        published = parse_human_date(
            page_text[:5000]
        )


    if not published:
        published = fallback_date


    canonical = soup.select_one(
        'link[rel="canonical"]'
    )

    if (
        canonical
        and canonical.get("href")
    ):
        final_url = urljoin(
            final_url,
            canonical["href"]
        )


    return {
        "title_original": title,
        "summary_original": clean(description),
        "image": image,
        "url": normalize_url(final_url),
        "published": published
    }


# ============================================================
# DISCOVERY POMOCNÉ
# ============================================================

def link_context(a):
    text = [
        a.get_text(
            " ",
            strip=True
        )
    ]

    parent = a.parent

    for _ in range(2):
        if not parent:
            break

        text.append(
            parent.get_text(
                " ",
                strip=True
            )
        )

        parent = parent.parent

    return clean(
        " ".join(text)
    )


def add_candidate(result, seen, url, date=None):
    url = normalize_url(url)

    if not url:
        return

    if url in seen:
        return

    seen.add(url)

    result.append({
        "url": url,
        "date": date
    })


# ============================================================
# POKÉMON
# ============================================================

def discover_pokemon(source, html, soup, base_url):
    result = []
    seen = set()

    for a in soup.select("a[href]"):
        href = urljoin(
            base_url,
            a["href"]
        )

        if not same_domain(
            href,
            source["domain"]
        ):
            continue

        path = urlparse(href).path

        if not (
            path.startswith("/us/news/")
            or
            path.startswith("/us/pokemon-news/")
        ):
            continue

        context = link_context(a)

        # pouze TCG obsah
        lower = context.lower()

        if not (
            "trading card game" in lower
            or
            "pokémon tcg" in lower
            or
            "pokemon tcg" in lower
        ):
            continue

        date = parse_human_date(
            context
        )

        add_candidate(
            result,
            seen,
            href,
            date
        )

    return result[:MAX_PER_SOURCE]


# ============================================================
# ONE PIECE
# ============================================================

def discover_onepiece(source, html, soup, base_url):
    result = []
    seen = set()

    for a in soup.select("a[href]"):
        href = urljoin(
            base_url,
            a["href"]
        )

        if not same_domain(
            href,
            source["domain"]
        ):
            continue

        context = link_context(a)

        date = parse_human_date(
            context
        )

        # News položky mají datum
        if not date:
            continue

        path = urlparse(href).path.lower()

        if any(
            bad in path
            for bad in [
                "/cardlist",
                "/products/",
                "/rule",
                "/beginner",
                "/shop"
            ]
        ):
            continue

        add_candidate(
            result,
            seen,
            href,
            date
        )

    return result[:MAX_PER_SOURCE]


# ============================================================
# LORCANA
# ============================================================

def discover_lorcana(source, html, soup, base_url):
    result = []
    seen = set()

    pattern = re.compile(
        r"^/en-US/news/"
        r"\d{4}/"
        r"\d{2}/"
        r"[^/]+/?$",
        re.I
    )

    for a in soup.select("a[href]"):
        href = urljoin(
            base_url,
            a["href"]
        )

        if not same_domain(
            href,
            source["domain"]
        ):
            continue

        path = urlparse(href).path

        if not pattern.match(path):
            continue

        context = link_context(a)

        add_candidate(
            result,
            seen,
            href,
            parse_human_date(context)
        )

    return result[:MAX_PER_SOURCE]


# ============================================================
# MAGIC
# ============================================================

def discover_magic(source, html, soup, base_url):
    result = []
    seen = set()

    pattern = re.compile(
        r"^/en/news/"
        r"(?:"
        r"announcements|"
        r"feature|"
        r"magic-story|"
        r"making-magic|"
        r"mtg-arena"
        r")/"
        r"[^/]+/?$",
        re.I
    )

    for a in soup.select("a[href]"):
        href = urljoin(
            base_url,
            a["href"]
        )

        if not same_domain(
            href,
            source["domain"]
        ):
            continue

        path = urlparse(href).path

        if not pattern.match(path):
            continue

        context = link_context(a)

        if "terms and conditions" in context.lower():
            continue

        add_candidate(
            result,
            seen,
            href,
            parse_human_date(context)
        )

    return result[:MAX_PER_SOURCE]


# ============================================================
# YU-GI-OH!
# ============================================================

def discover_yugioh(source, html, soup, base_url):
    result = []
    seen = set()

    for a in soup.select("a[href]"):
        context = link_context(a)

        date = parse_human_date(
            context
        )

        if not date:
            continue

        lower = context.lower()

        # musí to být News nebo Update položka
        if not (
            "news" in lower
            or
            "update" in lower
        ):
            continue

        href = urljoin(
            base_url,
            a["href"]
        )

        if not same_domain(
            href,
            source["domain"]
        ):
            continue

        path = urlparse(href).path.lower()

        if any(
            bad in path
            for bad in [
                "/products/",
                "/events/",
                "/play/",
                "/category/"
            ]
        ):
            continue

        add_candidate(
            result,
            seen,
            href,
            date
        )

    return result[:MAX_PER_SOURCE]


# ============================================================
# STAR WARS UNLIMITED
# ============================================================

def discover_starwars(source, html, soup, base_url):
    result = []
    seen = set()

    pattern = re.compile(
        r"^/articles/[^/]+/?$",
        re.I
    )

    for a in soup.select("a[href]"):
        href = urljoin(
            base_url,
            a["href"]
        )

        if not same_domain(
            href,
            source["domain"]
        ):
            continue

        path = urlparse(href).path

        if not pattern.match(path):
            continue

        slug = path.rstrip("/").split("/")[-1]

        # vyhodíme jazykové mutace
        if re.search(
            r"-(de|fr|es|it|pl)$",
            slug,
            re.I
        ):
            continue

        add_candidate(
            result,
            seen,
            href
        )

    return result[:MAX_PER_SOURCE]


# ============================================================
# VÝBĚR DISCOVERY
# ============================================================

def discover(source):
    try:
        html, soup, base_url = fetch(
            source["url"]
        )

    except Exception as exc:
        print(
            "Nelze načíst zdroj:",
            source["game"],
            exc
        )
        return []


    category = source["category"]


    if category == "pokemon":
        return discover_pokemon(
            source, html, soup, base_url
        )

    if category == "onepiece":
        return discover_onepiece(
            source, html, soup, base_url
        )

    if category == "lorcana":
        return discover_lorcana(
            source, html, soup, base_url
        )

    if category == "magic":
        return discover_magic(
            source, html, soup, base_url
        )

    if category == "yugioh":
        return discover_yugioh(
            source, html, soup, base_url
        )

    if category == "starwars":
        return discover_starwars(
            source, html, soup, base_url
        )

    return []


# ============================================================
# CACHE
# ============================================================

def load_cache():
    if not OUTPUT.exists():
        return {}

    try:
        old = json.loads(
            OUTPUT.read_text(
                encoding="utf-8"
            )
        )

    except Exception:
        return {}


    cache = {}

    for item in old:
        if (
            item.get("pipeline_version")
            != PIPELINE_VERSION
        ):
            continue

        url = normalize_url(
            item.get("url", "")
        )

        if url:
            cache[url] = item

    return cache


cache = load_cache()


# ============================================================
# SBĚR
# ============================================================

all_items = []

cutoff = (
    datetime.now(timezone.utc)
    -
    timedelta(days=MAX_AGE_DAYS)
)


for source in SOURCES:

    print()
    print(
        "Sleduji:",
        source["game"]
    )


    candidates = discover(
        source
    )


    print(
        "Nalezeno kandidátů:",
        len(candidates)
    )


    accepted = 0


    for candidate in candidates:

        if accepted >= MAX_PER_SOURCE:
            break


        url = candidate["url"]

        fallback_date = candidate.get(
            "date"
        )


        cached = cache.get(
            normalize_url(url)
        )


        if cached:
            all_items.append(
                cached
            )

            accepted += 1

            print(
                "  CACHE:",
                cached.get(
                    "title",
                    ""
                )[:70]
            )

            continue


        article = get_article(
            url,
            fallback_date
        )


        if not article:
            continue


        published = article.get(
            "published"
        )


        if (
            published
            and
            published < cutoff
        ):
            continue


        original_title = article[
            "title_original"
        ]


        if title_is_junk(
            original_title
        ):
            continue


        title_cs = translate_cs(
            original_title,
            350
        )


        original_summary = article.get(
            "summary_original",
            ""
        )


        if original_summary:

            summary_cs = translate_cs(
                original_summary,
                900
            )

        else:

            summary_cs = (
                "Aktuální informace "
                f"ze světa {source['game']}."
            )


        item = {
            "game": source["game"],
            "category": source["category"],

            "title": title_cs,
            "title_original": original_title,

            "summary": summary_cs,
            "summary_original": original_summary,

            "image": article.get(
                "image",
                ""
            ),

            "url": article["url"],

            "published": (
                published.isoformat()
                if published
                else ""
            ),

            "date": (
                published.strftime("%d.%m.%Y")
                if published
                else ""
            ),

            "source_type": "official",

            "pipeline_version":
                PIPELINE_VERSION
        }


        all_items.append(item)

        accepted += 1


        print(
            "  +",
            source["game"],
            ":",
            title_cs[:75]
        )


        time.sleep(0.2)


# ============================================================
# DUPLICITY
# ============================================================

unique = {}


for item in all_items:

    key = (
        item.get("category", ""),
        normalize_url(
            item.get("url", "")
        )
    )

    if not key[1]:
        continue

    if key not in unique:
        unique[key] = item

    elif (
        not unique[key].get("image")
        and item.get("image")
    ):
        unique[key] = item


items = list(
    unique.values()
)


# ============================================================
# ŘAZENÍ
# ============================================================

def timestamp(item):
    date = parse_iso_date(
        item.get(
            "published",
            ""
        )
    )

    if date:
        return date.timestamp()

    return 0


items.sort(
    key=timestamp,
    reverse=True
)


items = items[:MAX_TOTAL]


# ============================================================
# ULOŽENÍ
# ============================================================

OUTPUT.parent.mkdir(
    parents=True,
    exist_ok=True
)


OUTPUT.write_text(
    json.dumps(
        items,
        ensure_ascii=False,
        indent=2
    ),
    encoding="utf-8"
)


# ============================================================
# STATISTIKA
# ============================================================

counts = {}


for item in items:

    game = item.get(
        "game",
        "Ostatní"
    )

    counts[game] = (
        counts.get(game, 0)
        + 1
    )


print()
print(
    "========================================"
)

print(
    "RADARKARET HOTOVO"
)

print(
    "Celkem čistých zpráv:",
    len(items)
)

print(
    "Zapsáno do:",
    OUTPUT
)

print()
print(
    "Podle kategorií:"
)


for game, count in counts.items():

    print(
        f" - {game}: {count}"
    )


print(
    "========================================"
)
