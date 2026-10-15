import hashlib
from pathlib import Path
from hwpx_automation.preview_runtime.jobs import JobManager
import pytest,time,sys

worker_python = getattr(sys, "_base_executable", sys.executable) if sys.platform == "win32" else sys.executable

def wait_for(manager,predicate,seconds=5):
    limit=time.monotonic()+seconds
    while time.monotonic()<limit:
        snapshot=manager.snapshot()
        if predicate(snapshot):return snapshot
        time.sleep(.02)
    raise AssertionError(manager.snapshot())

def worker(tmp_path,delay):
    script=tmp_path/'controlled_worker.py'
    script.write_text('''import json,sys,time
from pathlib import Path
job=json.loads(Path(sys.argv[-1]).read_text(encoding='utf8'))
time.sleep('''+str(delay)+''')
Path(job['result']).write_text(json.dumps({'ok':True,'status':'supported','pages':0}),encoding='utf8')
''',encoding='utf8')
    return [worker_python,str(script)]

def test_new_revision_supersedes_old_worker_and_keeps_source_copy(tmp_path):
    manager=JobManager(tmp_path/'jobs',command=worker(tmp_path,.4))
    try:
        first=manager.submit(b'first immutable snapshot',label='first')
        wait_for(manager,lambda s:s['latest']['state']=='running')
        second=manager.submit(b'newer snapshot',label='second')
        state=wait_for(manager,lambda s:s['latest']['state']=='ready')
        assert state['latest']['id']==state['displayed']==second
        assert state['displayedJob']['id']==second and state['displayedJob']['result']['status']=='supported'
        assert manager.jobs[first]['state']=='superseded'
        assert (manager.root/str(first)/'input.hwpx').read_bytes()==b'first immutable snapshot'
        assert state['latest']['inputSha256']==hashlib.sha256(b'newer snapshot').hexdigest()
    finally:manager.close()

def test_cancel_and_timeout_terminate_only_owned_child(tmp_path):
    manager=JobManager(tmp_path/'jobs',timeout=.15,command=worker(tmp_path,10))
    try:
        manager.submit(b'timeout')
        state=wait_for(manager,lambda s:s['latest']['state']=='error')
        assert '처리 시간' in state['latest']['result']['error']
        manager.submit(b'cancel')
        wait_for(manager,lambda s:s['latest']['state']=='running')
        manager.cancel()
        assert manager.snapshot()['latest']['state']=='cancelled'
        assert manager.snapshot()['displayed'] is None
    finally:manager.close()
    assert manager.process is None

def test_invalid_request_does_not_supersede_valid_revision(tmp_path):
    manager=JobManager(tmp_path/'jobs',command=worker(tmp_path,0))
    try:
        job_id=manager.submit(b'valid request')
        for mapping in [[],['not a mapping']]:
            with pytest.raises(ValueError,match='글꼴 대체'):
                manager.submit(b'invalid request',font_substitutions=mapping)
        assert manager.latest==job_id
    finally:manager.close()

def test_snapshot_exposes_completed_page_when_next_revision_is_cancelled(tmp_path):
    manager=JobManager(tmp_path/'jobs',command=worker(tmp_path,.05))
    try:
        first=manager.submit(b'completed revision')
        wait_for(manager,lambda s:s['latest']['state']=='ready')
        manager.submit(b'next revision');manager.cancel()
        snapshot=manager.snapshot()
        assert snapshot['latest']['state']=='cancelled'
        assert snapshot['displayedJob']['id']==first
        assert snapshot['displayedJob']['result']['ok'] is True
    finally:manager.close()

def test_output_budget_stops_owned_worker_before_more_pages_are_written(tmp_path):
    script=tmp_path/'large_output_worker.py'
    script.write_text('''import json,sys,time
from pathlib import Path
job=json.loads(Path(sys.argv[-1]).read_text(encoding='utf8'))
out=Path(job['output']);out.mkdir();(out/'p0.png').write_bytes(b'x'*100)
time.sleep(10)
''',encoding='utf8')
    manager=JobManager(tmp_path/'jobs',output_limit=50,command=[worker_python,str(script)])
    try:
        manager.submit(b'bounded output')
        state=wait_for(manager,lambda s:s['latest']['state']=='error')
        assert '결과 크기' in state['latest']['result']['error']
    finally:manager.close()

@pytest.mark.skipif(sys.platform not in {"win32", "darwin"}, reason="native RSS measurement supports Windows/macOS")
def test_working_set_limit_terminates_owned_child(tmp_path):
    script=tmp_path/'memory_worker.py'
    script.write_text('import time\nheld=b"x"*(64*1024*1024)\ntime.sleep(10)\n',encoding='utf8')
    # A Windows venv executable may be a redirector whose resident memory is
    # separate from its Python child. This stdlib-only worker needs the real
    # interpreter so the owned PID is the process allocating the test memory.
    worker_python=getattr(sys,'_base_executable',sys.executable) if sys.platform=='win32' else sys.executable
    manager=JobManager(tmp_path/'jobs',memory_limit=32*1024*1024,command=[worker_python,str(script)])
    try:
        manager.submit(b'bounded memory')
        state=wait_for(manager,lambda s:s['latest']['state']=='error')
        assert '메모리 사용량' in state['latest']['result']['error']
        assert state['latest']['observedPeakResidentMemoryBytes']>32*1024*1024
        if sys.platform=='win32':
            assert state['latest']['observedPeakWorkingSetBytes']>32*1024*1024
        else:
            assert state['latest']['observedPeakWorkingSetBytes'] is None
    finally:manager.close()


def test_completed_nested_output_over_budget_keeps_previous_preview(tmp_path):
    script=tmp_path/'fast_output_worker.py'
    script.write_text('''import json,sys
from pathlib import Path
job=json.loads(Path(sys.argv[-1]).read_text(encoding='utf8'))
if Path(job['input']).read_bytes()==b'large':
    out=Path(job['output'])/'nested';out.mkdir(parents=True)
    (out/'p0.png').write_bytes(b'x'*100)
Path(job['result']).write_text(json.dumps({'ok':True,'status':'supported','pages':0}),encoding='utf8')
''',encoding='utf8')
    manager=JobManager(tmp_path/'jobs',output_limit=50,command=[worker_python,str(script)])
    try:
        first=manager.submit(b'valid')
        wait_for(manager,lambda s:s['latest']['state']=='ready')
        manager.submit(b'large')
        state=wait_for(manager,lambda s:s['latest']['state']=='error')
        assert '결과 크기' in state['latest']['result']['error']
        assert state['displayed']==first
    finally:manager.close()


def test_failed_exit_cannot_publish_success_receipt(tmp_path):
    command=worker(tmp_path,0)
    with Path(command[1]).open('a',encoding='utf8') as script:
        script.write('sys.exit(7)\n')
    manager=JobManager(tmp_path/'jobs',command=command)
    try:
        manager.submit(b'failed worker')
        state=wait_for(manager,lambda s:s['latest']['state']=='error')
        assert state['displayed'] is None
        assert '정상적으로 종료' in state['latest']['result']['error']
    finally:manager.close()
