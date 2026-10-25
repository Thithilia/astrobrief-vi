from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

import pipeline.cli as cli
import pipeline.daily as daily
from pipeline.store import Store
from pipeline.cli import main


def test_custom_data_root_cannot_publish_default_repository(tmp_path, monkeypatch, capsys):
    import pipeline.publish as publication

    def forbidden(*args, **kwargs):
        raise AssertionError("A custom data root must never mutate the default GitHub repository")

    monkeypatch.setattr(publication, "publish", forbidden)
    assert main(["--root", str(tmp_path), "publish"]) == 1
    assert "thư mục dự án mặc định" in capsys.readouterr().out


def _clock(monkeypatch, moment):
    monkeypatch.setattr(cli, "datetime", SimpleNamespace(now=lambda tz: moment.astimezone(tz)))


def _summary(store, number, day):
    doi = f"10.1234/cli{number}"
    store.upsert_papers([{"doi": doi, "journal": "apj", "title": f"Paper {number}"}])
    store.save_summary({"doi": doi, "summary_date": day, "generated_at": day + "T01:00:00Z",
                        "review": {"passed": True}})


@pytest.mark.parametrize("moment,existing,limit,status", [
    (datetime(2026, 10, 25, 23, 59, tzinfo=timezone.utc), 0, 5, "not_due"),
    (datetime(2026, 10, 26, 1, tzinfo=timezone.utc), 1, 1, "complete"),
])
def test_daily_refresh_skips_before_vietnam_seven_or_when_cap_met(
        tmp_path, monkeypatch, capsys, moment, existing, limit, status):
    _clock(monkeypatch, moment)
    with Store(tmp_path / ".local" / "state.sqlite") as store:
        for number in range(existing):
            _summary(store, number, "2026-10-26")

    def forbidden(*args, **kwargs):
        raise AssertionError("A skipped day must not collect or select articles")

    monkeypatch.setattr(cli, "collect_all", forbidden)
    monkeypatch.setattr(daily, "run_daily", forbidden)
    monkeypatch.setattr(daily, "recover_summary_files", lambda *args: None)
    monkeypatch.setattr(cli, "export_catalog", lambda *args: None)
    assert main(["--root", str(tmp_path), "daily", "--catch-up", "--refresh", "--limit", str(limit)]) == 0
    import json
    report = json.loads(capsys.readouterr().out)
    assert report["date"] == "2026-10-26"
    assert report["status"] == status


def test_daily_refresh_finishes_collection_before_selection_at_seven(tmp_path, monkeypatch, capsys):
    # 00:00 UTC is exactly the 07:00 boundary in Vietnam.
    _clock(monkeypatch, datetime(2026, 10, 26, tzinfo=timezone.utc))
    events = []
    with Store(tmp_path / ".local" / "state.sqlite") as store:
        for number in range(5):
            _summary(store, number, "2026-10-25")

    def collect(store):
        events.append("collect")
        with pytest.raises(RuntimeError):
            with daily.process_lock(tmp_path, "collect"):
                pass
        store.upsert_papers([{"doi": "10.1234/fresh", "journal": "apj", "title": "Fresh"}])
        return {"status": "refreshed"}

    def select(store, root, **kwargs):
        events.append("daily")
        assert store.get_paper("10.1234/fresh") is not None
        assert kwargs == {"limit": 5, "catch_up": True}
        return {"status": "complete", "created": 1}

    monkeypatch.setattr(cli, "collect_all", collect)
    monkeypatch.setattr(daily, "run_daily", select)
    monkeypatch.setattr(daily, "recover_summary_files", lambda *args: events.append("recover"))
    monkeypatch.setattr(cli, "export_catalog", lambda *args: events.append("export"))
    assert main(["--root", str(tmp_path), "daily", "--catch-up", "--refresh"]) == 0
    assert events == ["collect", "daily", "recover", "export"]
    import json
    assert json.loads(capsys.readouterr().out)["refresh"]["status"] == "refreshed"


def test_daily_refresh_busy_is_retryable_and_never_selects_or_publishes(tmp_path, monkeypatch, capsys):
    import json
    import pipeline.publish as publication
    _clock(monkeypatch, datetime(2026, 10, 26, 1, tzinfo=timezone.utc))
    monkeypatch.setattr(cli, "ROOT", tmp_path)

    def forbidden(*args, **kwargs):
        raise AssertionError("A busy collector must not permit stale selection or publication")

    monkeypatch.setattr(cli, "collect_all", forbidden)
    monkeypatch.setattr(daily, "run_daily", forbidden)
    monkeypatch.setattr(daily, "recover_summary_files", forbidden)
    monkeypatch.setattr(cli, "export_catalog", forbidden)
    monkeypatch.setattr(publication, "publish", forbidden)
    with daily.process_lock(tmp_path, "collect"):
        assert main(["daily", "--catch-up", "--refresh", "--publish"]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "refresh_wait"
    assert report["retryable"] is True
    assert report["created"] == 0


def test_normal_manual_daily_does_not_refresh(tmp_path, monkeypatch):
    calls = []

    def forbidden(*args, **kwargs):
        raise AssertionError("Manual daily only refreshes when --refresh is supplied")

    monkeypatch.setattr(cli, "collect_all", forbidden)
    monkeypatch.setattr(daily, "run_daily", lambda *args, **kwargs: calls.append(kwargs) or {"status": "complete"})
    monkeypatch.setattr(daily, "recover_summary_files", lambda *args: None)
    monkeypatch.setattr(cli, "export_catalog", lambda *args: None)
    assert main(["--root", str(tmp_path), "daily"]) == 0
    assert calls == [{"limit": 5, "catch_up": False}]
