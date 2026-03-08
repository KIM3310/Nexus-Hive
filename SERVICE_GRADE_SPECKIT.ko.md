# Nexus-Hive Service-Grade SPECKIT

Last updated: 2026-03-08

## S - Scope
- 대상: multi-agent federated BI copilot
- 이번 iteration 목표: reviewer가 첫 화면과 API surface만 봐도 `질문 -> SQL -> 실행 -> 시각화 -> 검토` 계약을 이해하게 만들고, 이를 executive review pack으로 고정한다.

## P - Product Thesis
- Nexus-Hive는 단순한 text-to-SQL demo가 아니라 `exec-facing analytics runtime`이어야 한다.
- 화려한 차트보다 먼저, 답변 구조와 agent 책임 경계를 보여줘야 신뢰가 생긴다.

## E - Execution
- `/api/runtime/brief`로 runtime posture, retry budget, review flow, watchouts를 고정한다.
- `/api/review-pack`으로 executive promises, trust boundary, review routes를 분리한다.
- `/api/schema/answer`로 SQL, chart payload, result preview, agent trace를 포함한 답변 contract를 고정한다.
- landing UI에 runtime brief panel과 review pack panel을 올려 질문 전에 reviewer posture를 확인하게 만든다.
- `/health`, `/api/meta`, `/api/ask`에도 같은 contract 링크를 연결해 surface 간 의미를 맞춘다.

## C - Criteria
- `pytest -q tests` green
- `python3 -m compileall -q .` green
- `node --check frontend/app.js` green
- `/health`, `/api/meta`, `/api/runtime/brief`, `/api/review-pack`, `/api/schema/answer` contract가 일관된다.
- 첫 화면에서 answer schema, model, warehouse readiness, review flow, executive promises가 즉시 보인다.

## K - Keep
- stateful multi-agent narrative
- SQL safety와 read-only executor posture
- streamed trace를 중심으로 한 reviewer workflow

## I - Improve
- benchmark query pack과 expected answers를 추가해 deterministic demo story를 강화
- seeded warehouse provenance와 chart quality rubric을 별도 문서로 분리
- stream trace export와 screenshot evidence를 릴리스 체크리스트에 넣기

## T - Trace
- `main.py`
- `frontend/index.html`
- `frontend/app.js`
- `frontend/style.css`
- `tests/test_runtime_endpoints.py`
- `README.md`
