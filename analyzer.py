"""
travel_seo_analyzer — analyzer.py
5 modules d'analyse SEO. Les pages inaccessibles (4xx, erreur réseau)
sont incluses dans chaque rapport avec leur statut HTTP.
"""
import json, re
from bs4 import BeautifulSoup
from scraper import scrape_page, load_cache_index


# ── Helpers privés ────────────────────────────────────────────────────────────

def _get_soup(url: str) -> tuple:
    """Retourne (BeautifulSoup | None, error_str | None)."""
    html, _ = scrape_page(url)
    if not html:
        return None, "Page vide"
    if html.startswith("<!-- HTTP_"):
        code = re.search(r"HTTP_(\d+)", html)
        return None, f"HTTP {code.group(1) if code else '???'}"
    if html.startswith("<!-- SCRAPE_ERROR"):
        msg = re.search(r"SCRAPE_ERROR: (.+?) -->", html)
        return None, f"Erreur réseau : {msg.group(1)[:80] if msg else '?'}"
    return BeautifulSoup(html, "html.parser"), None


def _status(url: str) -> int:
    return load_cache_index().get(url, {}).get("status", 0)


def _txt(el) -> str:
    if el is None: return ""
    return re.sub(r"\s+", " ", el.get_text(separator=" ", strip=True))


def _schemas(soup) -> list:
    out = []
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            d = json.loads(tag.string or "{}")
            out.extend(d if isinstance(d, list) else [d])
        except Exception:
            pass
    return out


def _stypes(schemas: list) -> set:
    types: set = set()
    for d in schemas:
        if not isinstance(d, dict): continue
        t = d.get("@type", "")
        types.update(t if isinstance(t, list) else [t])
    return types


def _error_row(url: str, err: str, extra: dict | None = None) -> dict:
    base = {"url": url, "status": _status(url), "error": err}
    if extra:
        base.update(extra)
    return base


# ── Analyse 1 : SEO basique ───────────────────────────────────────────────────

def analyze_basic(urls: list[str]) -> list[dict]:
    rows = []
    for url in urls:
        soup, err = _get_soup(url)
        if err:
            rows.append(_error_row(url, err, {
                "h1":"", "h1_ok":False, "h1_count":0,
                "title":"", "title_ok":False,
                "meta_desc":"", "meta_ok":False, "issues":[err],
            }))
            continue
        h1s  = soup.find_all("h1")
        h1   = _txt(h1s[0]) if h1s else ""
        tit  = _txt(soup.find("title"))
        mt   = soup.find("meta", attrs={"name":"description"})
        meta = (mt.get("content","") or "").strip() if mt else ""
        iss  = []
        if not h1:       iss.append("H1 absent")
        if len(h1s) > 1: iss.append(f"{len(h1s)} H1 détectés")
        if not tit:      iss.append("Title absent")
        if not meta:     iss.append("Meta description absente")
        rows.append({
            "url":url, "status":_status(url), "error":None,
            "h1":h1, "h1_ok":bool(h1), "h1_count":len(h1s),
            "title":tit, "title_ok":bool(tit),
            "meta_desc":meta, "meta_ok":bool(meta), "issues":iss,
        })
    return rows


# ── Analyse 2 : Offres ────────────────────────────────────────────────────────

def _extract_offer_count(soup, html_raw: str) -> tuple[bool, int | None]:
    """
    Extrait le nombre d'offres avec 3 méthodes en cascade.
    Retourne (has_offers: bool, count: int | None)
    """
    # ── Méthode 1 : data-offers-count sur #filterEngine (le plus fiable)
    fe = soup.find(id="filterEngine")
    if fe:
        v = fe.get("data-offers-count", "")
        if v and v.isdigit():
            n = int(v)
            return n > 0, n

    # ── Méthode 2 : div.result-offers > span.label
    div = soup.find("div", class_="result-offers")
    if div:
        span = div.find("span", class_="label")
        if span:
            m = re.search(r"(\d+)", span.get_text())
            if m:
                n = int(m.group(1))
                return n > 0, n
        return True, None   # div présente mais count non parsé

    # ── Méthode 3 : GTM datalayer (travelSearchResults)
    m = re.search(r'travelSearchResults\s*=\s*"(\d+)"', html_raw)
    if m:
        n = int(m.group(1))
        return n > 0, n

    return False, None


def analyze_offers(urls: list[str]) -> list[dict]:
    rows = []
    for url in urls:
        soup, err = _get_soup(url)
        if err:
            rows.append(_error_row(url, err, {"has_offers":False, "count":None}))
            continue

        html_raw, _ = scrape_page(url)
        has_offers, count = _extract_offer_count(soup, html_raw)

        rows.append({
            "url":       url,
            "status":    _status(url),
            "error":     None,
            "has_offers":has_offers,
            "count":     count,
        })
    return rows


# ── Analyse 3 : Conformité specs ──────────────────────────────────────────────

def analyze_spec(urls: list[str]) -> list[dict]:
    rows = []
    for url in urls:
        soup, err = _get_soup(url)
        if err:
            rows.append(_error_row(url, err, {"checks":{}, "issues":[err], "score":0, "total":0, "pct":0}))
            continue
        checks: dict = {}
        issues: list = []
        title  = _txt(soup.find("title"))
        h1s    = soup.find_all("h1")
        h1     = _txt(h1s[0]) if h1s else ""
        mt     = soup.find("meta", attrs={"name":"description"})
        meta   = (mt.get("content","") or "").strip() if mt else ""
        ct     = soup.find("link", rel="canonical")
        can    = (ct.get("href","") or "").strip() if ct else ""
        sts    = _stypes(_schemas(soup))

        def chk(k, ok, msg=None):
            checks[k] = ok
            if not ok and msg: issues.append(msg)

        chk("title_format",     bool(re.search(r".+\|\s*Showroompriv[eé]", title, re.I)),
                                f"Title mal formaté : «{title[:70]}»")
        chk("h1_unique",        len(h1s)==1, f"{len(h1s)} H1 trouvé(s)")
        chk("h1_format",        h1.lower().startswith("voyage"),
                                f"H1 ne commence pas par «Voyages» : «{h1[:60]}»")
        chk("canonical_present",bool(can), "Canonical absent")
        chk("canonical_clean",  not bool(re.search(r"[?&](utm_|ref_|s_c\.)", can)),
                                "Canonical avec paramètres interdits")
        chk("og_title",         bool(soup.find("meta", property="og:title")),       "og:title absent")
        chk("og_description",   bool(soup.find("meta", property="og:description")), "og:description absent")
        chk("og_image",         bool(soup.find("meta", property="og:image")),        "og:image absent")
        chk("breadcrumb_schema",  "BreadcrumbList" in sts, "BreadcrumbList Schema.org absent")
        chk("meta_desc_length", 120 <= len(meta) <= 165, f"Meta desc : {len(meta)} chars (cible 120-165)")
        if soup.find(class_=re.compile(r"cpt.?faq|faq", re.I)):
            chk("faq_schema", "FAQPage" in sts, "FAQ présente sans FAQPage Schema.org")

        valid = {k:v for k,v in checks.items() if v is not None}
        score = sum(1 for v in valid.values() if v is True)
        total = len(valid)
        rows.append({"url":url, "status":_status(url), "error":None,
                     "checks":checks, "issues":issues,
                     "score":score, "total":total, "pct":round(score/total*100) if total else 0})
    return rows


# ── Analyse 4 : Guide Google AIO ─────────────────────────────────────────────

def analyze_google_ai(urls: list[str]) -> list[dict]:
    rows = []
    for url in urls:
        soup, err = _get_soup(url)
        if err:
            rows.append(_error_row(url, err, {"checks":{}, "issues":[err], "score":0, "total":0, "pct":0, "words":0}))
            continue
        checks: dict = {}
        issues: list = []
        sts   = _stypes(_schemas(soup))
        mt    = soup.find("meta", attrs={"name":"description"})
        meta  = (mt.get("content","") or "").strip() if mt else ""
        ct    = soup.find("link", rel="canonical")
        can   = (ct.get("href","") or "").strip() if ct else ""
        words = len(soup.get_text(separator=" ", strip=True).split())
        imgs  = soup.find_all("img")
        alts  = [i for i in imgs if (i.get("alt","") or "").strip()]

        def chk(k, ok, msg=None):
            checks[k] = ok
            if not ok and msg: issues.append(msg)

        chk("structured_data",    len(_schemas(soup)) > 0,      "Aucun JSON-LD détecté")
        chk("h2_present",         bool(soup.find_all("h2")),     "Pas de H2 — contenu peu structuré")
        chk("meta_desc_length",   len(meta) >= 120,              f"Meta desc trop courte ({len(meta)} chars)")
        chk("sufficient_content", words >= 300,                  f"Contenu insuffisant ({words} mots)")
        url_n = url.rstrip("/")
        can_n = can.rstrip("/")
        chk("canonical_self_ref", bool(can) and (url_n==can_n or can_n.startswith(url_n+"?page=")),
                                  f"Canonical ne se référence pas lui-même")
        if imgs:
            chk("img_alt_text", len(alts)/len(imgs) >= 0.8,
                                f"{len(imgs)-len(alts)}/{len(imgs)} images sans alt")
        chk("faq_schema",     "FAQPage" in sts, "FAQPage Schema.org absent")
        chk("main_landmark",  bool(soup.find("main")),           "Balise <main> absente")

        valid = {k:v for k,v in checks.items() if v is not None}
        score = sum(1 for v in valid.values() if v is True)
        total = len(valid)
        rows.append({"url":url, "status":_status(url), "error":None,
                     "checks":checks, "issues":issues,
                     "score":score, "total":total, "pct":round(score/total*100) if total else 0,
                     "words":words})
    return rows


# ── Export contenu éditorial ──────────────────────────────────────────────────

def extract_content(urls: list[str]) -> list[dict]:
    rows = []
    for url in urls:
        soup, err = _get_soup(url)
        if err:
            rows.append(_error_row(url, err, {
                "h1":"", "meta_title":"", "meta_desc":"",
                "header_intro":"", "bloc_edito":"", "cpt_faq":"",
            }))
            continue
        h1s = soup.find_all("h1")
        mt  = soup.find("meta", attrs={"name":"description"})
        rows.append({
            "url":url, "status":_status(url), "error":None,
            "h1":           _txt(h1s[0]) if h1s else "",
            "meta_title":   _txt(soup.find("title")),
            "meta_desc":    (mt.get("content","") or "").strip() if mt else "",
            "header_intro": _txt(soup.find(class_="header-intro")),
            "bloc_edito":   _txt(soup.find(class_="bloc-edito-content")),
            "cpt_faq":      _txt(soup.find(class_="cpt-faq")),
        })
    return rows