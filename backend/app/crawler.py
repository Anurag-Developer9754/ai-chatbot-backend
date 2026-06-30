"""
Two ingestion paths:
1. WooCommerce REST API -> structured product data (reliable, preferred)
2. Generic page crawler -> FAQ/policy/about/contact pages (text scraping)

Structured data is always preferred over scraping where available — it's
more reliable and includes fields (price, stock, SKU) that free text often
loses formatting on.
"""
import re
import time
from typing import List, Dict, Set
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from . import config
from .vector_store import upsert_chunks


def sync_woocommerce_products(
    tenant_id: str, site_url: str, consumer_key: str, consumer_secret: str
) -> int:
    """Pull all products via WooCommerce REST API and index them.
    Returns number of products indexed."""
    site_url = site_url.rstrip("/")
    page = 1
    total_indexed = 0

    while True:
        resp = requests.get(
            f"{site_url}/wp-json/wc/v3/products",
            auth=(consumer_key, consumer_secret),
            params={"per_page": 100, "page": page, "status": "publish"},
            timeout=config.CRAWL_TIMEOUT_SECONDS,
        )
        if resp.status_code != 200:
            raise RuntimeError(
                f"WooCommerce API error {resp.status_code}: {resp.text[:300]}"
            )
        products = resp.json()
        if not products:
            break

        ids, texts, metas = [], [], []
        for p in products:
            categories = ", ".join(c["name"] for c in p.get("categories", []))
            tags = ", ".join(t["name"] for t in p.get("tags", []))
            description = _strip_html(p.get("short_description") or p.get("description") or "")
            stock_status = p.get("stock_status", "unknown")
            price = p.get("price", "")

            # Rich text chunk: category/tags explicit so embeddings capture
            # "gifting", "home decor" style intent matching, not just keywords.
            text_chunk = (
                f"Product: {p['name']}\n"
                f"Category: {categories}\n"
                f"Tags: {tags}\n"
                f"Description: {description}\n"
                f"Price: ₹{price}\n"
                f"Stock: {stock_status}"
            )

            ids.append(f"product_{p['id']}")
            texts.append(text_chunk)
            metas.append({
                "type": "product",
                "product_id": p["id"],
                "name": p["name"],
                "price": str(price),
                "url": p.get("permalink", ""),
                "image": (p.get("images") or [{}])[0].get("src", ""),
                "stock_status": stock_status,
                "category": categories,
            })

        upsert_chunks(tenant_id, ids, texts, metas)
        total_indexed += len(products)
        page += 1
        if page > 50:  # safety cap: 5000 products max per sync run
            break

    return total_indexed


def sync_woocommerce_categories(
    tenant_id: str, site_url: str, consumer_key: str, consumer_secret: str
) -> int:
    """Index category descriptions too, helps with broad queries like
    'what kind of home decor do you have'."""
    site_url = site_url.rstrip("/")
    resp = requests.get(
        f"{site_url}/wp-json/wc/v3/products/categories",
        auth=(consumer_key, consumer_secret),
        params={"per_page": 100},
        timeout=config.CRAWL_TIMEOUT_SECONDS,
    )
    if resp.status_code != 200:
        return 0
    categories = resp.json()
    ids, texts, metas = [], [], []
    for c in categories:
        desc = _strip_html(c.get("description", ""))
        text_chunk = f"Category: {c['name']}\nDescription: {desc}\nProduct count: {c.get('count', 0)}"
        ids.append(f"category_{c['id']}")
        texts.append(text_chunk)
        metas.append({"type": "category", "name": c["name"], "url": c.get("permalink", "") or ""})
    upsert_chunks(tenant_id, ids, texts, metas)
    return len(categories)


# ---------------- Generic page crawler (FAQ/policy/about/contact) ----------------

PRIORITY_PATH_HINTS = [
    "faq", "shipping", "return", "refund", "policy", "policies",
    "contact", "about", "terms", "privacy", "warranty",
]


def crawl_site_pages(tenant_id: str, site_url: str) -> Dict:
    """Crawl static informational pages (not product listing pages —
    those come from the WooCommerce API instead). Returns a status report."""
    site_url = site_url.rstrip("/")
    visited: Set[str] = set()
    failed: List[str] = []
    to_visit = [site_url]
    indexed = 0
    domain = urlparse(site_url).netloc

    headers = {"User-Agent": config.CRAWL_USER_AGENT}

    while to_visit and len(visited) < config.MAX_PAGES_TO_CRAWL:
        url = to_visit.pop(0)
        if url in visited:
            continue
        visited.add(url)

        try:
            resp = requests.get(url, headers=headers, timeout=config.CRAWL_TIMEOUT_SECONDS)
            if resp.status_code != 200 or "text/html" not in resp.headers.get("Content-Type", ""):
                continue
        except requests.RequestException:
            failed.append(url)
            continue

        soup = BeautifulSoup(resp.text, "html.parser")

        # extract internal links to keep crawling (breadth-first, bounded by MAX_PAGES_TO_CRAWL)
        for a in soup.find_all("a", href=True):
            link = urljoin(url, a["href"]).split("#")[0]
            if urlparse(link).netloc == domain and link not in visited:
                # skip obvious product/cart/account/checkout noise to save crawl budget
                if not re.search(r"/(cart|checkout|account|wp-admin|wp-login)", link):
                    to_visit.append(link)

        # extract main text content
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        text = soup.get_text(separator=" ", strip=True)
        text = re.sub(r"\s+", " ", text)

        if len(text) < 80:  # skip near-empty pages
            continue

        # chunk long pages (~1000 chars) so retrieval stays precise
        chunks = [text[i:i + 1000] for i in range(0, len(text), 1000)]
        ids, texts, metas = [], [], []
        for idx, chunk in enumerate(chunks[:10]):  # cap chunks per page
            ids.append(f"page_{abs(hash(url))}_{idx}")
            texts.append(f"Page: {soup.title.string if soup.title else url}\nURL: {url}\nContent: {chunk}")
            metas.append({"type": "page", "url": url})

        upsert_chunks(tenant_id, ids, texts, metas)
        indexed += 1

    return {
        "pages_indexed": indexed,
        "pages_visited": len(visited),
        "failed_urls": failed,
    }


def _strip_html(raw_html: str) -> str:
    if not raw_html:
        return ""
    text = BeautifulSoup(raw_html, "html.parser").get_text(separator=" ", strip=True)
    return re.sub(r"\s+", " ", text)
