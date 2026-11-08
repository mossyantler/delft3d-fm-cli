# 공정표

**2026-11-06부터 활성 공정의 상태와 의존성은 Beads가 단일 원본이다**([이관 기록](research/notes/delivery/graph-ops-phase2.md)).
이 문서에는 승인 기준점, 공정 규칙, 최근 승인 기록, 그리고 Beads에서 생성한 스냅숏만 남긴다.
2026-11-06 이전의 단계별 서술 기록은 [공정 기록](research/notes/delivery/history-to-20261106.md)에 원문 그대로 있다.

- **조회(누구나):** `python -m research.workflows.graph.bdw ready --json --exclude-type epic`, `... show <id>`, `... blocked`.
  대시보드는 `python -m research.workflows.graph.dashboard pages` 뒤 `preview`(http://127.0.0.1:9000) 또는 `tui`. 읽기 전용 사본만 본다.
- **갱신(코디네이터만):** `DFM_BD_ROLE=coordinator`로 bdw를 통해서만 한다. 작업자는 결과 영수증을 제출한다.
- **기록 방식:** G Task를 닫을 때 근거를 `--reason`에 남기고, 아래 「최근 승인」에 한 줄을 더한다.
  스냅숏은 `python -m research.workflows.graph.seed report`로 다시 만든다. 손으로 고치지 않는다.
  그다음 `bdw backup-sync`로 OneDrive Dolt 백업과 `research/notes/delivery/beads-state.jsonl`을 갱신하고, 이 둘을 같은 노드로 커밋한다.

## 승인 기준점

| 항목 | 현재 값 |
| --- | --- |
| 제품 | `G18-G` (`954f5b3`). 제품 201파일이 wheel `7bfb1844…`와 일치. 그 전은 `S07-G` (`32ae74f`, 196파일), `B06-RUN-PROFILE-G` (`d22876a`, 193파일). S07·B06 G의 wheel 지문은 작업 트리 `diagnostics.py`의 줄끝 차이(CRLF, 내용 동일)를 포함했다([기록](research/experiments/G18-G-20261108-01/acceptance.json)) |
| 공개 계약 | 명령 102개(`section export`·`import` 추가), JSON 프로토콜 2, manifest 3, 기본 물리 프로필 불변 |
| 전체 회귀 | 1,806개 통과, 선택 `geo` 33 건너뜀, 실패·오류 0 ([기록](research/experiments/G18-G-20261108-01/acceptance.json)). 직전 기준은 1,715개 중 1,679 통과 ([기록](research/proposals/short-close-native-gates/root-verification.json)) |
| 실제 엔진 | #231 direct/DIMR 각 6사례, 원래 멤버 24개 종료, 600초·최종 restart, 원본 191변수 일치 ([`3851697` 검수](research/proposals/short-close-native231-review/RELEASE_VERDICT.md)) |
| 거부 보존 | #229는 관찰 tick 동률로 `NOT_ACCEPTED`. 원본 192파일 유지 ([해제 검수](research/proposals/short-close-native229-review/RELEASE_VERDICT.md)) |
| 네이티브 슬롯 | `idle237` (`G18-NATIVE-V-Run`의 #236 여섯 실행 뒤 `native-236` 해제). 실행 허가가 아니다 |

승인 범위는 f34 2D UTC cold-start 600초, direct와 단일 FM DIMR까지다. 강제 종료의
인과 귀속, 정상 마무리, 사용 가능한 restart, 다른 모델·CRS·MPI·결합·GUI 동등성은
승인하지 않았다.

## 활성 공정 스냅숏 (Beads, 2026-11-08 G18 마감 직후)

모든 후보는 현재 191파일 제품을 기준으로 **새로 구성**한다. 과거 `23f9` 또는 구형 제품 기반 결합 wheel을
승인본으로 재사용하지 않는다. 체크포인트의 후보 코드는 [중단 체크포인트](research/checkpoints/20261105-quota-pause/README.md)에 있다.
「(임대)」 Task는 Ready가 되어도 실행 허가가 아니다.

| Epic | Task | 상태 | Beads ID |
| --- | --- | --- | --- |
| B06 | B06-READER-I: 공개 기록 판독기 Mill 203d9def 동결 | ✓ | `dfm-985.1` |
| B06 | B06-READER-V-Plan: Einstein 사전 명세 오류 70·정상 6 | ✓ | `dfm-985.2` |
| B06 | B06-READER-V-Run: 판독기 독립 검수 (작성자 82통과는 근거 아님) | ✓ | `dfm-985.3` |
| B06 | B06-READER-G: 판독기 통합 검수 | ✓ | `dfm-985.4` |
| B06 | B06-RUN-PROFILE-I: 현재 191파일 기준 새 구성·공개 실행 프로필 | ✓ | `dfm-985.5` |
| B06 | B06-RUN-PROFILE-V-Plan: #225 6입력·170변수 사전 기준 (Mill) | ✓ | `dfm-985.6` |
| B06 | B06-RUN-PROFILE-V-Run: direct/DIMR 공개 실행 대조 (임대) | ✓ | `dfm-985.7` |
| B06 | B06-RUN-PROFILE-G: B06 실행 프로필 통합·루트 병합 | ✓ | `dfm-985.8` |
| B06 | HUMAN-20261107-01: Native runs for B06-RUN-PROFILE-V-Run (4 serial runs, candidate cf810b0) | ✓ | `dfm-985.9` |
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
| G18 | G18-NATIVE-I: 현재 191파일 기준 새 구성 | ✓ | `dfm-vbl.3` |
| G18 | G18-NATIVE-V-Run: 6사례 실행·Mill 독립 대조 (임대) | ✓ | `dfm-vbl.4` |
| G18 | G18-G: G18 루트 병합 통합 검수 | ✓ | `dfm-vbl.5` |
| G18 | G18-REBIND-V-Plan: Mill 계획을 현재 제품에 재결합 (엔진 실행 없음) | ✓ | `dfm-vbl.6` |
| G18 | HUMAN-20261108-03: Native runs for G18-NATIVE-V-Run (6 serial short runs, candidate f95f415) | ✓ | `dfm-vbl.7` |
| G18 | HUMAN-20261108-04: Re-run G18 native 6 cases with the R6.5 appended-section geometry | ✓ | `dfm-vbl.8` |
| GRAPH-OPS | GRAPH-OPS-P0P1: Phase 0 현황 점검·Phase 1 격리 시험 보고, 사용자 승인 2026-11-06 | ✓ | `dfm-fmc.1` |
| GRAPH-OPS | GRAPH-OPS-VIEWER-I: bv 0.25.2 로컬 대시보드 (JSONL 사본, 읽기 전용) | ✓ | `dfm-fmc.10` |
| GRAPH-OPS | GRAPH-OPS-VIEWER-V: 뷰어 독립 검증 (작업 공간·저장소 불변) | ✓ | `dfm-fmc.11` |
| GRAPH-OPS | GRAPH-OPS-VIEWER-G: 뷰어 통합 검수 | ✓ | `dfm-fmc.12` |
| GRAPH-OPS | HUMAN-20261106-01: Phase 0·1 보고 승인과 Phase 2 진행 | ✓ | `dfm-fmc.13` |
| GRAPH-OPS | HUMAN-20261106-02: BEADS_DIR 위치 | ✓ | `dfm-fmc.14` |
| GRAPH-OPS | HUMAN-20261106-03: bd 래퍼(bdw) 작성 | ✓ | `dfm-fmc.15` |
| GRAPH-OPS | HUMAN-20261106-04: bd 사용 통계 전역 설정 | ✓ | `dfm-fmc.16` |
| GRAPH-OPS | HUMAN-20261106-05: 코디네이터 세션 모델 | ✓ | `dfm-fmc.17` |
| GRAPH-OPS | HUMAN-20261106-06: Beads 백업 방식 | ✓ | `dfm-fmc.18` |
| GRAPH-OPS | HUMAN-20261106-07: beads.role | ✓ | `dfm-fmc.19` |
| GRAPH-OPS | GRAPH-OPS-BDW-I: bdw 래퍼 구현 | ✓ | `dfm-fmc.2` |
| GRAPH-OPS | HUMAN-20261106-08: 공정 대시보드 방식 | ✓ | `dfm-fmc.20` |
| GRAPH-OPS | HUMAN-20261106-09: GitHub 푸시 | ✓ | `dfm-fmc.21` |
| GRAPH-OPS | HUMAN-20261106-10: VIEWER-V 지시서 모호성 (소유 폴더의 임시 저장소에서 실행 여부) | ✓ | `dfm-fmc.22` |
| GRAPH-OPS | HUMAN-20261106-11: human 노드 방식 | ✓ | `dfm-fmc.23` |
| GRAPH-OPS | HUMAN-20261106-12: GitHub 푸시 (VIEWER 완료분) | ✓ | `dfm-fmc.24` |
| GRAPH-OPS | DUPLICATE of dfm-fmc.24 (created twice by a coordinator script error) | ✓ | `dfm-fmc.25` |
| GRAPH-OPS | HUMAN-20261106-13: Start Phase 3 (GRAPH-OPS-P3) | ✓ | `dfm-fmc.26` |
| GRAPH-OPS | HUMAN-20261106-14: Agent language | ✓ | `dfm-fmc.27` |
| GRAPH-OPS | HUMAN-20261106-15: Models for GRAPH-OPS-P3-DISPATCH | ✓ | `dfm-fmc.28` |
| GRAPH-OPS | HUMAN-20261106-16: Permission mode for Claude workers in Herdr panes | ✓ | `dfm-fmc.29` |
| GRAPH-OPS | GRAPH-OPS-BDW-V: bdw 독립 검증 (Codex gpt-6.1-sol high) | ✓ | `dfm-fmc.3` |
| GRAPH-OPS | GRAPH-OPS-P3-DISPATCH-I: dispatch tool and bdw human/gate allowlist | ✓ | `dfm-fmc.30` |
| GRAPH-OPS | GRAPH-OPS-P3-DISPATCH-V: independent verification of dispatch and the allowlist | ✓ | `dfm-fmc.31` |
| GRAPH-OPS | GRAPH-OPS-P3-DISPATCH-G: integration review of dispatch | ✓ | `dfm-fmc.32` |
| GRAPH-OPS | GRAPH-OPS-P3-SMOKE: live dispatch smoke test (G of GRAPH-OPS-P3-DISPATCH) | ✓ | `dfm-fmc.33` |
| GRAPH-OPS | HUMAN-20261106-17: Push P3-DISPATCH and start the pilot | ✓ | `dfm-fmc.34` |
| GRAPH-OPS | GRAPH-OPS-P3-CODEFIX-I: accept existing mixed-case task codes in dispatch | ✓ | `dfm-fmc.35` |
| GRAPH-OPS | GRAPH-OPS-P3-CODEFIX-V: verify the task-code amendment | ✓ | `dfm-fmc.36` |
| GRAPH-OPS | GRAPH-OPS-P3-CODEFIX-G: integrate the task-code amendment | ✓ | `dfm-fmc.37` |
| GRAPH-OPS | HUMAN-20261106-18: Finish Phase 3 | ✓ | `dfm-fmc.38` |
| GRAPH-OPS | GRAPH-OPS-P3-RECOVERY: interruption and recovery trial with dispatch | ✓ | `dfm-fmc.39` |
| GRAPH-OPS | GRAPH-OPS-BDW-G: bdw 통합 검수 | ✓ | `dfm-fmc.4` |
| GRAPH-OPS | GRAPH-OPS-P3-RECOVERY-T: recovery trial task (three staged files) | ✓ | `dfm-fmc.40` |
| GRAPH-OPS | GRAPH-OPS-P3-LIVEFIX-I: confirm the prompt started a turn; mark interrupted attempts | ✓ | `dfm-fmc.41` |
| GRAPH-OPS | GRAPH-OPS-P3-LIVEFIX-V: verify Contract C5 | ✓ | `dfm-fmc.42` |
| GRAPH-OPS | GRAPH-OPS-P3-LIVEFIX-G: integrate Contract C5 | ✓ | `dfm-fmc.43` |
| GRAPH-OPS | HUMAN-20261106-19: Codex quota policy | ✓ | `dfm-fmc.44` |
| GRAPH-OPS | GRAPH-OPS-P4: Phase 4: parallel multi-agent orchestration (isolation, ownership, fan-in gates) | ✓ | `dfm-fmc.45` |
| GRAPH-OPS | GRAPH-OPS-P4-PARALLEL-I: implement Contract P1-P6 in dispatch | ✓ | `dfm-fmc.46` |
| GRAPH-OPS | GRAPH-OPS-P4-PARALLEL-V-Plan: cases and verifier from Contract P1-P6 | ✓ | `dfm-fmc.47` |
| GRAPH-OPS | GRAPH-OPS-P4-PARALLEL-V-Run: verify frozen candidate | ✓ | `dfm-fmc.48` |
| GRAPH-OPS | GRAPH-OPS-P4-PARALLEL-G: integrate and live-trial Tests A-E | ✓ | `dfm-fmc.49` |
| GRAPH-OPS | GRAPH-OPS-P2-MIGRATE-G: 공정 이관과 DELIVERY 교차 검수 | ✓ | `dfm-fmc.5` |
| GRAPH-OPS | GRAPH-OPS-P3-LIVEFIX-SMOKE-C: live C5 check with Claude | ✓ | `dfm-fmc.50` |
| GRAPH-OPS | GRAPH-OPS-P3-LIVEFIX-SMOKE-X: live C5 check with Codex | ✓ | `dfm-fmc.51` |
| GRAPH-OPS | GRAPH-OPS-RELIABILITY-I: bind attempts, receipts, gates and recovery | in_progress | `dfm-fmc.52` |
| GRAPH-OPS | GRAPH-OPS-RELIABILITY-G: isolated integration review and local adoption | in_progress | `dfm-fmc.53` |
| GRAPH-OPS | GRAPH-OPS-P3: Phase 3: Herdr 코디네이터 통합(배정·영수증·복구 시험) | ✓ | `dfm-fmc.6` |
| GRAPH-OPS | GRAPH-OPS-BACKUP-I: bdw backup-sync (OneDrive Dolt + Git JSONL) | ✓ | `dfm-fmc.7` |
| GRAPH-OPS | GRAPH-OPS-BACKUP-V: backup-sync 독립 검증·복원 대조 | ✓ | `dfm-fmc.8` |
| GRAPH-OPS | GRAPH-OPS-BACKUP-G: 백업 통합 검수·첫 실제 백업 | ✓ | `dfm-fmc.9` |
| S07 | S07-EDITOR-G: 설치 편집 통합 검수 (8입력 보존) | ✓ | `dfm-lo0.1` |
| S07 | S07-V-Plan: 풍응력 7사례 판독 기준 (Lovelace) | ✓ | `dfm-lo0.2` |
| S07 | S07-I: 현재 191파일 기준 새 구성 | ✓ | `dfm-lo0.3` |
| S07 | S07-V-Run: 풍응력 7사례 엔진 검수 (임대) | ✓ | `dfm-lo0.4` |
| S07 | S07-G: S07 통합 검수 | ✓ | `dfm-lo0.5` |
| S07 | S07-V-Plan: re-bind the predeclared wind stress plan to the current product | ✓ | `dfm-lo0.6` |
| S07 | HUMAN-20261108-01: Native runs for S07-V-Run (7 serial short runs, candidate 10c33f4) | ✓ | `dfm-lo0.7` |
| S07 | HUMAN-20261108-02: Re-run S07 native 7 cases with operand = O fixtures | ✓ | `dfm-lo0.8` |
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
| G18-G | `954f5b3` (merge of `f95f415`) | [#235·#236 관측 단면 교환](research/notes/verification/section-transfer.md). `section export`·`import`. 실제 6회 실행에서 수동·공개 입력 결과가 정확히 일치, 방향 반전 오차 0(사용자 승인 `HUMAN-20261108-03`·`-04`) |
| S07-G | `32ae74f` (merge of `10c33f4`) | [#233 풍속별 항력 계수](research/notes/verification/wind-drag.md). `wind drag-inspect`·`drag-set`. 실제 7회 실행의 풍응력이 예측값과 허용 오차 안에서 일치(사용자 승인 `HUMAN-20261108-01`·`-02`) |
| B06-RUN-PROFILE-G | `d22876a` (merge of `cf810b0`) | [#232 공개 실행 프로필](research/notes/verification/source-sink.md#public-run). `run start --profile source-sink` direct·DIMR. 독립 검증 2회차 358/358, 실제 4회 실행이 #225와 170변수 정확히 일치(사용자 승인 `HUMAN-20261107-01`) |
| GRAPH-OPS-P4 (Phase 4) | `b3fef1f` (merge of `d6352b9`) | [Phase 4 G 기록](research/notes/delivery/graph-ops-p4-parallel.md#g-record-coordinator-2026-11-07). 병렬 dispatch(`fill`·`status`·`reconcile`·`gate`, 담당 경로·모델 정책). 독립 검증 2회차 PASS 936건, 실제 Herdr 시험 A~E 통과 |
| GRAPH-OPS-P3 (Phase 3) | `4156e61` | [Phase 3 마감](research/notes/delivery/graph-ops-p3-dispatch.md#phase-3-close-coordinator-2026-11-06). C5 독립 검증 2회차 PASS 27건, Claude·Codex 실제 시험 통과 |
| B06-READER-G | 실험 폴더(`freeze.json` `74789de6…937d`) | 판독기 rev2 독립 검증 PASS 76/76. 판독·기록 계층만 승인, 실제 엔진 실행 없음 |
| GRAPH-OPS-P3-CODEFIX-G | `1e4b316` | 대소문자 섞인 작업 코드 허용(C4.6 개정) |
| GRAPH-OPS-P3-DISPATCH-G | `09de210` (merge of `641c887`) | [dispatch 도구 승인](research/notes/delivery/graph-ops-p3-dispatch.md#g-record). 독립 검증 2회차 PASS 282건, 실제 Herdr 시험 통과 |
| GRAPH-OPS-VIEWER-G | `git log --grep GRAPH-OPS-VIEWER` | 로컬 bv 대시보드(사용자 결정). 독립 검증 3회차 PASS 224건, 앞선 두 회차 결함 4건 수정 |
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
