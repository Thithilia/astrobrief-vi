from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path

import httpx
import pytest

from pipeline.daily import atomic_json
from pipeline.store import Store
from pipeline.fulltext import CACHE_VERSION, FullTextUnavailable
from pipeline.editorial import review_fingerprint
from pipeline.inventory import approve, validate_envelope, load_inventory, digest
from pipeline.producer import produce, cached_source
from pipeline.release import prepare, materialize, confirm, ledger, health, verify_live, TZ
from pipeline.codex_runner import CodexQuotaExceeded
from test_daily import paper, source, draft, passing_review, silence


def world(root, count):
    store=Store(root/".local/state.sqlite")
    store.upsert_papers([paper(n) for n in range(count)])
    atomic_json(root/"public/data/releases.json",{"schema_version":1,"releases":[]})
    atomic_json(root/"public/data/catalog.json",{"papers":store.papers(),"summaries":[],"journals":[],"generated_at":"2026-11-01T00:00:00Z"})
    return store


def cache(p, cache_root):
    package=source(p)
    folder=cache_root/"fulltext"/p["id"];folder.mkdir(parents=True,exist_ok=True)
    text_path=folder/"source.txt";text_path.write_text(package["text"],encoding="utf-8")
    checksum=hashlib.sha256(text_path.read_bytes()).hexdigest()
    package.update(cache_version=CACHE_VERSION,sha256=checksum,text_sha256=checksum,text_path=str(text_path))
    atomic_json(folder/"source.json",package)
    return package


def acquisition(p, cache_root, **kwargs): return cache(p,cache_root)


def ranked_runner(prompt,schema,work,**kwargs):
    if schema=="selection":
        data=json.loads(prompt.split("DỮ LIỆU:\n",1)[1])
        return {"candidates":[{"doi":p["doi"],"topic":"stars","rationale":"Scientific question"} for p in data]}
    return draft() if schema=="draft" else passing_review()


def stock(root,store):
    for p in store.papers():
        package=cache(p,root/".local/cache");d=draft()
        proof={"fingerprint":review_fingerprint(d,package),"checked_at":"2026-11-01T00:00:00Z"}
        approve(root,p,package,d,passing_review(),proof,topic="stars",model="configured",generated_at="2026-11-01T00:00:00Z")


def test_cloud_releases_seven_days_without_any_codex_and_never_duplicates(tmp_path):
    store=world(tmp_path,35);stock(tmp_path,store)
    first=datetime(2026,11,4,8,tzinfo=TZ)
    for n in range(7):
        now=first+timedelta(days=n)
        plan=prepare(tmp_path,now)
        assert len(plan["ids"])==5
        assert prepare(tmp_path,now)==plan
        materialize(tmp_path,plan)
        assert health(tmp_path,now)["published"]==0  # A local build is not a release.
        assert confirm(tmp_path,plan,published_at=now.isoformat(),deployment=f"run-{n}",verified=True)["confirmed"]==5
        assert health(tmp_path,now)["status"]=="complete"
        assert prepare(tmp_path,now)["status"]=="idle"
        # A late idempotent confirm must not move yesterday's article to today.
        before=(tmp_path/f"content/summaries/{plan['ids'][0]}.md").read_bytes()
        assert confirm(tmp_path,plan,published_at=(now+timedelta(days=1)).isoformat(),deployment="retry",verified=True)["confirmed"]==0
        assert (tmp_path/f"content/summaries/{plan['ids'][0]}.md").read_bytes()==before
    history=ledger(tmp_path)["releases"]
    assert len(history)==35 and len({r["doi"] for r in history})==35
    assert health(tmp_path,first+timedelta(days=6))["approved_available"]==0


def test_short_inventory_reports_exact_shortfall_and_cutoff(tmp_path):
    store=world(tmp_path,3);stock(tmp_path,store)
    now=datetime(2026,11,4,8,tzinfo=TZ)
    plan=prepare(tmp_path,now);assert len(plan["ids"])==3
    with pytest.raises(ValueError,match="Chưa xác minh"):
        confirm(tmp_path,plan,published_at=now.isoformat(),deployment="x",verified=False)
    assert not ledger(tmp_path)["releases"]
    confirm(tmp_path,plan,published_at=now.isoformat(),deployment="x",verified=True)
    value=health(tmp_path,now.replace(hour=23,minute=30))
    assert value["status"]=="missed" and value["published"]==3 and value["missing"]==2
    assert prepare(tmp_path,now.replace(hour=23,minute=30))["status"]=="idle"
    assert health(tmp_path,now+timedelta(days=1))["published"]==0


def test_actual_deployment_date_is_used_after_midnight(tmp_path):
    store=world(tmp_path,5);stock(tmp_path,store)
    plan=prepare(tmp_path,datetime(2026,11,4,23,10,tzinfo=TZ))
    result=confirm(tmp_path,plan,published_at="2026-11-04T17:01:00Z",deployment="late",verified=True)
    assert result["date"]=="2026-11-05"
    assert {r["summary_date"] for r in ledger(tmp_path)["releases"]}=={"2026-11-05"}


def test_live_verification_requires_matching_doi_catalog_hash_and_page_version(tmp_path):
    store=world(tmp_path,1);stock(tmp_path,store)
    plan=prepare(tmp_path,datetime(2026,11,4,8,tzinfo=TZ));key=plan["ids"][0]
    record=load_inventory(tmp_path)[key]
    def handler(request):
        if request.url.path.endswith('catalog.json'):
            return httpx.Response(200,json={"summaries":[{"id":key,"doi":record["summary"]["doi"],"content_hash":plan["hashes"][key]}]})
        return httpx.Response(200,text=f'<div data-content-hash="{plan["hashes"][key]}"></div>')
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert verify_live(tmp_path,plan,client=client)
    def stale(request): return httpx.Response(200,json={"summaries":[]})
    with httpx.Client(transport=httpx.MockTransport(stale)) as client:
        assert not verify_live(tmp_path,plan,client=client)


def test_inventory_is_bound_to_review_content_and_excludes_private_fields(tmp_path):
    store=world(tmp_path,1);stock(tmp_path,store)
    record=next(iter(load_inventory(tmp_path).values()))
    assert 'evidence' not in record['summary']
    record['summary']['title']='Changed after approval'
    with pytest.raises(ValueError,match="thay đổi"): validate_envelope(record,tmp_path)
    record['approval']['content_hash']=digest(record['summary'])
    record['summary']['source']['pdf_path']='C:\\private.pdf'
    record['approval']['content_hash']=digest(record['summary'])
    with pytest.raises(ValueError,match="Sai nguồn"): validate_envelope(record,tmp_path)


def test_producer_continues_after_first_fifteen_inaccessible_sources(tmp_path):
    store=world(tmp_path,17);tried=[]
    def acquire(p,cache_root,**kwargs):
        tried.append(p['doi'])
        if len(tried)<=16: raise FullTextUnavailable('fulltext_unavailable',attempts=[{'url':'https://example.org/paper','reason':'http_403'}])
        return cache(p,cache_root)
    report=produce(store,tmp_path,target=35,max_items=1,budget_seconds=60,runner=ranked_runner,acquire=acquire,progress=silence)
    assert report['created']==1 and len(tried)==17
    assert not store.summaries() and not (tmp_path/'content/summaries').exists()
    assert len(load_inventory(tmp_path))==1
    assert health(tmp_path)['published']==0
    assert store.conn.execute("select count(*) from editorial_items where state='waiting_source' and retry_at is not null").fetchone()[0]==16


def test_quota_interrupt_preserves_draft_and_resumes_without_rewriting(tmp_path):
    store=world(tmp_path,1);calls=[]
    def runner(prompt,schema,work,**kwargs):
        calls.append(schema)
        if schema=='review' and calls.count('review')==1: raise CodexQuotaExceeded('usage limit')
        return ranked_runner(prompt,schema,work,**kwargs)
    first=produce(store,tmp_path,max_items=1,budget_seconds=60,runner=runner,acquire=acquisition,progress=silence)
    assert first['status']=='waiting_quota' and calls.count('draft')==1
    second=produce(store,tmp_path,max_items=1,budget_seconds=60,runner=runner,acquire=acquisition,progress=silence)
    assert second['status']=='waiting_quota' and calls.count('review')==1
    store.set_state('producer:retry_at','2000-01-01T00:00:00Z')
    store.conn.execute("update editorial_items set retry_at='2000-01-01T00:00:00Z'");store.conn.commit()
    third=produce(store,tmp_path,max_items=1,budget_seconds=60,runner=runner,acquire=acquisition,progress=silence)
    assert third['created']==1 and calls.count('draft')==1 and calls.count('review')==2


def test_bad_review_consumes_bounded_repairs_then_another_candidate_is_used(tmp_path):
    store=world(tmp_path,2)
    for p in store.papers(): cache(p,tmp_path/'.local/cache')
    bad=store.papers()[0]['id'];repairs=[]
    def runner(prompt,schema,work,**kwargs):
        if schema=='review' and work.name==bad:
            return passing_review()|{'passed':False,'issues':['Unsupported result']}
        if schema=='repair':
            text=prompt.split('BẢN NHÁP HIỆN CÓ:\n',1)[1]
            d=json.JSONDecoder().raw_decode(text)[0]
            repairs.append(1)
            return {'edits':[{'path':'/title','before':d['title'],'after':d['title']+' sửa'}]}
        return ranked_runner(prompt,schema,work,**kwargs)
    result=produce(store,tmp_path,max_items=1,budget_seconds=60,runner=runner,acquire=acquisition,progress=silence)
    assert result['created']==1 and len(repairs)==3
    assert store.conn.execute("select state from editorial_items where doi=?",(store.papers()[0]['doi'],)).fetchone()[0]=='needs_attention'
    produce(store,tmp_path,max_items=1,budget_seconds=60,runner=runner,acquire=acquisition,progress=silence)
    assert len(repairs)==3


def test_stale_source_checksum_is_not_ready(tmp_path):
    store=world(tmp_path,1);p=store.papers()[0];s=cache(p,tmp_path/'.local/cache')
    assert cached_source(tmp_path,p)
    Path(s['text_path']).write_text('truncated',encoding='utf-8')
    assert cached_source(tmp_path,p) is None


def test_cli_one_approval_does_not_mark_the_day_complete(tmp_path,monkeypatch,capsys):
    import pipeline.cli as cli
    import pipeline.producer as producer
    import pipeline.migration as migration
    store=world(tmp_path,1);store.close()
    original=producer.produce
    def fast(store,root,**kwargs):
        return original(store,root,runner=ranked_runner,acquire=acquisition,progress=silence,**kwargs)
    monkeypatch.setattr(producer,'produce',fast)
    monkeypatch.setattr(migration,'reconcile_local',lambda *a,**kw:0)
    assert cli.main(['--root',str(tmp_path),'daily','--limit','1'])==2
    result=json.loads(capsys.readouterr().out)
    assert result['production']['created']==1
    assert result['day']['published']==0 and result['day']['missing']==5
    assert result['day']['status']!='complete'


def test_history_records_a_missed_day_when_the_scheduler_did_not_run(tmp_path):
    from pipeline.cloud import save_editions
    store=world(tmp_path,0)
    first=health(tmp_path,datetime(2026,11,4,8,tzinfo=TZ));save_editions(tmp_path,first)
    third=health(tmp_path,datetime(2026,11,6,8,tzinfo=TZ));save_editions(tmp_path,third)
    history=json.loads((tmp_path/'public/data/editions.json').read_text(encoding='utf-8'))
    assert history['days']['2026-11-05']['status']=='missed'
    assert history['days']['2026-11-05']['published']==0


def test_cloud_recovery_confirms_old_deployment_before_selecting_more(tmp_path,monkeypatch):
    import pipeline.cloud as cloud
    store=world(tmp_path,5);stock(tmp_path,store)
    plan=prepare(tmp_path,datetime(2026,11,4,8,tzinfo=TZ))
    plan['workflow_run_id']='123';atomic_json(tmp_path/'public/data/release-state.json',plan)
    monkeypatch.setattr(cloud,'verify_live',lambda *a,**kw:True)
    monkeypatch.setattr(cloud,'deployment_timestamp',lambda run_id:'2026-11-04T01:05:00Z')
    monkeypatch.setattr(cloud,'persist',lambda *a,**kw:{'changed':True})
    result=cloud.preflight(tmp_path,event='workflow_dispatch')
    assert len(ledger(tmp_path)['releases'])==5
    assert not result['release']


def test_cloud_does_not_overwrite_a_partially_visible_pending_deployment(tmp_path,monkeypatch):
    import pipeline.cloud as cloud
    store=world(tmp_path,2);stock(tmp_path,store)
    plan=prepare(tmp_path,datetime(2026,11,4,8,tzinfo=TZ))
    monkeypatch.setattr(cloud,'verify_live',lambda *a,**kw:False)
    monkeypatch.setattr(cloud,'live_ids',lambda *a,**kw:{plan['ids'][0]})
    with pytest.raises(RuntimeError,match='lan truyền'):
        cloud.preflight(tmp_path,event='workflow_dispatch')
    assert json.loads((tmp_path/'public/data/release-state.json').read_text(encoding='utf-8'))==plan


def test_codex_error_classification_ignores_unrelated_stderr_and_handles_auth():
    from pipeline.codex_runner import failure_kind
    assert failure_kind('MCP warning: rate limit exceeded')=='unavailable'
    assert failure_kind(json.dumps({'type':'error','message':'You hit your usage limit'}))=='quota'
    assert failure_kind(json.dumps({'type':'turn.failed','error':{'message':'Refresh token authentication failed'}}))=='auth'
    assert failure_kind(json.dumps({'type':'turn.failed','error':'network failure'}))=='unavailable'


def test_repository_source_discovery_only_uses_doi_linked_official_records():
    from pipeline.repository_sources import parse_leads
    raw=b'<ul><li><a href="https://doi.org/10.1234/test">DOI</a><a href="https://authors.library.caltech.edu/records/abc">record</a></li><li><a href="https://evil.example/10.1234/wrong">fake DOI</a><a href="https://authors.library.caltech.edu/records/wrong">record</a></li></ul>'
    assert parse_leads(raw)=={'10.1234/test':'https://authors.library.caltech.edu/records/abc'}


def test_cloud_release_is_imported_for_a_local_preview_without_regeneration(tmp_path,monkeypatch):
    import pipeline.migration as migration
    store=world(tmp_path,1);stock(tmp_path,store)
    plan=prepare(tmp_path,datetime(2026,11,4,8,tzinfo=TZ))
    confirm(tmp_path,plan,published_at='2026-11-04T01:05:00Z',deployment='cloud',verified=True)
    article=tmp_path/f"content/summaries/{plan['ids'][0]}.md";article.unlink()
    monkeypatch.setattr(migration,'sync_release_state',lambda *a,**kw:'sha')
    assert migration.reconcile_local(store,tmp_path)==1
    assert article.exists() and len(store.summaries())==1
    assert store.summaries()[0]['content_hash']==plan['hashes'][plan['ids'][0]]


def test_unapproved_markdown_cannot_leak_through_a_metadata_deployment(tmp_path):
    from pipeline.release import validate_public_tree
    store=world(tmp_path,1);stock(tmp_path,store)
    plan=prepare(tmp_path,datetime(2026,11,4,8,tzinfo=TZ));materialize(tmp_path,plan)
    validate_public_tree(tmp_path,plan)
    (tmp_path/'content/summaries/unreviewed.md').write_text('Unreviewed content',encoding='utf-8')
    with pytest.raises(ValueError,match='chưa được'):validate_public_tree(tmp_path,plan)
