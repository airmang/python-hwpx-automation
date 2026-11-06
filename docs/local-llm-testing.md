# 로컬 LLM(Ollama)으로 시험하기 — `test/local-llm` 브랜치

이 브랜치는 발행 전 시험용이다. 두 저장소의 `test/local-llm` 브랜치를 함께 설치한다.

- `python-hwpx` `test/local-llm`: `doc.text.outline/apply_changes`(#666~#668) + Markdown 가져오기(#669)
- `python-hwpx-automation` `test/local-llm`: `--profile minimal` 도구 6개·글 나눠 보내기(#198·#199) + read_extract 수리(#197)

## 1. 준비물

- Python 3.12와 [uv](https://docs.astral.sh/uv/)
- [Ollama](https://ollama.com)와 도구 호출을 지원하는 모델(목록: <https://ollama.com/search?c=tools>)
- Ollama용 MCP 클라이언트. 아래는 `ollmcp`(mcp-client-for-ollama) 기준이다.

## 2. 설치

```bash
uv venv -p 3.12 hwpx-llm
uv pip install -p hwpx-llm "python-hwpx @ git+https://github.com/airmang/python-hwpx@test/local-llm" "python-hwpx-automation[mcp] @ git+https://github.com/airmang/python-hwpx-automation@test/local-llm"
```

서버 실행 파일 위치:

- macOS·Linux: `hwpx-llm/bin/hwpx-automation-mcp`
- Windows: `hwpx-llm\Scripts\hwpx-automation-mcp.exe`

브랜치가 갱신되면 같은 명령에 `--reinstall`을 붙여 다시 설치한다.

## 3. 모델 없이 먼저 확인

이 저장소를 받아 둔 경우:

```bash
hwpx-llm/bin/python scripts/minimal_profile_smoke.py hwpx-llm/bin/hwpx-automation-mcp ./smoke-work
```

마지막 줄이 `SMOKE PASS`면 서버 쪽은 정상이다.

## 4. Ollama에 붙이기

`servers.json`(경로는 절대 경로로):

```json
{
  "mcpServers": {
    "hwpx": {
      "command": "/절대/경로/hwpx-llm/bin/hwpx-automation-mcp",
      "args": ["--profile", "minimal"]
    }
  }
}
```

```bash
uv tool install ollmcp
ollmcp -j servers.json -m qwen3.5
```

`-m`에는 받아 둔 모델 이름을, Ollama가 다른 주소면 `-H http://주소:11434`를 준다.
`--profile minimal` 대신 `"env": {"HWPX_AUTOMATION_PROFILE": "minimal"}`도 된다.

## 5. 시험해 볼 일

1. **양식 읽기**: "`C:/…/양식.hwpx` 내용 보여줘" → `read_outline`이 `[id] 위치: 글` 목록을 돌려주는지, 길면 `nextAfter`로 이어 읽는지.
2. **칸 채우기**: "표의 성명 칸에 홍길동, 날짜 칸에 오늘 날짜 넣어줘" → `apply_text_changes`가 한 번에 여러 id를 바꾸고 `원본.edited.hwpx`로 저장하는지. `overflow`가 나오면 그 칸에 글이 넘칠 수 있다는 뜻이다.
3. **새 문서 만들기**: "현장체험학습 가정통신문 만들어줘(표 포함, 1000자 이상)" → 모델이 `stage_text`로 나눠 보낸 뒤 `create_from_markdown(draft_id=…)`를 부르는지, 긴 글을 한 번에 넣다 깨지지 않는지.
4. **찾아 바꾸기**: "문서의 2025를 2026으로 바꿔줘" → `replace_text`.
5. 결과 파일을 한/글로 열어 모양을 확인한다.

## 6. 알려 줄 것

잘 안 되면 아래를 적어 이슈나 메시지로 보낸다.

- 모델 이름·크기, 컨텍스트 길이(`num_ctx`)
- 시킨 말, 모델이 부른 도구와 인자, 돌아온 결과(`error.code`)
- 모델이 헤맨 지점: 도구를 잘못 고름 / 인자 JSON이 깨짐 / id를 지어냄 / 결과를 잘못 읽음
- 한/글에서 연 결과 화면(문제가 있으면)
