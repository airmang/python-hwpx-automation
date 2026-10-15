from hwpx_automation.preview_runtime.memory import macos_resident_bytes
from hwpx_automation.preview_runtime.jobs import JobManager
from test_native_preview_jobs import wait_for, worker
from types import SimpleNamespace
import pytest, subprocess


def test_macos_rss_uses_owned_pid_and_converts_kib_to_bytes(monkeypatch):
    calls=[]
    def run(argv, **kwargs):
        calls.append((argv,kwargs))
        return SimpleNamespace(returncode=0,stdout=b'  65536\n')
    monkeypatch.setattr('hwpx_automation.preview_runtime.memory.subprocess.run',run)
    assert macos_resident_bytes(1234)==64*1024*1024
    assert calls[0][0]==['/bin/ps','-p','1234','-o','rss=']
    assert calls[0][1]['timeout']==.5
    assert 'shell' not in calls[0][1]
    with pytest.raises(ValueError):macos_resident_bytes('1234; other-command')


@pytest.mark.parametrize('status,output',[(1,b''),(0,b''),(0,b'RSS\n123'),(0,b'12\n13'),(0,b'-1')])
def test_unavailable_rss_is_not_reported_as_zero(monkeypatch,status,output):
    monkeypatch.setattr('hwpx_automation.preview_runtime.memory.subprocess.run',lambda *a,**k:SimpleNamespace(returncode=status,stdout=output))
    assert macos_resident_bytes(1234) is None


def test_stalled_ps_query_has_a_bounded_timeout(monkeypatch):
    def fail(*a,**k):raise subprocess.TimeoutExpired(a[0],k['timeout'])
    monkeypatch.setattr('hwpx_automation.preview_runtime.memory.subprocess.run',fail)
    assert macos_resident_bytes(1234) is None


def test_rss_budget_terminates_owned_renderer_worker(tmp_path,monkeypatch):
    monkeypatch.setattr('hwpx_automation.preview_runtime.memory.subprocess.run',lambda *a,**k:SimpleNamespace(returncode=0,stdout=b'65536\n'))
    monkeypatch.setattr('hwpx_automation.preview_runtime.jobs.sys.platform','darwin')
    manager=JobManager(tmp_path/'jobs',command=worker(tmp_path,10),memory_limit=32*1024*1024)
    try:
        manager.submit(b'bounded macOS RSS contract')
        state=wait_for(manager,lambda s:s['latest']['state']=='error')
        assert '메모리 사용량' in state['latest']['result']['error']
        assert state['latest']['observedPeakResidentMemoryBytes']==64*1024*1024
        assert state['latest']['observedPeakWorkingSetBytes'] is None
        assert state['latest']['memoryMeasurementKind']=='rss'
    finally:manager.close()
    assert manager.process is None


def test_macos_monitor_failure_stops_worker_and_preserves_last_page(tmp_path,monkeypatch):
    monkeypatch.setattr('hwpx_automation.preview_runtime.jobs.sys.platform','darwin')
    monkeypatch.setattr('hwpx_automation.preview_runtime.memory.subprocess.run',lambda *a,**k:SimpleNamespace(returncode=0,stdout=b'1\n'))
    manager=JobManager(tmp_path/'jobs',command=worker(tmp_path,.05))
    try:
        first=manager.submit(b'completed page')
        wait_for(manager,lambda s:s['latest']['state']=='ready')
        manager.command=worker(tmp_path,10)
        monkeypatch.setattr('hwpx_automation.preview_runtime.memory.subprocess.run',lambda *a,**k:SimpleNamespace(returncode=1,stdout=b''))
        manager.submit(b'memory monitor unavailable')
        state=wait_for(manager,lambda s:s['latest']['state']=='error')
        assert '확인할 수 없어' in state['latest']['result']['error']
        assert state['displayed']==first
        assert state['displayedJob']['result']['ok']
    finally:manager.close()
    assert manager.process is None
