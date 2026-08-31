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
# FINÁLNÍ ROBUSTNÍ SBĚRAČ TCG NOVINEK
# ============================================================

OUTPUT = Path("data/news.json")

MAX_PER_SOURCE = 12
MAX_TOTAL = 60
MAX_AGE_DAYS = 270

# Pokud změníme způsob zpracování, zvýšíme číslo.
PIPELINE_VERSION = 6


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36 RadarKaret/1.0"
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
        "url": "https://www.yugioh-card.com/eu/news/",
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


# ============================================================
# TEXT
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


# ============================================================
# HTTP
# ============================================================

def fetch(url):
    response = session.get(
        url,
        timeout=30,
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
# DETEKCE CHYBOVÉ STRÁNKY
# ============================================================

ERROR_MARKERS = [
    "error 500",
    "500 server error",
    "internal server error",
    "that's an error",
    "that’s an error",
    "there was an error",
    "please try again later",
    "service unavailable",
    "temporarily unavailable",
    "bad gateway",
]


def is_error_page(soup):
    text = clean(
        soup.get_text(
            " ",
            strip=True
        )
    ).lower()

    title = ""

    if soup.title:
        title = clean(
            soup.title.get_text(
                " ",
                strip=True
            )
        ).lower()

    sample = (
        title
        + " "
        + text[:2500]
    )

    return any(
        marker in sample
        for marker in ERROR_MARKERS
    )


# ============================================================
# TITULEK
# ============================================================

def clean_title(text):
    text = clean(text)

    suffixes = [
        r"\s*\|\s*ONE PIECE CARD GAME.*$",
        r"\s*-\s*Official Web Site.*$",
        r"\s*\|\s*Magic: The Gathering.*$",
        r"\s*\|\s*Daily MTG.*$",
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
    "more articles",
    "view all",
    "latest products",
    "card set archive",
    "learn to play",
    "digital",
    "terms and conditions",
    "arena direct | terms and conditions",
}


def title_is_junk(text):
    value = clean(text).lower()

    if not value:
        return True

    if value in JUNK_TITLES:
        return True

    if any(
        marker in value
        for marker in ERROR_MARKERS
    ):
        return True

    if value.startswith(
        "product category:"
    ):
        return True

    if value.startswith(
        "article archive"
    ):
        return True

    return False


# ============================================================
# META
# ============================================================

def meta_content(soup, selectors):
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
                tag.get("content")
            )

    return ""


# ============================================================
# DATUM
# ============================================================

MONTHS = (
    r"January|February|March|April|May|June|July|"
    r"August|September|October|November|December|"
    r"Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec"
)


DATE_PATTERNS = [
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

    for regex in DATE_PATTERNS:
        match = regex.search(
            text
        )

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
# ČESKÝ PŘEKLAD
# ============================================================

def translate_cs(text, max_chars=1300):
    text = clean(text)[:max_chars]

    if not text:
        return ""

    for attempt in range(3):
        try:
            translator = GoogleTranslator(
                source="auto",
                target="cs"
            )

            translated = translator.translate(
                text
            )

            if translated:
                time.sleep(0.20)

                return clean(
                    translated
                )

        except Exception as exc:
            print(
                f"  Překlad pokus {attempt + 1} selhal:",
                exc
            )

            time.sleep(
                1.5
            )

    return ""


# ============================================================
# DELŠÍ ANOTACE
# ============================================================

def extract_paragraphs(soup, max_chars=1200):
    selectors = [
        "article p",
        "main article p",
        ".article-content p",
        ".article__content p",
        ".entry-content p",
        ".content p",
        "main p",
    ]

    paragraphs = []
    seen = set()

    for selector in selectors:
        for p in soup.select(
            selector
        ):
            text = clean(
                p.get_text(
                    " ",
                    strip=True
                )
            )

            if len(text) < 45:
                continue

            lower = text.lower()

            junk = [
                "cookie",
                "privacy policy",
                "all rights reserved",
                "enable javascript",
                "terms of use",
                "sign up",
                "subscribe",
                "click here",
                "follow us",
            ]

            if any(
                word in lower
                for word in junk
            ):
                continue

            if text in seen:
                continue

            seen.add(text)

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


def build_description(soup):
    meta_description = meta_content(
        soup,
        [
            'meta[property="og:description"]',
            'meta[name="description"]',
            'meta[name="twitter:description"]',
        ]
    )

    body = extract_paragraphs(
        soup,
        1200
    )

    # Delší skutečný text má přednost.
    if len(body) >= 150:
        return body

    return meta_description


# ============================================================
# OBRÁZEK
# ============================================================

def find_image(soup, base_url):
    image = meta_content(
        soup,
        [
            'meta[property="og:image"]',
            'meta[property="og:image:secure_url"]',
            'meta[name="twitter:image"]',
        ]
    )

    if image:
        return urljoin(
            base_url,
            image
        )

    selectors = [
        "article img",
        "main article img",
        ".article-content img",
        ".content img",
        "main img",
    ]

    for selector in selectors:
        for img in soup.select(
            selector
        ):
            src = (
                img.get("src")
                or img.get("data-src")
                or img.get("data-lazy-src")
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
                part in lower
                for part in [
                    "logo",
                    "icon",
                    "sprite",
                    "cookie",
                    "avatar",
                ]
            ):
                continue

            return src

    return ""


# ============================================================
# LINK KONTEXT
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
        " ".join(parts)
    )


def add_candidate(
    result,
    seen,
    url,
    date=None
):
    url = normalize_url(
        url
    )

    if not url:
        return

    if url in seen:
        return

    seen.add(url)

    result.append(
        {
            "url": url,
            "date": date,
        }
    )


# ============================================================
# DISCOVERY POKÉMON
# ============================================================

def discover_pokemon(
    source,
    html,
    soup,
    base_url
):
    result = []
    seen = set()

    # 1) Normální HTML odkazy
    for a in soup.select(
        "a[href]"
    ):
        href = normalize_url(
            urljoin(
                base_url,
                a.get("href", "")
            )
        )

        if not same_domain(
            href,
            source["domain"]
        ):
            continue

        path = urlparse(
            href
        ).path.lower()

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

        if path.rstrip("/") in (
            "/us/news",
            "/us/pokemon-news",
        ):
            continue

        add_candidate(
            result,
            seen,
            href,
            parse_human_date(
                link_context(a)
            )
        )

    # 2) Pokémon někdy schovává odkazy v JSON/JS
    raw = html.replace(
        "\\/",
        "/"
    )

    patterns = [
        r'(/us/news/[a-zA-Z0-9\-_/]+)',
        r'(/us/pokemon-news/[a-zA-Z0-9\-_/]+)',
    ]

    for pattern in patterns:
        for path in re.findall(
            pattern,
            raw
        ):
            add_candidate(
                result,
                seen,
                urljoin(
                    base_url,
                    path
                )
            )

    return result[:30]


# ============================================================
# DISCOVERY LORCANA
# ============================================================

def discover_lorcana(
    source,
    html,
    soup,
    base_url
):
    result = []
    seen = set()

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
                a.get("href", "")
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

        if not article_pattern.match(
            path
        ):
            continue

        add_candidate(
            result,
            seen,
            href,
            parse_human_date(
                link_context(a)
            )
        )

    return result[:MAX_PER_SOURCE]


# ============================================================
# DISCOVERY ONE PIECE
# ============================================================

def discover_onepiece(
    source,
    html,
    soup,
    base_url
):
    result = []
    seen = set()

    for a in soup.select(
        "a[href]"
    ):
        context = link_context(
            a
        )

        date = parse_human_date(
            context
        )

        # skutečná News položka musí mít datum
        if not date:
            continue

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
        ).path.lower()

        bad = [
            "/cardlist",
            "/beginner",
            "/rules",
            "/shop",
        ]

        if any(
            part in path
            for part in bad
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
# DISCOVERY MAGIC
# ============================================================

def discover_magic(
    source,
    html,
    soup,
    base_url
):
    result = []
    seen = set()

    pattern = re.compile(
        r"^/en/news/"
        r"(?:"
        r"announcements|"
        r"feature|"
        r"magic-story|"
        r"making-magic|"
        r"mtg-arena|"
        r"daily-magic"
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

        if not pattern.match(
            path
        ):
            continue

        context = link_context(
            a
        )

        if "terms and conditions" in context.lower():
            continue

        add_candidate(
            result,
            seen,
            href,
            parse_human_date(
                context
            )
        )

    return result[:MAX_PER_SOURCE]


# ============================================================
# DISCOVERY YU-GI-OH!
# ============================================================

def discover_yugioh(
    source,
    html,
    soup,
    base_url
):
    result = []
    seen = set()

    for a in soup.select(
        "a[href]"
    ):
        context = link_context(
            a
        )

        date = parse_human_date(
            context
        )

        if not date:
            continue

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
        ).path.lower()

        bad = [
            "/products/",
            "/category/",
            "/play/",
            "/events/",
            "/accessories/",
        ]

        if any(
            part in path
            for part in bad
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
# DISCOVERY STAR WARS
# ============================================================

def discover_starwars(
    source,
    html,
    soup,
    base_url
):
    result = []
    seen = set()

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

        if not pattern.match(
            path
        ):
            continue

        slug = (
            path
            .rstrip("/")
            .split("/")[-1]
        )

        # jiné jazykové mutace pryč
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
            parse_human_date(
                link_context(a)
            )
        )

    return result[:MAX_PER_SOURCE]


# ============================================================
# DISCOVERY
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

    category = source[
        "category"
    ]

    if category == "pokemon":
        return discover_pokemon(
            source,
            html,
            soup,
            base_url
        )

    if category == "onepiece":
        return discover_onepiece(
            source,
            html,
            soup,
            base_url
        )

    if category == "lorcana":
        return discover_lorcana(
            source,
            html,
            soup,
            base_url
        )

    if category == "magic":
        return discover_magic(
            source,
            html,
            soup,
            base_url
        )

    if category == "yugioh":
        return discover_yugioh(
            source,
            html,
            soup,
            base_url
        )

    if category == "starwars":
        return discover_starwars(
            source,
            html,
            soup,
            base_url
        )

    return []


# ============================================================
# DETAIL ČLÁNKU
# ============================================================

def get_article(
    url,
    fallback_date=None,
    category=""
):
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

    # Nikdy neuložit falešnou HTTP error stránku.
    if is_error_page(
        soup
    ):
        print(
            "  Přeskočena chybová stránka:",
            url
        )

        return None

    # --------------------------------------------------------
    # TITULEK
    # --------------------------------------------------------

    title = meta_content(
        soup,
        [
            'meta[property="og:title"]',
            'meta[name="twitter:title"]',
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
    # POKÉMON: pouze normální TCG, ne Pocket
    # --------------------------------------------------------

    if category == "pokemon":
        page_text = clean(
            soup.get_text(
                " ",
                strip=True
            )
        ).lower()

        tcg_ok = (
            "trading card game" in page_text
            or
            "pokémon tcg" in page_text
            or
            "pokemon tcg" in page_text
        )

        pocket = (
            "tcg pocket" in title.lower()
            or
            "trading card game pocket"
            in title.lower()
        )

        if (
            not tcg_ok
            or pocket
        ):
            return None

    # --------------------------------------------------------
    # ANOTACE
    # --------------------------------------------------------

    original_summary = build_description(
        soup
    )

    # --------------------------------------------------------
    # OBRÁZEK
    # --------------------------------------------------------

    image = find_image(
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
                'meta[name="publish-date"]',
                'meta[name="datePublished"]',
            ]
        )
    )

    # <time datetime="">
    if not published:
        time_tag = soup.select_one(
            "time[datetime]"
        )

        if time_tag:
            published = parse_iso_date(
                time_tag.get(
                    "datetime"
                )
            )

    # datum ve viditelném textu
    if not published:
        published = parse_human_date(
            clean(
                soup.get_text(
                    " ",
                    strip=True
                )
            )[:7000]
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
            canonical.get(
                "href"
            )
        )

    return {
        "title_original":
            title,

        "summary_original":
            original_summary,

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
# STARÁ DATA
# ============================================================

def load_old_items():
    if not OUTPUT.exists():
        return []

    try:
        data = json.loads(
            OUTPUT.read_text(
                encoding="utf-8"
            )
        )

        if isinstance(
            data,
            list
        ):
            return data

    except Exception:
        pass

    return []


old_items = load_old_items()


# ============================================================
# VALIDACE STARÉHO / NOVÉHO ITEMU
# ============================================================

def item_is_valid(item):
    if not isinstance(
        item,
        dict
    ):
        return False

    title = clean(
        item.get("title")
        or
        item.get("title_original")
    )

    url = normalize_url(
        item.get(
            "url",
            ""
        )
    )

    if not title:
        return False

    if not url:
        return False

    if title_is_junk(
        title
    ):
        return False

    combined = (
        title
        + " "
        + clean(
            item.get(
                "summary",
                ""
            )
        )
    ).lower()

    if any(
        marker in combined
        for marker in ERROR_MARKERS
    ):
        return False

    return True


# ============================================================
# CACHE
# ============================================================

cache = {}

for item in old_items:
    if not item_is_valid(
        item
    ):
        continue

    url = normalize_url(
        item.get(
            "url",
            ""
        )
    )

    if (
        item.get(
            "pipeline_version"
        )
        ==
        PIPELINE_VERSION
        and
        len(
            clean(
                item.get(
                    "summary",
                    ""
                )
            )
        )
        >=
        180
    ):
        cache[url] = item


# ============================================================
# SBĚR
# ============================================================

new_items = []

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

        url = normalize_url(
            candidate["url"]
        )

        # Už máme kvalitní nový cache item.
        if url in cache:
            new_items.append(
                cache[url]
            )

            accepted += 1

            print(
                "  CACHE:",
                cache[url]
                .get(
                    "title",
                    ""
                )[:75]
            )

            continue

        article = get_article(
            url,
            candidate.get(
                "date"
            ),
            source["category"]
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

        original_title = clean(
            article.get(
                "title_original"
            )
        )

        if title_is_junk(
            original_title
        ):
            continue

        # ----------------------------------------------------
        # ČESKÝ TITULEK
        # ----------------------------------------------------

        title_cs = translate_cs(
            original_title,
            400
        )

        # Když překlad selže, zkusíme starší
        # českou verzi stejného URL.
        previous = next(
            (
                item
                for item in old_items
                if normalize_url(
                    item.get(
                        "url",
                        ""
                    )
                )
                ==
                article["url"]
            ),
            None
        )

        if not title_cs:
            if (
                previous
                and
                previous.get("title")
            ):
                title_cs = previous[
                    "title"
                ]
            else:
                title_cs = original_title

        # ----------------------------------------------------
        # DELŠÍ ČESKÁ ANOTACE
        # ----------------------------------------------------

        original_summary = clean(
            article.get(
                "summary_original",
                ""
            )
        )

        summary_cs = ""

        if original_summary:
            summary_cs = translate_cs(
                original_summary,
                1300
            )

        if not summary_cs:
            if (
                previous
                and
                len(
                    clean(
                        previous.get(
                            "summary",
                            ""
                        )
                    )
                )
                > 120
            ):
                summary_cs = previous[
                    "summary"
                ]

            else:
                summary_cs = (
                    "Nová informace z oficiálního webu "
                    f"{source['game']}. "
                    "Podrobnosti najdete v původním článku."
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

        if not item_is_valid(
            item
        ):
            continue

        new_items.append(
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
            0.25
        )


# ============================================================
# ZACHOVÁNÍ STARÝCH DOBRÝCH ČLÁNKŮ
# ============================================================

# Důležité:
# pokud Lorcana, Pokémon nebo jiný web
# jeden den nefunguje, staré dobré články nezmizí.

merged = {}


# Nejprve starší validní položky.
for item in old_items:
    if not item_is_valid(
        item
    ):
        continue

    published = parse_iso_date(
        item.get(
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

    if key[1]:
        merged[key] = item


# Nové položky mají přednost.
for item in new_items:
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

    if key[1]:
        merged[key] = item


items = list(
    merged.values()
)


# ============================================================
# POSLEDNÍ ČIŠTĚNÍ
# ============================================================

clean_items = []

for item in items:
    if not item_is_valid(
        item
    ):
        continue

    clean_items.append(
        item
    )


items = clean_items


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

counts = {
    source["game"]: 0
    for source in SOURCES
}


with_images = 0
with_long_summaries = 0


for item in items:
    game = item.get(
        "game",
        ""
    )

    if game in counts:
        counts[game] += 1

    if item.get("image"):
        with_images += 1

    if len(
        clean(
            item.get(
                "summary",
                ""
            )
        )
    ) >= 180:
        with_long_summaries += 1


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
    "S obrázkem:",
    with_images
)

print(
    "S delší anotací:",
    with_long_summaries
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
