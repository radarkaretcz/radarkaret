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

PIPELINE_VERSION = 3


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36 "
        "RadarKaret/1.0"
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
        "url": "https://www.yugioh-card.com/eu/news/",
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
# TEXT
# ============================================================

def clean(text):

    if not text:
        return ""

    return re.sub(
        r"\s+",
        " ",
        str(text)
    ).strip()


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
            flags=re.IGNORECASE
        )

    return clean(text)


# ============================================================
# PŘEKLAD
# ============================================================

def translate_cs(text, limit=1000):

    text = clean(text)[:limit]

    if not text:
        return ""

    for attempt in range(2):

        try:

            result = translator.translate(text)

            if result:
                time.sleep(0.15)
                return clean(result)

        except Exception as exc:

            print(
                "  Překlad - pokus",
                attempt + 1,
                "selhal:",
                exc
            )

            time.sleep(1)

    # pokud bezplatný překladač právě nefunguje
    return text


# ============================================================
# WEB
# ============================================================

def fetch(url):

    response = session.get(
        url,
        timeout=25,
        allow_redirects=True
    )

    response.raise_for_status()

    html = response.text

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    return html, soup, response.url


# ============================================================
# URL
# ============================================================

def normalize_url(url):

    if not url:
        return ""

    url, _ = urldefrag(url)

    return url.rstrip("/")


def same_domain(url, domain):

    try:

        hostname = (
            urlparse(url)
            .hostname
            or ""
        ).lower()

        return (
            hostname == domain
            or
            hostname.endswith(
                "." + domain
            )
        )

    except Exception:
        return False


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
    "%d %b %Y",

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
# KONTEXT ODKAZU
# ============================================================

def link_context(a):

    parts = [
        a.get_text(
            " ",
            strip=True
        )
    ]

    parent = a.parent

    # stačí 2 úrovně, ať nevezmeme celé menu stránky
    for _ in range(2):

        if not parent:
            break

        parts.append(
            parent.get_text(
                " ",
                strip=True
            )
        )

        parent = parent.parent

    return clean(
        " ".join(parts)
    )


def context_has_date(text):

    return any(
        regex.search(text)
        for regex in DATE_REGEXES
    )


# ============================================================
# BLACKLIST MENU / NAVIGACE
# ============================================================

BLACKLIST_TITLES = {

    "products",
    "all products",
    "card list",
    "cards",
    "find cards",
    "recommended decks",
    "getting started",
    "for stores",
    "for beginners",
    "rules",
    "faq",
    "shop",
    "official shop",
    "events",
    "news",
    "archive",
    "article archive",
    "latest releases",
    "booster packs",
    "structure decks",
    "starter decks",
    "accessories",
    "product category: booster packs",
    "product category: structure decks",
    "product category: starter decks",
    "product category: ots tournament packs",
    "product category: accessories",
    "more articles",
    "view all",
    "latest products",
    "card set archive",
    "learn to play",
    "learn to play!",
    "play",
    "digital"

}


def title_is_junk(text):

    value = clean(text).lower()

    if not value:
        return True

    if value in BLACKLIST_TITLES:
        return True

    junk_starts = [

        "product category:",
        "article archive",
        "card category:",
        "getting started",
        "cookie policy",
        "privacy policy",
        "legal notice"

    ]

    return any(
        value.startswith(prefix)
        for prefix in junk_starts
    )


# ============================================================
# DISCOVERY: POKÉMON
# ============================================================

def discover_pokemon(source, html, soup, base_url):

    links = []

    # klasické <a>
    for a in soup.select(
        "a[href]"
    ):

        href = urljoin(
            base_url,
            a.get("href", "")
        )

        path = urlparse(
            href
        ).path

        if not same_domain(
            href,
            source["domain"]
        ):
            continue

        if not (
            path.startswith(
                "/us/news/"
            )
            or
            path.startswith(
                "/us/pokemon-news/"
            )
        ):
            continue

        if path.rstrip("/") in [
            "/us/news",
            "/us/pokemon-news"
        ]:
            continue

        links.append(
            normalize_url(href)
        )


    # Pokémon web je částečně JS.
    # Najdeme cesty i uvnitř vložených dat.
    raw = html.replace(
        "\\/",
        "/"
    )

    patterns = [

        r'["\'](/us/news/[a-zA-Z0-9\-_/]+)["\']',

        r'["\'](/us/pokemon-news/[a-zA-Z0-9\-_/]+)["\']'

    ]

    for pattern in patterns:

        for found in re.findall(
            pattern,
            raw
        ):

            links.append(
                normalize_url(
                    urljoin(
                        base_url,
                        found
                    )
                )
            )

    return links


# ============================================================
# DISCOVERY: ONE PIECE
# ============================================================

def discover_onepiece(source, html, soup, base_url):

    links = []

    allowed_prefixes = (

        "/events/",
        "/products/",
        "/news/",
        "/rules/"

    )

    for a in soup.select(
        "a[href]"
    ):

        href = normalize_url(
            urljoin(
                base_url,
                a["href"]
            )
        )

        if not same_domain(
            href,
            source["domain"]
        ):
            continue

        path = urlparse(
            href
        ).path

        if not path.startswith(
            allowed_prefixes
        ):
            continue

        context = link_context(a)

        # skutečné položky na News stránce mají datum
        if not context_has_date(
            context
        ):
            continue

        links.append(href)

    return links


# ============================================================
# DISCOVERY: LORCANA
# ============================================================

def discover_lorcana(source, html, soup, base_url):

    links = []

    article_pattern = re.compile(

        r"^/en-US/news/"
        r"\d{4}/"
        r"\d{2}/"
        r"[^/]+/?$",

        re.I

    )

    for a in soup.select(
        "a[href]"
    ):

        href = normalize_url(
            urljoin(
                base_url,
                a["href"]
            )
        )

        if not same_domain(
            href,
            source["domain"]
        ):
            continue

        path = urlparse(
            href
        ).path

        if article_pattern.match(
            path
        ):

            links.append(href)

    return links


# ============================================================
# DISCOVERY: MAGIC
# ============================================================

def discover_magic(source, html, soup, base_url):

    links = []

    pattern = re.compile(

        r"^/en/news/"
        r"(?:"
        r"announcements|"
        r"feature|"
        r"magic-story|"
        r"making-magic|"
        r"card-preview|"
        r"mtg-arena"
        r")/"
        r"[^/]+/?$",

        re.I

    )

    for a in soup.select(
        "a[href]"
    ):

        href = normalize_url(
            urljoin(
                base_url,
                a["href"]
            )
        )

        if not same_domain(
            href,
            source["domain"]
        ):
            continue

        path = urlparse(
            href
        ).path

        if pattern.match(path):

            links.append(href)

    return links


# ============================================================
# DISCOVERY: YU-GI-OH!
# ============================================================

def discover_yugioh(source, html, soup, base_url):

    links = []

    for a in soup.select(
        "a[href]"
    ):

        href = normalize_url(
            urljoin(
                base_url,
                a["href"]
            )
        )

        if not same_domain(
            href,
            source["domain"]
        ):
            continue

        path = urlparse(
            href
        ).path

        if not path.startswith(
            "/eu/"
        ):
            continue

        # vyhodíme jisté navigační části
        bad_paths = (

            "/eu/products",
            "/eu/events",
            "/eu/play",
            "/eu/news",
            "/eu/category",
            "/eu/cards",
            "/eu/accessories"

        )

        if path.rstrip("/") in bad_paths:
            continue

        context = link_context(a)

        # News karty mají datum, navigace ne
        if not context_has_date(
            context
        ):
            continue

        links.append(href)

    return links


# ============================================================
# DISCOVERY: STAR WARS UNLIMITED
# ============================================================

def discover_starwars(source, html, soup, base_url):

    links = []

    pattern = re.compile(
        r"^/articles/[^/]+/?$",
        re.I
    )

    for a in soup.select(
        "a[href]"
    ):

        href = normalize_url(
            urljoin(
                base_url,
                a["href"]
            )
        )

        if not same_domain(
            href,
            source["domain"]
        ):
            continue

        path = urlparse(
            href
        ).path

        if pattern.match(path):

            links.append(href)

    return links


# ============================================================
# DISCOVER PODLE ZDROJE
# ============================================================

def discover_links(source):

    try:

        html, soup, base_url = fetch(
            source["url"]
        )

    except Exception as exc:

        print(
            "Nelze načíst seznam:",
            source["game"],
            exc
        )

        return []


    category = source[
        "category"
    ]


    if category == "pokemon":

        links = discover_pokemon(
            source,
            html,
            soup,
            base_url
        )


    elif category == "onepiece":

        links = discover_onepiece(
            source,
            html,
            soup,
            base_url
        )


    elif category == "lorcana":

        links = discover_lorcana(
            source,
            html,
            soup,
            base_url
        )


    elif category == "magic":

        links = discover_magic(
            source,
            html,
            soup,
            base_url
        )


    elif category == "yugioh":

        links = discover_yugioh(
            source,
            html,
            soup,
            base_url
        )


    elif category == "starwars":

        links = discover_starwars(
            source,
            html,
            soup,
            base_url
        )


    else:

        links = []


    # odstranění duplicit
    result = []

    seen = set()

    for link in links:

        link = normalize_url(
            link
        )

        if not link:
            continue

        if link in seen:
            continue

        seen.add(link)

        result.append(link)


    return result[
        :MAX_PER_SOURCE
    ]


# ============================================================
# META TAGY
# ============================================================

def meta_content(soup, selectors):

    for selector in selectors:

        tag = soup.select_one(
            selector
        )

        if not tag:
            continue

        value = tag.get(
            "content"
        )

        if value:

            return clean(value)

    return ""


# ============================================================
# JSON-LD
# ============================================================

def walk_json(data):

    if isinstance(
        data,
        dict
    ):

        yield data

        for value in data.values():

            yield from walk_json(
                value
            )

    elif isinstance(
        data,
        list
    ):

        for value in data:

            yield from walk_json(
                value
            )


def json_ld_data(soup):

    output = []

    for script in soup.select(
        'script[type="application/ld+json"]'
    ):

        try:

            data = json.loads(
                script.get_text()
            )

            output.extend(
                walk_json(data)
            )

        except Exception:
            pass

    return output


# ============================================================
# POPIS Z TEXTU
# ============================================================

def first_good_paragraph(soup):

    candidates = soup.select(

        "article p, "
        "main p, "
        ".article p, "
        ".content p"

    )

    for paragraph in candidates:

        text = clean(
            paragraph.get_text(
                " ",
                strip=True
            )
        )

        if len(text) < 70:
            continue

        lowered = text.lower()

        junk = [

            "cookie",
            "privacy policy",
            "javascript",
            "enable cookies",
            "all rights reserved"

        ]

        if any(
            value in lowered
            for value in junk
        ):
            continue

        return text[:1200]

    return ""


# ============================================================
# OBRÁZEK
# ============================================================

def fallback_image(soup, base_url):

    selectors = [

        "article img[src]",
        "main img[src]",
        ".article img[src]",
        ".content img[src]"

    ]

    for selector in selectors:

        for img in soup.select(
            selector
        ):

            src = (

                img.get("src")
                or
                img.get("data-src")
                or
                ""

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
                    "avatar",
                    "cookie"
                ]
            ):
                continue

            return src

    return ""


# ============================================================
# ČLÁNEK
# ============================================================

def get_article(url):

    try:

        html, soup, final_url = fetch(
            url
        )

    except Exception as exc:

        print(
            "  Nelze načíst článek:",
            url,
            exc
        )

        return None


    # TITULEK
    title = meta_content(

        soup,

        [
            'meta[property="og:title"]',
            'meta[name="twitter:title"]'
        ]

    )


    if not title:

        h1 = soup.select_one(
            "h1"
        )

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


    title = clean_title(
        title
    )


    if (
        not title
        or
        title_is_junk(title)
    ):

        return None


    # POPIS
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


    # OBRÁZEK
    image = meta_content(

        soup,

        [
            'meta[property="og:image"]',
            'meta[property="og:image:secure_url"]',
            'meta[name="twitter:image"]'
        ]

    )


    # JSON-LD
    json_items = json_ld_data(
        soup
    )


    published = None


    for item in json_items:

        if not published:

            published = parse_iso_date(

                item.get(
                    "datePublished"
                )
                or
                item.get(
                    "dateCreated"
                )
                or
                ""

            )


        if not image:

            value = item.get(
                "image"
            )

            if isinstance(
                value,
                str
            ):

                image = value

            elif isinstance(
                value,
                list
            ) and value:

                first = value[0]

                if isinstance(
                    first,
                    str
                ):

                    image = first

                elif isinstance(
                    first,
                    dict
                ):

                    image = (
                        first.get("url")
                        or ""
                    )

            elif isinstance(
                value,
                dict
            ):

                image = (
                    value.get("url")
                    or ""
                )


    # META DATUM
    if not published:

        date_meta = meta_content(

            soup,

            [
                'meta[property="article:published_time"]',
                'meta[name="date"]',
                'meta[name="publish-date"]',
                'meta[name="datePublished"]'
            ]

        )

        published = parse_iso_date(
            date_meta
        )


    # VIDITELNÉ DATUM
    if not published:

        page_text = clean(
            soup.get_text(
                " ",
                strip=True
            )
        )

        published = parse_human_date(
            page_text[:6000]
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


    # canonical URL
    canonical = soup.select_one(
        'link[rel="canonical"]'
    )

    if (
        canonical
        and
        canonical.get("href")
    ):

        final_url = urljoin(

            final_url,

            canonical["href"]

        )


    return {

        "title_original":
            title,

        "summary_original":
            clean(description),

        "image":
            image,

        "url":
            normalize_url(final_url),

        "published":
            published

    }


# ============================================================
# CACHE STARÝCH PŘEKLADŮ
# ============================================================

def load_cache():

    if not OUTPUT.exists():
        return {}

    try:

        data = json.loads(

            OUTPUT.read_text(
                encoding="utf-8"
            )

        )

    except Exception:

        return {}


    result = {}


    for item in data:

        if (
            item.get(
                "pipeline_version"
            )
            != PIPELINE_VERSION
        ):
            continue

        url = normalize_url(
            item.get(
                "url",
                ""
            )
        )

        if url:

            result[url] = item

    return result


cache = load_cache()


# ============================================================
# SBĚR
# ============================================================

all_items = []

cutoff = (
    datetime.now(
        timezone.utc
    )
    -
    timedelta(
        days=MAX_AGE_DAYS
    )
)


for source in SOURCES:

    print()
    print(
        "Sleduji:",
        source["game"]
    )


    links = discover_links(
        source
    )


    print(
        "Nalezeno kandidátů:",
        len(links)
    )


    accepted = 0


    for url in links:

        if accepted >= MAX_PER_SOURCE:
            break


        cached = cache.get(
            normalize_url(url)
        )


        # už přeložený čistý článek
        if cached:

            published = parse_iso_date(
                cached.get(
                    "published",
                    ""
                )
            )

            if (
                published
                and
                published < cutoff
            ):
                continue

            all_items.append(
                cached
            )

            accepted += 1

            print(
                "  CACHE:",
                cached.get(
                    "title",
                    ""
                )[:75]
            )

            continue


        article = get_article(
            url
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

                950

            )

        else:

            summary_cs = (

                "Aktuální informace "
                f"ze světa {source['game']}."

            )


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
                original_summary,

            "image":
                article.get(
                    "image",
                    ""
                ),

            "url":
                article[
                    "url"
                ],

            "published":
                (
                    published.isoformat()
                    if published
                    else ""
                ),

            "date":
                (
                    published.strftime(
                        "%d.%m.%Y"
                    )
                    if published
                    else ""
                ),

            "source_type":
                "official",

            "pipeline_version":
                PIPELINE_VERSION

        }


        all_items.append(
            item
        )


        accepted += 1


        print(
            "  +",
            source["game"],
            ":",
            title_cs[:80]
        )


        time.sleep(
            0.2
        )


# ============================================================
# DUPLICITY
# ============================================================

unique = {}


for item in all_items:

    key = (
        item.get(
            "category",
            ""
        ),
        normalize_url(
            item.get(
                "url",
                ""
            )
        )
    )


    if not key[1]:
        continue


    old = unique.get(key)


    if not old:

        unique[key] = item

        continue


    # pokud máme dvě verze,
    # přednost dostane ta s obrázkem

    if (
        not old.get("image")
        and
        item.get("image")
    ):

        unique[key] = item


items = list(
    unique.values()
)


# ============================================================
# ŘAZENÍ
# ============================================================

def item_timestamp(item):

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
    key=item_timestamp,
    reverse=True
)


items = items[
    :MAX_TOTAL
]


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
        counts.get(
            game,
            0
        )
        +
        1
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
