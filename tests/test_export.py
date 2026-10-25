import json
import multiprocessing
from pathlib import Path

import pytest

from pipeline.daily import process_lock
from pipeline.export import export_catalog
from pipeline.store import Store


def _paper(suffix):
    return {"doi": f"10.3847/1538-4357/{suffix}", "journal": "apj", "title": suffix}


def _export_worker(root, ready, read_started, results):
    """Use a separate connection/process, as the hourly and daily tasks do."""
    try:
        with Store(root / ".local" / "state.sqlite") as store:
            get_state = store.get_state

            def observe_read(*args, **kwargs):
                read_started.set()
                return get_state(*args, **kwargs)

            store.get_state = observe_read
            ready.set()
            export_catalog(store, root)
        results.put(None)
    except Exception as exc:
        results.put(repr(exc))
        raise


def test_waiting_export_reads_commits_after_acquiring_process_lock(tmp_path):
    db_path = tmp_path / ".local" / "state.sqlite"
    with Store(db_path) as store:
        store.upsert_papers([_paper("original")])

    context = multiprocessing.get_context("spawn")
    ready, read_started = context.Event(), context.Event()
    results = context.Queue()
    worker = context.Process(target=_export_worker, args=(tmp_path, ready, read_started, results))
    try:
        with process_lock(tmp_path, "export"):
            worker.start()
            assert ready.wait(15), "Exporter did not start"
            assert not read_started.wait(0.3), "Exporter read stale data before acquiring the lock"
            with Store(db_path) as store:
                store.upsert_papers([_paper("committed-while-waiting")])
        worker.join(15)
        assert not worker.is_alive(), "Exporter did not resume after the lock was released"
        assert worker.exitcode == 0
        assert results.get(timeout=2) is None
        catalog = json.loads((tmp_path / "public" / "data" / "catalog.json").read_text(encoding="utf-8"))
        assert {paper["title"] for paper in catalog["papers"]} == {"original", "committed-while-waiting"}
    finally:
        if worker.is_alive():
            worker.terminate()
            worker.join(5)
        results.close()


def test_failed_replace_keeps_catalog_and_releases_export_lock(tmp_path, monkeypatch):
    with Store(tmp_path / ".local" / "state.sqlite") as store:
        store.upsert_papers([_paper("original")])
        target = export_catalog(store, tmp_path)
        original = target.read_text(encoding="utf-8")
        store.upsert_papers([_paper("new")])
        replace = Path.replace

        def fail_catalog_replace(path, destination):
            if Path(destination) == target:
                raise OSError("Simulated interrupted catalog replacement")
            return replace(path, destination)

        with monkeypatch.context() as patch:
            patch.setattr(Path, "replace", fail_catalog_replace)
            with pytest.raises(OSError, match="interrupted"):
                export_catalog(store, tmp_path)
        assert target.read_text(encoding="utf-8") == original
        assert not list(target.parent.glob(".catalog.json.*.tmp"))
        export_catalog(store, tmp_path)
        catalog = json.loads(target.read_text(encoding="utf-8"))
        assert {paper["title"] for paper in catalog["papers"]} == {"original", "new"}
