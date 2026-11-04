# O02 · restart 출력 간격과 계산 완료

`dfm model set MODEL.mdu output/rstinterval 45`는 기존 단일 간격을 초 단위로 바꾸는 미리보기다. 적용에는 해당 MDU의 `before_sha256`이 필요하다. 지원하는 값은 0 또는 `DtUser`에 맞는 양의 정수 초다. 이미 세 값으로 정의한 출력 창을 단일 숫자로 덮어쓰지 않는다.

```powershell
$p = dfm model set .\model.mdu output/rstinterval 45 | ConvertFrom-Json
dfm model set .\model.mdu output/rstinterval 45 --apply --expect-sha256 $p.result.before_sha256
dfm run start .\model.mdu --route direct --restart-policy configured --out ..\run-45
```

실행 폴더는 입력 모델 폴더 밖의 새 경로여야 한다.

기본 `require-final`은 기존처럼 계산 종료 시각의 restart가 없으면 종료 코드 6을 반환한다. 직렬 cold 모델에 명시적으로 `--restart-policy configured`를 지정하면 해당 MDU가 요구한 restart 시각 목록 전체를 실제 NetCDF의 CF 시간축과 대조한다. history와 map의 요청 시간축은 두 정책 모두 검증한다. 종료 시점 restart가 없는 일정이 통과해도 그 시점에서 재시작할 수 있다는 뜻은 아니다.

| 120초 수로의 MDU `RstInterval` | 직접 FM과 DIMR에서 읽은 실제 restart 시각(초) | 120초 checkpoint |
| --- | --- | --- |
| `30` | 0, 30, 60, 90, 120 | 있음 |
| `45` | 0, 45, 90, 120 | 있음 |
| `0` | 파일 없음 | 없음 |
| `30 30 90` (기존 출력 창) | 0, 30, 60, 90 | 없음 |

0초 파일과 창 종료 시각은 간격으로 단순 나눗셈해 추측하지 않았다. 고정한 FM 소스에는 [창 기본값 선택](https://github.com/Deltares/Delft3D/blob/5a4649830b1e5072caf019fb4850bbdefd9ad431/src/engines_gpl/dflowfm/packages/dflowfm_kernel/src/dflowfm_data/unstruc_model.f90#L4164), [첫 출력 시각 초기화](https://github.com/Deltares/Delft3D/blob/5a4649830b1e5072caf019fb4850bbdefd9ad431/src/engines_gpl/dflowfm/packages/dflowfm_kernel/src/dflowfm_data/m_flowtimes.f90#L318), [양수 간격과 마지막 출력 시각 처리](https://github.com/Deltares/Delft3D/blob/5a4649830b1e5072caf019fb4850bbdefd9ad431/src/engines_gpl/dflowfm/packages/dflowfm_kernel/src/dflowfm_manager/flow_externaloutput.F90#L255)가 나뉘어 있다. 설치 엔진 자체의 소스 커밋은 알려지지 않았다.

[독립 시험](../../experiments/O02-V-native-slot78-20261104-01/verification.json)과 [통합 시험](../../experiments/O02-G-cadence-tree-01/verification.json)에서 각각 네 입력 × 두 경로로 8회 실행했다. [통합자의 원자료 대조](../../experiments/O02-G-cadence-tree-01/coordinator-raw.json)에서 8개 실행의 history 57변수·map 34변수 값과 마스크가 모두 같았다. 각 실행에서 실제 Job 멤버 2개의 종료를 보존한 핸들로 확인했고 Job은 비었다. [별도 오류 대조](../../experiments/O02-G-archive-audit-01/verification.json)에서 누락·중복·이동한 CF 시각, 한 파일의 여러 시각 및 비활성 상태의 추가 파일을 거부했다.

재현은 [독립 검증기](../../workflows/verification/verify_output_schedule.py)에 M3 기준 입력 폴더와 새 결과 폴더를 준다. 기본값은 입력 준비이며 실제 실행에는 `--native --native-slot N --install SUITE`가 필요하다. GUI의 restart 입력 대화상자, 다중 rank와 결합 모델의 일정, checkpoint 내용에서의 재개 가능 여부는 별도 시험 대상이다.
