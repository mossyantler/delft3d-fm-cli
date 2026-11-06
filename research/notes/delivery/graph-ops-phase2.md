# GRAPH-OPS Phase 2: Beads 이관 기록 (2026-11-06)

사용자가 2026-11-06에 [Phase 0·1 보고](graph-ops-phase0-1.md)를 승인했다. 함께 정한 사항은
`BEADS_DIR`를 저장소 옆 디렉터리에 두는 것, 래퍼 작성 허용, 사용 통계 전역 설정은 건드리지 않는 것이다.
이 문서는 래퍼의 I/V/G와 실제 이관·교차 검수(GRAPH-OPS-P2-MIGRATE-G)의 근거다.

## bdw 래퍼: I → V → G

| 노드 | 커밋 | 결과 |
| --- | --- | --- |
| GRAPH-OPS-BDW-I rev1 | `aec83cb` | [`bdw.py`](../../workflows/graph/bdw.py). 작성자 시험 12/12 |
| GRAPH-OPS-BDW-V 1차 | (반려) | 64건 중 57건 통과, 결함 4개. 아래 표 |
| GRAPH-OPS-BDW-I rev2 | `29bdb26` | 네 결함 수정. 작성자 시험 13/13 |
| GRAPH-OPS-BDW-V 2차 | `a8d47db` | 동결된 같은 검증기(SHA-256 `0e5894a5…7914`)로 64/64, 결함 없음 |
| GRAPH-OPS-BDW-G | 이 문서 | 승인 |

V 수행 조건: Codex CLI 0.166.0이 별도 Herdr 세션에서 `gpt-6.1-sol` `high`로 실행됐다(작성자와 다른 계열, 시작 배너로 확인, Fallback 없음).
분리된 detached worktree에서 작업했고, [Task Packet](../../experiments/GRAPH-OPS-BDW-V-20261106-01/TASK.md)의
Contract만으로 사례를 설계했다(로컬 기록). 검증기 원본은
[`verify_bdw.py`](../../workflows/verification/verify_bdw.py)다. `--out`은 검증기가 있는 폴더 아래만 허용하므로
재현할 때는 실험 폴더의 사본으로 실행한다.

| 결함 | 내용 | rev2 수정 |
| --- | --- | --- |
| BDW-V-001 | 호출자가 `--sandbox=false`로 강제 샌드박스를 끌 수 있음 | 호출자가 준 `--sandbox`·`--readonly`·`--actor`는 값과 무관하게 거부 |
| BDW-V-002 | 작업자가 `--readonly=false`를 주거나, 플래그 값 뒤에 `comments add`를 숨겨 실제 댓글을 기록함 | 하위 명령 앞에 플래그가 오면 거부. 작업자는 `comments ... add` 불가 |
| BDW-V-003 | `init-workspace`가 `--discard-remote` 같은 인자를 조용히 무시함 | 인자를 받지 않음 |
| BDW-V-004 | `bd init`이 `.git/config`에 `beads.role=maintainer`를 쓰는데 래퍼는 "변경 없음"으로 보고함 | 바뀐 것이 그 키 하나뿐이면 원래 바이트로 복원. `.git/config`·hooks를 변경 검사에 포함 |

G 판단: 두 차례 검증 기록에서 검증기 해시가 같고, 사례 64개는 이름의 fixture ID만 다르며, 1차 실패 7건이 2차에서 모두 통과했다.
이 래퍼는 도구 수준의 정책이고 보안 경계가 아니다. 다른 경로로 `bd.exe`를 직접 실행하는 것까지 막지는 않는다.

## 실제 작업 공간

- `C:\Users\minyeop\project\delft3d-fm-cli-beads\.beads`(작업 트리 밖, 모든 worktree가 공유), prefix `dfm`, Dolt 임베디드.
- `init-workspace` 결과: Git HEAD·index·status·`.git/config`(SHA-256 `39f8dda…7f8f` 전후 동일)·hooks가 바뀌지 않았다.
  origin(GitHub)의 `refs/dolt/*`는 없고, `sync.remote`는 해제됐다.
- 이관 직후 작업자 쓰기(`create`)는 거부됐다(exit 2).

## 이관과 교차 검수 (GRAPH-OPS-P2-MIGRATE-G)

[`seed-20261106.json`](../../workflows/graph/seed-20261106.json)을 [`seed.py`](../../workflows/graph/seed.py)로 한 번 적용했다.
Epic 7개와 Task 39개, 모두 46개 이슈가 만들어졌다. 영수증은 [`beads-seed-20261106.json`](beads-seed-20261106.json)이다
(코드→Beads ID, ready 집합, `dep cycles`, `graph check`). 닫힌 Task는 각각 커밋 또는 동결 파일을 근거로 들며,
그 파일이 실제로 있는지 이관 전에 확인했다.

| DELIVERY.md 현재판(이관 직전) | Beads | 판정 |
| --- | --- | --- |
| GRAPH-OPS: 사용자 승인 → Phase 2 | P2-MIGRATE-G Ready, P3 Blocked | 일치 |
| B06 Ready: 판독기 독립 검수 → G → 실행 프로필 새 구성 | READER-V-Run Ready, READER-G·RUN-PROFILE-I Blocked | 일치 |
| B14 Ready: 실행기 독립 최종 검수 → G → BMI 4진단. 새 구성·공개 direct는 SHORT-CLOSE 뒤 | RUNNER-V-Run·PUBLIC-I Ready, BMI·PUBLIC-V-Run Blocked | 일치(그래프의 RG→BD 간선) |
| S07: 새 구성 → 7사례 | S07-I Ready, V-Run Blocked | 일치 |
| G15: 후보 동결 → 독립 설치 검수 → G | G15-I Ready, 나머지 Blocked | 일치 |
| G18: 새 구성 → 임대 → 6사례 | NATIVE-I Ready, V-Run Blocked | 일치 |
| (현재판에 없음) | B06-RUN-PROFILE-V-Plan Ready | 의도적 추가. V-Plan은 Contract만 있으면 I와 병렬로 진행한다(INTENT §4.3) |

임대가 필요한 Task 6개(`needs-lease`)는 모두 Blocked다. Ready 상태는 실행 허가가 아니다. 네이티브 실행은
여전히 코디네이터의 계획·패키지·판독기 검수와 독점 임대를 거친다.

이관하지 않은 것: 2026-11-06 이전에 승인된 공정(M1–M5, B01–B13, G06–G16 등)은
[공정 기록](history-to-20261106.md)과 검증 노트에 그대로 둔다.
