from datetime import datetime, timezone
import json

import pytest

from pipeline.collect import CachedFetcher, SourceError, RateLimited, collect_all, parse_crossref, parse_feed
from pipeline.journals import BY_ID
from pipeline.store import Store

NOW = datetime(2026, 10, 26, 7, tzinfo=timezone.utc)
RDF = b'''<?xml version="1.0"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
 xmlns="http://purl.org/rss/1.0/" xmlns:dc="http://purl.org/dc/elements/1.1/"
 xmlns:prism="http://prismstandard.org/namespaces/1.2/basic/">
<item><title>Older unsorted item</title><link>https://www.aanda.org/10.1051/0004-6361/202600001</link>
<description>Authors: A. One, B. Two</description><dc:creator>A. One</dc:creator><dc:creator>B. Two</dc:creator>
<dc:identifier>10.1051/0004-6361/202600001</dc:identifier><dc:date>2026-10-10</dc:date>
<dc:subject>interstellar matter</dc:subject><dc:subject>stars</dc:subject>
<prism:volume>714</prism:volume><prism:startingPage>A1</prism:startingPage><prism:issueIdentifier>aa/2026/10</prism:issueIdentifier></item>
<item><title>Newer item</title><link>https://www.aanda.org/10.1051/0004-6361/202600002</link>
<dc:identifier>10.1051/0004-6361/202600002</dc:identifier><dc:date>2026-10-25</dc:date><prism:startingPage>L2</prism:startingPage></item>
</rdf:RDF>'''


def crossref_item(n=1, **changes):
    return {"DOI": f"10.3847/1538-4357/p{n}", "title": [f"Paper {n}"],
            "container-title": ["The Astrophysical Journal"], "volume": "1011", "issue": "1",
            "published-online": {"date-parts": [[2026, 10, 20]]},
            "published-print": {"date-parts": [[2026, 11, 1]]},
            "issued": {"date-parts": [[2026, 10, 20]]}, **changes}


class FakeFetcher:
    def __init__(self, pages, feed=RDF):
        self.pages = iter(pages)
        self.feed = feed
        self.requests = []

    def get(self, url, **kwargs):
        return self.feed

    def get_json(self, url, **kwargs):
        self.requests.append((url, kwargs))
        value = next(self.pages)
        if isinstance(value, Exception):
            raise value
        return value


def test_rdf_namespaces_repeated_creators_unsorted_and_bibliography_not_abstract():
    papers = parse_feed(RDF, BY_ID["aa"], NOW)
    assert len(papers) == 2
    assert papers[0]["authors"] == ["A. One", "B. Two"]
    assert papers[0]["keywords"] == ["interstellar matter", "stars"]
    assert papers[0]["abstract"] == ""
    assert papers[0]["published_online"] == "2026-10-10"
    assert papers[0]["issue_date"] == "2026-10"
    assert papers[1]["kind"] == "letter"


def test_html_captcha_is_not_an_empty_successful_feed():
    with pytest.raises(SourceError, match="Expected RSS"):
        parse_feed("<html><body>Confirm you are a human</body></html>", "apj", NOW)


def test_online_print_and_issued_dates_are_separate():
    paper = parse_crossref(crossref_item(), BY_ID["apj"], NOW)
    assert paper["published_online"] == "2026-10-20"
    assert paper["issue_date"] == "2026-11-01"
    missing = crossref_item()
    del missing["published-online"]
    assert parse_crossref(missing, BY_ID["apj"], NOW)["published_online"] is None
    missing["published-online"] = {"date-parts": [[2026, 10]]}
    partial = parse_crossref(missing, BY_ID["apj"], NOW)
    assert partial["published_online"] == "2026-10"
    assert partial["online_date_precision"] == "month"
    assert parse_crossref(crossref_item(**{"container-title": ["The Astrophysical Journal Letters"]}), BY_ID["apj"], NOW) is None


def test_checkpoint_rolls_back_on_partial_fetch_and_same_scroll_id_is_allowed(tmp_path):
    first_page = {"message": {"items": [crossref_item(n) for n in range(1000)], "next-cursor": "same-scroll-id"}}
    second_page = {"message": {"items": [crossref_item(1001)], "next-cursor": "same-scroll-id"}}
    with Store(tmp_path / "state.sqlite") as store:
        original_checkpoint = "2026-10-25T07:00:00Z"
        store.set_state("crossref_checkpoint:apj", original_checkpoint)
        failing = FakeFetcher([first_page, SourceError("network interrupted")], feed=b"<rss><channel/></rss>")
        report = collect_all(store, now=NOW, journals=[BY_ID["apj"]], fetcher=failing)
        assert report["journals"]["apj"]["status"] == "partial"
        assert store.get_state("crossref_checkpoint:apj") == original_checkpoint
        assert "from-index-date:2026-10-24T07:00:00" in failing.requests[0][1]["params"]["filter"]
        assert "until-index-date:2026-10-26T07:00:00" in failing.requests[0][1]["params"]["filter"]
        assert "Z" not in failing.requests[0][1]["params"]["filter"]
        successful = FakeFetcher([first_page, second_page], feed=b"<rss><channel/></rss>")
        collect_all(store, now=NOW, journals=[BY_ID["apj"]], fetcher=successful)
        assert store.get_state("crossref_checkpoint:apj") == "2026-10-26T07:00:00Z"
        assert len(store.papers()) == 1001


def test_late_deposit_keeps_online_date_and_existing_old_paper_updates(tmp_path):
    late = crossref_item(1)
    old = crossref_item(2, **{"published-online": {"date-parts": [[2010, 1, 1]]}, "published-print": {"date-parts": [[2010, 2, 1]]}})
    with Store(tmp_path / "state.sqlite") as store:
        store.set_state("tracking_start", "2026-09-26T07:00:00Z")
        fetcher = FakeFetcher([{"message": {"items": [late, old]}}], feed=b"<rss><channel/></rss>")
        collect_all(store, now=NOW, journals=[BY_ID["apj"]], fetcher=fetcher)
        assert len(store.papers()) == 1
        saved = store.get_paper(late["DOI"])
        assert saved["published_online"] == "2026-10-20"
        assert saved["first_seen"] == "2026-10-26T07:00:00Z"
        assert "from-pub-date:2026-09-01" in fetcher.requests[0][1]["params"]["filter"]
        old_parsed = parse_crossref(old, BY_ID["apj"], NOW)
        store.upsert_papers([old_parsed])
        old["title"] = ["Erratum: Old title"]
        collect_all(store, now=NOW, journals=[BY_ID["apj"]], fetcher=FakeFetcher(
            [{"message": {"items": [old]}}], feed=b"<rss><channel/></rss>"))
        assert store.get_paper(old["DOI"])["kind"] == "correction"


def test_rate_limit_does_not_advance_or_retry_other_journals(tmp_path):
    with Store(tmp_path / "state.sqlite") as store:
        fetcher = FakeFetcher([RateLimited(3600)], feed=b"<rss><channel/></rss>")
        collect_all(store, now=NOW, journals=[BY_ID["apj"], BY_ID["aj"]], fetcher=fetcher)
        assert len(fetcher.requests) == 1
        assert store.get_state("crossref_checkpoint:apj") is None
        assert store.get_state("crossref_checkpoint:aj") is None
        assert store.get_state("crossref:cooldown_until") == "2026-10-26T08:00:00Z"


def test_http_cache_conditional_fetch_and_rate_limit(tmp_path):
    import httpx
    calls = []
    def transport(request):
        calls.append(request)
        if request.url.path == "/limited":
            return httpx.Response(429, headers={"Retry-After": "3600"})
        if request.headers.get("If-None-Match") == '"feed-v1"':
            return httpx.Response(304)
        return httpx.Response(200, content=RDF, headers={"ETag": '"feed-v1"'})
    with httpx.Client(transport=httpx.MockTransport(transport)) as client:
        fetcher = CachedFetcher(tmp_path, client=client)
        assert fetcher.get("https://example.org/feed") == RDF
        assert fetcher.get("https://example.org/feed") == RDF
        assert len(calls) == 1
        assert fetcher.get("https://example.org/feed", ttl=0) == RDF
        assert calls[-1].headers["If-None-Match"] == '"feed-v1"'
        with pytest.raises(RateLimited) as exception:
            fetcher.get("https://example.org/limited")
        assert exception.value.seconds == 3600


def test_null_crossref_date_does_not_become_issue_date():
    item = crossref_item(**{"published-online": {"date-parts": []}, "resource": None, "license": None})
    parsed = parse_crossref(item, BY_ID["apj"], NOW)
    assert parsed["published_online"] is None
    assert parsed["issue_date"] == "2026-11-01"
