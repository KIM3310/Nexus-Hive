# Nexus-Hive Service-Grade SPECKIT

Last updated: 2026-03-08

## S - Scope
- 대상: multi-agent federated BI copilot
- baseline 목표: SQL safety, streaming UX, agent orchestration을 서비스 수준으로 고정

## P - Product Thesis
- Nexus-Hive는 flashy dashboard가 아니라 `exec-grade BI copilot`이어야 한다.
- 질문 -> SQL -> execution -> visualization -> guardrail 흐름이 명확해야 한다.

## E - Execution
- runtime meta, health, ask endpoint를 핵심 contract로 유지
- SQL safety 및 streaming flow를 테스트로 계속 고정
- 이번 baseline에서 Python CI를 추가해 repo 신뢰도를 맞춤

## C - Criteria
- `pytest -q tests` green
- README 첫 부분에서 multi-agent BI 가치와 safety posture가 이해됨
- `/health`, `/api/meta`, `/api/ask` contract가 유지됨

## K - Keep
- stateful multi-agent narrative
- SQL safety 강조

## I - Improve
- sample dashboard captures와 query pack 강화
- warehouse scale story 및 retry trace 문서 추가

## T - Trace
- `README.md`
- `main.py`
- `tests/`
- `.github/workflows/ci.yml`

