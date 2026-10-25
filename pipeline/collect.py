"""Bounded metadata discovery, with separate publication and discovery dates.

Feeds are a fast hint, not an inventory. Crossref checkpoints cover index dates
with a frozen upper bound, and advance only after every page has been read.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import unquote, urlencode, urlparse

import httpx
from bs4 import BeautifulSoup

from .journals import JOURNALS
from .store import Store, normalize_doi, paper_id

USER_AGENT = "AstroBriefViet/0.1 (+https://github.com/Thithilia/astrobrief-vi; noncommercial astronomy metadata)"
CROSSREF_URL = "https://api.crossref.org/journals/{issn}/works"
CROSSREF_FIELDS = "DOI,title,container-title,author,abstract,published,published-online,published-print,issued,volume,issue,page,article-number,link,URL,resource,license,relation"
DC = "http://purl.org/dc/elements/1.1/"


class SourceError(RuntimeError):
    pass


class RateLimited(SourceError):
    def __init__(self, seconds: int = 900):
        self.seconds = max(1, seconds)
        super().__init__(f"Source rate limited; retry after {self.seconds} seconds")


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def crossref_date(dt: datetime) -> str:
    """Crossref accepts UTC clock fields but rejects a trailing Z/offset."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def _as_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def clean_text(value: str | None) -> str:
    return " ".join(BeautifulSoup(html.unescape(str(value or "")), "html.parser").get_text(" ", strip=True).split())


def parse_date(value: str | None) -> tuple[str | None, str | None]:
    text = str(value or "").strip()
    if not text:
        return None, None
    if re.fullmatch(r"\d{4}", text):
        return text, "year"
    if re.fullmatch(r"\d{4}-\d{2}", text):
        try:
            datetime.strptime(text, "%Y-%m")
            return text, "month"
        except ValueError:
            return None, None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if "T" in text or " " in text:
            if dt.tzinfo is not None:
                return iso(dt), "day"
        return dt.date().isoformat(), "day"
    except ValueError:
        pass
    try:
        dt = parsedate_to_datetime(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return iso(dt), "day"
    except (ValueError, TypeError, OverflowError):
        return None, None


def date_parts(value: dict | None) -> tuple[str | None, str | None]:
    if not isinstance(value, dict):
        return None, None
    dates = value.get("date-parts")
    if not isinstance(dates, list) or not dates or not isinstance(dates[0], list):
        return None, None
    parts = dates[0]
    if not parts:
        return None, None
    formatted = "-".join(str(x).zfill(4 if i == 0 else 2) for i, x in enumerate(parts[:3]))
    return parse_date(formatted)


def infer_kind(title: str, article_number: str | None = None, journal: str | None = None) -> str:
    if re.search(r"\b(erratum|corrigendum|correction|retraction)\b", title, re.I):
        return "correction"
    if journal == "aa" and re.fullmatch(r"C\d+", str(article_number or "")):
        return "correction"
    if re.match(r"(?:editorial|foreword|preface)\b", title, re.I):
        return "editorial"
    if re.match(r"(?:review\s*:|a (?:systematic )?review of|review article\s*:)", title, re.I):
        return "review"
    if journal == "apjl" or re.fullmatch(r"L\d+", str(article_number or "")):
        return "letter"
    return "research"


def infer_topic(text: str) -> str:
    # These are discovery hints. The daily selector can refine the topic after reading.
    rules = (
        ("cosmology", r"cosmolog|dark matter|dark energy|reioniz|cosmic microwave|inflation|hubble tension"),
        ("compact", r"black hole|neutron star|pulsar|gravitational.wave|gamma.ray burst|supernova|compact object"),
        ("planets", r"exoplanet|planetary|planet formation|protoplanet|hot jupiter|transiting planet|habitable"),
        ("galaxies", r"galax|active galactic|\bagn\b|quasar"),
        ("solar", r"\bsun\b|solar wind|solar flare|coronal|heliosph|asteroid|comet|jupiter|saturn|mars"),
        ("stars", r"\bstar|stellar|interstellar|molecular cloud|accretion|dust|nova|globular cluster"),
        ("methods", r"instrument|spectrograph|detector|telescope|algorithm|machine learning|survey|simulation|spectroscopy"),
    )
    for topic, pattern in rules:
        if re.search(pattern, text, re.I):
            return topic
    return "other"


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _values(item: ET.Element, name: str) -> list[str]:
    return ["".join(child.itertext()).strip() for child in item if _local(child.tag).lower() == name.lower()]


def _first(item: ET.Element, *names: str) -> str:
    for name in names:
        values = _values(item, name)
        if values and values[0]:
            return values[0]
    return ""


def _doi_in(value: str) -> str:
    direct = normalize_doi(value)
    if direct:
        return direct
    match = re.search(r"10\.\d{4,9}/[^\s<>\"?&#]+", html.unescape(unquote(value)), re.I)
    return normalize_doi(match.group(0)) if match else ""


def parse_feed(raw: bytes | str, journal: dict | str, now: datetime | None = None) -> list[dict]:
    """Parse all entries, including RDF namespaces and repeated DC creators/subjects."""
    key = journal if isinstance(journal, str) else journal["id"]
    now = now or datetime.now(timezone.utc)
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise SourceError("Feed is not valid XML (publisher may be blocking access)") from exc
    if _local(root.tag).lower() not in {"rss", "rdf", "feed"}:
        raise SourceError("Expected RSS/Atom, received another document")
    result = []
    for item in root.iter():
        if _local(item.tag).lower() not in {"item", "entry"}:
            continue
        identifiers = _values(item, "doi") + _values(item, "identifier") + _values(item, "guid") + _values(item, "link")
        doi = next((value for value in map(_doi_in, identifiers) if value), "")
        if not doi:
            # A source ID without an established DOI is kept in the raw feed cache, not guessed.
            continue
        title = clean_text(_first(item, "title"))
        if not title:
            continue
        link = _first(item, "link")
        if not link:
            for child in item:
                if _local(child.tag) == "link" and child.get("href") and child.get("rel", "alternate") == "alternate":
                    link = child.get("href", "")
                    break
        creators = [clean_text(value) for value in _values(item, "creator") if clean_text(value)]
        if not creators:
            for author in [child for child in item if _local(child.tag) == "author"]:
                names = _values(author, "name")
                creators.extend(clean_text(value) for value in names if clean_text(value))
        if not creators:
            authors = clean_text(_first(item, "authors", "author"))
            if authors:
                creators = [name.strip() for name in re.split(r"\s*;\s*|\s+and\s+", authors) if name.strip()]
        description = clean_text(_first(item, "description", "summary", "encoded"))
        # The A&A feed description is bibliography/author metadata, not an abstract.
        abstract = "" if key == "aa" else re.sub(r"^Abstract\s*", "", description)
        published_online, precision = parse_date(_first(item, "date", "pubDate", "published", "publicationDate"))
        article_number = clean_text(_first(item, "startingPage", "articleNumber")) or None
        issue_date = None
        issue_identifier = _first(item, "issueIdentifier")
        if key == "aa":
            match = re.search(r"/(\d{4})/(\d{2})$", issue_identifier)
            if match:
                issue_date = f"{match[1]}-{match[2]}"
        keywords = list(dict.fromkeys(clean_text(v) for v in _values(item, "subject") if clean_text(v)))
        corridor = clean_text(_first(item, "corridor"))
        result.append({
            "id": paper_id(doi), "doi": doi, "title": title, "journal": key,
            "authors": list(dict.fromkeys(creators)), "abstract": abstract,
            "published_online": published_online, "online_date_precision": precision,
            "issue_date": issue_date, "first_seen": iso(now), "updated_at": iso(now),
            "volume": _first(item, "volume") or None, "issue": _first(item, "number", "issue") or None,
            "article_number": article_number, "source_url": link or f"https://doi.org/{doi}",
            "pdf_url": _first(item, "pdf") or None, "arxiv_id": None,
            "kind": infer_kind(title, article_number, key),
            "topic": infer_topic(" ".join([title, abstract, corridor, *keywords])),
            "keywords": keywords, "corridor": corridor,
            "_online_source": "rss", "_metadata_sources": ["rss"],
        })
    return result


def parse_crossref(item: dict, journal: dict | str, now: datetime | None = None) -> dict | None:
    key = journal if isinstance(journal, str) else journal["id"]
    doi = normalize_doi(item.get("DOI"))
    if not doi:
        return None
    if not isinstance(journal, str) and item.get("container-title"):
        title = re.sub(r"[^a-z0-9]", "", clean_text(item["container-title"][0]).lower())
        expected = re.sub(r"[^a-z0-9]", "", journal["name"].lower())
        if title.removeprefix("the") != expected.removeprefix("the"):
            return None
    title = clean_text(" ".join(item.get("title", [])))
    if not title:
        return None
    now = now or datetime.now(timezone.utc)
    online, precision = date_parts(item.get("published-online"))
    issue_date, _ = date_parts(item.get("published-print") or (item.get("journal-issue") or {}).get("published-print"))
    authors = []
    for author in item.get("author", []):
        name = " ".join(str(author.get(part, "")).strip() for part in ("given", "family")).strip()
        name = name or author.get("name", "")
        if name:
            authors.append(name)
    article_number = str(item.get("article-number") or item.get("page") or "") or None
    abstract = clean_text(item.get("abstract", ""))
    links = item.get("link") or []
    pdf = next((link.get("URL") for link in links if "pdf" in link.get("content-type", "").lower()), None)
    source_url = ((item.get("resource") or {}).get("primary") or {}).get("URL") or item.get("URL") or f"https://doi.org/{doi}"
    licences = [{"url": license_.get("URL"), "content_version": license_.get("content-version")}
                for license_ in (item.get("license") or []) if license_.get("URL")]
    return {
        "id": paper_id(doi), "doi": doi, "journal": key, "title": title, "authors": authors,
        "abstract": abstract, "published_online": online, "online_date_precision": precision,
        "issue_date": issue_date, "first_seen": iso(now), "updated_at": iso(now),
        "volume": item.get("volume"), "issue": item.get("issue"), "article_number": article_number,
        "source_url": source_url, "pdf_url": pdf, "arxiv_id": None,
        "kind": infer_kind(title, article_number, key), "topic": infer_topic(title + " " + abstract),
        "licenses": licences, "relations": item.get("relation", {}),
        "_online_source": "crossref", "_metadata_sources": ["crossref"],
        # This is only a tracking eligibility hint, never displayed as an online date.
        "_publication_hint": date_parts(item.get("published") or item.get("issued"))[0],
    }


def _retry_after(value: str | None) -> int:
    try:
        return max(1, int(value or "900"))
    except ValueError:
        try:
            return max(1, int((parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds()))
        except (ValueError, TypeError):
            return 900


class CachedFetcher:
    def __init__(self, cache_dir: Path, *, timeout: float = 35, client=None):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.client = client or httpx.Client(timeout=httpx.Timeout(timeout, connect=10), follow_redirects=True,
                                             headers={"User-Agent": USER_AGENT})
        self._own_client = client is None
        self._crossref_last = 0.0

    def close(self):
        if self._own_client:
            self.client.close()

    def get(self, url: str, *, params: dict | None = None, ttl: int = 900) -> bytes:
        key = hashlib.sha256((url + "?" + urlencode(sorted((params or {}).items()))).encode()).hexdigest()
        body_path, meta_path = self.cache_dir / f"{key}.body", self.cache_dir / f"{key}.json"
        meta = {}
        if body_path.exists() and meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                if time.time() - float(meta.get("cached_at", 0)) < ttl:
                    return body_path.read_bytes()
            except (ValueError, OSError):
                meta = {}
        headers = {}
        if meta.get("etag"):
            headers["If-None-Match"] = meta["etag"]
        if meta.get("last_modified"):
            headers["If-Modified-Since"] = meta["last_modified"]
        if urlparse(url).hostname == "api.crossref.org":
            delay = 1.0 - (time.monotonic() - self._crossref_last)
            if delay > 0:
                time.sleep(delay)
            self._crossref_last = time.monotonic()
        try:
            response = self.client.get(url, params=params, headers=headers)
        except httpx.HTTPError as exc:
            raise SourceError(f"Network error: {type(exc).__name__}") from exc
        if response.status_code == 429:
            raise RateLimited(_retry_after(response.headers.get("Retry-After")))
        if response.status_code in (401, 403):
            raise SourceError(f"HTTP {response.status_code}: source blocked automated access")
        if response.status_code == 304 and body_path.exists():
            meta["cached_at"] = time.time()
            meta_path.write_text(json.dumps(meta), encoding="utf-8")
            return body_path.read_bytes()
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise SourceError(f"HTTP {response.status_code}") from exc
        raw = response.content
        prefix = raw[:10000].lower()
        if any(marker in prefix for marker in (b"radware bot manager", b"cf-chl-", b"confirm you are a human", b"<title>captcha")):
            raise SourceError("Publisher returned a CAPTCHA page")
        # Atomic replacement keeps a terminated collection from corrupting its cache.
        temp = body_path.with_suffix(".tmp")
        temp.write_bytes(raw)
        temp.replace(body_path)
        meta = {"cached_at": time.time(), "etag": response.headers.get("ETag"),
                "last_modified": response.headers.get("Last-Modified"), "url": str(response.url)}
        meta_path.write_text(json.dumps(meta), encoding="utf-8")
        return raw

    def get_json(self, url: str, *, params: dict | None = None, ttl: int = 900) -> dict:
        try:
            return json.loads(self.get(url, params=params, ttl=ttl))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise SourceError("Metadata endpoint did not return JSON") from exc


def _eligible(paper: dict, store: Store, tracking_start: str, now: datetime) -> bool:
    if store.get_paper(paper["doi"]):
        return True
    date = paper.get("published_online") or paper.get("issue_date") or paper.get("_publication_hint")
    if not date:
        # Retain weak metadata without inventing a date. It can be reconciled later.
        return True
    # Month/year precision overlaps the interval; it is not converted to a fake day.
    start_date = tracking_start[:10]
    if date[:len(start_date)] > iso(now + timedelta(days=1))[:len(date[:10])]:
        return False
    return date[:10] >= start_date[:len(date[:10])]


def collect_all(store: Store, days: int = 30, reconcile: bool = True, now: datetime | None = None,
                *, fetcher=None, journals=None) -> dict:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    journal_list = list(journals or JOURNALS)
    tracking_start = store.get_state("tracking_start")
    if not tracking_start:
        tracking_start = iso(now - timedelta(days=days))
        store.set_state("tracking_start", tracking_start)
    own_fetcher = fetcher is None
    fetcher = fetcher or CachedFetcher(store.db_path.parent / "cache" / "metadata")
    health = store.get_state("journal_health", {})
    report = {"started_at": iso(now), "tracking_start": tracking_start, "new_papers": 0,
              "processed": 0, "journals": {}}
    crossref_cooldown = store.get_state("crossref:cooldown_until")
    blocked_until = _as_datetime(crossref_cooldown) if crossref_cooldown else None
    try:
        for journal in journal_list:
            key = journal["id"]
            previous = health.get(key, {})
            result = {"rss_count": 0, "crossref_count": 0, "errors": []}
            successes = 0
            try:
                raw = fetcher.get(journal["feed"], ttl=600)
                parsed = parse_feed(raw, journal, now)
                papers = [paper for paper in parsed if _eligible(paper, store, tracking_start, now)]
                result["rss_count"] = len(parsed)
                result["rss_eligible"] = len(papers)
                report["new_papers"] += store.upsert_papers(papers)
                report["processed"] += len(papers)
                successes += 1
            except (SourceError, ValueError, OSError) as exc:
                result["errors"].append(f"RSS: {exc}")
            if reconcile:
                checkpoint_key = f"crossref_checkpoint:{key}"
                checkpoint = store.get_state(checkpoint_key)
                try:
                    if blocked_until and blocked_until > now:
                        raise RateLimited(int((blocked_until - now).total_seconds()))
                    if checkpoint:
                        window_start = _as_datetime(checkpoint) - timedelta(hours=24)
                        filters = f"type:journal-article,from-index-date:{crossref_date(window_start)},until-index-date:{crossref_date(now)}"
                    else:
                        # Crossref may use a month-only print date as the earliest date.
                        # Query from the month's beginning and apply the precise local cutoff.
                        first_month = tracking_start[:7] + "-01"
                        filters = (f"type:journal-article,from-pub-date:{first_month},until-pub-date:{iso(now + timedelta(days=1))[:10]},"
                                   f"until-index-date:{crossref_date(now)}")
                    cursor = "*"
                    seen_pages = set()
                    for _ in range(200):
                        params = {"filter": filters, "rows": 1000, "cursor": cursor, "select": CROSSREF_FIELDS}
                        response = fetcher.get_json(CROSSREF_URL.format(issn=journal["issn"]), params=params, ttl=600)
                        message = response.get("message", {})
                        batch = message.get("items")
                        if not isinstance(batch, list):
                            raise SourceError("Crossref response has no item list")
                        signature = hashlib.sha256(json.dumps(batch, sort_keys=True).encode()).hexdigest()
                        if batch and signature in seen_pages:
                            raise SourceError("Crossref pagination repeated an entire page")
                        seen_pages.add(signature)
                        parsed = [paper for item in batch if (paper := parse_crossref(item, journal, now))]
                        papers = [paper for paper in parsed if _eligible(paper, store, tracking_start, now)]
                        result["crossref_count"] += len(parsed)
                        report["new_papers"] += store.upsert_papers(papers)
                        report["processed"] += len(papers)
                        next_cursor = message.get("next-cursor")
                        if len(batch) < 1000 or not next_cursor:
                            break
                        # Elasticsearch scroll ids can stay identical while the server
                        # advances the cursor. Detect repeated CONTENT, not just ids.
                        cursor = next_cursor
                    else:
                        raise SourceError("Crossref pagination exceeded the bounded page count")
                    # Failed/partial traversals never reach this commit.
                    store.set_state(checkpoint_key, iso(now))
                    result["checkpoint"] = iso(now)
                    successes += 1
                except RateLimited as exc:
                    blocked_until = now + timedelta(seconds=exc.seconds)
                    store.set_state("crossref:cooldown_until", iso(blocked_until))
                    result["errors"].append(f"Crossref: {exc}")
                except (SourceError, ValueError, OSError) as exc:
                    result["errors"].append(f"Crossref: {exc}")
            status = "ok" if not result["errors"] else "partial" if successes else "error"
            health[key] = {
                "status": status, "last_attempt": iso(now),
                "last_success": iso(now) if successes else previous.get("last_success"),
                "error": "; ".join(result["errors"]) or None,
                "rss_count": result["rss_count"], "crossref_count": result["crossref_count"],
            }
            result["status"] = status
            report["journals"][key] = result
            store.set_state("journal_health", health)
        report["finished_at"] = iso(datetime.now(timezone.utc))
        store.set_state("last_collection", report)
        return report
    finally:
        if own_fetcher:
            fetcher.close()
