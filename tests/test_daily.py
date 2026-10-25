from datetime import datetime
from pathlib import Path

from pipeline.store import Store
from pipeline.daily import run_daily, TZ, public_figures, recover_summary_files, candidate_pool
from pipeline.editorial import validate_draft
from pipeline.codex_runner import CodexQuotaExceeded


def paper(n):
    return {"doi": f"10.1234/paper{n}", "title": f"Research result {n}", "journal": "apj",
            "authors": ["A. Author"], "published_online": "2026-09-28", "kind": "research"}


def source(paper, *args, **kwargs):
    return {"kind": "arxiv", "url": "https://arxiv.org/abs/2601.00001v2", "version": "v2",
            "doi": paper["doi"], "sha256": "abc", "complete": True, "license": None, "figures": [],
            "text": "[P001-S001] The sample contains 30 stars.\n[P002-S001] The measured flux increased by 10 percent.\n[P003-S001] The model is valid for isolated stars."}


def draft():
    text = "bồi tụ (accretion), thiên hà (galaxy), quang phổ (spectrum), khối lượng (mass). "
    text += " ".join(["Các phép đo được đối chiếu với mô hình và điều kiện vật lý."] * 11)
    return {"title": "Một kết quả vật lý", "dek": "Giải thích kết quả.",
            "sections": [{"heading": f"Phần {i}", "body": text} for i in range(6)],
            "glossary": [{"vi": a, "en": b} for a,b in [("bồi tụ","accretion"),("thiên hà","galaxy"),("quang phổ","spectrum"),("khối lượng","mass")]],
            "evidence": [{"claim":"Cỡ mẫu", "locator":"[P001-S001]", "quote":"The sample contains 30 stars."},
                         {"claim":"Thông lượng", "locator":"[P002-S001]", "quote":"The measured flux increased by 10 percent."},
                         {"claim":"Phạm vi", "locator":"[P003-S001]", "quote":"The model is valid for isolated stars."}],
            "figure_explanations": []}


def passing_review():
    return {k: True for k in ("passed","doi_matches","fulltext_used","numbers_supported","conclusions_supported","figures_supported","terminology_consistent")} | {"issues": []}


def good_runner(prompt, schema, *args, **kwargs):
    if schema == "selection":
        return {"candidates": [{"doi":f"10.1234/paper{i}","topic":"stars","rationale":"Câu hỏi rõ."} for i in range(8)]}
    return draft() if schema == "draft" else passing_review()


def silence(*args, **kwargs):
    pass


def test_daily_cap_and_rerun_and_late_paper(tmp_path):
    store = Store(tmp_path / "state.sqlite")
    store.upsert_papers([paper(i) for i in range(8)])
    now = datetime(2026,10,26,8,tzinfo=TZ)
    report = run_daily(store,tmp_path,now=now,runner=good_runner,acquire=source,progress=silence)
    assert report["created"] == 5
    assert len(store.summaries()) == 5
    assert all(s["published_online"] == "2026-09-28" for s in store.summaries())
    assert len(list((tmp_path / "content/summaries").glob("*.md"))) == 5
    def forbidden(*args, **kwargs):
        raise AssertionError("A completed date must not invoke Codex again")
    report2 = run_daily(store,tmp_path,now=now,runner=forbidden,acquire=source,progress=silence)
    assert report2["created"] == 0 and len(store.summaries()) == 5


def test_unsupported_claim_never_published(tmp_path):
    store=Store(tmp_path / "state.sqlite"); store.upsert_papers([paper(0)])
    def runner(prompt,schema,*args,**kwargs):
        if schema == "review":
            return passing_review() | {"passed":False,"numbers_supported":False,"issues":["Claim unsupported"]}
        return good_runner(prompt,schema,*args,**kwargs)
    result=run_daily(store,tmp_path,now=datetime(2026,10,26,8,tzinfo=TZ),runner=runner,acquire=source,progress=silence)
    assert result["created"] == 0 and not store.summaries()
    assert not (tmp_path / "content/summaries").exists()


def test_quota_preserves_queue_and_can_resume(tmp_path):
    store=Store(tmp_path / "state.sqlite"); store.upsert_papers([paper(0)])
    def exhausted(*args,**kwargs):
        raise CodexQuotaExceeded("limit")
    now=datetime(2026,10,26,8,tzinfo=TZ)
    result=run_daily(store,tmp_path,now=now,runner=exhausted,acquire=source,progress=silence)
    assert result["status"] == "quota_wait" and not store.summaries()
    result=run_daily(store,tmp_path,now=now,runner=good_runner,acquire=source,progress=silence)
    assert result["created"] == 1


def test_schedule_gate_before_seven(tmp_path):
    store=Store(tmp_path / "state.sqlite")
    result=run_daily(store,tmp_path,now=datetime(2026,10,26,6,59,tzinfo=TZ),catch_up=True,progress=silence)
    assert result["status"] == "not_due"


def test_fabricated_quote_and_page_render_are_rejected(tmp_path):
    item=draft(); item["evidence"][0]["quote"]="The sample contains 9000 stars."
    assert validate_draft(item,source(paper(0)))
    image=tmp_path/"page.png"; image.write_bytes(b"private render")
    figures={"figures":[{"image_path":str(image),"local_only":True,"license":"CC BY 4.0"}]}
    assert public_figures(tmp_path,{"id":"p"},figures,{"figure_explanations":[{"index":0}]}) == []


def test_wrong_source_locator_and_unsafe_heading_are_rejected():
    item = draft()
    item["evidence"][0]["locator"] = "[P003-S001]"
    assert any("không nằm tại vị trí" in issue for issue in validate_draft(item, source(paper(0))))
    item = draft()
    item["sections"][0]["heading"] = '<img src="x" onerror="alert(1)">'
    assert any("HTML" in issue for issue in validate_draft(item, source(paper(0))))


def test_reusable_figure_contract_matches_fulltext(tmp_path):
    image = tmp_path / "figure.png"
    image.write_bytes(b"licensed fixture image")
    figures = {"url": "https://example.org/paper", "figures": [{"image_path": str(image),
               "public_safe": True, "license": "https://creativecommons.org/licenses/by/4.0/"}]}
    public = public_figures(tmp_path, {"id": "p", "title": "Paper", "doi": "10.1234/paper0"}, figures,
                            {"figure_explanations": [{"index": 0, "caption_vi": "Hình có nguồn.", "alt_vi": "Một đồ thị."}]})
    assert len(public) == 1
    assert (tmp_path / "public" / "figures" / "p" / "figure-0.png").is_file()


def test_truncated_caches_are_ignored_and_regenerated(tmp_path):
    store = Store(tmp_path / "state.sqlite")
    store.upsert_papers([paper(0)])
    work = tmp_path / ".local" / "runs" / "2026-10-26"
    work.mkdir(parents=True)
    (work / "selection.json").write_text('{"candidates": [', encoding="utf-8")
    paper_work = work / store.get_paper(paper(0)["doi"])["id"]
    paper_work.mkdir()
    (paper_work / "draft.json").write_text('{"title":', encoding="utf-8")
    result = run_daily(store, tmp_path, now=datetime(2026,10,26,8,tzinfo=TZ), runner=good_runner,
                       acquire=source, progress=silence)
    assert result["created"] == 1


def test_db_first_commit_recovers_markdown_and_keeps_daily_cap(tmp_path, monkeypatch):
    import pipeline.daily as daily
    import pytest
    store = Store(tmp_path / "state.sqlite")
    store.upsert_papers([paper(0)])
    original = daily.write_summary
    def interrupted(*args, **kwargs):
        raise OSError("simulated interruption after SQLite commit")
    monkeypatch.setattr(daily, "write_summary", interrupted)
    now = datetime(2026,10,26,8,tzinfo=TZ)
    with pytest.raises(OSError, match="simulated interruption"):
        run_daily(store, tmp_path, now=now, limit=1, runner=good_runner, acquire=source, progress=silence)
    assert len(store.summaries()) == 1
    monkeypatch.setattr(daily, "write_summary", original)
    def forbidden(*args, **kwargs):
        raise AssertionError("Repairing a committed summary must not call Codex")
    result = run_daily(store, tmp_path, now=now, limit=1, runner=forbidden, acquire=source, progress=silence)
    assert result["total_today"] == 1 and result["created"] == 0
    assert len(list((tmp_path / "content" / "summaries").glob("*.md"))) == 1


def test_orphan_markdown_is_not_silently_published(tmp_path):
    import pytest
    store = Store(tmp_path / "state.sqlite")
    directory = tmp_path / "content" / "summaries"
    directory.mkdir(parents=True)
    (directory / "unregistered.md").write_text("Unregistered body", encoding="utf-8")
    with pytest.raises(RuntimeError, match="chưa được đăng ký"):
        recover_summary_files(store, tmp_path)
    assert (directory / "unregistered.md").is_file()


def test_cached_older_source_and_late_discovery_remain_in_candidate_pool(tmp_path):
    import json
    store = Store(tmp_path / "state.sqlite")
    items = [paper(n) | {"published_online": "2026-10-25", "first_seen": "2026-10-25T00:00:00Z"} for n in range(200)]
    items += [paper(201) | {"published_online": "2026-09-28", "first_seen": "2026-10-25T00:00:00Z"},
              paper(202) | {"published_online": "2026-09-28", "first_seen": "2026-10-26T01:00:00Z"}]
    store.upsert_papers(items)
    old = store.get_paper(paper(201)["doi"])
    cache = tmp_path / ".local" / "cache" / "fulltext" / old["id"] / "source.json"
    cache.parent.mkdir(parents=True)
    cache.write_text(json.dumps(source(old)), encoding="utf-8")
    pool, ready = candidate_pool(store.papers(), tmp_path)
    assert old["doi"] in ready
    assert {paper(201)["doi"], paper(202)["doi"]}.issubset({p["doi"] for p in pool})


def test_exhausted_cached_shortlist_is_reranked(tmp_path):
    import json
    store = Store(tmp_path / "state.sqlite")
    store.upsert_papers([paper(0)])
    work = tmp_path / ".local" / "runs" / "2026-10-26"
    work.mkdir(parents=True)
    stale = [{"doi": f"10.1234/absent{n}", "topic": "stars", "rationale": "Old shortlist"} for n in range(15)]
    stale.append({"doi": paper(0)["doi"], "topic": "stars", "rationale": "Beyond shortlist bound"})
    (work / "selection.json").write_text(json.dumps({"candidates": stale}), encoding="utf-8")
    calls = []
    def runner(prompt, schema, *args, **kwargs):
        calls.append(schema)
        return good_runner(prompt, schema, *args, **kwargs)
    result = run_daily(store, tmp_path, now=datetime(2026,10,26,8,tzinfo=TZ), runner=runner,
                       acquire=source, progress=silence)
    assert result["created"] == 1 and calls.count("selection") == 1


def test_review_cache_binds_draft_text_and_actual_figure(tmp_path):
    from copy import deepcopy
    from pipeline.editorial import review_fingerprint
    original = draft()
    package = source(paper(0))
    baseline = review_fingerprint(original, package)
    changed = deepcopy(original)
    changed["sections"][0]["body"] += " A changed conclusion."
    assert review_fingerprint(changed, package) != baseline
    assert review_fingerprint(original, package | {"text": package["text"] + " revised source"}) != baseline
    image = tmp_path / "plot.png"
    image.write_bytes(b"original figure")
    package["figures"] = [{"image_path": str(image)}]
    original["figure_explanations"] = [{"index": 0}]
    before = review_fingerprint(original, package)
    image.write_bytes(b"corrected figure")
    assert review_fingerprint(original, package) != before
