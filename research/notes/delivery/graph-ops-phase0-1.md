# GRAPH-OPS Phase 0·1 보고 (2026-11-06)

[INTENT](../../../INTENT.md) §12의 Phase 0(현황 점검)과 Phase 1(격리된 Beads 시험) 결과다.
§15가 요구한 Phase 2 이관 전 보고 항목을 이 순서로 정리했다. 제품 코드 변경, 네이티브 실행,
원격 동기화, 실제 공정표 이관은 하지 않았다.

- 시험 도구: [`beads_trial.py`](../../workflows/verification/beads_trial.py)
- 원시 기록(로컬, Git 제외): `research/experiments/GRAPH-OPS-P1-20261106-01/` 안의 `verification.json`(검사 15/15 통과)과 `calls.json`(bd·git 호출 전체)
- 재현: `python -m research.workflows.verification.beads_trial --bd research/tools/beads/1.3.1/bd.exe --out research/experiments/<새 폴더>`

## 1. 확인된 현재 개발·승인 상태

| 항목 | 관찰값 |
| --- | --- |
| 제품 기준점 | `SHORT-CLOSE-ROOT-G` `df447d8`. 세부는 [공정표](../../../DELIVERY.md)의 승인 기준점 |
| Git | `main` 하나, worktree 없음. origin은 `git@github.com:mossyantler/delft3d-fm-cli.git`, `origin/main` = `607c61c`. 로컬은 문서 커밋 `19cbd35`·`04aba08`만큼 앞서 있고 푸시하지 않았다 |
| 활성 Epic | B06, B14, S07, G15, G18. 모두 체크포인트 후보와 I/V/G 관문이 남아 있다 |
| Herdr | 0.9.5, protocol 22, 서버 실행 중. 살아 있는 에이전트는 이 코디네이터 세션(`w2:pA`) 하나뿐이고 다른 작업자는 없다 |
| 네이티브 | 엔진 프로세스 없음. 슬롯은 `idle232`([release231.json](../../proposals/short-close-native-gates/release231.json)). 사용자의 `DeltaShell.Gui`가 실행 중이며 조사 대상이 아니라 손대지 않았다 |
| 검증 관문 | 테스트 모듈 107개(정적 집계 `def test_` 1,718개), `verify_*.py` 143개, `research/catalog/*gate*.json` 21개. 최근 전체 회귀는 1,715개 실행 |

**바꾸면 안 되는 범위:** `src/` 아래 191파일(wheel 동일성 검사 대상), 체크포인트 343파일,
`research/proposals/`의 검수 영수증, I/V/G 체계, 네이티브 임대 규칙, 공용 Git 직렬화, 기존 회귀 단언.

### 실행기와 모델 (§6.3)

| 실행기 | 버전 | 기본 설정 | 비고 |
| --- | --- | --- | --- |
| Codex CLI | 0.166.0 | `gpt-6.1-sol`, `high`, `approval_policy=never`, `danger-full-access` | opencodex 카탈로그에 `gpt-6-luna`, `gpt-6.1-terra`, `gpt-6.1-sol`, `gpt-6-astra` 등이 **올라 있음**(호출 검증 아님). Astra 항목은 `xhigh`도 광고하므로 §6.8의 `high` 상한을 호출 전에 강제해야 한다 |
| Claude Code | 2.1.318 | `~/.claude/settings.json`의 `model: "opus"` | `--model` 없이 시작하면 프리미엄 Opus가 기본이다. premium `default_assignment: false`와 충돌하므로 **항상 `--model`을 명시**한다. 관찰된 ID: `claude-sonnet-5-5`(2026-11-05), `claude-opus-5-5`(이 세션). Haiku·Fable은 미검증 |

YAML의 `availability_verified`는 아직 모두 `false`로 둔다. 첫 배정 때 시작 배너와 실제 모델 ID를
확인해 기록한 뒤에만 `true`로 바꾼다.

## 2. 기존 시스템과의 충돌 가능성

Phase 1에서 실제로 관찰한 내용이다(bd 1.3.1, `--sandbox`, 메트릭·hook·원격 채택을 끈 환경 변수 사용).

| 위험 | 관찰 | 대응 |
| --- | --- | --- |
| **자동 Git 커밋** | 작업 트리 안에서 `bd init --quiet --skip-agents --skip-hooks`를 실행해도 `bd init: initialize beads issue tracking` 커밋을 만든다. 이미 stage돼 있던 **다른 작업자의 파일까지 함께 커밋했다**. 루트 `.gitignore`도 수정한다(소스 `cmd/bd/init.go:2152`의 `!stealth && isGitRepo() && useLocalBeads` 조건) | `BEADS_DIR`를 작업 트리 밖에 둔다. 이렇게 하면 커밋, `.gitignore`, AGENTS.md, hook, origin이 모두 그대로였다 |
| **원격 동기화** | 두 방식 모두 init이 git origin을 `sync.remote`로 설정한다. 이번 시험에서는 origin에 `refs/dolt/*`가 생기지 않았다(로컬 bare origin, 무샌드박스 쓰기 1회 포함) | 실제 저장소의 origin은 GitHub다. 이관 시 `sync.remote`를 해제하고 모든 호출에 `--sandbox`와 `BD_NO_REMOTE_ADOPT=1`을 쓴다. `bd sync`·`bd dolt push`는 별도 승인 없이 쓰지 않는다. 이관 뒤 `git ls-remote origin`에 `refs/dolt`가 없는지 확인한다 |
| 사용 통계 전송 | 기본값이 켜짐(`gastownhall-eventsapi.com`) | `BD_DISABLE_METRICS=1`. 전역 `bd metrics off`는 사용자 판단으로 남긴다 |
| 에이전트 지침 생성 | 기본 init은 AGENTS.md·Claude/Codex 설정을 만들거나 고친다 | `--skip-agents`. 시험에서 AGENTS.md는 그대로였다 |
| Worktree 탐색 | 작업 트리 밖 `BEADS_DIR`를 쓰면 worktree에서 `BEADS_DIR` 없이는 `no beads database found` | Herdr로 시작하는 모든 pane에 같은 `BEADS_DIR`를 넘긴다 |
| 단일 Writer | 기본은 누구나 쓸 수 있다 | 작업자 호출에 전역 `--readonly`. 시험에서 쓰기가 거부되고 상태가 유지됐다. 지침 외에 래퍼에서도 강제한다 |
| `bd doctor` | 임베디드 모드에서 미지원(`--check=artifacts/conventions/pollution`만 가능) | 무결성 확인은 `bd graph check`, `bd dep cycles`로 한다 |
| 오래된 dispatch | 체크포인트 `dispatch.json`은 `idle228`, `paused_by_explicit_user_request`로 남아 있다(불변 기록) | 이관 시 슬롯과 실행 정책은 최신 G 영수증(`release231.json`)에서 가져온다 |

## 3. Beads 도입 시 변경될 파일

- **저장소 안(커밋 대상):** COORDINATOR.md의 전환 현황과 Beads 운영 규칙, DELIVERY.md(활성 상태를
  Beads로 넘기고 승인 기록·생성 보고만 유지), RESUME.md, 래퍼 스크립트 하나(§5), 이 보고서.
- **저장소 밖 또는 Git 제외:** Beads 데이터베이스(`BEADS_DIR`), `research/tools/beads/1.3.1/bd.exe`.
- **바뀌지 않음:** `.gitignore`, git hooks, AGENTS.md 생성물, `src/`, 체크포인트, 기존 영수증.

## 4. 실제 작업 분배와 상태 관리 방법

1. 코디네이터만 쓰기 가능한 `bd`를 쓴다. 작업자는 `--readonly`로 자기 Task만 읽는다.
2. Epic마다 `<CODE>-Contract/-I/-V-Plan/-V-Run/-G`를 만들고 프로젝트 코드는 `metadata.task_code`에 둔다
   (시험에서 보존 확인). 의존성은 `--deps blocked-by:`로 명시한다.
3. 다음 작업은 `bd ready --json --exclude-type epic`으로 고른다. epic은 의존성이 없으면 ready 목록에 섞여 나온다.
4. Epic은 하위 Task가 모두 닫혀도 자동으로 닫히지 않는다(시험 관찰). 따라서 승인은 G Task를 닫는 것으로만
   표현되고, 이는 INTENT §4.4와 일치한다.
5. 하위 공정은 상위 G Task에만 막힌다. 시험에서 `B14-I`는 `B06-G`가 닫힌 뒤에만 ready가 됐다.
6. 배정은 Herdr pane에 Task Packet(COORDINATOR.md)으로 전달하고, 결과 영수증을 확인한 뒤 코디네이터가 닫는다.

## 5. 새로 추가해야 할 최소 설정·스크립트

- `bd` 래퍼 하나(Python 또는 PowerShell). 하는 일: 고정 `bd.exe` 경로와 SHA-256 확인, `BEADS_DIR`·`BD_DISABLE_METRICS`·
  `BD_NO_INSTALL_HOOKS`·`BD_NO_REMOTE_ADOPT`·`BD_NON_INTERACTIVE` 설정, 항상 `--sandbox`, 역할이 coordinator가
  아니면 `--readonly`, `sync`·`dolt push`·`init --reinit-local`·`--discard-remote`·`compact`·`cleanup` 거부.
- `BEADS_DIR` 위치 결정: 작업 트리 밖이면서 모든 worktree가 공유하는 경로(예: 저장소 옆 디렉터리).
- 초기에는 이 밖의 서버·데이터베이스·GUI를 추가하지 않는다(INTENT §3.2).

## 6. 자동 검증 범위

`beads_trial.py`가 결정론적으로 확인한 범위다.

- init이 Git 기록, `.gitignore`, AGENTS.md, hook, origin을 바꾸지 않음(외부 `BEADS_DIR`)
- 순환 의존성 추가 거부, `dep cycles` 없음, `graph check` 통과
- Contract → I ∥ V-Plan → V-Run → G → 하위 Epic의 ready 집합 6단계가 모두 기대와 일치
- `bd blocked`의 시작 시점 목록, 메타데이터 보존, worktree 공유, `--readonly` 쓰기 거부, 남은 dolt 프로세스 없음

다루지 않은 범위: 동시 쓰기 경쟁, Dolt 서버 모드, 원격 동기화, 실제 공정 데이터 이관, Herdr와의 연동,
모델 호출. Python 테스트 통과는 공정 이관의 정확성을 보장하지 않는다.

## 7. Phase 2 진행을 위한 선행 조건

1. 이 보고에 대한 사용자 승인.
2. `BEADS_DIR` 위치와 래퍼(§5)를 결정하고 구현한다. 래퍼에 대한 독립 검증(V)을 받는다.
3. 실제 저장소에서 init한 직후 `sync.remote`를 해제하고, origin에 `refs/dolt`가 없는지 확인한다.
4. 이관할 범위를 정한다. 활성 Epic 5개와 GRAPH-OPS, 각 Task의 근거 영수증·선행 G를 정리한다.
   승인 완료 이력은 이관하지 않고 기록 문서에 둔다.
5. 이관 결과를 교차 검수한다. Beads의 ready/blocked 결과가 DELIVERY.md 현재판과 일치해야 하고,
   일치를 확인한 뒤에만 DELIVERY.md에 전환 시점을 기록한다.
6. Herdr 시작 절차에 `BEADS_DIR` 전달과 `--model` 명시를 추가한다.
