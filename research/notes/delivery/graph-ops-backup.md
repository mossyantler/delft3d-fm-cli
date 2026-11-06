# Beads 백업과 beads.role (2026-11-06)

사용자 결정(2026-11-06): **Git JSONL + OneDrive Dolt 백업**, `beads.role`은 **maintainer**로 설정.

## 확인한 사실 (bd 1.3.1)

- 자동 백업은 이미 켜져 있었다. `backup.enabled`가 비어 있으면 git remote가 있는 임베디드 작업 공간에서 자동으로
  켜진다. 쓰기 명령 뒤 최대 15분 간격으로 같은 폴더의 `.beads/backup/`(Dolt 형식)에 쓰며, git remote로는
  아무것도 보내지 않는다(소스 `cmd/bd/backup_auto.go`, `backup_export.go`). 작업 공간 폴더를 잃으면 이 백업도 함께 사라진다.
- 실제 작업 공간의 **사본**으로 두 복원 경로를 시험했다. Dolt 백업(`bd backup init/sync` → 새 작업 공간에
  `bd backup restore --force`)과 JSONL(`bd export` → 새 작업 공간에 `bd import`) 모두 46개 이슈의
  ID·제목·상태·유형·라벨·메타데이터·종료 사유·설명·의존성과 ready 집합을 그대로 복원했다.
- JSONL에는 Dolt 내부 변경 이력이 없다. 대신 Git 커밋 이력이 그 역할을 한다.
- 저장소는 공개(GitHub `PUBLIC`)다. JSONL에는 DELIVERY.md와 같은 수준의 공정 내용과 `owner` 이메일이 들어간다.
  그 이메일은 이미 공개 커밋 45개의 작성자 정보에 있다.

## 운영 방식

| 사본 | 위치 | 언제 | 복원 |
| --- | --- | --- | --- |
| 자동 Dolt 백업 | `<작업 공간>/.beads/backup/` | bd가 자동으로(15분 간격) | 같은 폴더의 손상에만 유효 |
| 전체 Dolt 백업 | `%OneDrive%\delft3d-fm-cli-beads-backup` (`DFM_BEADS_BACKUP`로 변경 가능) | 코디네이터가 G Task를 닫은 뒤 `bdw backup-sync` | 아래 절차 A |
| 이슈 JSONL | `research/notes/delivery/beads-state.jsonl` (Git) | 같은 `backup-sync`. 그 노드 커밋에 함께 넣는다 | 아래 절차 B |

`backup-sync`는 코디네이터만, 인자 없이 실행한다. 작업 트리나 작업 공간 안을 백업 대상으로 지정하면 거부하고,
JSONL 줄 수가 `bd count`와 다르면 실패로 보고한다. bdw를 통한 일반 `backup`·`restore`·`import` 명령은 계속 막혀 있다.

## 복원 절차 (작업 공간을 잃었을 때)

복원은 드물게 하는 코디네이터 작업이라 bdw 밖에서 bd를 직접 실행한다. 먼저 살아 있는 Herdr 작업자와
bd 프로세스가 없는지 확인한다.

```powershell
$env:BEADS_DIR = "C:\Users\minyeop\project\delft3d-fm-cli-beads\.beads"
$env:BD_NON_INTERACTIVE = "1"; $env:BD_DISABLE_METRICS = "1"; $env:BD_NO_REMOTE_ADOPT = "1"; $env:BD_NO_INSTALL_HOOKS = "1"
$bd = "research\tools\beads\1.3.1\bd.exe"
$env:DFM_BD_ROLE = "coordinator"; python -m research.workflows.graph.bdw init-workspace   # 빈 작업 공간 생성
# A. 전체 Dolt 백업에서(변경 이력 포함)
& $bd --sandbox backup restore "$env:OneDrive\delft3d-fm-cli-beads-backup" --force
# B. A가 불가능할 때 Git의 JSONL에서
& $bd --sandbox import research\notes\delivery\beads-state.jsonl
python -m research.workflows.graph.bdw count --json; python -m research.workflows.graph.seed report
```

복원 뒤에는 이슈 수와 ready 집합을 마지막 `beads-state.jsonl`과 대조하고, 그 결과를 노드로 기록한다.

## beads.role

`beads.role`(maintainer/contributor)은 우리의 코디네이터/작업자 권한과 관계없다. bd는 이 값을 새 이슈를
기여자 개인의 계획 저장소로 보내는 자동 라우팅(`routing.mode`)에만 쓰는데, 이 프로젝트는 그 라우팅을 설정하지 않았다
(소스 `internal/routing/routing.go`, `cmd/bd/create.go`). 값이 비어 있으면 bd는 origin URL로 추정하고
(SSH이므로 maintainer), 쓰기마다 `beads.role not configured` 경고를 낸다.

2026-11-06에 코디네이터가 `git config --local beads.role maintainer`를 한 번 실행했다. `.git/config` SHA-256은
`39f8dda…7f8f`에서 `fca6076…0132`로 바뀌었고 그 밖의 변경은 없다. 이 파일은 Git이 추적하지 않으며 모든 worktree가 공유한다.
`init-workspace`가 bd init의 같은 쓰기를 되돌리는 것은 그대로 둔다. 초기화가 Git 설정을 몰래 바꾸지 않게 하려는
것이고, 이번 설정은 사용자가 결정해 기록한 별도 변경이다. 다른 컴퓨터에서도 같은 명령을 실행한다.

## I → V → G 기록

| 노드 | 커밋 | 결과 |
| --- | --- | --- |
| GRAPH-OPS-BACKUP-I | `040fc9f` | `bdw backup-sync` 추가. 작성자 시험 13/13 |
| GRAPH-OPS-BACKUP-V | `9251048` | 새 Codex 세션(`gpt-6.1-sol` high)이 [`verify_backup.py`](../../workflows/verification/verify_backup.py)로 37/37, 이전 64건 회귀 통과 |
| GRAPH-OPS-BACKUP-G 1차 | (반려) | 첫 실제 실행이 `no backup destination`으로 거부됐다. Windows의 `os.environ`은 변수 이름을 대문자(`ONEDRIVE`)로 복사하는데 코드는 `OneDrive`를 찾았다. V는 기본 경로를 합성 리졸버로만 시험해서 이 문제를 잡지 못했다 |
| GRAPH-OPS-BACKUP-I rev2 | `842438c` | 대소문자를 무시하고 찾도록 수정. 작성자 시험 14/14 |
| GRAPH-OPS-BACKUP-V 재검증 | 이 노드 | 새 세션이 실제 프로세스 환경 변수로 기본 경로 사례 8건을 추가했다([`verify_backup_rev2.py`](../../workflows/verification/verify_backup_rev2.py)). 45/45, 64/64 통과. 실제 OneDrive에는 쓰지 않았다 |
| GRAPH-OPS-BACKUP-G | 이 노드 | 승인 |

G 근거:
- 첫 실제 `backup-sync`가 `%OneDrive%\delft3d-fm-cli-beads-backup`(1.9MB)와 `beads-state.jsonl`(49개 이슈)을 만들었다.
  Git HEAD·`.git/config`는 그대로였고 origin의 `refs/dolt`도 0개다.
- 두 사본을 각각 새 작업 공간에 복원해 원본과 대조했다. 이슈 49개의 모든 필드와 ready 집합 9개가 같았다.
- 검증 중 V Task의 담당자 잠금 때문에 코디네이터가 종료할 수 없었다. 끝난 세션의 잠금을
  `unclaim --if-assignee`로 풀었고, 이후로는 작업자를 담당자(assignee)로 지정하지 않는다(COORDINATOR.md).
