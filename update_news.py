import json
import re
import time
from pathlib import Path
from datetime import datetime, timezone, timedelta
from urllib.parse import urljoin, urlparse, urldefrag

import requests
from bs4 import BeautifulSoup
from deep_translator import GoogleTranslator


OUTPUT = Path("data/news.json")

MAX_PER_SOURCE = 10
MAX_TOTAL = 50
MAX_AGE_DAYS = 240

# zvýšení verze způsobí, že se staré krátké anotace
# nebudou brát z cache
PIPELINE_VERSION = 5


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124 Safari/537.36 RadarKaret/1.0"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


SOURCES = [

    {
        "game": "Pokémon",
        "category": "pokemon",
        "url": "https://www.pokemon.com/us/pokemon-news/",
        "domain": "pokemon.com",
    },

    {
        "game": "One Piece",
        "category": "onepiece",
        "url": "https://en.onepiece-cardgame.com/news/",
        "domain": "en.onepiece-cardgame.com",
    },

    {
        "game": "Disney Lorcana",
        "category": "lorcana",
        "url": "https://www.disneylorcana.com/en-US/news/",
        "domain": "disneylorcana.com",
    },

    {
        "game": "Magic",
        "category": "magic",
        "url": "https://magic.wizards.com/en/news",
        "domain": "magic.wizards.com",
    },

    {
        "game": "Yu-Gi-Oh!",
        "category": "yugioh",
        "url": "https://www.yugioh-card.com/eu/news/?view=all",
        "domain": "yugioh-card.com",
    },

    {
        "game": "Star Wars Unlimited",
        "category": "starwars",
        "url": "https://starwarsunlimited.com/articles",
        "domain": "starwarsunlimited.com",
    },

]


session = requests.Session()
session.headers.update(HEADERS)

translator = GoogleTranslator(
    source="auto",
    target="cs"
)


# ============================================================
# ZÁKLAD
# ============================================================

def clean(text):

    return re.sub(
        r"\s+",
        " ",
        str(text or "")
    ).strip()


def normalize_url(url):

    url, _ = urldefrag(
        url or ""
    )

    return url.rstrip("/")


def same_domain(url, domain):

    host = (
        urlparse(url).hostname
        or ""
    ).lower()

    return (
        host == domain
        or
        host.endswith(
            "." + domain
        )
    )


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


def meta_content(
    soup,
    selectors
):

    for selector in selectors:

        tag = soup.select_one(
            selector
        )

        if (
            tag
            and
            tag.get("content")
        ):

            return clean(
                tag["content"]
            )

    return ""


# ============================================================
# TITULKY
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

        r"\s*-\s*Pokemon\.com.*$",

    ]

    for pattern in suffixes:

        text = re.sub(
            pattern,
            "",
            text,
            flags=re.I
        )

    return clean(text)


JUNK = {

    "products",
    "all products",
    "card list",
    "cards",
    "getting started",
    "for stores",
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
    "terms and conditions",

}


def title_is_junk(text):

    value = clean(
        text
    ).lower()

    return (

        not value

        or

        value in JUNK

        or

        "error 500" in value

        or

        "server error" in value

        or

        value.startswith(
            "product category:"
        )

        or

        value.startswith(
            "article archive"
        )

    )


# ============================================================
# DATUM
# ============================================================

MONTHS = (
    r"January|February|March|April|May|June|July|"
    r"August|September|October|November|December|"
    r"Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec"
)


DATE_RES = [

    re.compile(
        rf"\b(?:{MONTHS})\s+\d{{1,2}},\s+\d{{4}}\b",
        re.I
    ),

    re.compile(
        rf"\b\d{{1,2}}\s+(?:{MONTHS})\s+\d{{4}}\b",
        re.I
    ),

]


DATE_FORMATS = [

    "%B %d, %Y",
    "%b %d, %Y",

    "%d %B %Y",
    "%d %b %Y",

]


def parse_human_date(text):

    text = clean(text)

    for regex in DATE_RES:

        match = regex.search(
            text
        )

        if not match:
            continue


        for fmt in DATE_FORMATS:

            try:

                return datetime.strptime(
                    match.group(0),
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

        date = datetime.fromisoformat(

            value.replace(
                "Z",
                "+00:00"
            )

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
# DELŠÍ ČESKÝ PŘEKLAD
# ============================================================

def translate_long(
    text,
    max_chars=2200
):

    text = clean(
        text
    )[:max_chars]


    if not text:
        return ""


    # Rozdělení podle vět
    sentences = re.split(
        r"(?<=[.!?])\s+",
        text
    )


    chunks = []

    current = ""


    for sentence in sentences:

        if (
            len(current)
            +
            len(sentence)
            +
            1
            >
            2200
            and
            current
        ):

            chunks.append(
                current
            )

            current = sentence

        else:

            current = (
                f"{current} {sentence}"
            ).strip()


    if current:

        chunks.append(
            current
        )


    translated_parts = []


    for chunk in chunks:

        try:

            translated = (
                translator.translate(
                    chunk
                )
            )

            translated_parts.append(

                clean(
                    translated
                    or
                    chunk
                )

            )

            time.sleep(
                0.15
            )


        except Exception as error:

            print(
                "  Překlad selhal:",
                error
            )

            translated_parts.append(
                chunk
            )


    return clean(

        " ".join(
            translated_parts
        )

    )


# ============================================================
# DELŠÍ ANOTACE Z ČLÁNKU
# ============================================================

def article_paragraphs(
    soup,
    max_chars=2200
):

    selectors = [

        "article p",

        "main article p",

        ".article-content p",

        ".article__content p",

        ".content p",

        "main p",

    ]


    seen = set()

    paragraphs = []


    for selector in selectors:

        for paragraph in soup.select(
            selector
        ):

            text = clean(

                paragraph.get_text(
                    " ",
                    strip=True
                )

            )


            lower = text.lower()


            if len(text) < 55:
                continue


            if text in seen:
                continue


            if any(
                junk in lower
                for junk in [

                    "cookie",

                    "privacy policy",

                    "all rights reserved",

                    "enable javascript",

                    "sign up for",

                    "subscribe to",

                    "terms of use",

                    "click here",

                ]
            ):

                continue


            seen.add(
                text
            )


            paragraphs.append(
                text
            )


            joined = " ".join(
                paragraphs
            )


            if len(joined) >= max_chars:

                return joined[
                    :max_chars
                ]


    return " ".join(
        paragraphs
    )[:max_chars]


# ============================================================
# OBRÁZEK
# ============================================================

def fallback_image(
    soup,
    base_url
):

    for image in soup.select(

        "article img, "
        "main img, "
        ".article img, "
        ".content img"

    ):

        src = (

            image.get("src")

            or

            image.get("data-src")

            or

            image.get(
                "data-lazy-src"
            )

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

                "cookie",

                "avatar",

                "sprite",

            ]
        ):

            continue


        return src


    return ""


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

        " ".join(
            parts
        )

    )


def add_candidate(
    items,
    seen,
    url,
    date=None
):

    url = normalize_url(
        url
    )


    if (
        url
        and
        url not in seen
    ):

        seen.add(
            url
        )

        items.append({

            "url": url,

            "date": date,

        })


# ============================================================
# HLEDÁNÍ ČLÁNKŮ
# ============================================================

def discover(source):

    try:

        html, soup, base = fetch(
            source["url"]
        )

    except Exception as error:

        print(
            "Nelze načíst zdroj:",
            source["game"],
            error
        )

        return []


    category = source[
        "category"
    ]


    result = []

    seen = set()


    for link in soup.select(
        "a[href]"
    ):

        href = normalize_url(

            urljoin(
                base,
                link["href"]
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


        lower_path = (
            path.lower()
        )


        context = link_context(
            link
        )


        lower_context = (
            context.lower()
        )


        date = parse_human_date(
            context
        )


        # ----------------------------------------------------
        # POKÉMON
        # ----------------------------------------------------

        if category == "pokemon":

            if not path.startswith(
                "/us/pokemon-news/"
            ):

                continue


            if (
                path.rstrip("/")
                ==
                "/us/pokemon-news"
            ):

                continue


            if not (

                "trading card game"
                in lower_context

                or

                "pokémon tcg"
                in lower_context

                or

                "pokemon tcg"
                in lower_context

            ):

                continue


            # Pocket nechceme
            if (
                "tcg pocket"
                in lower_context
            ):

                continue


        # ----------------------------------------------------
        # ONE PIECE
        # ----------------------------------------------------

        elif category == "onepiece":

            if not date:
                continue


            if any(
                value in lower_path
                for value in [

                    "/cardlist",

                    "/rule",

                    "/beginner",

                    "/shop",

                ]
            ):

                continue


        # ----------------------------------------------------
        # LORCANA
        # ----------------------------------------------------

        elif category == "lorcana":

            if not lower_path.startswith(
                "/en-us/news/"
            ):

                continue


            if (
                lower_path.rstrip("/")
                ==
                "/en-us/news"
            ):

                continue


        # ----------------------------------------------------
        # MAGIC
        # ----------------------------------------------------

        elif category == "magic":

            if not lower_path.startswith(
                "/en/news/"
            ):

                continue


            if any(
                value in lower_path
                for value in [

                    "/archive",

                    "/terms",

                    "/privacy",

                ]
            ):

                continue


            if (
                lower_path.rstrip("/")
                ==
                "/en/news"
            ):

                continue


        # ----------------------------------------------------
        # YU-GI-OH
        # ----------------------------------------------------

        elif category == "yugioh":

            if not date:
                continue


            if any(
                value in lower_path
                for value in [

                    "/products/",

                    "/category/",

                    "/play/",

                    "/events/",

                ]
            ):

                continue


        # ----------------------------------------------------
        # STAR WARS
        # ----------------------------------------------------

        elif category == "starwars":

            if not re.match(

                r"^/articles/[^/]+/?$",

                path,

                re.I

            ):

                continue


            slug = (
                path
                .rstrip("/")
                .split("/")[-1]
            )


            if re.search(

                r"-(de|fr|es|it|pl)$",

                slug,

                re.I

            ):

                continue


        add_candidate(

            result,

            seen,

            href,

            date

        )


    return result[
        :MAX_PER_SOURCE
    ]


# ============================================================
# DETAIL ČLÁNKU
# ============================================================

def get_article(
    url,
    fallback_date=None
):

    try:

        html, soup, final_url = fetch(
            url
        )

    except Exception as error:

        print(
            "  Nelze načíst článek:",
            url,
            error
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


    if (
        not title
        and
        soup.title
    ):

        title = clean(

            soup.title.get_text(
                " ",
                strip=True
            )

        )


    title = clean_title(
        title
    )


    if title_is_junk(
        title
    ):

        return None


    # --------------------------------------------------------
    # ANOTACE
    # --------------------------------------------------------

    short_description = meta_content(

        soup,

        [
            'meta[property="og:description"]',

            'meta[name="description"]',

            'meta[name="twitter:description"]'
        ]

    )


    long_description = article_paragraphs(

        soup,

        max_chars=2200

    )


    # Pokud se podaří získat skutečný text článku,
    # použijeme jej místo krátkého meta popisu.
    if len(long_description) >= 120:

        description = (
            long_description
        )

    else:

        description = (
            short_description
        )


    # --------------------------------------------------------
    # OBRÁZEK
    # --------------------------------------------------------

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


    # --------------------------------------------------------
    # DATUM
    # --------------------------------------------------------

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

        published = parse_human_date(

            clean(

                soup.get_text(
                    " ",
                    strip=True
                )

            )[:6000]

        )


    if not published:

        published = fallback_date


    # --------------------------------------------------------
    # CANONICAL
    # --------------------------------------------------------

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
            description,

        "image":
            image,

        "url":
            normalize_url(
                final_url
            ),

        "published":
            published,

    }


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

        # Pouze nová verze.
        # Tím zahodíme staré krátké anotace.
        if (
            item.get(
                "pipeline_version"
            )
            !=
            PIPELINE_VERSION
        ):

            continue


        url = normalize_url(

            item.get(
                "url",
                ""
            )

        )


        if url:

            cache[url] = item


    return cache


cache = load_cache()


# ============================================================
# SBĚR
# ============================================================

cutoff = (

    datetime.now(
        timezone.utc
    )

    -

    timedelta(
        days=MAX_AGE_DAYS
    )

)


all_items = []


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


    for candidate in candidates:


        url = candidate[
            "url"
        ]


        # CACHE
        if url in cache:

            all_items.append(
                cache[url]
            )

            print(
                "  CACHE:",
                cache[url]
                .get(
                    "title",
                    ""
                )[:70]
            )

            continue


        article = get_article(

            url,

            candidate.get(
                "date"
            )

        )


        if not article:
            continue


        published = article[
            "published"
        ]


        if (
            published
            and
            published < cutoff
        ):

            continue


        original_title = article[
            "title_original"
        ]


        original_summary = article[
            "summary_original"
        ]


        # ----------------------------------------------------
        # ČESKÝ TITULEK
        # ----------------------------------------------------

        title_cs = translate_long(

            original_title,

            350

        )


        # ----------------------------------------------------
        # DELŠÍ ČESKÁ ANOTACE
        # ----------------------------------------------------

        if original_summary:

            summary_cs = translate_long(

                original_summary,

                2200

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
                article["image"],

            "url":
                article["url"],

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
                PIPELINE_VERSION,

        }


        all_items.append(
            item
        )


        print(
            "  +",
            source["game"],
            ":",
            title_cs[:75]
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


    if key not in unique:

        unique[key] = item


    elif (

        not unique[key].get(
            "image"
        )

        and

        item.get(
            "image"
        )

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
# STATISTIKY
# ============================================================

counts = {}


for item in items:

    game = item[
        "game"
    ]

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
