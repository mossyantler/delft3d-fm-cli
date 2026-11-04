# E012: 두 rank의 완료와 병합 결과는 별도다

Windows 2026.02 OpenHMWQ에서 합성 수로(48셀)를 로컬 두 rank로 120초 실행했다. 독립 시험 4와 새 통합 시험 모두 직렬 대조·출력 재조립·취소 격리를 통과했다. 아래 첫 세 시험은 어떤 경로가 실패했는지 보존한 기록이다.

| 단계 | 설치본에서 직접 확인한 결과 |
| --- | --- |
| 로컬 MPI 실행 인자 | 첫 시험에서 `mpiexec.exe`가 `-noprompt`를 거부했다. 도움말이나 다른 MPI 배포판의 옵션을 이 설치에 적용할 수 없었다. |
| 자식 프로세스 소유와 통신 | 두 번째 시험은 두 rank를 소유 job에서 확인했지만 DIMR이 PMI 통신 핸들을 받지 못해 `MPI_Init`에서 실패했다. 세 번째 시험은 검증한 PMI 핸들만 상속했다. rank 0·1의 guard와 DIMR 각각의 종료를 보관한 핸들로 확인했다. |
| 계산 결과 | 각 rank의 map과 최종 restart가 120초에 도달했다. 두 rank의 최종 restart는 각각 변수 39개와 시간값 120초 한 개를 담았다. |
| 병합 | 설치본 `dfmoutput mapmerge`가 쓴 병합 restart에는 `time`·`timestep` **두 변수만** 있었고 시간 차원의 길이가 0이었다. 상태 배열도 없으므로 시각을 채워 넣는 것으로 복구할 수 없다. 직렬 기준의 최종 restart에는 34개 변수가 있었다. |

세 번째 실행의 `mpi/manifest.json`은 rank 계산에 한해 `completed`이고, `assembled/manifest.json`과 독립 검증은 `failed`다. 이 시험으로 조립된 입력에서 다시 시작할 수 있다거나, 합친 필드 전체가 직렬과 일치한다거나, MPI 취소 격리가 검증됐다고 보지 않는다.

[독립 검증기](../../workflows/verification/verify_parallel.py). 로컬 원본은 `research/experiments/E012-V-native-20261104-{01,02,03}/`이며, 세 번째 `verification.json`의 SHA-256은 `d8f8f8b4bf54bff508179fdb4ae2bc10e7c50f4c08a6a29170263a18a1ccffed`다. 비교 허용오차 선언은 실행 전에 기록해 둔 `comparison-plan.json`에 있다.

후속 **오프라인 재조립**은 실패한 병합 파일을 덮어쓰지 않고 두 rank의 원본 restart·망·map 및 전역 입력망을 사용했다. 새 restart에서 120초의 시각 한 개와 원본 변수 39개 전부를 다시 읽었다. 노드 좌표 및 CRS 정보를 포함하면 43개다. 기록은 `research/experiments/E012-G-checkpoint-offline-01/verification.json`, 생성 파일 SHA-256은 `09cc5c03b74691fa0cade5c50117863c91053db5fe79fde0a3fc68889b1da3d0`이다. 직렬과의 수치 동등성, 이 파일을 읽는 후속 엔진 계산, MPI 취소 격리는 이 검사 결과에 포함되지 않는다.

**네 번째 독립 시험과 통합 재현.** `E012-V-native-20261104-04` 이후 통합자가 새 복사본으로 분할부터 다시 실행했다. `E012-G-coordinator-final-01/verification.json`의 SHA-256은 `d2ea5866973fed95761fa27db4dcfb0108c64dfce6fea3ad7db75805e5a1a811`이다. 두 rank의 map과 최종 restart는 모두 120초에 도달했다. 미리 정한 허용오차에서 직렬 대비 history 4변수와 map 5변수가 통과했다. 수위 차이는 0이었고, 112개 edge의 방향과 면·변수 마스크도 대조했다. 최종 restart는 39개 입력 변수를 보존하고 72개 배열 대조를 무오차로 통과했다. 원본 48개 셀 중심을 좌표로 정렬해 직렬 restart와 별도로 대조한 `s1/s0/ucx/ucy`의 최대 절대 차이는 각각 6.60×10⁻¹⁷ m, 5.21×10⁻¹⁷ m, 1.12×10⁻¹⁶ m/s, 4.89×10⁻¹⁷ m/s 이하였다.

취소 요청을 받은 실행의 job 구성원 종료를 확인한 뒤에도 별도의 같은 `dimr.exe` 대조 프로세스는 같은 PID·생성 시각으로 살아 있었다. 기준 입력·준비된 입력·대조 기준 파일의 지문은 변하지 않았다. 검수 범위는 이 로컬 2-rank 수로다. 이 첫 E012 시험에서는 조립한 restart로 이어 계산하지 않았다. 아래 E012-R에서 그 경로를 따로 시험했다. 다른 rank 수나 여러 호스트, GUI 분할기와의 동등성은 확인하지 않았다.

재현: `python -m research.workflows.verification.verify_parallel --baseline <M3의-이동된-수로-입력> --install <suite> --out <새-폴더> --native-slot <할당한-슬롯>`. 슬롯을 생략하면 입력 준비와 읽기 검사만 한다.

**실제 이어 계산 준비(E012-R).** 공개 `dfm restart prepare ASSEMBLED MDU --assembled --stop YYYYMMDDhhmmss --out NEW`는 기존 직렬 부모 검사와 분리했다. 조립 manifest와 원래의 두 rank, FM 라이브러리, 전역 격자·입력·실제 배열을 다시 확인하며 다른 경계 신호로 바꿔 끼우지 않는다. `E012-R-G-interface-01`에서 기존 120초 모델을 240초로 잇는 미리보기는 `insufficient_restart_forcing: east_0001`로 쓰기 전에 거절됐다. 이 거절은 원본 조립이 손상됐다는 뜻이 아니다. 동일한 입력으로 연속·분할 계산을 비교하려면 첫 실행의 경계 입력부터 후속 시각을 포함해야 한다.

**후속 실측(E012-R, 48셀).** 처음부터 240초까지의 경계 신호를 준 별도 수로에서, 두 rank가 120초에 쓴 restart를 조립했다. 직렬 FM이 이 파일을 읽어 240초에 도달했고, 연속 계산과의 최종 checkpoint 비교를 통과했다. 그러나 중간 history·map까지 포함한 원본 배열 비교는 통과하지 않았다. [보관한 시험 판정](../../experiments/E012-R-V-native-slot54-20261104-01/handoff.json)과 [변수별 차이](../../experiments/E012-R-V-native-slot54-20261104-01/raw-difference-detail.json)를 구분해 본다. CLI 소스 동결 검사도 실패했으므로 이 기록은 전체 기능 승인이나 GUI 실행 증거가 아니다. 재현기는 [이어 계산 검증 모듈](../../workflows/verification/verify_parallel_continuation_replay.py)이다.

**통합 재현.** `E012-R-G-continuation-01`에서는 제품과 검증기를 별도 스냅샷에서 실행했다. 시작 전후 제품 지문은 같고, 6개 모의와 분할·조립 작업은 모두 종료됐으며 Job은 비었다. 조립본을 읽은 120초 초기 수위와 같은 시각 cold 대조군의 차이는 최대 0.0439756 m였다. 240초 최종 restart 34개 변수는 모두 선언된 오차 안에 들었다. 원본을 다시 읽으면 정확히 같은 변수는 16개이고 나머지 18개에는 부동소수점 차이가 있다. 모든 history/map을 포함한 비교는 실패했다. 두 재시작(직렬/조립본) 사이에도 `water_balance_volume_error`가 달랐다. [전체 변수 판정](../../experiments/E012-R-G-continuation-01/verification.json), [원본 대조](../../experiments/E012-R-G-continuation-01/coordinator-raw.json), [작업 종료 기록](../../experiments/E012-R-G-continuation-01/release-summary.json).
