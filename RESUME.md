# 작업 재개 지점

**2026-11-06 기준.** 공용 `short` 종료 처리(SHORT-CLOSE)는 제품에 통합됐다(`df447d8`).
전체 제품 로드맵은 아직 끝나지 않았다. 이번에 새로 연 공정은 [INTENT.md](INTENT.md)에 따른
Beads 기반 공정 관리 전환(GRAPH-OPS)이다. 첫 범위는 Phase 0 현황 점검과 Phase 1 격리 시험이다.
현재 승인 범위와 활성 Epic은 [공정표](DELIVERY.md)에만 기록한다. 이 문서에는 재개 순서만 둔다.

## 재개 순서

1. 루트 [AGENTS.md](AGENTS.md)와 작업할 디렉터리의 AGENTS.md를 읽는다. 코디네이터라면
   [COORDINATOR.md](COORDINATOR.md)도 읽는다.
2. [공정표](DELIVERY.md)의 승인 기준점과 활성 Epic 표를 확인한다. Beads 이관 뒤에는
   `bd ready --json`으로 실행 가능한 작업을 확인한다.
3. 실제 상태를 대조한다: `git status --short`, 현재 브랜치와 원격 SHA, 살아 있는 Herdr 세션,
   작업 worktree의 변경, 진행 중인 네이티브 프로세스, 슬롯 상태(`idle232`).
   세션이 끝났다는 이유로 작업을 처음부터 다시 시작하지 않는다. 살아 있는 실행은 중복으로 시작하지 않는다.
4. 노드를 재개할 때는 [중단 체크포인트](research/checkpoints/20261105-quota-pause/README.md)의
   노드별 표와 `pending/coordinator/dispatch.json`을 읽는다. 체크포인트(343파일)는 수정하지 않고
   새 후보와 새 검수 단위로 진행한다. 후보 코드를 제품 디렉터리에 일괄 복사하지 않는다.

## 다음 작업

- **GRAPH-OPS (Ready):** Phase 0에서 확인할 것은 기존 상태, 바꾸면 안 되는 범위, 사용 가능한 모델·effort,
  worktree 현황, 공용 파일·네이티브 자원 소유, 현재 검증 관문 목록이다. Phase 1에서는 `bd`를 설치하고
  저장소 밖 시험 디렉터리에서 모의 Epic/I/V/G로 의존성·`bd ready`·worktree 공유를 확인한다.
  두 단계가 끝나면 INTENT §15의 항목으로 사용자에게 보고한다. Phase 2 이관은 그 승인 뒤에 한다.
- **제품 (Ready):** B06 공개 기록 판독기 `203d9def`의 독립 검수(사전 오류 70·정상 6)와 B14 실행기
  후보 6의 독립 최종 검수. 실제 엔진 실행은 각각 정확한 계획·패키지·판독기 검수와 새 독점 임대를 거친다.

## 확인된 환경 (2026-11-06)

Herdr 0.9.5, `HERDR_ENV=1`. `bd`는 아직 설치되지 않았다. INTENT.md는 아직 Git에 커밋되지 않아서
다른 worktree에서는 보이지 않는다. 2026-11-05에는 Claude Code 2.1.318에서
`claude-sonnet-5-5 --effort high`가 실행됐다. 다른 컴퓨터나 새 세션에서는 다시 확인한다.
공유 Git의 staging·commit·push와 네이티브 임대는 코디네이터가 순서대로 처리한다.
