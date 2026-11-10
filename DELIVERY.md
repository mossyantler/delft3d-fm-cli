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
| 제품 | `RUN-OPEN-A1-G` (`255d582`). 제품 214파일이 wheel `8f00b301…`와 일치. 그 전은 `RUNIN-G` (`b347cfb`, 212파일, wheel `a8db94f1…`), `CONSUMERS-G` (`cd67e7a`), `INI-ALIGN-G` (`e7c32a0`), `INI-STAR-G` (`9c2a735`), `B14-G` (`aad1bf8`), 모두 212파일. S07·B06 G의 wheel 지문은 작업 트리 `diagnostics.py`의 줄끝 차이(CRLF, 내용 동일)를 포함했다([기록](research/experiments/G18-G-20261108-01/acceptance.json)) |
| 공개 계약 | 명령 107개(`boundary constituents-inspect`·`constituents-set` 추가), JSON 프로토콜 2, manifest 3, 기본 물리 프로필 불변 |
| 전체 회귀 | 2,015개 통과, 선택 `geo` 33 건너뜀, 실패·오류 0 ([기록](research/experiments/RUN-OPEN-A1-G-20261110-01/acceptance.json)). 직전 기준은 1,936개 ([RUNIN-G](research/experiments/RUNIN-G-20261109-01/acceptance.json)) |
| 실제 엔진 | #231 direct/DIMR 각 6사례, 원래 멤버 24개 종료, 600초·최종 restart, 원본 191변수 일치 ([`3851697` 검수](research/proposals/short-close-native231-review/RELEASE_VERDICT.md)) |
| 거부 보존 | #229는 관찰 tick 동률로 `NOT_ACCEPTED`. 원본 192파일 유지 ([해제 검수](research/proposals/short-close-native229-review/RELEASE_VERDICT.md)) |
| 네이티브 슬롯 | `idle241` (`RUN-OPEN-A1-V-Run-r2`의 `native-239` 1회, `-r3`의 #240 두 실행 뒤 해제). 실행 허가가 아니다 |

승인 범위는 f34 2D UTC cold-start 600초, direct와 단일 FM DIMR까지다. 강제 종료의
인과 귀속, 정상 마무리, 사용 가능한 restart, 다른 모델·CRS·MPI·결합·GUI 동등성은
승인하지 않았다.

## 활성 공정 스냅숏 (Beads, 2026-11-11 RUN-OPEN A1 통합 검수 직후)

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
| B14 | HUMAN-20261109-01: Native runs for B14-NATIVE-V-Run (6 serial short direct runs, candidate e2b4079) | ✓ | `dfm-jtm.10` |
| B14 | B14-NATIVE-V-Run: six direct short runs judged by the frozen direct gate (임대) | ✓ | `dfm-jtm.11` |
| B14 | B14-RUNNER-V-Plan: 독립 검사 75건 (Plato) | ✓ | `dfm-jtm.2` |
| B14 | B14-RUNNER-V-Run: 실행기 독립 최종 검수·판정 봉인 | deferred | `dfm-jtm.3` |
| B14 | B14-RUNNER-G: 실행기 통합 검수 | deferred | `dfm-jtm.4` |
| B14 | B14-BMI-V-Run: BMI 4진단 실제 실행 (4진단만으로 B14 승인 아님) (임대) | deferred | `dfm-jtm.5` |
| B14 | B14-PUBLIC-I: rebuild on main after G15-G (Contract b14-rebuild) | ✓ | `dfm-jtm.6` |
| B14 | B14-PUBLIC-V-Run: 공개 direct 6사례 (임대) | ✓ | `dfm-jtm.7` |
| B14 | B14-G: B14 전체 합류 검수 | ✓ | `dfm-jtm.8` |
| B14 | B14-REBIND-V-Plan: re-bind the frozen direct gate to the current short lifecycle | ✓ | `dfm-jtm.9` |
| G15 | G15-Contract: 수정 계약 승인 (23의무·16범위) | ✓ | `dfm-h9c.1` |
| G15 | G15-ENGINE-V-Plan: cases, frozen inputs and reader for structure transfer engine runs | ✓ | `dfm-h9c.10` |
| G15 | G15-ENGINE-V-Run: run and judge the approved structure transfer cases (임대) | ✓ | `dfm-h9c.11` |
| G15 | G15-ENGINE-G: record structure transfer engine evidence | ✓ | `dfm-h9c.12` |
| G15 | G15-GUI-PARITY: DeltaShell export/import parity for structures (deferred by user) | deferred | `dfm-h9c.13` |
| G15 | G15-SCALAR-WEIR-PROFILE: a public run profile that admits scalar-crest weir models | Ready | `dfm-h9c.14` |
| G15 | HUMAN-20261109-02: Native runs for G15-ENGINE-V-Run (6 serial direct runs: weir_tim and pump_scalar x control/public/manual) | ✓ | `dfm-h9c.15` |
| G15 | G15-V-Plan: 공개 30·저장 오류 11 시험 준비 (Lovelace) | ✓ | `dfm-h9c.2` |
| G15 | G15-I: 정확한 후보 확정·동결 (package-02 이후 추가분 포함) | ✓ | `dfm-h9c.3` |
| G15 | G15-V-Run: 독립 설치 검수 | ✓ | `dfm-h9c.4` |
| G15 | G15-G: G15 파일 기능 통합 검수 | ✓ | `dfm-h9c.5` |
| G15 | G15-ENGINE-Contract: 엔진·GUI 검증 별도 계획 | ✓ | `dfm-h9c.6` |
| G15 | HUMAN-20261108-05: ACL writes for G15-V-Run inside its own experiment folder | ✓ | `dfm-h9c.7` |
| G15 | G15-CLOSURE-I: qualify uncatalogued MDU keys that name model entities (R6) | ✓ | `dfm-h9c.8` |
| G15 | G15-CLOSURE-V-Run: round 3 on the R6-fixed candidate | ✓ | `dfm-h9c.9` |
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
| GRAPH-OPS | GRAPH-OPS-RELIABILITY-I: bind attempts, receipts, gates and recovery | ✓ | `dfm-fmc.52` |
| GRAPH-OPS | GRAPH-OPS-RELIABILITY-G: isolated integration review and local adoption | ✓ | `dfm-fmc.53` |
| GRAPH-OPS | GRAPH-PASTE-WRAP: unwrap Claude Code pasted_content in the prompt check | ✓ | `dfm-fmc.54` |
| GRAPH-OPS | GRAPH-CODEX-SESSION: record the Codex session id after start so stop can verify identity | ✓ | `dfm-fmc.55` |
| GRAPH-OPS | GRAPH-CODEX-NEWLINES: Codex interactive prompts lose newlines; prefer startup_argument delivery | ✓ | `dfm-fmc.56` |
| GRAPH-OPS | GRAPH-CLAUDE-PROMPT-RACE: Claude start-time prompt check returns false although the transcript later matches | ✓ | `dfm-fmc.57` |
| GRAPH-OPS | GRAPH-OPS-P3: Phase 3: Herdr 코디네이터 통합(배정·영수증·복구 시험) | ✓ | `dfm-fmc.6` |
| GRAPH-OPS | GRAPH-OPS-BACKUP-I: bdw backup-sync (OneDrive Dolt + Git JSONL) | ✓ | `dfm-fmc.7` |
| GRAPH-OPS | GRAPH-OPS-BACKUP-V: backup-sync 독립 검증·복원 대조 | ✓ | `dfm-fmc.8` |
| GRAPH-OPS | GRAPH-OPS-BACKUP-G: 백업 통합 검수·첫 실제 백업 | ✓ | `dfm-fmc.9` |
| INI | INI-STAR-V-Plan: independent cases for * comment lines | ✓ | `dfm-3ks.1` |
| INI | INI-ALIGN-CONSUMERS: decide the comment mode for the other callers of boundary._blocks (EXT/BC/inifield readers in boundary_export, boundary_vertical, boundary_preview, boundary_import, boundary_series, boundary_constituents, source_sink) | ✓ | `dfm-3ks.10` |
| INI | CONSUMERS-I: pass the file-kind comment mode at every boundary._blocks caller | ✓ | `dfm-3ks.11` |
| INI | CONSUMERS-V-Plan: independent cases per caller and command family | ✓ | `dfm-3ks.12` |
| INI | CONSUMERS-V-Run: verify the frozen consumers candidate | ✓ | `dfm-3ks.13` |
| INI | CONSUMERS-G: merge and close the comment-rule gap | ✓ | `dfm-3ks.14` |
| INI | CONSUMERS-RUN-INPUTS: pass the bc comment mode at source_sink_run_inputs.py:110 | ✓ | `dfm-3ks.15` |
| INI | RUNIN-I: bc comment mode in source_sink_run_inputs bc_state | ✓ | `dfm-3ks.16` |
| INI | RUNIN-V-Plan: independent cases for the source-sink run inputs | ✓ | `dfm-3ks.17` |
| INI | RUNIN-V-Run: verify the frozen run-inputs candidate | ✓ | `dfm-3ks.18` |
| INI | RUNIN-G: merge and close the last comment-rule gap | ✓ | `dfm-3ks.19` |
| INI | INI-STAR-V-Run: verify the frozen model.parse candidate | ✓ | `dfm-3ks.2` |
| INI | INI-STAR-G: merge and record * comment lines | ✓ | `dfm-3ks.3` |
| INI | INI-STAR-OTHER-PARSERS: map the four other line parsers to their engine readers before any change | ✓ | `dfm-3ks.4` |
| INI | INI-ALIGN-I: engine comment rules in EXT, inifield, PLI and BC header parsers | ✓ | `dfm-3ks.5` |
| INI | INI-ALIGN-V-Plan: independent cases per file-kind comment rule | ✓ | `dfm-3ks.6` |
| INI | INI-ALIGN-V-Run: verify the frozen alignment candidate | ✓ | `dfm-3ks.7` |
| INI | INI-ALIGN-G: merge and record per-file-kind comment rules | ✓ | `dfm-3ks.8` |
| INI | INI-ALIGN-V-Run-r2: rerun the frozen plan with the reviewed _blocks mode adapter | ✓ | `dfm-3ks.9` |
| INI | INI-STAR-COMMENT: decide whether INI inputs may start lines with '*' (engine/GUI evidence first) | ✓ | `dfm-qu3` |
| RUN-OPEN · open run route for integrated user models | RUN-OPEN-Contract: open run route for integrated user models (Garolim target) | ✓ | `dfm-7tv` |
| RUN-OPEN · open run route for integrated user models | RUN-OPEN-A1-I: open profile admission, INI/sediment closure and layered report | ✓ | `dfm-9l0.1` |
| RUN-OPEN · open run route for integrated user models | RUN-OPEN-A1-FIX3-I: trace open profile Job members (Contract R11.2) | ✓ | `dfm-9l0.10` |
| RUN-OPEN · open run route for integrated user models | RUN-OPEN-A1-V-Plan-r2: correct the integrated fixture's morphology boundary names and re-freeze (Contract R11.1) | ✓ | `dfm-9l0.11` |
| RUN-OPEN · open run route for integrated user models | RUN-OPEN-A1-V-Run-r3: verify the R11 candidate on the corrected plan, two native runs | ✓ | `dfm-9l0.12` |
| RUN-OPEN · open run route for integrated user models | RUN-OPEN-A1-V-Plan: open profile admission, INI/sediment closure and layered report | ✓ | `dfm-9l0.2` |
| RUN-OPEN · open run route for integrated user models | RUN-OPEN-A1-V-Run: open profile admission, INI/sediment closure and layered report | ✓ | `dfm-9l0.3` |
| RUN-OPEN · open run route for integrated user models | RUN-OPEN-A1-G: open profile admission, INI/sediment closure and layered report | ✓ | `dfm-9l0.4` |
| RUN-OPEN · open run route for integrated user models | RUN-OPEN-A1-FIX-I: resolve files named inside sed/mor from the MDU folder (Contract R8) | ✓ | `dfm-9l0.5` |
| RUN-OPEN · open run route for integrated user models | HUMAN-20261110-01: Native runs for RUN-OPEN-A1-V-Run (2 serial direct runs: integrated test model public run start --profile open and manual dflowfm, 120 s each) | ✓ | `dfm-9l0.6` |
| RUN-OPEN · open run route for integrated user models | RUN-OPEN-A1-FIX2-I: feature rows and statuses by gate scope, not_performed pre-launch layers, dia diagnostics (Contract R10) | ✓ | `dfm-9l0.7` |
| RUN-OPEN · open run route for integrated user models | RUN-OPEN-A1-V-Run-r2: verify the R10 candidate, two native runs | ✓ | `dfm-9l0.8` |
| RUN-OPEN · open run route for integrated user models | HUMAN-20261110-02: Native runs for RUN-OPEN-A1-V-Run-r3 (2 serial direct runs: corrected integrated test model public open and manual dflowfm, 120 s each) | ✓ | `dfm-9l0.9` |
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
| RUN-OPEN-A1-G | `255d582` (merge of `227ccc0`) | [통합 모델용 `run start --profile open`](research/notes/verification/run-open.md). 입력 그래프가 닫혔는지만 보고 실행을 허용하고(INI·`.sed`/`.mor` 참조 추적 추가), 단계별 보고와 게이트 범위 기반 기능 표를 남김. 통합 시험 모델의 공개·수동 실행 출력이 정확히 일치(#240, 사용자 승인 `HUMAN-20261110-02`). 가로림 복사본은 입력 닫힘 확인 후 파랑 연동으로 실행 전 거절. 장시간 분리 실행(A2)과 FM+Waves(Phase B)는 미구현 |
| G15-ENGINE-G | 병합 없음 (`b93a31f`의 제품 검증) | [#238 구조물 교환 엔진 실행](research/notes/verification/structure-transfer.md). TIM 보·펌프를 `structure export`·`import`로 옮긴 모델과 수동 편집 모델의 출력이 6회 실행에서 정확히 일치, 원래 모델과는 구조물 관측값이 다름(사용자 승인 `HUMAN-20261109-02`). 고정 마루 보는 공개 프로필이 없어 미실행, GUI 대조는 사용자 결정으로 보류 |
| RUNIN-G | `b347cfb` (merge of `c48c089`) | [파일 종류별 주석 규칙](research/notes/verification/ini-comments.md). 취·방류 실행 프로필의 입력 검사(`bc_state`)도 `.bc` 주석 규칙을 따름. 독립 검증 156검사 통과(엔진 실행 전 단계). INI 주석 규칙 epic 완료 |
| CONSUMERS-G | `cd67e7a` (merge of `7aec98c`) | [파일 종류별 주석 규칙](research/notes/verification/ini-comments.md). `boundary._blocks`를 쓰는 나머지 12곳이 읽는 파일 종류의 주석 모드를 넘김. 독립 검증 7,717검사(공개 CLI 2,033호출) 통과. 남은 1곳은 `CONSUMERS-RUN-INPUTS` |
| INI-ALIGN-G | `e7c32a0` (merge of `3a419d6`) | [파일 종류별 주석 규칙](research/notes/verification/ini-comments.md). EXT·inifield·PLI·`.bc` 헤더 판독기가 엔진 규칙을 따름. 독립 검증 2회차 410사례 통과(1회차는 검사 호출 인자 누락으로 REJECT). `boundary._blocks`의 다른 호출 11곳은 후속 `INI-ALIGN-CONSUMERS` |
| INI-STAR-G | `9c2a735` (merge of `bce84e9`) | [INI `*` 주석 줄](research/notes/verification/ini-comments.md). 공용 판독기 `model.parse`가 엔진처럼 공백 뒤 `*` 줄을 주석으로 넘김(탭 앞은 기존대로 거부). 독립 검증 265사례 통과, 명령·스키마 불변. 엔진·GUI 실행 없음 |
| B14-G | `aad1bf8` (merge of `e2b4079`) | [#237 분조 일괄 지정](research/notes/verification/boundary-constituents.md). `boundary constituents-inspect`·`constituents-set`. 실제 6회 직접 실행에서 날짜별 수동·CLI 편집 출력 169변수가 정확히 일치(사용자 승인 `HUMAN-20261109-01`). 연구용 BMI 실행기 갈래는 사용자 결정으로 보류 |
| G15-G | `d8665fc` (merge of `bdd90b0`) | [G15 구조물 파일 교환](research/notes/verification/structure-transfer.md). `structure inspect`·`export`·`import`, W2D 보·P2D 펌프 쓰기. 독립 검증 3회차 공개 30/30·저장 오류 11/11, 2회차에서 찾은 참조 누락 결함(R6) 수정 확인(ACL 사용자 승인 `HUMAN-20261108-05`). 엔진·GUI 미검증 |
| GRAPH-OPS-RELIABILITY-G | `a8d1801` (candidate `ab064b1`, V `c657725`) | [Graph protocol 2 acceptance](research/notes/delivery/graph-ops-reliability.md#accepted-g-evidence-and-local-cutover-2026-11-08): 63 checks, no skips; scoped independent V and isolated live receipt/Gate/cleanup checks. Tooling only; no Native/scientific claim. |
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
