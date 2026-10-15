# SPDX-License-Identifier: Apache-2.0
"""Frozen-executable entry point; no separately installed Python required."""
import argparse,json,sys,os
from pathlib import Path
from .render import render_bytes


def configure_renderer_defaults():
    # The private Windows evaluation bundle uses the retained-corpus-tested
    # adapters. Preserve explicit baseline overrides and other OS recipes.
    if getattr(sys,'frozen',False) and sys.platform=='win32':
        os.environ.setdefault('HWPX_PREVIEW_NATIVE_TABLE_BORDERS','1')
        os.environ.setdefault('HWPX_PREVIEW_NATIVE_PICTURE_CROP','1')

def main():
    configure_renderer_defaults()
    parser=argparse.ArgumentParser(description='로컬 HWPX 미리보기')
    parser.add_argument('--render',type=Path);parser.add_argument('--out',type=Path)
    parser.add_argument('--font-map',type=Path);parser.add_argument('--font-directory',type=Path)
    parser.add_argument('--dpi',type=int,default=300);parser.add_argument('--worker',type=Path)
    parser.add_argument('--watch',type=Path);parser.add_argument('--no-browser',action='store_true');parser.add_argument('--ready-file',type=Path)
    args=parser.parse_args()
    if args.worker:
        job=json.loads(args.worker.read_text(encoding='utf8'))
        try:
            status=render_bytes(Path(job['input']).read_bytes(),job['output'],font_substitutions=job.get('fontSubstitutions'),
                                font_directory=job.get('fontDirectory'),dpi=job.get('dpi',300),label=job.get('label','HWPX'))
            result=dict(ok=True,**status)
        except Exception as exc:result=dict(ok=False,status='error',error=str(exc),errorType=type(exc).__name__)
        Path(job['result']).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
        return 0 if result['ok'] else 1
    mapping=json.loads(args.font_map.read_text(encoding='utf8')) if args.font_map else {}
    if not args.render:
        from .server import serve
        serve(watch=args.watch,font_substitutions=mapping,font_directory=args.font_directory,dpi=args.dpi,
              open_browser=not args.no_browser,ready_file=args.ready_file)
        return 0
    if not args.out:parser.error('--render에는 --out 새결과폴더가 필요합니다.')
    result=render_bytes(args.render.read_bytes(),args.out,font_substitutions=mapping,font_directory=args.font_directory,
                        dpi=args.dpi,label=args.render.name)
    if sys.stdout is not None:print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0 if result['status']=='supported' else 2

if __name__=='__main__':
    try:sys.exit(main())
    except Exception as exc:
        if sys.stderr is not None:print(str(exc),file=sys.stderr)
        sys.exit(1)
