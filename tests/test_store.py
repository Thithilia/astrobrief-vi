from pathlib import Path

import pytest

from pipeline.export import export_catalog
from pipeline.store import Store, normalize_doi, paper_id


def paper(**changes):
    return {"doi": "10.3847/1538-4357/example", "journal": "apj", "title": "A real source title",
            "authors": ["A. Author", "B. Author"], "abstract": "Full abstract",
            "published_online": "2026-10-21T23:00:00Z", "online_date_precision": "day",
            "issue_date": "2026-11-01", "first_seen": "2026-10-26T01:00:00Z",
            "_online_source": "rss", "_metadata_sources": ["rss"], **changes}


def summary(**changes):
    return {"doi": paper()["doi"], "title": "Bài viết tiếng Việt", "dek": "Một kết quả vật lý.",
            "journal": "apj", "paper_title": paper()["title"], "summary_date": "2026-10-26",
            "generated_at": "2026-10-26T02:00:00Z", "topic": "stars", "reading_minutes": 6,
            "source": {"kind": "arxiv", "url": "https://arxiv.org/abs/2610.12345v2", "version": "2610.12345v2", "path": "C:/secret/cache.pdf"},
            "sections": [{"heading": "Kết quả", "body": "Nội dung kiểm tra tìm kiếm."}],
            "review": {"passed": True}, **changes}


def test_identity_merge_preserves_discovery_and_best_online_date(tmp_path):
    with Store(tmp_path / "state.sqlite") as store:
        assert store.upsert_papers([paper()]) == 1
        assert store.upsert_papers([paper(doi="https://doi.org/10.3847/1538-4357/EXAMPLE",
                                        authors=["A. Author"], abstract="", published_online="2026-10",
                                        online_date_precision="month", first_seen="2026-10-27T00:00:00Z",
                                        _online_source="crossref", _metadata_sources=["crossref"])]) == 0
        saved = store.get_paper(paper()["doi"])
        assert saved["first_seen"] == "2026-10-26T01:00:00Z"
        assert saved["published_online"] == "2026-10-21T23:00:00Z"
        assert saved["_online_source"] == "rss"
        assert saved["issue_date"] == "2026-11-01"
        assert len(saved["authors"]) == 2
        assert saved["abstract"] == "Full abstract"
        assert saved["_metadata_sources"] == ["rss", "crossref"]
        assert saved["id"] == paper_id(saved["doi"])
        with pytest.raises(ValueError, match="another journal"):
            store.upsert_papers([paper(journal="apjl")])


def test_no_fake_online_date_and_missing_doi_rejected(tmp_path):
    with Store(tmp_path / "state.sqlite") as store:
        store.upsert_papers([paper(published_online=None, online_date_precision=None)])
        assert store.papers()[0]["published_online"] is None
        with pytest.raises(ValueError, match="valid DOI"):
            store.upsert_papers([paper(doi="not-a-doi")])


def test_only_reviewed_summaries_saved_and_public_export_is_allowlisted(tmp_path):
    import json
    with Store(tmp_path / "state.sqlite") as store:
        store.upsert_papers([paper(private="secret", pdf_url="C:/cache/file.pdf")])
        with pytest.raises(ValueError, match="passed factual review"):
            store.save_summary(summary(review={"passed": False}))
        store.save_summary(summary())
        store.save_summary(summary())
        assert len(store.summaries()) == 1
        path = export_catalog(store, tmp_path)
        output = json.loads(path.read_text(encoding="utf-8"))
        assert output["papers"][0]["has_summary"] is True
        assert output["papers"][0]["summary_id"] == paper_id(paper()["doi"])
        assert "abstract" not in output["papers"][0]
        assert "private" not in output["papers"][0]
        assert "pdf_url" not in output["papers"][0]
        assert "path" not in output["summaries"][0]["source"]
        assert "Nội dung" in output["summaries"][0]["search_text"]


def test_normalize_doi_is_stable():
    assert normalize_doi("https://doi.org/10.3847/1538-4357/ABCD") == "10.3847/1538-4357/abcd"
    assert normalize_doi("doi:10.1051/0004-6361/202661121") == "10.1051/0004-6361/202661121"
    assert normalize_doi("https://example.com/paper") == ""
