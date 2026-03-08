# Nexus-Hive Governed Analytics Flagship Spec

작성일: 2026-03-08

이 문서는 `Nexus-Hive`를 단순 BI copilot이 아니라 `governed analytics flagship`으로 끌어올리기 위한 기술 spec이다.

## 목표

자연어 질문 -> SQL 생성 -> 안전한 실행 -> 시각화라는 현재 흐름 위에,
데이터 플랫폼과 운영 소프트웨어에서 중요한 증거를 추가한다.

핵심은 아래 네 가지다.

1. warehouse / lakehouse style data modeling
2. governed NL2SQL evaluation
3. data quality + lineage + security posture
4. reviewable operator workflow

## 현재 강점

- 자연어 -> SQL -> 차트라는 흐름이 이미 있다
- read-only audit enforcement가 있다
- agent trace / runtime brief / review pack surface가 있다

## 아직 부족한 것

- medallion or semantic modeling narrative
- warehouse adapter contract
- query audit history with reviewer-friendly storage
- row/column security simulation
- freshness / lineage / quality status
- gold query set 기반 NL2SQL evaluation
- cost / latency / explainability proof

## Phase 1: Data Platform Core

- `warehouse adapters`
  - local SQLite demo adapter
  - cloud warehouse adapter contract
  - lakehouse SQL adapter contract
- `data contracts`
  - source -> modeled tables relationship
  - freshness / owner / SLA metadata
- `quality gate`
  - schema mismatch
  - null/range checks
  - broken join / orphan detection

## Phase 2: Governed Querying

- `query audit log`
  - question
  - generated SQL
  - approval state
  - execution time
  - row count
- `policy simulation`
  - masked columns
  - role-based access examples
  - denied query examples
- `gold eval pack`
  - canonical business questions
  - expected SQL characteristics
  - pass/fail scoring

## Phase 3: Reviewer Surfaces

- `GET /api/schema/query-audit`
- `GET /api/schema/lineage`
- `GET /api/runtime/warehouse-brief`
- `GET /api/review-pack/data-platform`
- landing screen cards for:
  - warehouse mode
  - lineage status
  - quality gate verdict
  - policy examples

## Proof assets to produce

- one architecture diagram
- one lineage screenshot
- one audited SQL trace screenshot
- one quality-gate report screenshot
- one benchmark/eval screenshot

## Guardrails

- do not claim production integrations unless actually wired
- do not hide SQL under a magic demo
- do not add more agents if the governance layer is still thin

## Success condition

리뷰어가 `README + first screen + review pack + screenshot set`만 보고도 아래를 이해할 수 있어야 한다.

- 이 시스템은 데이터 플랫폼 언어를 안다
- NL2SQL을 운영 관점으로 다룬다
- governance / audit / lineage / quality를 함께 생각한다
- object workflow와 operator review까지 확장할 감각이 있다
