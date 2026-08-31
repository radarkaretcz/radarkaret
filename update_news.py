import json
import re
import time
from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from deep_translator import GoogleTranslator


OUTPUT = Path("data/news.json")
MAX_PER_SOURCE = 12

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/124 Safari/537.36 "
        "RadarKaret/1.0"
    ),
    "Accept-Language": "en-US,en;q=0.9"
}


SOURCES = [
    {
        "game": "Pokémon",
        "category": "pokemon",
        "url": "https://www.pokemon.com/us/pokemon-news/",
        "domain": "pokemon.com",
        "must_contain": "/us/news/"
    },
    {
        "game": "One Piece",
        "category": "onepiece",
        "url": "https://en.onepiece-cardgame.com/news/",
        "domain": "en.onepiece-cardgame.com",
        "must_contain": "/"
    },
    {
        "game": "Disney Lorcana",
        "category": "lorcana",
        "url": "https://www.disneylorcana.com/en-US/news/",
        "domain": "disneylorcana.com",
        "must_contain": "/news/"
    },
    {
        "game": "Magic",
        "category": "magic",
        "url": "https://magic.wizards.com/en/news",
        "domain": "magic.wizards.com",
        "must_contain": "/en/news/"
    },
    {
        "game": "Yu-Gi-Oh!",
        "category": "yugioh",
        "url": "https://www.yugioh-card.com/eu/category/news/?view=all",
        "domain": "yugioh-card.com",
        "must_contain": "/eu/"
    },
]


translator = GoogleTranslator(
    source="auto",
    target="cs"
)


def clean(text):
    if not text:
        return ""

    return re.sub(
        r"\s+",
        " ",
        text
    ).strip()


def translate(text, limit=1000):

    text = clean(text)[:limit]

    if not text:
        return ""

    try:
        result = translator.translate(text)

        if result:
            return clean(result)

    except Exception as exc:
        print("Překlad selhal:", exc)

    return text


def soup_from_url(url):

    response = requests.get(
        url,
        headers=HEADERS,
        timeout=25
    )

    response.raise_for_status()

    return (
        BeautifulSoup(
            response.text,
            "html.parser"
        ),
        response.url
    )


def meta_content(soup, selectors):

    for selector in selectors:

        tag = soup.select_one(selector)

        if not tag:
            continue

        value = tag.get("content")

        if value:
            return clean(value)

    return ""


def get_article(url):

    try:

        soup, final_url = soup_from_url(url)

    except Exception as exc:

        print(
            "Nelze načíst článek:",
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

    if not title and soup.title:

        title = clean(
            soup.title.get_text(
                " ",
                strip=True
            )
        )


    description = meta_content(
        soup,
        [
            'meta[property="og:description"]',
            'meta[name="description"]',
            'meta[name="twitter:description"]'
        ]
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


    published = meta_content(
        soup,
        [
            'meta[property="article:published_time"]',
            'meta[name="date"]',
            'meta[name="publish-date"]'
        ]
    )


    # JSON-LD datum
    if not published:

        for script in soup.select(
            'script[type="application/ld+json"]'
        ):

            try:

                data = json.loads(
                    script.get_text()
                )

                candidates = (
                    data
                    if isinstance(data, list)
                    else [data]
                )

                for item in candidates:

                    if not isinstance(
                        item,
                        dict
                    ):
                        continue

                    published = (
                        item.get("datePublished")
                        or
                        item.get("dateCreated")
                    )

                    if published:
                        break

                if published:
                    break

            except Exception:
                pass


    # fallback
    if not published:
        published = datetime.now(
            timezone.utc
        ).isoformat()


    return {
        "title_original": title,
        "summary_original": description,
        "image": image,
        "url": final_url,
        "published": published
    }


def get_links(source):

    try:

        soup, base_url = soup_from_url(
            source["url"]
        )

    except Exception as exc:

        print(
            "Nelze načíst seznam:",
            source["game"],
            exc
        )

        return []


    links = []

    seen = set()


    for a in soup.find_all(
        "a",
        href=True
    ):

        href = urljoin(
            base_url,
            a["href"]
        )

        parsed = urlparse(href)

        if source["domain"] not in parsed.netloc:
            continue

        if (
            source["must_contain"]
            not in parsed.path
        ):
            continue

        # nechceme samotnou hlavní stránku
        if (
            href.rstrip("/")
            ==
            source["url"].rstrip("/")
        ):
            continue

        # ignorovat obecné sekce
        bad_parts = [
            "/privacy",
            "/contact",
            "/terms",
            "/cookie",
            "/faq",
            "/rules"
        ]

        if any(
            bad in href.lower()
            for bad in bad_parts
        ):
            continue

        text = clean(
            a.get_text(
                " ",
                strip=True
            )
        )

        # velmi krátké menu odkazy nechceme
        if len(text) < 8:
            continue

        href = href.split("#")[0]

        if href in seen:
            continue

        seen.add(href)

        links.append(href)


    return links[
        :MAX_PER_SOURCE
    ]


all_items = []


for source in SOURCES:

    print()
    print(
        "Sleduji:",
        source["game"]
    )

    links = get_links(source)

    print(
        "Nalezeno kandidátů:",
        len(links)
    )


    for url in links:

        article = get_article(url)

        if not article:
            continue


        original_title = clean(
            article.get(
                "title_original"
            )
        )

        if not original_title:
            continue


        # odfiltruj homepage/menu
        if len(original_title) < 10:
            continue


        print(
            " +",
            original_title[:80]
        )


        title_cs = translate(
            original_title,
            350
        )


        description_original = clean(
            article.get(
                "summary_original"
            )
        )


        if description_original:

            summary_cs = translate(
                description_original,
                850
            )

        else:

            summary_cs = (
                f"Aktuální informace "
                f"ze světa {source['game']}."
            )


        all_items.append(
            {
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
                    description_original,

                "image":
                    article.get(
                        "image",
                        ""
                    ),

                "url":
                    article.get(
                        "url",
                        url
                    ),

                "published":
                    article.get(
                        "published"
                    ),

                "source_type":
                    "official"
            }
        )


        time.sleep(0.25)


# ==================================================
# DUPLICITY
# ==================================================

unique = {}


for item in all_items:

    key = (
        item["category"],
        item["url"]
    )

    unique[key] = item


items = list(
    unique.values()
)


# ==================================================
# ŘAZENÍ
# ==================================================

def timestamp(item):

    value = item.get(
        "published",
        ""
    )

    try:

        value = value.replace(
            "Z",
            "+00:00"
        )

        return datetime.fromisoformat(
            value
        ).timestamp()

    except Exception:

        return 0


items.sort(
    key=timestamp,
    reverse=True
)


items = items[:80]


# ==================================================
# ULOŽIT
# ==================================================

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


print()
print(
    "=============================="
)

print(
    "RADARKARET HOTOVO"
)

print(
    "Celkem zpráv:",
    len(items)
)

print(
    "Zapsáno do:",
    OUTPUT
)

print(
    "=============================="
)
