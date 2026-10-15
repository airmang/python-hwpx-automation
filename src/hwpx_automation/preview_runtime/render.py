# SPDX-License-Identifier: Apache-2.0
"""Bounded local bytes-to-preview API; never initializes an external oracle."""
import hashlib,html,io,json,zipfile,time
from pathlib import Path
from .backend import Backend
from .fonts import font_resources

MAX_INPUT_BYTES=32*1024*1024
MAX_EXPANDED_BYTES=128*1024*1024
MAX_PAGES=256

def check_input(data):
    if len(data)>MAX_INPUT_BYTES:raise ValueError('입력 파일은 32 MiB 이하여야 합니다.')
    try:archive=zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ValueError('파일 저장이 아직 끝나지 않았거나 올바른 HWPX 파일이 아닙니다.') from exc
    with archive:
        entries=archive.infolist()
        if len(entries)>4096 or sum(i.file_size for i in entries)>MAX_EXPANDED_BYTES:
            raise ValueError('압축을 푼 문서 크기가 실행 한도를 넘습니다.')
        if any(i.flag_bits&1 for i in entries):raise ValueError('암호화된 문서는 지원하지 않습니다.')
        if len({i.filename for i in entries})!=len(entries):raise ValueError('중복 ZIP 항목이 있습니다.')
        if 'Contents/section0.xml' not in archive.namelist():raise ValueError('HWPX 문서 구조를 찾을 수 없습니다.')

def render_bytes(data,out,*,font_substitutions=None,font_directory=None,dpi=300,label='HWPX'):
    try:
        from hwpx.layout.object_scene import build_document_scene  # pyright: ignore[reportMissingImports] -- coordinated core scene feature
    except ImportError as exc:
        raise RuntimeError('Native preview requires a core build with hwpx.layout.object_scene support.') from exc
    if dpi not in {144,300}:raise ValueError('지원 해상도는 144 또는 300 dpi입니다.')
    if font_substitutions is not None and not isinstance(font_substitutions,dict):raise ValueError('글꼴 대체는 이름과 이름의 대응이어야 합니다.')
    check_input(data);started=time.monotonic();out=Path(out);out.mkdir(parents=True,exist_ok=False)
    registry=font_resources(font_directory)
    backend=Backend(font_files=registry,font_substitutions=font_substitutions)
    scene=build_document_scene(data,backend)
    if len(scene['pages'])>MAX_PAGES:raise ValueError('문서가 256쪽 실행 한도를 넘습니다.')
    if scene['status']=='supported':backend.draw(scene,out,dpi)
    scene_path=out/'scene.json';scene_path.write_text(json.dumps(scene,ensure_ascii=False),encoding='utf8')
    status=dict(status=scene['status'],pages=len(scene['pages']),unsupported=scene['unsupported'],errors=scene['errors'],
                inputSha256=hashlib.sha256(data).hexdigest(),elapsedSeconds=round(time.monotonic()-started,3),
                fonts=backend.manifest(),qualityValidated=scene.get('qualityValidated',False),dpi=dpi,
                network='No outbound network code in renderer. Host AI services are separate.',sourceWritten=False)
    (out/'status.json').write_text(json.dumps(status,ensure_ascii=False,indent=2),encoding='utf8')
    unsupported=''.join('<li>'+html.escape(str(item))+'</li>' for item in scene['unsupported']+scene['errors'])
    images=''.join(f'<figure><figcaption>{i+1} / {len(scene["pages"])}</figcaption><img width="{round(page["size"]["width"]*dpi/7200)}" height="{round(page["size"]["height"]*dpi/7200)}" loading="lazy" src="p{i}.png" alt="{i+1}쪽"></figure>' for i,page in enumerate(scene['pages'])) if scene['status']=='supported' else '<h2>이 문서의 서식은 아직 지원하지 않습니다.</h2><ul>'+unsupported+'</ul>'
    substitutions=html.escape(json.dumps(font_substitutions or {},ensure_ascii=False))
    content='''<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src 'self' data:; style-src 'unsafe-inline'">
<title>HWPX 미리보기</title><style>body{margin:0;background:#edf0f3;color:#20252b;font:15px system-ui}header{padding:18px 24px;background:white;border-bottom:1px solid #d9dde2}h1{margin:0 0 8px;font-size:20px}small{color:#606974}main{max-width:1000px;margin:24px auto}figure{margin:24px 16px}figcaption{margin:8px 0;color:#606974}img{width:100%;height:auto;box-shadow:0 3px 12px #0002}</style>
<header><h1>'''+html.escape(label)+'''</h1><small>로컬 미리보기 · 글꼴 대체: '''+substitutions+''' · 지원 범위 내 렌더링, 모든 문서의 정확도를 보증하지 않음</small></header><main>'''+images+'</main></html>'
    (out/'preview.html').write_text(content,encoding='utf8')
    return status
