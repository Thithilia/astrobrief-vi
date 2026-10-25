"""Acquire an identified, complete paper for a local Codex reading job.

The cache is private.  Rendered PDF pages are reading aids, never public assets.
arXiv discovery by title is deliberately separated from DOI identity validation.
"""
from __future__ import annotations

import contextlib
import difflib
from email.utils import parsedate_to_datetime
import hashlib
import html
import json
import os
from pathlib import Path
import re
import time
import unicodedata
from urllib.parse import quote, urlencode, urljoin, urlparse
import xml.etree.ElementTree as ET

import httpx
from bs4 import BeautifulSoup


USER_AGENT = "AstroBriefViet/1.0 (non-commercial astronomy reading; cached requests)"
CACHE_VERSION = 4
MAX_DOCUMENT_BYTES = 60 * 1024 * 1024
ARXIV_INTERVAL = 3.1
ATOM = {"a": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
ALLOWED_HOSTS = {
    "doi.org", "dx.doi.org", "iopscience.iop.org", "www.aanda.org", "aanda.org",
    "academic.oup.com", "arxiv.org", "www.arxiv.org", "export.arxiv.org",
    "cdn.iopscience.iop.org", "content.cld.iop.org", "oup.silverchair-cdn.com", "oup.silverchair.com", "api.crossref.org", "authors.library.caltech.edu", "orca.cardiff.ac.uk", "researchprofiles.ku.dk", "researchonline.ljmu.ac.uk",
}
CHALLENGE_HOSTS = {"validate.perfdrive.com", "challenges.cloudflare.com"}
CAPTCHA_MARKERS = (
    "radware bot manager", "verify you are human", "confirm you are a human",
    "captcha", "checking your browser", "just a moment...", "access denied",
)
FIGURE_CAPTION_RE = re.compile(r"(?:^|\n)\s*(?:Figure|Fig\.)\s*\d+\s*[.:]", re.I)


class FullTextUnavailable(RuntimeError):
    """A safe acquisition failure; ``retry_after`` is seconds, when known."""

    def __init__(self, reason: str, *, attempts: list[dict] | None = None, retry_after: float | None = None):
        super().__init__(reason)
        self.reason = reason
        self.attempts = attempts or []
        self.retry_after = retry_after


def normalize_doi(value: str) -> str:
    value = html.unescape(str(value or "")).strip()
    value = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", value, flags=re.I)
    return value.strip().lower()


def _hash(value: bytes | str) -> str:
    return hashlib.sha256(value.encode("utf-8") if isinstance(value, str) else value).hexdigest()


def _atomic(path: Path, data: bytes | str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    tmp.write_bytes(data.encode("utf-8") if isinstance(data, str) else data)
    tmp.replace(path)


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(value or "")).strip()


def _header_has_doi(header: str, expected_doi: str) -> bool:
    """Match the whole DOI, allowing a typesetter's whitespace within it."""
    # A substring match would authenticate adfed8 against adfed8a or adfed8.1.
    # A final sentence period may follow the DOI, but cannot begin a suffix.
    spelling = r"\s*".join(re.escape(char) for char in expected_doi)
    return bool(re.search(r"(?<!\w)" + spelling + r"(?![\w/:;()\-]|\.[A-Za-z0-9])", header, re.I))


def _normal_title(value: str) -> str:
    value = BeautifulSoup(value or "", "html.parser").get_text(" ", strip=True)
    value = unicodedata.normalize("NFKD", value).casefold()
    return " ".join(re.findall(r"[a-z0-9]+", value))


def _title_matches(expected: str, actual: str) -> bool:
    a, b = _normal_title(expected), _normal_title(actual)
    if not a or not b:
        return False
    # Publisher feeds sometimes emit only a short series title; DOI + author
    # validation still remains mandatory for arXiv identification.
    if len(a.split()) <= 3 and (b == a or b.startswith(a + " ")):
        return True
    shared = len(set(a.split()) & set(b.split())) / max(1, min(len(set(a.split())), len(set(b.split()))))
    return difflib.SequenceMatcher(None, a, b).ratio() >= .55 and shared >= .55


def _safe_url(url: str) -> bool:
    p = urlparse(url)
    caltech_storage = p.hostname == "s3.us-west-2.amazonaws.com" and p.path.startswith("/caltechauthors/")
    return p.scheme in {"http", "https"} and (p.hostname in ALLOWED_HOSTS or caltech_storage) and not p.username and not p.password


@contextlib.contextmanager
def _arxiv_slot(cache: Path):
    """One connection and >=3 seconds between arXiv calls, across local jobs."""
    cache.mkdir(parents=True, exist_ok=True)
    lock = cache / "arxiv.lock"
    started = time.monotonic()
    while True:
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            break
        except FileExistsError:
            if time.monotonic() - started > 75:
                raise FullTextUnavailable("arxiv_busy")
            # Only remove a lock older than a bounded request plus timeout.
            try:
                if time.time() - lock.stat().st_mtime > 180:
                    lock.unlink(missing_ok=True)
            except FileNotFoundError:
                pass
            time.sleep(.25)
    stamp = cache / "arxiv-last-call.txt"
    try:
        try:
            wait = ARXIV_INTERVAL - (time.time() - float(stamp.read_text()))
        except (OSError, ValueError):
            wait = 0
        if wait > 0:
            time.sleep(wait)
        yield
    finally:
        _atomic(stamp, str(time.time()))
        lock.unlink(missing_ok=True)


class FetchCache:
    def __init__(self, root: Path):
        self.root = Path(root) / "http"
        self.root.mkdir(parents=True, exist_ok=True)
        self.control_root = Path(root)

    def _cooldown_path(self, host: str | None) -> Path:
        return self.control_root / f"host-block-{_hash(host or '')[:16]}.json"

    def _check_cooldown(self, url: str) -> None:
        path = self._cooldown_path(urlparse(url).hostname)
        if path.exists():
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
                remaining = float(record.get("until", 0)) - time.time()
                if remaining > 0:
                    raise FullTextUnavailable(record.get("reason", "host_cooldown"), retry_after=remaining)
            except (OSError, ValueError, TypeError):
                pass

    def _cooldown(self, url: str, reason: str, delay: float) -> None:
        _atomic(self._cooldown_path(urlparse(url).hostname), json.dumps({"reason": reason, "until": time.time() + delay}))

    def get(self, url: str, *, ttl: int = 7 * 86400) -> dict:
        if not _safe_url(url):
            raise FullTextUnavailable("untrusted_source_url")
        key = _hash(url)
        metadata_path, body_path = self.root / f"{key}.json", self.root / f"{key}.body"
        if metadata_path.exists():
            try:
                meta = json.loads(metadata_path.read_text(encoding="utf-8"))
                if meta.get("expires", 0) > time.time():
                    if meta.get("error"):
                        raise FullTextUnavailable(meta["error"], retry_after=max(0, meta["expires"] - time.time()))
                    if body_path.exists() and _hash(body_path.read_bytes()) == meta.get("sha256"):
                        return {**meta, "body": body_path.read_bytes()}
            except (OSError, ValueError, KeyError):
                pass
        self._check_cooldown(url)
        guard = _arxiv_slot(self.control_root) if urlparse(url).hostname in {"arxiv.org", "www.arxiv.org", "export.arxiv.org"} else contextlib.nullcontext()
        try:
            with guard, httpx.Client(timeout=httpx.Timeout(45, connect=15), headers={"User-Agent": USER_AGENT}, follow_redirects=False) as client:
                current = url
                for _ in range(6):
                    if not _safe_url(current):
                        raise FullTextUnavailable("untrusted_redirect")
                    self._check_cooldown(current)
                    response = client.get(current)
                    if response.status_code in {301, 302, 303, 307, 308}:
                        current = urljoin(current, response.headers.get("location", ""))
                        if urlparse(current).hostname in CHALLENGE_HOSTS:
                            self._cooldown(str(response.url), "captcha_or_access_block", 6 * 3600)
                            raise FullTextUnavailable("captcha_or_access_block")
                        continue
                    break
                else:
                    raise FullTextUnavailable("too_many_redirects")
            status = response.status_code
            if status != 200:
                delay = 6 * 3600 if status in {401, 403} else 900
                if status == 429:
                    retry_header = response.headers.get("retry-after", "900")
                    try:
                        delay = max(60, int(retry_header))
                    except ValueError:
                        try:
                            delay = max(60, int(parsedate_to_datetime(retry_header).timestamp() - time.time()))
                        except (TypeError, ValueError, OverflowError):
                            delay = 900
                reason = f"http_{status}"
                if status in {401, 403, 429}:
                    self._cooldown(str(response.url), reason, delay)
                _atomic(metadata_path, json.dumps({"error": reason, "expires": time.time() + delay, "url": url}))
                raise FullTextUnavailable(reason, retry_after=delay)
            body = response.content
            if not body or len(body) > MAX_DOCUMENT_BYTES:
                raise FullTextUnavailable("empty_or_oversized_document")
            ctype = response.headers.get("content-type", "").split(";")[0].lower()
            if "html" in ctype or body.lstrip().lower().startswith((b"<!doctype html", b"<html")):
                head = body[:25000].decode("utf-8", "replace").casefold()
                if any(marker in head for marker in CAPTCHA_MARKERS):
                    self._cooldown(str(response.url), "captcha_or_access_block", 6 * 3600)
                    _atomic(metadata_path, json.dumps({"error": "captcha_or_access_block", "expires": time.time() + 6 * 3600, "url": url}))
                    raise FullTextUnavailable("captcha_or_access_block")
            meta = {"url": str(response.url), "content_type": ctype, "sha256": _hash(body), "fetched_at": time.time(), "expires": time.time() + ttl}
            _atomic(body_path, body)
            _atomic(metadata_path, json.dumps(meta))
            return {**meta, "body": body}
        except FullTextUnavailable as exc:
            if exc.reason in {"captcha_or_access_block", "untrusted_redirect", "too_many_redirects"}:
                _atomic(metadata_path, json.dumps({"error": exc.reason, "expires": time.time() + 6 * 3600, "url": url}))
            raise
        except httpx.HTTPError as exc:
            raise FullTextUnavailable(f"network_{type(exc).__name__}") from exc


def _validate_text(text: str, *, pdf: bool = False) -> None:
    if len(text) < 2000 or len(re.findall(r"\b\w+\b", text)) < 320:
        raise FullTextUnavailable("abstract_only_or_too_short")
    clean = re.sub(r"\[[A-Z0-9\- ]+\]", "", text)
    section_names = re.findall(r"\b(introduction|methods?|results?|discussion|conclusions?|references|acknowledg\w*|appendix|observations?|model(?:ling)?|analysis)\b", clean, re.I)
    if not pdf and len({x.lower() for x in section_names}) < 3:
        raise FullTextUnavailable("no_complete_article_body")
    # An abstract export can be long; require substantial body outside its abstract.
    if re.search(r"\babstract\b", clean[:1500], re.I) and not re.search(r"\b(introduction|1\.?\s+background|observations?|methods?|model)\b", clean[500:], re.I):
        raise FullTextUnavailable("abstract_only_or_missing_body")


def _license_from_html(soup: BeautifulSoup) -> str | None:
    link = soup.select_one('link[rel="license"]')
    if link and link.get("href"):
        return str(link["href"])
    for meta in soup.find_all("meta"):
        name = str(meta.get("name", meta.get("property", ""))).lower()
        if name in {"citation_license", "dc.rights", "dcterms.license", "dc.rights.uri"} and meta.get("content"):
            return str(meta["content"])
    for a in soup.find_all("a", href=re.compile(r"creativecommons\.org/licenses/")):
        if "license" in str(a.get("rel", "")) or "creative commons" in a.parent.get_text(" ", strip=True).lower():
            return str(a["href"])
    return None


def _is_ccby(license_value: str | None) -> bool:
    return bool(license_value and (re.search(r"creativecommons\.org/licenses/by/(?:[34]\.0)", license_value, re.I) or re.search(r"\bcc\s*by\s*[34]\.0\b", license_value, re.I)))


def _parse_html_document(raw: bytes, url: str, expected_doi: str, title: str, *, arxiv_identity: bool = False) -> dict:
    soup = BeautifulSoup(raw, "html.parser")
    front = soup.get_text(" ", strip=True)[:16000].lower()
    if any(marker in front for marker in CAPTCHA_MARKERS):
        raise FullTextUnavailable("captcha_or_access_block")
    if urlparse(url).hostname in {"authors.library.caltech.edu", "orca.cardiff.ac.uk", "researchprofiles.ku.dk", "researchonline.ljmu.ac.uk"}:
        raise FullTextUnavailable("html_landing_page_without_fulltext")
    meta_dois = [normalize_doi(str(m.get("content", ""))) for m in soup.find_all("meta") if str(m.get("name", "")).lower() in {"citation_doi", "dc.identifier", "dc.identifier.doi"}]
    if not arxiv_identity and expected_doi not in meta_dois:
        raise FullTextUnavailable("publisher_html_doi_mismatch")
    meta_title = soup.find("meta", attrs={"name": "citation_title"})
    actual_title = str(meta_title.get("content", "")) if meta_title else (soup.h1.get_text(" ", strip=True) if soup.h1 else "")
    if actual_title and not _title_matches(title, actual_title):
        raise FullTextUnavailable("source_title_mismatch")
    body = None
    for selector in (".ltx_document", "#article-body", ".article-body", ".article__body", ".widget-ArticleFulltext", "#fulltext", ".fulltext-view", "article"):
        candidate = soup.select_one(selector)
        if candidate and len(candidate.get_text(" ", strip=True)) > 2000:
            body = candidate
            break
    if body is None:
        raise FullTextUnavailable("html_landing_page_without_fulltext")
    scientific_headings = [_clean(h.get_text(" ", strip=True)).lower() for h in body.find_all(["h2", "h3", "h4"])]
    if not any(re.search(r"introduction|method|result|discussion|conclusion|observations?|model|analysis", heading) for heading in scientific_headings):
        raise FullTextUnavailable("html_landing_page_without_fulltext")
    for node in body.select("script,style,nav,header,footer,.related-articles,.references-button,.ltx_bibliography .ltx_bib_extra"):
        node.decompose()
    pieces, locators = [], []
    nodes = body.find_all(["h1", "h2", "h3", "h4", "p", "figcaption", "table"])
    for node in nodes:
        if any(parent.name in {"table", "figcaption"} for parent in node.parents if parent is not body):
            continue
        value = _clean(node.get_text(" ", strip=True))
        if not value:
            continue
        locator = f"H{len(pieces)+1:04d}"
        pieces.append(f"[{locator}] {value}")
        locators.append({"id": locator, "text": value})
    text = "\n\n".join(pieces)
    _validate_text(text)
    figures = []
    for fig in body.find_all("figure"):
        image = fig.find("img", src=True)
        caption_node = fig.find("figcaption")
        if not image or not caption_node:
            continue
        caption = _clean(caption_node.get_text(" ", strip=True))
        figure_url = urljoin(url, str(image["src"]))
        if not _safe_url(figure_url):
            continue
        figures.append({"alt": str(image.get("alt", "")), "caption": caption, "original_url": figure_url, "source_locator": str(fig.get("id", caption[:80])), "third_party": bool(re.search(r"reproduced|used with permission|©|copyright|courtesy of|credit:", caption, re.I))})
    return {"text": text, "locators": locators, "figures": figures, "license": _license_from_html(soup)}


def _extract_pdf(raw: bytes, expected_doi: str, title: str, directory: Path, *, arxiv_identity: bool = False) -> dict:
    from pypdf import PdfReader
    import pypdfium2 as pdfium
    import io
    if not raw.startswith(b"%PDF-") or b"%%EOF" not in raw[-8192:]:
        raise FullTextUnavailable("invalid_or_truncated_pdf")
    try:
        reader = PdfReader(io.BytesIO(raw), strict=False)
        if reader.is_encrypted or not 1 <= len(reader.pages) <= 400:
            raise FullTextUnavailable("encrypted_or_oversized_pdf")
        # PDFium extracts the full page without pypdf's form-XObject invocation
        # cap. pypdf remains an independent page-count/structure validation.
        document = pdfium.PdfDocument(raw)
        if len(document) != len(reader.pages):
            document.close()
            raise FullTextUnavailable("pdf_page_count_mismatch")
        pages = []
        for page in document:
            textpage = page.get_textpage()
            pages.append(textpage.get_text_bounded(errors="replace").replace("\r\n", "\n").replace("\r", "\n"))
            textpage.close()
            page.close()
        document.close()
    except FullTextUnavailable:
        raise
    except Exception as exc:
        raise FullTextUnavailable("pdf_extraction_failed") from exc
    empty = [i + 1 for i, page in enumerate(pages) if len(page.strip()) < 20]
    if empty:
        raise FullTextUnavailable("pdf_has_unreadable_pages", attempts=[{"pages": empty}])
    # The expected DOI must be in the paper header, not merely in References.
    # A bibliography on the first page must not authenticate a different paper.
    header_region = re.split(r"(?:^|\n)\s*(?:references|bibliography)\s*(?:\n|$)", pages[0], maxsplit=1, flags=re.I)[0]
    header_doi_matches = _header_has_doi(header_region, expected_doi)
    if not arxiv_identity and not header_doi_matches:
        raise FullTextUnavailable("publisher_pdf_header_doi_mismatch")
    if title and not _title_matches(title, " ".join(pages[0].splitlines()[:18])):
        # On typeset pages the title can follow a long author/header block.
        title_tokens = set(_normal_title(title).split())
        header_tokens = set(_normal_title(pages[0][:5000]).split())
        if len(title_tokens & header_tokens) / max(1, len(title_tokens)) < .8:
            raise FullTextUnavailable("source_title_mismatch")
    chunks, locators, figure_pages = [], [], []
    for number, page in enumerate(pages, 1):
        paragraphs = re.split(r"\n\s*\n", page)
        if len(paragraphs) < 3:
            lines = page.splitlines()
            paragraphs = [" ".join(lines[i:i+10]) for i in range(0, len(lines), 10)]
        for index, paragraph in enumerate(paragraphs, 1):
            value = _clean(paragraph)
            if value:
                locator = f"P{number:03d}-S{index:03d}"
                chunks.append(f"[{locator}] {value}")
                locators.append({"id": locator, "text": value, "page": number})
        match = FIGURE_CAPTION_RE.search(page)
        if match and len(figure_pages) < 2:
            figure_pages.append({"page": number, "caption": _clean(page[match.start():match.start()+1200])})
    text = "\n\n".join(chunks)
    _validate_text(text, pdf=True)
    pdf_path = directory / "paper.pdf"
    _atomic(pdf_path, raw)
    figures = []
    try:
        document = pdfium.PdfDocument(str(pdf_path))
        for entry in figure_pages:
            path = directory / f"reading-page-{entry['page']:03d}.png"
            page = document[entry["page"]-1]
            bitmap = page.render(scale=1.8)
            bitmap.to_pil().save(path)
            bitmap.close()
            page.close()
            figures.append({"image_path": str(path.resolve()), "src": None, "alt": f"Paper page {entry['page']} (private reading aid)", "caption": entry["caption"], "source_locator": f"P{entry['page']:03d}", "public_safe": False, "license": None, "credit": "Local rendering of the original paper; not exported", "original_url": None})
        document.close()
    except Exception:
        # Text remains usable; a failed render is not a claimed figure inspection.
        figures = []
    license_value = None
    if re.search(r"Creative Commons Attribution 4\.0|CC BY 4\.0", _clean(pages[0]), re.I):
        license_value = "https://creativecommons.org/licenses/by/4.0/"
    identity_excerpt = None
    if header_doi_matches:
        for line in header_region.splitlines():
            if expected_doi in re.sub(r"\s+", "", line).lower():
                identity_excerpt = _clean(line)
                break
        if identity_excerpt is None:
            identity_excerpt = "Expected DOI spans adjacent first-page header lines; whitespace-normalized match"
    return {"text": text, "locators": locators, "pdf_path": str(pdf_path.resolve()), "figures": figures, "page_count": len(pages), "license": license_value, "doi_header_excerpt": identity_excerpt, "extraction_method": "PDFium full-page text; pypdf page-count validation"}


def _parse_arxiv_feed(raw: bytes, expected_doi: str, title: str, authors: list[str] | None = None, *, candidates: bool = False) -> list[dict]:
    if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        raise FullTextUnavailable("invalid_arxiv_xml")
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise FullTextUnavailable("invalid_arxiv_xml") from exc
    found = []
    for entry in root.findall("a:entry", ATOM):
        doi_node = entry.find("arxiv:doi", ATOM)
        doi_values = [] if doi_node is None else [normalize_doi(x).rstrip(".,") for x in re.split(r"[\s;]+", doi_node.text or "") if x]
        verified = expected_doi in doi_values
        if doi_values and not verified:
            # An explicit contradictory DOI is not a missing metadata field.
            continue
        if not verified and not candidates:
            continue
        entry_title = _clean(entry.findtext("a:title", "", ATOM))
        if not _title_matches(title, entry_title):
            continue
        names = [x.findtext("a:name", "", ATOM) for x in entry.findall("a:author", ATOM)]
        if authors and names:
            # Some RSS feeds put the entire author list in one dc:creator.
            expected_names = [name for combined in authors for name in re.split(r",|\s+and\s+", combined)]
            expected_surnames = {_normal_title(a).split()[-1] for a in expected_names if _normal_title(a).split()}
            actual_surnames = {_normal_title(a).split()[-1] for a in names if _normal_title(a).split()}
            if not expected_surnames & actual_surnames:
                continue
        identifier = entry.findtext("a:id", "", ATOM).rsplit("/abs/", 1)[-1]
        if not re.fullmatch(r"(?:\d{4}\.\d{4,5}|[a-z.-]+/\d{7})v\d+", identifier, re.I):
            continue
        found.append({"id": identifier, "title": entry_title, "authors": names, "doi": expected_doi if verified else None, "version": identifier, "updated": entry.findtext("a:updated", "", ATOM), "metadata_doi_verified": verified})
    return found


def _find_arxiv(paper: dict, fetcher: FetchCache) -> dict:
    doi = normalize_doi(paper["doi"])
    existing = str(paper.get("arxiv_id") or "").strip()
    existing = re.sub(r"^(?:https?://arxiv\.org/(?:abs|pdf)/|arxiv:)", "", existing, flags=re.I).removesuffix(".pdf")
    direct_id = existing and re.fullmatch(r"(?:\d{4}\.\d{4,5}|[a-z.-]+/\d{7})(?:v\d+)?", existing, re.I)
    if direct_id:
        requests = [{"id_list": existing, "max_results": 1}]
    else:
        title = _clean(BeautifulSoup(paper.get("title", ""), "html.parser").get_text(" "))
        title = title.replace('"', " ")[:300]
        requests = [{"search_query": f'ti:"{title}"', "start": 0, "max_results": 5}]
        stop = {"the", "and", "with", "from", "for", "into", "its", "their", "through", "between", "using", "based", "observations", "study", "analysis"}
        words = list(dict.fromkeys(x for x in _normal_title(title).split() if len(x) >= 4 and x not in stop))[:8]
        if len(words) >= 3:
            requests.append({"search_query": " AND ".join("ti:" + x for x in words), "start": 0, "max_results": 8})
        if len(words) > 4:
            requests.append({"search_query": " AND ".join("ti:" + x for x in words[:4]), "start": 0, "max_results": 12})
    for params in requests:
        response = fetcher.get("https://export.arxiv.org/api/query?" + urlencode(params), ttl=24*3600)
        matches = _parse_arxiv_feed(response["body"], doi, paper.get("title", ""), paper.get("authors"))
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise FullTextUnavailable("arxiv_doi_identity_ambiguous")
        candidates = _parse_arxiv_feed(response["body"], doi, paper.get("title", ""), paper.get("authors"), candidates=True)
        if len(candidates) == 1:
            # Discovery is not identity verification. The caller must require
            # the journal DOI in the PDF header or an explicit Crossref relation.
            return candidates[0]
    # A title may have changed after submission. An explicit journal-deposited
    # has-preprint identifier can guide discovery without a fuzzy title merge.
    for relation in _crossref_preprints(doi, fetcher):
        response = fetcher.get("https://export.arxiv.org/api/query?" + urlencode({"id_list": relation["arxiv_id"], "max_results": 1}), ttl=24*3600)
        candidates = _parse_arxiv_feed(response["body"], doi, paper.get("title", ""), paper.get("authors"), candidates=True)
        if len(candidates) == 1:
            candidates[0]["crossref_identity_relation"] = relation
            return candidates[0]
    raise FullTextUnavailable("arxiv_doi_identity_unconfirmed")


def _crossref_preprints(doi: str, fetcher: FetchCache) -> list[dict]:
    response = fetcher.get("https://api.crossref.org/works/" + quote(doi, safe="/"), ttl=6*3600)
    try:
        message = json.loads(response["body"])["message"]
    except (ValueError, KeyError, TypeError):
        return []
    if normalize_doi(message.get("DOI", "")) != doi:
        return []
    results = []
    for relation in message.get("relation", {}).get("has-preprint", []):
        identifier = str(relation.get("id", "")).strip()
        found = re.search(r"(?:arxiv[.:/]|arxiv\.org/(?:abs|pdf)/)(\d{4}\.\d{4,5}|[a-z.-]+/\d{7})(?:v\d+)?", identifier, re.I)
        if found and relation.get("asserted-by") == "subject":
            results.append({"doi": doi, "relation": "has-preprint", "id": identifier, "arxiv_id": found.group(1), "asserted-by": "subject", "source": "https://api.crossref.org/works/" + doi})
    return results


def _crossref_confirms_arxiv(doi: str, arxiv_id: str, fetcher: FetchCache) -> dict | None:
    """Accept only an explicit publisher-deposited has-preprint relationship."""
    base_id = re.sub(r"v\d+$", "", arxiv_id, flags=re.I)
    return next((r for r in _crossref_preprints(doi, fetcher) if r["arxiv_id"].lower() == base_id.lower()), None)


def _arxiv_abstract_confirms_doi(doi: str, arxiv_id: str, fetcher: FetchCache) -> dict | None:
    """Read explicit DOI/report-number metadata on the official arXiv record."""
    url = "https://arxiv.org/abs/" + arxiv_id
    response = fetcher.get(url, ttl=24*3600)
    soup = BeautifulSoup(response["body"], "html.parser")
    identifier = soup.find("meta", attrs={"name": "citation_arxiv_id"})
    if not identifier or re.sub(r"v\d+$", "", str(identifier.get("content", ""))) != re.sub(r"v\d+$", "", arxiv_id):
        return None
    values = []
    for meta in soup.find_all("meta", attrs={"name": "citation_doi"}):
        values.append(("citation_doi", str(meta.get("content", ""))))
    for row in soup.find_all("tr"):
        cells = row.find_all("td", recursive=False)
        if len(cells) >= 2 and re.match(r"^(?:related\s+)?doi\s*:|^report\s*(?:number|no)\s*:", _clean(cells[0].get_text(" ")), re.I):
            values.append((_clean(cells[0].get_text(" ")), _clean(cells[1].get_text(" "))))
    for field, value in values:
        tokens = [normalize_doi(x).rstrip(".,") for x in value.split()]
        if doi in tokens:
            return {"method": "official_arxiv_record", "field": field, "doi": doi, "arxiv_id": arxiv_id, "source": url}
    return None


def _publisher_urls(paper: dict) -> list[str]:
    doi = normalize_doi(paper["doi"])
    urls = []
    # A declared institutional publisher-copy lead still has to pass the exact
    # journal DOI first-page check; it is not an identity shortcut.
    for key in ("repository_pdf_url", "repository_url"):
        if paper.get(key) and _safe_url(paper[key]):
            urls.append(paper[key])
    if paper.get("pdf_url") and _safe_url(paper["pdf_url"]):
        urls.append(paper["pdf_url"])
    if doi.startswith("10.3847/"):
        urls.append(f"https://iopscience.iop.org/article/{doi}/pdf")
    if paper.get("source_url") and _safe_url(paper["source_url"]):
        urls.append(paper["source_url"])
    urls.append(f"https://doi.org/{doi}")
    return list(dict.fromkeys(urls))


def _html_links(raw: bytes, url: str) -> list[str]:
    soup = BeautifulSoup(raw, "html.parser")
    found = []
    for meta in soup.find_all("meta", attrs={"name": "citation_pdf_url"}):
        if meta.get("content"):
            found.append(urljoin(url, str(meta["content"])))
    if "/abs/" in url and "aanda.org" in url:
        found.append(url.replace("/abs/", "/full_html/"))
    for a in soup.find_all("a", href=True):
        href = str(a["href"])
        if urlparse(href).path.lower().endswith(".pdf") or "/full_html/" in href:
            found.append(urljoin(url, href))
    return list(dict.fromkeys(x for x in found if _safe_url(x)))[:3]


def _capture_html_figures(parsed: dict, fetcher: FetchCache, directory: Path) -> list[dict]:
    figures = []
    for index, item in enumerate(parsed.get("figures", [])[:2], 1):
        try:
            response = fetcher.get(item["original_url"])
            ctype = response.get("content_type", "")
            if ctype not in {"image/png", "image/jpeg", "image/webp"}:
                continue
            ext = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}[ctype]
            path = directory / f"figure-{index}{ext}"
            _atomic(path, response["body"])
            license_value = parsed.get("license")
            public_safe = _is_ccby(license_value) and not item.get("third_party")
            figures.append({**item, "image_path": str(path.resolve()), "src": str(path.resolve()) if public_safe else None, "public_safe": public_safe, "license": license_value, "credit": "Original paper figure; see DOI and source locator"})
        except FullTextUnavailable:
            continue
    return figures


def _finish(parsed: dict, response: dict, paper: dict, directory: Path, *, kind: str, version: str | None, url: str, identity: str, attempts: list[dict]) -> dict:
    text_path = directory / "source.txt"
    _atomic(text_path, parsed["text"])
    result = {**parsed, "cache_version": CACHE_VERSION, "doi": normalize_doi(paper["doi"]), "kind": kind, "version": version, "url": url, "retrieved_url": response["url"], "sha256": _hash(response["body"]), "text_sha256": _hash(parsed["text"]), "text_path": str(text_path.resolve()), "identity_evidence": identity, "complete": True, "attempts": attempts, "fetched_at": response.get("fetched_at", time.time())}
    _atomic(directory / "source.json", json.dumps(result, ensure_ascii=False, indent=2))
    return result


def acquire_fulltext(paper: dict, cache_dir: Path, allow_arxiv: bool = True) -> dict:
    """Return a complete, identified cached paper, or retain it as unavailable.

    Exceptions never cause fallback to an abstract-only summary.  Rendered pages
    in ``figures`` have ``public_safe=False`` and must stay in the private cache.
    """
    doi = normalize_doi(paper.get("doi", ""))
    if not re.fullmatch(r"10\.\d{4,9}/\S+", doi):
        raise FullTextUnavailable("missing_or_invalid_doi")
    directory = Path(cache_dir) / "fulltext" / _hash(doi)[:16]
    directory.mkdir(parents=True, exist_ok=True)
    manifest = directory / "source.json"
    if manifest.exists():
        try:
            cached = json.loads(manifest.read_text(encoding="utf-8"))
            text_path = Path(cached["text_path"])
            if cached.get("cache_version") == CACHE_VERSION and cached.get("doi") == doi and cached.get("complete") and text_path.exists() and _hash(text_path.read_bytes()) == cached.get("text_sha256"):
                if allow_arxiv or cached.get("kind") == "publisher":
                    cached["text"] = text_path.read_text(encoding="utf-8")
                    return cached
        except (OSError, ValueError, KeyError):
            pass
    fetcher = FetchCache(Path(cache_dir))
    attempts = []
    candidates = _publisher_urls(paper)
    seen = set()
    blocked_hosts = set()
    for url in candidates:
        if url in seen or urlparse(url).hostname in blocked_hosts:
            continue
        seen.add(url)
        try:
            response = fetcher.get(url)
            if response["body"].startswith(b"%PDF-"):
                parsed = _extract_pdf(response["body"], doi, paper.get("title", ""), directory)
                return _finish(parsed, response, paper, directory, kind="publisher", version=None, url=url, identity="expected DOI in publisher PDF first-page header", attempts=attempts)
            parsed = None
            try:
                parsed = _parse_html_document(response["body"], response["url"], doi, paper.get("title", ""))
            except FullTextUnavailable as exc:
                if exc.reason in {"html_landing_page_without_fulltext", "no_complete_article_body", "abstract_only_or_too_short", "abstract_only_or_missing_body"}:
                    for linked in _html_links(response["body"], response["url"]):
                        if linked not in seen and len(candidates) < 7:
                            candidates.append(linked)
                raise
            parsed["figures"] = _capture_html_figures(parsed, fetcher, directory)
            return _finish(parsed, response, paper, directory, kind="publisher", version=None, url=response["url"], identity="publisher citation_doi metadata", attempts=attempts)
        except FullTextUnavailable as exc:
            attempts.append({"url": url, "reason": exc.reason})
            if exc.reason in {"http_403", "http_401", "captcha_or_access_block", "http_429"}:
                blocked_hosts.add(urlparse(url).hostname)
    if allow_arxiv:
        try:
            match = _find_arxiv(paper, fetcher)
            identifier = match["id"]
            canonical = f"https://arxiv.org/abs/{identifier}"
            response = fetcher.get(f"https://arxiv.org/pdf/{identifier}")
            identity = "exact arxiv:doi, matching title and author surname"
            verified_metadata = match.get("metadata_doi_verified", False)
            relation = match.get("crossref_identity_relation")
            official_record = None
            try:
                parsed = _extract_pdf(response["body"], doi, paper.get("title", ""), directory, arxiv_identity=verified_metadata or bool(relation))
                if not verified_metadata:
                    identity = "publisher-deposited Crossref has-preprint relation; matching arXiv title and authors" if relation else "journal DOI explicitly printed in arXiv PDF first-page header; matching arXiv title and authors"
            except FullTextUnavailable as exc:
                if not verified_metadata and exc.reason == "publisher_pdf_header_doi_mismatch":
                    official_record = _arxiv_abstract_confirms_doi(doi, identifier, fetcher)
                    if not official_record:
                        relation = _crossref_confirms_arxiv(doi, identifier, fetcher)
                    if not relation and not official_record:
                        raise FullTextUnavailable("arxiv_doi_identity_unconfirmed") from exc
                    parsed = _extract_pdf(response["body"], doi, paper.get("title", ""), directory, arxiv_identity=True)
                    identity = "exact journal DOI in official arXiv abstract-page DOI/report-number field; matching title and authors" if official_record else "publisher-deposited Crossref has-preprint relation; matching arXiv title and authors"
                else:
                    raise
            parsed["arxiv_metadata"] = match
            if relation:
                parsed["crossref_identity_relation"] = relation
            if official_record:
                parsed["arxiv_record_identity"] = official_record
            # PDF reading pages remain private even if the article is CC BY.
            return _finish(parsed, response, paper, directory, kind="arxiv", version=identifier, url=canonical, identity=identity, attempts=attempts)
        except FullTextUnavailable as exc:
            attempts.append({"source": "arxiv", "reason": exc.reason})
    raise FullTextUnavailable("fulltext_unavailable", attempts=attempts)
