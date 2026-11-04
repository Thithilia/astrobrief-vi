import json
from pathlib import Path
import subprocess

import pytest

from pipeline.repository import publish_files, merge_catalog
import pipeline.repository as repository


def git(root,*args):
    result=subprocess.run(['git',*args],cwd=root,capture_output=True,text=True,encoding='utf-8',errors='replace')
    assert result.returncode==0,result.stderr
    return result.stdout.strip()


def setup_repo(tmp_path):
    remote=tmp_path/'remote.git';remote.mkdir();git(remote,'init','--bare','--initial-branch=main')
    root=tmp_path/'local';root.mkdir();git(root,'init','--initial-branch=main')
    git(root,'config','user.name','Test');git(root,'config','user.email','test@example.org')
    (root/'.gitignore').write_text('.local/\n',encoding='utf-8')
    (root/'source.txt').write_text('source original',encoding='utf-8')
    folder=root/'public/data';folder.mkdir(parents=True)
    (folder/'catalog.json').write_text(json.dumps({'generated_at':'2026-11-01T00:00:00Z','papers':[],'summaries':[]}))
    git(root,'add','.');git(root,'commit','-m','Initial');git(root,'remote','add','origin',str(remote));git(root,'push','-u','origin','main')
    return root,remote


def test_metadata_merge_keeps_cloud_summaries_and_updates_papers():
    remote={'generated_at':'2026-11-01','papers':[{'doi':'a','title':'old'}],
            'summaries':[{'id':'s','doi':'a','summary_date':'2026-11-01','topic':'stars'}]}
    local={'generated_at':'2026-11-02','papers':[{'doi':'a','title':'new'},{'doi':'b','title':'new discovery'}], 'summaries':[]}
    result=merge_catalog(remote,local)
    assert result['summaries']==remote['summaries'] and len(result['papers'])==2
    assert next(p for p in result['papers'] if p['doi']=='a')['has_summary']


def test_publication_leaves_source_branch_and_user_changes_untouched(tmp_path):
    root,remote=setup_repo(tmp_path);head=git(root,'rev-parse','HEAD')
    (root/'source.txt').write_text('user unfinished change',encoding='utf-8')
    path=root/'public/data/producer.json';path.write_text('{"status":"running","heartbeat_at":"2026-11-04"}',encoding='utf-8')
    result=publish_files(root,['public/data/producer.json'],expected_remote=str(remote))
    assert result['changed'] and git(root,'rev-parse','HEAD')==head
    assert (root/'source.txt').read_text()=='user unfinished change'
    assert git(root,'diff','--cached','--name-only')==''
    assert json.loads(git(remote,'show','main:public/data/producer.json'))['status']=='running'
    assert not list((root/'.local/publication').glob('*'))


def test_concurrent_remote_push_is_retried_without_losing_source_or_metadata(tmp_path,monkeypatch):
    root,remote=setup_repo(tmp_path)
    other=tmp_path/'other';git(tmp_path,'clone',str(remote),str(other))
    git(other,'config','user.name','Other');git(other,'config','user.email','other@example.org')
    path=root/'public/data/producer.json';path.write_text('{"status":"waiting_quota","heartbeat_at":"2026-11-04"}',encoding='utf-8')
    original=repository.command;race=[]
    def racing(work,*args,**kwargs):
        if args[0]=='push' and not race:
            race.append(1);(other/'source.txt').write_text('remote source update',encoding='utf-8')
            git(other,'add','source.txt');git(other,'commit','-m','Concurrent update');git(other,'push','origin','main')
        return original(work,*args,**kwargs)
    monkeypatch.setattr(repository,'command',racing)
    result=publish_files(root,['public/data/producer.json'],expected_remote=str(remote))
    assert result['changed'] and len(race)==1
    assert git(remote,'show','main:source.txt')=='remote source update'
    assert json.loads(git(remote,'show','main:public/data/producer.json'))['status']=='waiting_quota'


def test_publisher_refuses_staged_user_edits_and_paths_outside_allowlist(tmp_path):
    root,remote=setup_repo(tmp_path)
    with pytest.raises(ValueError): publish_files(root,['source.txt'],expected_remote=str(remote))
    (root/'source.txt').write_text('user staged',encoding='utf-8');git(root,'add','source.txt')
    with pytest.raises(RuntimeError,match='staged'):
        publish_files(root,['public/data/catalog.json'],expected_remote=str(remote))
    assert git(root,'diff','--cached','--name-only')=='source.txt'


def test_local_publication_does_not_overwrite_cloud_authority_or_upload_temp_files(tmp_path):
    from pipeline.repository import generated_paths
    root,remote=setup_repo(tmp_path)
    (root/'public/data/editions.json').write_text('{}')
    (root/'public/data/releases.json').write_text('{}')
    (root/'public/data/.producer.tmp').write_text('partial')
    queue=root/'content/ready';queue.mkdir(parents=True)
    (queue/'.draft.tmp').write_text('partial')
    paths=generated_paths(root)
    assert 'public/data/editions.json' not in paths and 'public/data/releases.json' not in paths
    assert not any(path.endswith('.tmp') for path in paths)
