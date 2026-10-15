# SPDX-License-Identifier: Apache-2.0
"""Latest-revision local rendering in a cancellable, bounded child process."""
import json,hashlib,os,subprocess,sys,threading,time,shutil
from pathlib import Path
from .render import MAX_INPUT_BYTES
from .memory import resident_bytes

class JobManager:
    def __init__(self,root,*,font_directory=None,timeout=120,memory_limit=768*1024*1024,output_limit=512*1024*1024,command=None):
        self.root=Path(root).resolve();self.root.mkdir(parents=True,exist_ok=True)
        self.font_directory=str(font_directory) if font_directory else None
        self.timeout=timeout;self.memory_limit=memory_limit;self.output_limit=output_limit
        if command is None and not getattr(sys,'frozen',False) and sys.platform=='win32' and getattr(sys,'_base_executable',sys.executable)!=sys.executable:
            raise ValueError('Windows watch mode requires the frozen preview runtime; a venv redirector cannot enforce worker memory limits.')
        self.command=command or ([sys.executable] if getattr(sys,'frozen',False) else [sys.executable,'-m','hwpx_automation.preview_runtime.launcher'])
        self.child_env=os.environ.copy()
        if getattr(sys,'frozen',False):
            self.child_env.pop('PYTHONPATH',None);self.child_env.pop('PYTHONHOME',None)
        self.lock=threading.RLock();self.changed=threading.Event();self.closed=False
        self.jobs={};self.latest=0;self.displayed=None;self.process=None
        self.thread=threading.Thread(target=self._loop,daemon=True);self.thread.start()

    def submit(self,data,*,label='HWPX',font_substitutions=None,dpi=300):
        if len(data)>MAX_INPUT_BYTES:raise ValueError('입력 파일은 32 MiB 이하여야 합니다.')
        if not isinstance(label,str) or len(label)>256:raise ValueError('파일 이름이 너무 깁니다.')
        mapping={} if font_substitutions is None else font_substitutions
        if not isinstance(mapping,dict) or len(mapping)>32 or any(not isinstance(k,str) or not isinstance(v,str) or len(k)>128 or len(v)>128 for k,v in mapping.items()):
            raise ValueError('글꼴 대체는 이름과 이름의 대응이어야 합니다.')
        if dpi not in {144,300}:raise ValueError('지원 해상도는 144 또는 300 dpi입니다.')
        with self.lock:
            if self.closed:raise RuntimeError('미리보기 실행기가 종료되었습니다.')
            previous=self.jobs.get(self.latest)
            if previous and previous['state'] in {'queued','running'}:previous['state']='superseded'
            if self.process and self.process.poll() is None:self.process.terminate()
            self.latest+=1;job_id=self.latest;folder=self.root/str(job_id);folder.mkdir()
            (folder/'input.hwpx').write_bytes(data)
            spec=dict(input=str(folder/'input.hwpx'),output=str(folder/'output'),result=str(folder/'result.json'),
                      label=label,fontSubstitutions=mapping,fontDirectory=self.font_directory,dpi=dpi)
            (folder/'job.json').write_text(json.dumps(spec,ensure_ascii=False),encoding='utf8')
            self.jobs[job_id]=dict(id=job_id,state='queued',label=label,inputSha256=hashlib.sha256(data).hexdigest(),
                                  fontSubstitutions=mapping,submitted=time.time())
            self.changed.set();return job_id

    def cancel(self,job_id=None):
        with self.lock:
            job_id=self.latest if job_id is None else job_id;job=self.jobs.get(job_id)
            if job and job['state'] in {'queued','running'}:
                job['state']='cancelled'
                if job_id==self.latest and self.process and self.process.poll() is None:self.process.terminate()
            return self.snapshot()

    def snapshot(self):
        with self.lock:
            job=self.jobs.get(self.latest)
            displayed=self.jobs.get(self.displayed)
            return dict(latest=dict(job) if job else None,displayed=self.displayed,
                        displayedJob=dict(displayed) if displayed else None,closed=self.closed)

    def _memory(self,proc):
        return resident_bytes(proc)

    def _output_bytes(self, folder):
        return sum(p.stat().st_size for p in (folder/'output').rglob('*') if p.is_file())

    def _loop(self):
        while True:
            self.changed.wait(.25);self.changed.clear()
            with self.lock:
                if self.closed:return
                job=self.jobs.get(self.latest)
                if not job or job['state']!='queued':continue
                job['state']='running';job_id=job['id'];folder=self.root/str(job_id)
            error=None;peak=0;started=time.monotonic();proc=None;last_disk_check=0
            last_memory_check=0;memory=None;last_memory_success=started
            memory_interval=.5 if sys.platform=='darwin' else .05
            try:
                with (folder/'worker.log').open('w',encoding='utf8') as log:
                    with self.lock:
                        if job['state']!='running':continue
                        proc=subprocess.Popen(self.command+['--worker',str(folder/'job.json')],stdout=log,stderr=subprocess.STDOUT,
                                              env=self.child_env,
                                              creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
                        self.process=proc
                    while proc.poll() is None:
                        with self.lock:
                            invalid=self.closed or self.latest!=job_id or job['state']!='running'
                        if invalid:proc.terminate();break
                        now=time.monotonic()
                        if now-last_memory_check>=memory_interval:
                            last_memory_check=now;memory=self._memory(proc)
                            if memory is not None:last_memory_success=time.monotonic()
                            peak=max(peak,memory or 0)
                        if sys.platform=='darwin' and now-last_memory_success>2:
                            error='메모리 사용량을 확인할 수 없어 처리를 중단했습니다.';proc.terminate();break
                        if time.monotonic()-started>self.timeout:error='처리 시간이 실행 한도를 넘었습니다.';proc.terminate();break
                        if memory and memory>self.memory_limit:error='메모리 사용량이 실행 한도를 넘었습니다.';proc.terminate();break
                        if time.monotonic()-last_disk_check>.5:
                            last_disk_check=time.monotonic()
                            output_bytes=self._output_bytes(folder)
                            if output_bytes>self.output_limit:error='미리보기 결과 크기가 실행 한도를 넘었습니다.';proc.terminate();break
                        time.sleep(.05)
                    proc.wait(timeout=5)
                # A fast worker can finish between polling intervals. Enforce
                # the same budget before accepting its completed output.
                if not error and self._output_bytes(folder)>self.output_limit:
                    error='미리보기 결과 크기가 실행 한도를 넘었습니다.'
                result_path=folder/'result.json'
                result=json.loads(result_path.read_text(encoding='utf8')) if result_path.is_file() else dict(ok=False,error=error or '렌더러가 결과를 반환하지 않았습니다.')
                if error:result=dict(ok=False,error=error)
                elif proc.returncode!=0:result=dict(ok=False,error='렌더러가 정상적으로 종료되지 않았습니다.')
            except Exception as exc:
                result=dict(ok=False,error=str(exc))
                if proc and proc.poll() is None:proc.kill();proc.wait(timeout=5)
            with self.lock:
                if self.process is proc:self.process=None
                job.update(elapsedSeconds=round(time.monotonic()-started,3),
                           observedPeakWorkingSetBytes=peak if sys.platform=='win32' else None,
                           observedPeakResidentMemoryBytes=peak,
                           memoryMeasurementKind='working-set' if sys.platform=='win32' else 'rss' if sys.platform=='darwin' else 'unavailable')
                if self.latest!=job_id or job['state']!='running':continue
                job['result']=result;job['state']='ready' if result.get('ok') else 'error'
                if result.get('ok') and result.get('status')=='supported':self.displayed=job_id
                for old_id in sorted(self.jobs)[:-8]:
                    if old_id in {self.latest,self.displayed}:continue
                    target=(self.root/str(old_id)).resolve()
                    if target.parent!=self.root:raise RuntimeError('job cleanup escaped its owned root')
                    shutil.rmtree(target);del self.jobs[old_id]

    def close(self):
        with self.lock:
            self.closed=True
            if self.process and self.process.poll() is None:self.process.terminate()
            self.changed.set()
        self.thread.join(timeout=10)

class FileWatcher:
    def __init__(self,path,manager,*,font_substitutions=None,dpi=300):
        self.path=Path(path).resolve();self.manager=manager;self.mapping=font_substitutions;self.dpi=dpi
        self.stopped=threading.Event();self.error=None;self.last_hash=None
        self.thread=threading.Thread(target=self._loop,daemon=True);self.thread.start()
    def _loop(self):
        candidate=None;seen_at=0
        while not self.stopped.wait(.25):
            try:
                info=self.path.stat();signature=(info.st_size,info.st_mtime_ns)
                if signature!=candidate:candidate=signature;seen_at=time.monotonic();continue
                if time.monotonic()-seen_at<.5:continue
                if info.st_size>MAX_INPUT_BYTES:raise ValueError('입력 파일이 32 MiB를 넘습니다.')
                data=self.path.read_bytes();after=self.path.stat()
                if (after.st_size,after.st_mtime_ns)!=signature:continue
                digest=hashlib.sha256(data).hexdigest()
                if digest!=self.last_hash:
                    self.manager.submit(data,label=self.path.name,font_substitutions=self.mapping,dpi=self.dpi);self.last_hash=digest
                self.error=None
            except Exception as exc:self.error=str(exc)
    def close(self):self.stopped.set();self.thread.join(timeout=2)
