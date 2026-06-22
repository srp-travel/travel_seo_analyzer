"""
travel_seo_analyzer — scraper.py
Sitemap parsing + scraping avec cache persistant et user-agent réaliste.
"""
import gzip, hashlib, json, logging, os, re, threading, time
import requests
from bs4 import BeautifulSoup
from datetime import datetime
from urllib.parse import urlparse

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("travel_scraper")

CACHE_DIR   = "cache"
SITEMAP_URL = "https://voyage.showroomprive.com/sitemap_serp.xml"

# User-agent Chrome 125 — Accept-Encoding intentionnellement absent
# (requests gère la décompression automatiquement ; le forcer peut casser le décodage)
HEADERS = {
    "User-Agent":              "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Accept":                  "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language":         "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
    "Connection":              "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Ch-Ua":               '"Google Chrome";v="125", "Chromium";v="125", "Not.A/Brand";v="24"',
    "Sec-Ch-Ua-Mobile":        "?0",
    "Sec-Ch-Ua-Platform":      '"Windows"',
    "Sec-Fetch-Dest":          "document",
    "Sec-Fetch-Mode":          "navigate",
    "Sec-Fetch-Site":          "none",
    "Sec-Fetch-User":          "?1",
    "Cache-Control":           "max-age=0",
    "Referer":                 "https://www.google.fr/",
    "DNT":                     "1",
}

# ── Décodage ──────────────────────────────────────────────────────────────────

def _decode(content: bytes) -> str:
    """Décode bytes → str. Gère gzip résiduel et encodages alternatifs."""
    if content[:2] == b"\x1f\x8b":
        try:
            content = gzip.decompress(content)
        except Exception:
            pass
    for enc in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            return content.decode(enc)
        except Exception:
            continue
    return content.decode("utf-8", errors="replace")


def _fetch(url: str, timeout: int = 30) -> tuple[bytes, dict]:
    """GET réaliste. Retourne (content_bytes, headers)."""
    resp = requests.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
    resp.raise_for_status()
    content = resp.content
    # Détection contenu encore compressé (brotli non géré sans package)
    preview = content[:80].decode("utf-8", errors="replace")
    if "\ufffd" in preview and len(preview.replace("\ufffd","").strip()) < 8:
        log.warning("[fetch] Contenu binaire — tentative décompression manuelle")
        import zlib
        for fn in [gzip.decompress, lambda b: zlib.decompress(b, -zlib.MAX_WBITS)]:
            try: content = fn(content); break
            except Exception: pass
    log.info(f"[fetch] {resp.status_code} · {len(content)} bytes · {url[:80]}")
    return content, dict(resp.headers)


# ── Cache ─────────────────────────────────────────────────────────────────────

_lock = threading.Lock()


def _index_path() -> str:
    return os.path.join(CACHE_DIR, "_index.json")


def _slug(url: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]", "_", urlparse(url).path.strip("/"))[:60]
    return f"{s}_{hashlib.md5(url.encode()).hexdigest()[:8]}.html"


def load_cache_index() -> dict:
    path = _index_path()
    if not os.path.exists(path):
        return {}
    with _lock:
        try:
            raw = open(path, encoding="utf-8").read().strip()
            if not raw:
                return {}
            try:
                return json.loads(raw)
            except json.JSONDecodeError as e:
                if "Extra data" in str(e):
                    obj, _ = json.JSONDecoder().raw_decode(raw)
                    if isinstance(obj, dict):
                        _write_index(obj)
                        return obj
                log.error(f"[cache] Index corrompu : {e}")
                _backup(path)
                return {}
        except Exception as e:
            log.error(f"[cache] Lecture index : {e}")
            _backup(path)
            return {}


def _write_index(index: dict) -> None:
    """Écriture atomique (sans verrou — appelé depuis un contexte déjà verrouillé)."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    tmp = _index_path() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)
    os.replace(tmp, _index_path())


def _save_index(index: dict) -> None:
    with _lock:
        _write_index(index)


def _backup(path: str) -> None:
    import shutil
    try:
        shutil.copy(path, path + ".corrupt")
        os.remove(path)
    except Exception:
        pass


def get_cache_status() -> dict:
    idx = load_cache_index()
    if not idx:
        return {"exists": False, "count": 0, "date": None}
    dates = [v.get("scraped_at","") for v in idx.values() if v.get("scraped_at")]
    return {"exists": True, "count": len(idx), "date": max(dates) if dates else None}


# ── Sitemap ───────────────────────────────────────────────────────────────────

def _locs(content: bytes) -> list[str]:
    """Extrait <loc> avec 3 méthodes en cascade."""
    text = _decode(content)
    for parser in ("lxml-xml", "html.parser"):
        try:
            soup = BeautifulSoup(text, parser)
            locs = soup.find_all("loc")
            if locs:
                log.info(f"[sitemap] {parser} → {len(locs)} <loc>")
                return [l.get_text(strip=True) for l in locs]
        except Exception:
            pass
    # Regex fallback
    found = re.findall(r"<loc>\s*(.*?)\s*</loc>", text, re.DOTALL | re.I)
    log.info(f"[sitemap] regex → {len(found)} <loc>")
    return found


def parse_sitemap(url: str = SITEMAP_URL) -> list[str]:
    content, _ = _fetch(url)
    text = _decode(content)
    # Sitemap index ?
    if "<sitemapindex" in text or "<sitemap>" in text.lower():
        log.info("[sitemap] Sitemap index détecté")
        pages: list[str] = []
        for sub in _locs(content):
            try:
                sub_content, _ = _fetch(sub)
                pages.extend(_locs(sub_content))
            except Exception as e:
                log.error(f"[sitemap] {sub} : {e}")
        log.info(f"[sitemap] Total : {len(pages)} pages")
        return pages
    urls = _locs(content)
    if not urls:
        log.warning(f"[sitemap] Aucune URL. Aperçu :\n{text[:400]}")
    return urls


# ── Scraping ──────────────────────────────────────────────────────────────────

def scrape_page(url: str, force: bool = False) -> tuple[str, bool]:
    """Fetch + cache une page. Retourne (html, from_cache)."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    idx      = load_cache_index()
    filename = _slug(url)
    path     = os.path.join(CACHE_DIR, filename)

    # Depuis le cache
    if not force and url in idx and os.path.exists(path):
        return open(path, encoding="utf-8", errors="replace").read(), True

    time.sleep(0.3)
    status = 0
    try:
        resp   = requests.get(url, headers=HEADERS, timeout=30, allow_redirects=True)
        status = resp.status_code
        if status >= 400:
            html = f"<!-- HTTP_{status} -->"
            log.warning(f"[scraper] HTTP {status} · {url}")
        else:
            html = _decode(resp.content)
    except Exception as exc:
        html = f"<!-- SCRAPE_ERROR: {exc} -->"
        log.error(f"[scraper] {url} : {exc}")

    with open(path, "w", encoding="utf-8") as f:
        f.write(html)

    idx[url] = {"file": filename, "scraped_at": datetime.now().isoformat(), "status": status}
    _save_index(idx)
    return html, False



def scrape_batch(urls: list[str], force: bool = False, on_progress=None) -> dict:
    """
    Scrape optimisé : lit l'index UNE fois, scrape, écrit UNE fois.
    Evite les double-requêtes et les I/O excessives.
    on_progress(done, total, url, icon) — optionnel
    """
    os.makedirs(CACHE_DIR, exist_ok=True)
    idx = load_cache_index()   # lecture unique

    for i, url in enumerate(urls):
        filename   = _slug(url)
        cache_path = os.path.join(CACHE_DIR, filename)

        if not force and url in idx and os.path.exists(cache_path):
            icon = "📁"  # depuis cache
        else:
            time.sleep(0.3)
            status = 0
            try:
                resp   = requests.get(url, headers=HEADERS, timeout=30, allow_redirects=True)
                status = resp.status_code
                html   = f"<!-- HTTP_{status} -->" if status >= 400 else _decode(resp.content)
                icon   = "⚠" if status >= 400 else "✓"
            except Exception as exc:
                html = f"<!-- SCRAPE_ERROR: {exc} -->"
                icon = "✗"
                log.error(f"[scraper] {url} : {exc}")

            with open(cache_path, "w", encoding="utf-8") as f:
                f.write(html)

            idx[url] = {
                "file":       filename,
                "scraped_at": datetime.now().isoformat(),
                "status":     status,
            }

        if on_progress:
            on_progress(i + 1, len(urls), url, icon)

    _save_index(idx)   # écriture unique
    return idx

def scrape_all(urls: list[str], force: bool = False, on_progress=None) -> dict:
    for i, url in enumerate(urls):
        html, cached = scrape_page(url, force=force)
        if on_progress:
            on_progress(i + 1, len(urls), url, cached)
    return load_cache_index()