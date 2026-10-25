import hashlib
import json

import pytest

from pipeline import fulltext as ft


DOI = "10.3847/1538-4357/adfed8"
TITLE = "Effects of Dark Matter Self-interactions on Sagittarius and its Stream"


def atom(doi=DOI, title=TITLE, version="2503.15589v2"):
    return f'''<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom"><entry><id>https://arxiv.org/abs/{version}</id><title>{title}</title><author><name>Connor Hainje</name></author><arxiv:doi>{doi}</arxiv:doi><updated>2025-10-21T00:00:00Z</updated></entry></feed>'''.encode()


def article_html(doi=DOI):
    paragraphs = "".join(f"<h2>{heading}</h2><p>{('The measured stellar stream has a physical density distribution and the model predicts the following observations. ' * 35)}</p>" for heading in ["Introduction", "Methods", "Results", "Discussion", "Conclusions", "References"])
    return f'<html><head><meta name="citation_doi" content="{doi}"><meta name="citation_title" content="{TITLE}"></head><body><article><h1>{TITLE}</h1>{paragraphs}</article></body></html>'.encode()


def test_arxiv_identity_is_authoritative_not_title_only():
    assert ft._parse_arxiv_feed(atom(), DOI, TITLE, ["Connor Hainje"])[0]["version"] == "2503.15589v2"
    assert ft._parse_arxiv_feed(atom(doi="10.3847/wrong"), DOI, TITLE) == []
    assert ft._parse_arxiv_feed(atom(title="A completely different experiment"), DOI, TITLE) == []
    assert ft._parse_arxiv_feed(atom(), DOI, TITLE, ["An Unrelatedauthor"]) == []


def test_unversioned_arxiv_metadata_is_not_silently_promoted():
    assert ft._parse_arxiv_feed(atom(version="2503.15589"), DOI, TITLE) == []


def test_html_full_body_and_doi_required():
    parsed = ft._parse_html_document(article_html(), "https://iopscience.iop.org/article/" + DOI, DOI, TITLE)
    assert "[H0001]" in parsed["text"] and parsed["locators"]
    with pytest.raises(ft.FullTextUnavailable, match="doi_mismatch"):
        ft._parse_html_document(article_html("10.3847/wrong"), "https://iopscience.iop.org/article/x", DOI, TITLE)
    landing = f'<meta name="citation_doi" content="{DOI}"><article><h1>{TITLE}</h1><p>Abstract: A short description.</p></article>'.encode()
    with pytest.raises(ft.FullTextUnavailable, match="without_fulltext"):
        ft._parse_html_document(landing, "https://iopscience.iop.org/article/x", DOI, TITLE)


def test_captcha_http_200_is_not_a_paper():
    with pytest.raises(ft.FullTextUnavailable, match="captcha"):
        ft._parse_html_document(b"<html><title>Radware Bot Manager Captcha</title></html>", "https://iopscience.iop.org", DOI, TITLE)


def test_pdf_truncation_is_rejected_before_extraction(tmp_path):
    with pytest.raises(ft.FullTextUnavailable, match="truncated"):
        ft._extract_pdf(b"%PDF-1.7\nincomplete", DOI, TITLE, tmp_path)


def test_pdf_header_requires_whole_doi_instead_of_suffix_prefix():
    assert ft._header_has_doi("https://doi.org/" + DOI + "\nPublished by AAS", DOI)
    assert ft._header_has_doi("https://doi.org/" + DOI.replace("/", "/\n") + "\n", DOI)
    assert not ft._header_has_doi("https://doi.org/" + DOI + "a", DOI)
    assert not ft._header_has_doi("https://doi.org/" + DOI + ".1", DOI)


def test_arxiv_xml_entities_rejected():
    with pytest.raises(ft.FullTextUnavailable, match="invalid_arxiv_xml"):
        ft._parse_arxiv_feed(b'<!DOCTYPE x [<!ENTITY a SYSTEM "file:///etc/passwd">]><feed/>', DOI, TITLE)


def test_cached_verified_document_needs_no_network(tmp_path, monkeypatch):
    calls = []
    class FakeFetcher:
        def __init__(self, root):
            pass
        def get(self, url, **kwargs):
            calls.append(url)
            body = article_html()
            return {"body": body, "url": "https://iopscience.iop.org/article/" + DOI, "content_type": "text/html", "fetched_at": 1}
    monkeypatch.setattr(ft, "FetchCache", FakeFetcher)
    paper = {"doi": DOI, "title": TITLE, "source_url": "https://iopscience.iop.org/article/" + DOI}
    first = ft.acquire_fulltext(paper, tmp_path, False)
    count = len(calls)
    again = ft.acquire_fulltext(paper, tmp_path, False)
    assert len(calls) == count
    assert first["sha256"] == again["sha256"] and again["kind"] == "publisher"
    assert again["complete"] and again["doi"] == DOI


def test_source_url_allowlist_rejects_local_and_credentials():
    assert not ft._safe_url("http://127.0.0.1/private")
    assert not ft._safe_url("https://secret@arxiv.org/pdf/2503.15589")
    assert not ft._safe_url("file:///C:/Users/HP/.codex/auth.json")
    assert ft._safe_url("https://arxiv.org/pdf/2503.15589v2")


def test_figure_reuse_needs_explicit_ccby():
    assert ft._is_ccby("https://creativecommons.org/licenses/by/4.0/")
    assert not ft._is_ccby("https://creativecommons.org/licenses/by-nc/4.0/")
    assert not ft._is_ccby(None)


def test_host_cooldown_applies_across_papers(tmp_path):
    fetcher = ft.FetchCache(tmp_path)
    fetcher._cooldown("https://iopscience.iop.org/article/first/pdf", "captcha_or_access_block", 1000)
    with pytest.raises(ft.FullTextUnavailable, match="captcha_or_access_block"):
        fetcher.get("https://iopscience.iop.org/article/another/pdf")


def test_joined_rss_author_list_can_confirm_an_arxiv_author():
    assert ft._parse_arxiv_feed(atom(), DOI, TITLE, ["Connor Hainje, Oren Slone and Denis Erkal"])


def test_title_discovery_fallback_still_requires_exact_doi():
    class FakeFetcher:
        def __init__(self): self.calls = []
        def get(self, url, **kwargs):
            self.calls.append(url)
            return {"body": b'<feed xmlns="http://www.w3.org/2005/Atom"/>' if len(self.calls) == 1 else atom()}
    f = FakeFetcher()
    found = ft._find_arxiv({"doi": DOI, "title": TITLE, "authors": ["Connor Hainje"]}, f)
    assert found["doi"] == DOI and len(f.calls) == 2


def test_multiple_authoritative_dois_are_matched_exactly():
    assert ft._parse_arxiv_feed(atom(doi=DOI + "; 10.1234/other"), DOI, TITLE)
    assert not ft._parse_arxiv_feed(atom(doi=DOI + "extra"), DOI, TITLE)
    assert not ft._parse_arxiv_feed(atom(doi="10.1234/different"), DOI, TITLE, candidates=True)


def test_missing_doi_is_only_a_candidate_until_independent_evidence():
    raw = atom(doi="")
    assert ft._parse_arxiv_feed(raw, DOI, TITLE) == []
    candidate = ft._parse_arxiv_feed(raw, DOI, TITLE, candidates=True)[0]
    assert candidate["metadata_doi_verified"] is False and candidate["doi"] is None


def test_crossref_relation_must_be_exact_and_publisher_asserted():
    class FakeFetcher:
        def __init__(self, identifier, asserted="subject"):
            self.identifier, self.asserted = identifier, asserted
        def get(self, url, **kwargs):
            return {"body": json.dumps({"message": {"DOI": DOI, "relation": {"has-preprint": [{"id": self.identifier, "asserted-by": self.asserted}]}}}).encode()}
    assert ft._crossref_confirms_arxiv(DOI, "2503.15589v2", FakeFetcher("10.48550/arXiv.2503.15589"))
    assert not ft._crossref_confirms_arxiv(DOI, "2503.15589v2", FakeFetcher("10.48550/arXiv.2503.15588"))
    assert not ft._crossref_confirms_arxiv(DOI, "2503.15589v2", FakeFetcher("10.48550/arXiv.2503.15589", "object"))


def test_repository_record_never_counts_as_fulltext():
    with pytest.raises(ft.FullTextUnavailable, match="landing_page"):
        ft._parse_html_document(article_html(), "https://authors.library.caltech.edu/records/test", DOI, TITLE)


def test_reading_images_target_captions_not_prose_references():
    assert not ft.FIGURE_CAPTION_RE.search("Figure 5 shows a comparison between simulations.")
    assert not ft.FIGURE_CAPTION_RE.search("Fig. 1 (top panel), may be related to differences.")
    assert ft.FIGURE_CAPTION_RE.search("Figure 2. Surface temperature and ice coverage.")
    assert ft.FIGURE_CAPTION_RE.search("Fig. 1. Top panel: central electron fraction.")
