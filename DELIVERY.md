# 공정표

**2026-11-06부터 활성 공정의 상태와 의존성은 Beads가 단일 원본이다**([이관 기록](research/notes/delivery/graph-ops-phase2.md)).
이 문서에는 승인 기준점, 공정 규칙, 최근 승인 기록, 그리고 Beads에서 생성한 스냅숏만 남긴다.
2026-11-06 이전의 단계별 서술 기록은 [공정 기록](research/notes/delivery/history-to-20261106.md)에 원문 그대로 있다.

- **조회(누구나):** `python -m research.workflows.graph.bdw ready --json --exclude-type epic`, `... show <id>`, `... blocked`
- **갱신(코디네이터만):** `DFM_BD_ROLE=coordinator`로 bdw를 통해서만 한다. 작업자는 결과 영수증을 제출한다.
- **기록 방식:** G Task를 닫을 때 근거를 `--reason`에 남기고, 아래 「최근 승인」에 한 줄을 더한다.
  스냅숏은 `python -m research.workflows.graph.seed report`로 다시 만든다. 손으로 고치지 않는다.
  그다음 `bdw backup-sync`로 OneDrive Dolt 백업과 `research/notes/delivery/beads-state.jsonl`을 갱신하고, 이 둘을 같은 노드로 커밋한다.

## 승인 기준점

| 항목 | 현재 값 |
| --- | --- |
| 제품 | `SHORT-CLOSE-ROOT-G` (`df447d8`). 검증 wheel `e32bf84f…`의 종료 모듈 두 개만 반영, 제품 191파일이 wheel과 일치 |
| 공개 계약 | 명령 98개, JSON 프로토콜 2, manifest 3, 기본 물리 프로필 불변 |
| 전체 회귀 | 1,715개 중 1,679 통과, 기존 환경 조건 36 건너뜀, 이후 호환성 3건 통과 ([기록](research/proposals/short-close-native-gates/root-verification.json)) |
| 실제 엔진 | #231 direct/DIMR 각 6사례, 원래 멤버 24개 종료, 600초·최종 restart, 원본 191변수 일치 ([`3851697` 검수](research/proposals/short-close-native231-review/RELEASE_VERDICT.md)) |
| 거부 보존 | #229는 관찰 tick 동률로 `NOT_ACCEPTED`. 원본 192파일 유지 ([해제 검수](research/proposals/short-close-native229-review/RELEASE_VERDICT.md)) |
| 네이티브 슬롯 | `idle232` (`NATIVE231-REPLAY-G` `2af0673`). 실행 허가가 아니다 |

승인 범위는 f34 2D UTC cold-start 600초, direct와 단일 FM DIMR까지다. 강제 종료의
인과 귀속, 정상 마무리, 사용 가능한 restart, 다른 모델·CRS·MPI·결합·GUI 동등성은
승인하지 않았다.

## 활성 공정 스냅숏 (Beads, 2026-11-06 GRAPH-OPS-BACKUP-G 직후)

모든 후보는 현재 191파일 제품을 기준으로 **새로 구성**한다. 과거 `23f9` 또는 구형 제품 기반 결합 wheel을
승인본으로 재사용하지 않는다. 체크포인트의 후보 코드는 [중단 체크포인트](research/checkpoints/20261105-quota-pause/README.md)에 있다.
「(임대)」 Task는 Ready가 되어도 실행 허가가 아니다.

| Epic | Task | 상태 | Beads ID |
| --- | --- | --- | --- |
| B06 | B06-READER-I: 공개 기록 판독기 Mill 203d9def 동결 | ✓ | `dfm-985.1` |
| B06 | B06-READER-V-Plan: Einstein 사전 명세 오류 70·정상 6 | ✓ | `dfm-985.2` |
| B06 | B06-READER-V-Run: 판독기 독립 검수 (작성자 82통과는 근거 아님) | Ready | `dfm-985.3` |
| B06 | B06-READER-G: 판독기 통합 검수 | Blocked | `dfm-985.4` |
| B06 | B06-RUN-PROFILE-I: 현재 191파일 기준 새 구성·공개 실행 프로필 | Blocked | `dfm-985.5` |
| B06 | B06-RUN-PROFILE-V-Plan: #225 6입력·170변수 사전 기준 (Mill) | Ready | `dfm-985.6` |
| B06 | B06-RUN-PROFILE-V-Run: direct/DIMR 공개 실행 대조 (임대) | Blocked | `dfm-985.7` |
| B06 | B06-RUN-PROFILE-G: B06 실행 프로필 통합·루트 병합 | Blocked | `dfm-985.8` |
| B14 | B14-RUNNER-I: BMI 실행기 후보 6 2641efa9 동결 | ✓ | `dfm-jtm.1` |
| B14 | B14-RUNNER-V-Plan: 독립 검사 75건 (Plato) | ✓ | `dfm-jtm.2` |
| B14 | B14-RUNNER-V-Run: 실행기 독립 최종 검수·판정 봉인 | Ready | `dfm-jtm.3` |
| B14 | B14-RUNNER-G: 실행기 통합 검수 | Blocked | `dfm-jtm.4` |
| B14 | B14-BMI-V-Run: BMI 4진단 실제 실행 (4진단만으로 B14 승인 아님) (임대) | Blocked | `dfm-jtm.5` |
| B14 | B14-PUBLIC-I: 현재 191파일 기준 새 구성 | Ready | `dfm-jtm.6` |
| B14 | B14-PUBLIC-V-Run: 공개 direct 6사례 (임대) | Blocked | `dfm-jtm.7` |
| B14 | B14-G: B14 전체 합류 검수 | Blocked | `dfm-jtm.8` |
| G15 | G15-Contract: 수정 계약 승인 (23의무·16범위) | ✓ | `dfm-h9c.1` |
| G15 | G15-V-Plan: 공개 30·저장 오류 11 시험 준비 (Lovelace) | ✓ | `dfm-h9c.2` |
| G15 | G15-I: 정확한 후보 확정·동결 (package-02 이후 추가분 포함) | Ready | `dfm-h9c.3` |
| G15 | G15-V-Run: 독립 설치 검수 | Blocked | `dfm-h9c.4` |
| G15 | G15-G: G15 파일 기능 통합 검수 | Blocked | `dfm-h9c.5` |
| G15 | G15-ENGINE-Contract: 엔진·GUI 검증 별도 계획 | Blocked | `dfm-h9c.6` |
| G18 | G18-FILE-G: 파일 작업 최종 검수 (입력 편집만) | ✓ | `dfm-vbl.1` |
| G18 | G18-NATIVE-V-Plan: 수치 검증 계획·입력 동결 (Mill) | ✓ | `dfm-vbl.2` |
| G18 | G18-NATIVE-I: 현재 191파일 기준 새 구성 | Ready | `dfm-vbl.3` |
| G18 | G18-NATIVE-V-Run: 6사례 실행·Mill 독립 대조 (임대) | Blocked | `dfm-vbl.4` |
| G18 | G18-G: G18 루트 병합 통합 검수 | Blocked | `dfm-vbl.5` |
| GRAPH-OPS | GRAPH-OPS-P0P1: Phase 0 현황 점검·Phase 1 격리 시험 보고, 사용자 승인 2026-11-06 | ✓ | `dfm-fmc.1` |
| GRAPH-OPS | GRAPH-OPS-BDW-I: bdw 래퍼 구현 | ✓ | `dfm-fmc.2` |
| GRAPH-OPS | GRAPH-OPS-BDW-V: bdw 독립 검증 (Codex gpt-6.1-sol high) | ✓ | `dfm-fmc.3` |
| GRAPH-OPS | GRAPH-OPS-BDW-G: bdw 통합 검수 | ✓ | `dfm-fmc.4` |
| GRAPH-OPS | GRAPH-OPS-P2-MIGRATE-G: 공정 이관과 DELIVERY 교차 검수 | ✓ | `dfm-fmc.5` |
| GRAPH-OPS | GRAPH-OPS-P3: Phase 3: Herdr 코디네이터 통합(배정·영수증·복구 시험) | Ready | `dfm-fmc.6` |
| GRAPH-OPS | GRAPH-OPS-BACKUP-I: bdw backup-sync (OneDrive Dolt + Git JSONL) | ✓ | `dfm-fmc.7` |
| GRAPH-OPS | GRAPH-OPS-BACKUP-V: backup-sync 독립 검증·복원 대조 | ✓ | `dfm-fmc.8` |
| GRAPH-OPS | GRAPH-OPS-BACKUP-G: 백업 통합 검수·첫 실제 백업 | ✓ | `dfm-fmc.9` |
| S07 | S07-EDITOR-G: 설치 편집 통합 검수 (8입력 보존) | ✓ | `dfm-lo0.1` |
| S07 | S07-V-Plan: 풍응력 7사례 판독 기준 (Lovelace) | ✓ | `dfm-lo0.2` |
| S07 | S07-I: 현재 191파일 기준 새 구성 | Ready | `dfm-lo0.3` |
| S07 | S07-V-Run: 풍응력 7사례 엔진 검수 (임대) | Blocked | `dfm-lo0.4` |
| S07 | S07-G: S07 통합 검수 | Blocked | `dfm-lo0.5` |
| SHORT-CLOSE | SHORT-CLOSE-ROOT-G: 제품 통합 승인 df447d8 | ✓ | `dfm-nh0.1` |

## 공정 규칙

역할(I/V/G), Git 커밋 단위와 공용 파일 소유는 [AGENTS.md](AGENTS.md)를 따른다. 작업
배정, 모델 선택, 임대와 복구는 [COORDINATOR.md](COORDINATOR.md)를 따른다. 공개 명령
등록, 스키마 통합, 패키징, README·ROADMAP·이 문서는 코디네이터만 편집한다. 실제 엔진
실행은 어느 분기든 한 번에 하나의 독점 임대를 쓴다. 임대를 기다리는 분기라도 입력 검증과
판독기 검증은 계속 진행한다.

이전에 승인된 범위(M1–M5, P01–P04, E012–E015, B01–B13, G06–G16, O02–O04 등)의 근거는
[검증 노트](research/notes/verification/)와 [공정 기록](research/notes/delivery/history-to-20261106.md)에 있다.

## 최근 승인

| 노드 | 커밋 | 근거 |
| --- | --- | --- |
| GRAPH-OPS-BACKUP-G | `git log --grep GRAPH-OPS-BACKUP-G` | [백업 방식·복원 확인](research/notes/delivery/graph-ops-backup.md), 실제 백업 두 사본 복원 일치 |
| GRAPH-OPS-COORD-MODEL | `e7783f6` | 코디네이터 세션 모델 Sol 또는 Opus high (사용자 결정) |
| GRAPH-OPS-P2-MIGRATE-G | `git log --grep GRAPH-OPS-P2-MIGRATE-G` | [Beads 이관·교차 검수](research/notes/delivery/graph-ops-phase2.md) |
| GRAPH-OPS-BDW-G | `a8d47db` (V) | [bdw 래퍼 승인](research/notes/delivery/graph-ops-phase2.md#bdw-래퍼-i--v--g), 독립 검증 64/64 |
| GRAPH-OPS-P0P1 | `0ef1214` | [Phase 0·1 보고](research/notes/delivery/graph-ops-phase0-1.md). 이관 승인이 아니다 |
| GRAPH-OPS-DOC | `04aba08` | 에이전트 지침 분리, 공정표 현재판 전환 |
| GRAPH-OPS-INTENT | `19cbd35` | INTENT.md 등록 |
| SHORT-CLOSE-ROOT-DOC | `607c61c` | 재개 문서와 다음 관문 기록 |
| SHORT-CLOSE-ROOT-G | `df447d8` | 제품 통합. 종료 모듈 두 개 반영 |
| SHORT-CLOSE-ROOT-V | `0ceb728` | [통합 독립 검수 27항목](research/proposals/short-close-root-review/REVIEW.md) |
| NATIVE231-REPLAY-G | `2af0673` | [합류 승인과 임대 해제](research/proposals/short-close-native-gates/release231.json) |
| NATIVE231-RELEASE-V | `3851697` | [실제 회귀 37항목](research/proposals/short-close-native231-review/RELEASE_VERDICT.md) |
