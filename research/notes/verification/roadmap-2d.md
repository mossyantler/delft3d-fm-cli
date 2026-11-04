# 2D 로드맵: 공개 명령과 네이티브 증거

환경은 Windows, Delft3D FM Suite 2026.02 OpenHMWQ다. 이 문서의 실험은 사용자 프로젝트를 열지 않는다. 각 실험은 새 폴더를 사용한다. 파일 이름만으로 성공을 판정하지 않고 입력 바이트와 실제 NetCDF 데이터를 읽는다. 노드별 최종 승인 상태는 [공정표](../../../DELIVERY.md), 원본 검수 기록의 SHA-256은 [검수 색인](../../catalog/roadmap-2d-gates.json)에 있다.

## M1: 지원점 조회 → 한 셀 편집 → 두 번의 계산

원본은 [E001/E002](../replay/export-experiment.md)의 `console-export-1`이다. [E005](../replay/edit-experiment.md)의 콘솔 편집과 동일한 물리량을 공개 CLI로 바꾼다. 예시는 **복사본**을 가리킨다.

```powershell
$mdu = 'C:/models/copied-case/f34.mdu'
dfm boundary inspect $mdu
$select = @('--point', 'L1_0001', '--period-minutes', '750', '--amplitude-m', '1.75')
$preview = dfm boundary set $mdu @select | ConvertFrom-Json
dfm boundary set $mdu @select --apply --expect-sha256 $preview.result.input_sha256
```

`input_sha256`는 지원점을 결정한 입력의 지문이다. `before_sha256`는 BC 단일 파일의 해시이므로 적용 인자로 대신 쓰지 않는다. 적용 시 입력이 바뀌면 쓰지 않는다. 위상은 도, 주기는 분, 진폭은 미터다. BC 블록이 없는 PLI 점에서 진폭을 0으로 추정하지 않는다.

**실험:** `research/experiments/M1-boundary-independent-20261104-01`. 기준군과 변경군을 각각 독립된 폴더로 복사하고 공개 `model set`으로 모의기간 600초, history/map 간격 60초를 지정했다. 두 폴더의 10개 입력을 비교했다. 변경 전에는 모두 같았고, 경계 적용 후에는 `f34_001.bc` 15행의 바이트 오프셋 [488,491)에 있던 `1.5`만 `1.75`로 바뀌었다. PLI 13점 중 신호가 있는 점은 1·7·13번이다.

두 direct FM 실행 모두 history와 map에서 **0, 60, …, 600초**가, 최종 restart에서 **1990-08-05 00:10:00**이 확인됐다. 원본과 두 모델 입력 모두 실행으로 바뀌지 않았다. [독립 재현기](../../workflows/verification/verify_boundary.py)는 입력별 SHA-256, 실행 명령, manifest, 실제 CF 시간축을 새 출력 폴더의 `verification.json`에 남긴다.

```powershell
.venv/Scripts/python.exe -m research.workflows.verification.verify_boundary --baseline <export-folder> --install <suite-root> --out <new-folder>
```

## M2 통합 대조: 편집이 어느 관측점에 나타나는가

위 실험의 `baseline-direct`와 `current-direct`를 차례로 LEFT/RIGHT로 사용했다. `dfm results compare LEFT RIGHT --variable waterlevel`의 차이는 **RIGHT − LEFT**다. 별도로 두 history 파일의 `waterlevel`과 관측점 ID를 NetCDF로 직접 읽어 공개 명령의 **5개 관측점 × 11개 시각 = 55개** 차이가 일치하는지 대조했다.

| 관측점 | 600초 구간의 최대 절대 차이 (m) |
| --- | ---: |
| W1 | 0.0004703998565673828 |
| W2 | 0.0000013113021850585938 |
| W3, W4, W5 | 0 |

이는 저장된 11시각의 출력값 차이다. 경계 진폭 변화가 모든 관측점에 똑같이 나타난다는 뜻도, 짧은 계산만으로 모델의 물리적 타당성을 검증했다는 뜻도 아니다.

[독립 결과 검증기](../../workflows/verification/verify_results.py)는 두 history와 두 map을 입력으로 받는다. 최종 검수에서는 공개 명령 34회로 JSON/CSV, 두 시나리오의 면(222)·링크(415)·절점(258) 변수 추출, 차이가 0인 경우까지 직접 판독값과 대조했다. 네 원본 NetCDF의 해시는 그대로였다.

## M3: 제공한 격자에서 새 모델 만들기

`dfm model create SPEC --out NEW_DIRECTORY`는 [입력 명세 예시](../../../examples/channel/model.json)의 JSON과 UGRID 격자를 읽어 상대경로만 쓰는 MDU·EXT·BC·PLI·관측점·출처 기록을 만든다. 이 사례에서 검증한 좌표계는 EPSG:32631이며 바닥고는 위쪽이 양수인 m다. 입력 명세에는 수직 기준, 초기 수위, UTC 기간, 경계 신호 단위와 시간 범위를 명시한다.

[독립 합성 격자](../../workflows/verification/channel_fixture.py)로 120 × 40 m 수로(65절점·48셀, 바닥고 −3 m)를 새로 만들었다. 원래 위치를 비운 뒤 이동된 폴더에서 실행했다. 경계는 서쪽 조화 수위와 동쪽 시계열 수위다. native map의 셀 바닥고가 −3 m였고, history/map은 0–120초를 10초 간격으로 기록했다. 최종 restart는 120초였으며, 관측점 두 곳의 JSON·CSV가 원본과 일치했다. 단위·중복 ID·시간 범위·공간 위치 등 12개 잘못된 명세는 폴더를 발행하기 전에 거부됐다. 첫 실험에서는 MDU의 `program` 값을 엔진이 거부했다. 수정 후 실제 실행으로 재검증했다.

```powershell
.venv/Scripts/python.exe -m research.workflows.verification.verify_create --out <new-folder> --native-slot-granted --install <suite-root>
```

**최종 검수 원본:** 로컬 `research/experiments/` 아래 `M1-G-coordinator-final-01`, `M2-G-coordinator-final-01`, `M3-G-coordinator-final-01`의 각 `verification.json`. 통합 담당자가 각각 새 폴더에 다시 실행했다. 첫 M3 실패도 `M3-V-native-20261104-162944-1f43fbd3`에 남겼다. 기존 f34의 투영 경고와 새 수로의 출력 설정 경고는 삭제하지 않았다.

## M4: 격자 교체 후 엔진이 사용한 공간 입력 확인

`dfm mesh build SPEC --out NEW`는 쓰기 전에 격자·공간 입력과 품질을 계산한다. `--apply --expect-sha256 HASH`로 새 폴더에 UGRID와 MDU 설정을 발행한다. [기본 명세](../../../examples/channel/mesh.json)의 `crs`, 수직 기준, 초기 수위, Manning 계수를 모델 명세에도 일치시켜 `model create`로 입력을 만든다. `mesh inspect NET.nc`는 지원하는 망의 연결·면적·품질을 읽는다. 지원 범위는 평면 2D로, 임의 해안선·측량 기준 변환·모든 RGFGRID 연산을 보장하지 않는다.

| 독립 검사 | 최종 결과 |
| --- | --- |
| 공간 연결·세분화 | 원래 48셀/65절점 → 76셀/81절점, 총면적 4,800 m² 유지. 선택 구역 안 16개 셀의 면적은 각각 최대 25 m². 같은 행의 먼 셀 정점은 그대로이며 T자 접합과 미사용 절점이 없다. |
| 입력의 실제 소비 | native map 초기 수위 0.25 m, 셀 바닥고 −3.00~−2.83 m, 링크 Manning 계수 0.041(1,716개 값) 확인. 이 사례의 `BedlevType=3, Conveyance2D=1`에서는 노드 값의 단순 평균이 셀 바닥고가 아니다. |
| 시간축 | 세분화한 격자로 모델을 다시 만들고 실행해 history/map 13시각(0~120초), 최종 restart 120초 확인. |
| E006 GUI 자료 | E001에서 실제 내보낸 f34 망과 가져오기 전 망의 파일 해시가 같았다. 수평 EPSG:28992와 Z 단위 m·positive=up은 저장됐지만 수직 datum은 선언되지 않았다. 이를 NAP 등으로 임의 지정할 수 없다. |

[독립 공간 검증기](../../workflows/verification/verify_mesh.py)의 별도 수치·연결 검사와 최종 재실행: `research/experiments/M4-G-coordinator-final-01/verification.json`. 첫 세분화 구현의 영역 밖 변경과, 셀 바닥고를 잘못 평균한 초기 검증기 결과는 이 최종 판정의 근거로 쓰지 않았다.

## M5: 확장 직렬 프로필·실제 진행 시각·취소

기존 `run start`의 기본값은 여전히 최대 600초다. `--profile extended`는 지원하는 2D 수위 forcing·면/절점 수·출력량·기간을 먼저 검사한다. 이번 기준 수로에서는 동쪽 시계열의 끝을 실제 1,200초까지 연장했다. 기간을 바꾸고 forcing이 짧게 남은 사례는 엔진 실행 전에 거부됐다. 프로필 상한 7일은 이 실험에서 검증한 기간이 아니다.

독립 검증 및 최종 재현기: [verify_extended.py](../../workflows/verification/verify_extended.py). 새 수로를 `--progress`로 실행해 직접 읽은 NetCDF에서 history(10초 간격, 121개)·map(60초 간격, 21개)·마지막 restart가 모두 1,200초에 도달했음을 확인했다. `run status`는 엔진의 `Sim. time done` 열을 읽고 stdout 오프셋과 원본 행을 표시한다. 제어기의 경과 시간과 엔진의 단계 수 추정 백분율은 다른 값이며, 관측된 마지막 로그 시각은 완료 증거가 아니다. GUI 표시 시각과의 대조는 별도다.

첫 취소 시험에서는 job 종료가 확인됐는데도 Windows가 읽기 중인 manifest의 교체를 거절해 `stopping`이 남았다. 원본 실패는 `M5-V-native-20261104-01`에 보존했다. 기존 쓰기 가능한 메타데이터의 Windows 공유 충돌만 제한 시간 안에서 재시도하도록 수정했다. 독립 재현 `M5-V-native-20261104-02` 및 최종 검수 `M5-G-coordinator-final-01`에서 취소와 시간 초과는 각각 `cancelled`·`timed_out`으로 기록됐고, 부분 출력은 완료로 인정되지 않았다. 대상과 동일한 실행 파일의 대조 프로세스는 대상 취소 후에도 생존했다.

```powershell
.venv/Scripts/python.exe -m research.workflows.verification.verify_extended --baseline <relocated-M3-inputs> --out <new-folder> --install <suite-root> --native-slot-granted
```
