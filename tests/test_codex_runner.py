import json
from pathlib import Path
import subprocess

import pytest

import pipeline.codex_runner as runner


def test_cli_preserves_config_and_never_sends_api_keys(tmp_path,monkeypatch):
    seen={}
    monkeypatch.setattr(runner,'authenticated_cli',lambda:'fake-codex')
    monkeypatch.setattr(runner,'configuration',lambda:{'model':'configured-model','model_reasoning_effort':'max'})
    monkeypatch.setenv('OPENAI_API_KEY','test-secret')
    class Fake:
        returncode=0;pid=123
        def __init__(self,args,**kwargs):
            seen.update(args=args,kwargs=kwargs)
            Path(args[args.index('--output-last-message')+1]).write_text('{"candidates":[]}',encoding='utf-8')
        def communicate(self,**kwargs):seen['communicate']=kwargs
    monkeypatch.setattr(runner.subprocess,'Popen',Fake)
    assert runner.run_structured('source prompt','selection',tmp_path)=={'candidates':[]}
    assert seen['args'][seen['args'].index('--model')+1]=='configured-model'
    assert 'model_reasoning_effort="max"' in seen['args']
    assert 'OPENAI_API_KEY' not in seen['kwargs']['env']
    assert seen['communicate']['input']=='source prompt'


def test_usage_failure_is_classified_from_json_events(tmp_path,monkeypatch):
    monkeypatch.setattr(runner,'authenticated_cli',lambda:'fake-codex')
    class Fake:
        returncode=1;pid=123
        def __init__(self,args,**kwargs):self.events=kwargs['stdout']
        def communicate(self,**kwargs):self.events.write(json.dumps({'type':'turn.failed','error':{'message':'usage limit reached'}})+'\n');self.events.flush()
    monkeypatch.setattr(runner.subprocess,'Popen',Fake)
    with pytest.raises(runner.CodexQuotaExceeded):runner.run_structured('p','selection',tmp_path)


def test_timeout_terminates_the_owned_process_tree(tmp_path,monkeypatch):
    monkeypatch.setattr(runner,'authenticated_cli',lambda:'fake-codex')
    seen=[]
    class Fake:
        returncode=None;pid=123
        def __init__(self,*args,**kwargs):pass
        def communicate(self,**kwargs):raise subprocess.TimeoutExpired('fake-codex',1)
        def wait(self,**kwargs):self.returncode=-1
    monkeypatch.setattr(runner.subprocess,'Popen',Fake)
    monkeypatch.setattr(runner.subprocess,'run',lambda args,**kw:seen.append(args))
    monkeypatch.setattr(runner.os,'killpg',lambda pid,sig:seen.append(pid),raising=False)
    with pytest.raises(runner.CodexUnavailable,match='quá thời gian'):
        runner.run_structured('p','selection',tmp_path,timeout=1)
    assert (['taskkill.exe','/PID','123','/T','/F'] in seen) if runner.os.name=='nt' else (123 in seen)
