# 합성 fixture 블라인드 실무 평가

S-070의 공개 benchmark는 실사용 대체율을 주장하는 시험이 아니라, 설치 표면·익명화·판정·집계
계약을 재현하는 qualification fixture다. 기준 manifest는
`examples/s070_fixture_benchmark/manifest.json`이다.

1. `run_fixture_benchmark(manifest_path, output_dir, strict=true)`로 72개 합성 work order와 세 개의
   versioned fixture client profile을 동일한 `server-enforced-workflow.v1` 계약에 태운다.
2. 판정자는 `blind/artifact-*.json`만 받는다. `private-routing.json`은 판정자에게 전달하지 않는다.
3. `judge-templates/judge-a.json`과 `judge-b.json`은 서로 독립적으로 호출된 두 `agent_judge`가
   채우기 위한 빈 서식이다. 같은 실행이 두 역할을 흉내 내거나 사람 라벨을 만들면 안 된다.
4. 두 판정 패스가 실제로 채워지기 전 result 상태는
   `awaiting_two_independent_agent_judge_passes`이며 점수는 `null`이다.
5. `export_fixture_benchmark(result_manifest_path, output_dir, strict=true)`로 report/gallery/scorecard
   projection을 만든다. 모두 같은 result manifest 해시를 가리켜야 한다.

고정 경계: `humanLabels=false`, `humanControls=false`, `humanJudges=false`,
`realAgentClients=false`, `realAgentClientsVerified=false`, `realHancomVerified=false`,
`replacementClaimAllowed=false`. 합성 profile 세 개는 서로 다른 실제 에이전트를 의미하지 않는다.
실제 인간 대조군·인간 판정·세 실제 agent client·실한컴은 후속 외부 검증 전까지 미검증이다.
