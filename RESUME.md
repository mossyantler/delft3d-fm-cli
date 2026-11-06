# 작업 재개 지점

**2026-11-06 기준.** 공용 `short` 종료 처리(SHORT-CLOSE)는 제품에 통합됐다(`df447d8`).
전체 제품 로드맵은 아직 끝나지 않았다. [INTENT.md](INTENT.md)에 따른 Beads 기반 공정 관리
전환(GRAPH-OPS)은 Phase 0·1을 마쳤고, [보고서](research/notes/delivery/graph-ops-phase0-1.md)에 대한
사용자 승인을 기다린다. 현재 승인 범위와 활성 Epic은 [공정표](DELIVERY.md)에만 기록한다.
이 문서에는 재개 순서만 둔다.

## 재개 순서

1. 루트 [AGENTS.md](AGENTS.md)와 작업할 디렉터리의 AGENTS.md를 읽는다. 코디네이터라면
   [COORDINATOR.md](COORDINATOR.md)도 읽는다.
2. [공정표](DELIVERY.md)의 승인 기준점과 활성 Epic 표를 확인한다. Beads 이관 뒤에는
   `bd ready --json --exclude-type epic`으로 실행 가능한 작업을 확인한다.
3. 실제 상태를 대조한다: `git status --short`, 현재 브랜치와 원격 SHA, 살아 있는 Herdr 세션
   (`herdr agent list`), 작업 worktree의 변경, 진행 중인 네이티브 프로세스, 슬롯 상태(`idle232`).
   세션이 끝났다는 이유로 작업을 처음부터 다시 시작하지 않는다. 살아 있는 실행은 중복으로 시작하지 않는다.
4. 노드를 재개할 때는 [중단 체크포인트](research/checkpoints/20261105-quota-pause/README.md)의
   노드별 표를 읽는다. `dispatch.json`의 슬롯·실행 정책(`idle228`, paused)은 불변 기록이므로 최신 G 영수증을
   따른다. 체크포인트(343파일)는 수정하지 않고, 새 후보와 새 검수 단위로 진행한다.

## 다음 작업

- **GRAPH-OPS:** 사용자가 보고서를 승인하면 Phase 2를 시작한다. 선행 조건은 보고서 §7에 있다:
  `BEADS_DIR`를 작업 트리 밖에 두고, 래퍼를 독립 검증하고, `sync.remote`를 해제한 뒤 이관하고,
  DELIVERY.md와 교차 검수한다. 작업 트리 안에서 `bd init`을 실행하지 않는다. stage된 파일까지 자동으로 커밋된다.
- **제품 (Ready):** B06 공개 기록 판독기 `203d9def`의 독립 검수(사전 오류 70·정상 6)와 B14 실행기
  후보 6의 독립 최종 검수. 실제 엔진 실행은 각각 정확한 계획·패키지·판독기 검수와 새 독점 임대를 거친다.

## 확인된 환경 (2026-11-06)

Herdr 0.9.5, Codex CLI 0.166.0(기본 `gpt-6.1-sol` high), Claude Code 2.1.318(기본 별칭 `opus`이므로
작업자 시작 시 `--model`을 반드시 지정한다). `bd` 1.3.1은 `research/tools/beads/1.3.1/`에만 있고 PATH에는 없다.
다른 컴퓨터나 새 세션에서는 다시 확인한다. 공유 Git의 staging·commit·push와 네이티브 임대는
코디네이터가 순서대로 처리한다.
