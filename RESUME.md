# 작업 재개 지점

**2026-11-06 기준.** 공용 `short` 종료 처리(SHORT-CLOSE)는 제품에 통합됐다(`df447d8`).
전체 제품 로드맵은 아직 끝나지 않았다. [INTENT.md](INTENT.md)의 공정 관리 전환은 Phase 2까지 마쳤다
([이관 기록](research/notes/delivery/graph-ops-phase2.md)). 이제 활성 공정의 상태와 의존성은 **Beads**에만 있다.
이 문서에는 재개 순서만 둔다.

## 재개 순서

1. 루트 [AGENTS.md](AGENTS.md)와 작업할 디렉터리의 AGENTS.md를 읽는다. 코디네이터라면
   [COORDINATOR.md](COORDINATOR.md)도 읽는다.
2. 실행 가능한 작업을 확인한다: `python -m research.workflows.graph.bdw ready --json --exclude-type epic`.
   자세한 내용은 `... show <id>`로 본다. 승인 기준점은 [공정표](DELIVERY.md)에 있다.
3. 실제 상태를 대조한다: `git status --short`, 현재 브랜치와 원격 SHA, 살아 있는 Herdr 세션
   (`herdr agent list`), 작업 worktree의 변경, 진행 중인 네이티브 프로세스, 슬롯 상태(`idle232`),
   `In Progress`인 Beads Task. 세션이 끝났다는 이유로 작업을 처음부터 다시 시작하지 않는다.
   살아 있는 실행은 중복으로 시작하지 않는다.
4. 체크포인트 후보로 노드를 재개할 때는 [중단 체크포인트](research/checkpoints/20261105-quota-pause/README.md)를 읽는다.
   `dispatch.json`의 슬롯·실행 정책(`idle228`, paused)은 불변 기록이므로 최신 G 영수증을 따른다.

## 다음 작업 (Beads Ready, 2026-11-06)

- **GRAPH-OPS-P3:** Herdr 코디네이터 통합. 한 Task를 Task Packet으로 배정하고 영수증을 수집한 뒤,
  반복 실패와 중단 복구까지 시험한다(INTENT Phase 3).
- **제품:** `B06-READER-V-Run`, `B14-RUNNER-V-Run`(독립 검수), `B06-RUN-PROFILE-V-Plan`,
  `B14-PUBLIC-I`·`S07-I`·`G18-NATIVE-I`(현재 191파일 기준 새 구성), `G15-I`(후보 동결).
  임대가 필요한 실행은 아직 모두 Blocked이고, Ready가 되어도 실행 허가가 아니다.

## 확인된 환경 (2026-11-06)

- Herdr 0.9.5.
- Codex CLI 0.166.0: 기본 `gpt-6.1-sol` high. V 작업에서 시작 배너로 확인했다.
- Claude Code 2.1.318: 기본값이 별칭 `opus`라서 작업자를 시작할 때 `--model`을 반드시 지정한다.
- `bd` 1.3.1은 `research/tools/beads/1.3.1/`에 있고(PATH에는 없음), bdw를 통해서만 쓴다.
- Beads 작업 공간은 `C:\Users\minyeop\project\delft3d-fm-cli-beads\.beads`다. 백업과 원격 동기화는 아직 없다.
  이 디렉터리를 잃으면 [이관 영수증](research/notes/delivery/beads-seed-20261106.json)과 이후 기록으로 재구성해야 한다.

다른 컴퓨터나 새 세션에서는 환경을 다시 확인한다. 공유 Git의 staging·commit·push와 네이티브 임대는
코디네이터가 순서대로 처리한다.
