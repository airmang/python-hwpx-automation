# SPDX-License-Identifier: Apache-2.0
"""Token-protected loopback viewer; document bytes never sent to an operator."""
import base64,json,secrets,tempfile,threading,webbrowser
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from .jobs import JobManager,FileWatcher
from .render import MAX_INPUT_BYTES

def serve(*,watch=None,font_substitutions=None,font_directory=None,dpi=300,open_browser=True,ready_file=None):
    token=secrets.token_urlsafe(32)
    temp=tempfile.TemporaryDirectory(prefix='hwpx-preview-')
    manager=JobManager(Path(temp.name)/'jobs',font_directory=font_directory)
    watcher=FileWatcher(watch,manager,font_substitutions=font_substitutions,dpi=dpi) if watch else None
    page=Path(__file__).with_name('viewer.html').read_bytes()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def reply(self,status,data,content_type='application/json'):
            if not isinstance(data,bytes):data=json.dumps(data,ensure_ascii=False).encode('utf8')
            self.send_response(status);self.send_header('Content-Type',content_type);self.send_header('Content-Length',str(len(data)))
            self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src 'self' blob:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
            self.end_headers();self.wfile.write(data)
        def authorized(self):
            origin=self.headers.get('Origin')
            return self.headers.get('X-Preview-Token')==token and (origin is None or origin==base_url)
        def do_GET(self):
            if self.headers.get('Host')!=base_url.removeprefix('http://'):self.reply(403,dict(error='Invalid host'));return
            path=urlparse(self.path).path
            if path=='/':self.reply(200,page,'text/html; charset=utf-8');return
            if not self.authorized():self.reply(403,dict(error='Unauthorized'));return
            if path=='/api/status':
                state: dict[str, Any] = manager.snapshot();state.update(watching=Path(watch).name if watch else None,watchError=watcher.error if watcher else None)
                self.reply(200,state);return
            parts=path.split('/')
            if len(parts)==5 and parts[:3]==['','api','pages'] and parts[3].isdigit():
                job_id=int(parts[3]);filename=parts[4]
                if filename.startswith('p') and filename.endswith('.png') and filename[1:-4].isdigit():
                    with manager.lock:
                        job=manager.jobs.get(job_id)
                        file=manager.root/str(job_id)/'output'/filename
                        if job and job['state']=='ready' and file.is_file():self.reply(200,file.read_bytes(),'image/png');return
            self.reply(404,dict(error='Not found'))
        def do_POST(self):
            if self.headers.get('Host')!=base_url.removeprefix('http://') or not self.authorized():self.reply(403,dict(error='Unauthorized'));return
            path=urlparse(self.path).path
            try:
                size=int(self.headers.get('Content-Length','-1'))
                if size<0 or size>MAX_INPUT_BYTES:self.reply(413,dict(error='입력 크기 한도는 32 MiB입니다.'));return
                data=self.rfile.read(size)
                if len(data)!=size:raise ValueError('파일 전송이 완료되지 않았습니다.')
                if path=='/api/render':
                    label=self.headers.get('X-Preview-Name','HWPX')
                    label=base64.urlsafe_b64decode(label).decode('utf8') if label!='HWPX' else label
                    encoded=self.headers.get('X-Preview-Fonts')
                    mapping=json.loads(base64.urlsafe_b64decode(encoded).decode('utf8')) if encoded else {}
                    job_id=manager.submit(data,label=label,font_substitutions=mapping,dpi=dpi)
                    self.reply(202,dict(id=job_id));return
                if path=='/api/cancel':self.reply(200,manager.cancel());return
                if path=='/api/shutdown':
                    self.reply(200,dict(ok=True));threading.Thread(target=server.shutdown,daemon=True).start();return
                self.reply(404,dict(error='Not found'))
            except (ValueError,UnicodeError,json.JSONDecodeError) as exc:self.reply(400,dict(error=str(exc)))
            except Exception:self.reply(500,dict(error='처리를 시작하지 못했습니다.'))
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);server.daemon_threads=True
    base_url=f'http://127.0.0.1:{server.server_port}';url=base_url+'/#'+token
    if ready_file:Path(ready_file).write_text(json.dumps(dict(url=url,port=server.server_port),indent=2),encoding='utf8')
    if open_browser:webbrowser.open(url)
    import sys
    if sys.stdout is not None:print('HWPX preview listening on loopback.',flush=True)
    try:server.serve_forever(poll_interval=.2)
    finally:
        server.server_close()
        if watcher:watcher.close()
        manager.close();temp.cleanup()
