# B12 · 계산 전 경계 입력 미리보기

`dfm boundary preview`는 2D MDU → 새 EXT의 경계 → 위치 PLI와 신호 BC를 따라간다. 계산 전 한 지원점에 입력된 원자료와, 그 자료에서 지정한 시각의 값을 구한다. 격자나 결과 파일, 설치 엔진, NetCDF 라이브러리가 없어도 된다.

다음은 E001/E002에서 내보낸 f34 복사본의 예다. `--time`을 생략하면 자료 목록만 반환한다.

```powershell
dfm boundary preview f34.mdu --boundary L1 --signals all --row-limit 0
dfm boundary preview f34.mdu --boundary L1 --point L1_0001 --quantity waterlevelbnd --time 0 --time 11250 --time 22500 --time-unit 'seconds since 1990-08-05 00:00:00 +00:00'
```

프로토콜 2의 `result.signals[].authored`에는 원본 파일·행·열·단위와 발췌가 있고, `evaluation.samples[]`에는 시각별 값과 계산 방법이 있다. 명시된 상수, 선형 시계열, 한 조화 블록의 주기·진폭·위상만 계산한다. 시계열은 원래 시각과 두 행 사이 보간을 구분하고 범위 밖으로 외삽하지 않는다. 요청과 시계열 자료의 시간 원점은 명시적인 UTC, 모델은 `TZone=0`이어야 값을 계산한다. `--signals all`에서 신호가 없는 점은 `missing`과 null로 남는다. `active`는 내보낸 파일의 연결 여부이며 GUI에서 켠 데이터셋인지 알려주는 표시가 아니다.

| 공개 명령으로 확인한 입력 | 독립 대조 결과 |
| --- | --- |
| f34의 `L1_0001`, 주기 750분 | 0·¼·½·¾·1 주기의 값이 1.5, 약 0, −1.5, 약 0, 1.5 m. `L1_0002`의 신호는 없음. |
| 별도 수로 동쪽, 120초 동안 0 → 0.12 m | 0·30·60·90·120초에 0, 0.03, 0.06, 0.09, 0.12 m. 처음과 끝은 원래 행, 중간 세 값은 보간. |
| 서쪽 10분 주기, 위상 90°, 다른 BC 파일에 같은 점 이름의 미연결 보정 블록 추가 | 수정 전에는 서쪽 값이 사라졌다. 수정 후에는 서쪽이 두 경우 모두 30초에 0.0154508497 m. 서쪽 BC 자체에 보정이 있으면 추측하지 않고 `unsupported`와 null을 반환. 세 경우 모두 조회 전후 입력 해시 동일. |

공개 소스의 [파일별 BC 선택](https://github.com/Deltares/Delft3D/blob/5a4649830b1e5072caf019fb4850bbdefd9ad431/src/utils_lgpl/ec_module/packages/ec_module/src/ec_bcreader.f90#L167)과 [조화 성분 계산](https://github.com/Deltares/Delft3D/blob/5a4649830b1e5072caf019fb4850bbdefd9ad431/src/utils_lgpl/ec_module/packages/ec_module/src/ec_converter.f90#L2275)을 참고했다. 천문 분조·보정 합성, 점 사이 공간 보간, 여러 GUI 신호의 합, 설치 엔진 시계에서의 수치 일치는 이 검수 범위 밖이다. T3D 값은 [전용 명령](layers.md#b13)으로 조회한다.

[검수 기록과 SHA-256](../../catalog/boundary-preview-gate.json). 선택적 수치 라이브러리 없이 설치한 wheel에서 독립 시험 37건과 공개 명령 18회(13개 검사)를 통과했다. 통합자가 별도 수로·f34 및 두 BC 파일 사례를 다시 확인했다. 동일한 입력 계산은 저장소 루트에서 `.venv/Scripts/python.exe -m unittest discover -s tests -p 'test_boundary_preview*.py' -v`로 검증할 수 있다. 실제 엔진의 처방 수위 배열과 GUI 곡선은 각각 별도 시험 대상이다.

<a id="native-209"></a>

**설치 FM과 직접 비교한 결과(#209).** 12 × 4 셀 수로에서 양쪽 경계의 지원점 네 곳에 같은 신호를 주고, 120초짜리 직접 FM BMI 계산 세 건을 수행했다. 미리 정한 0·1·7·17·31·40·61·97·120초에 [처방 수위 배열 `zbndz`](https://github.com/Deltares/Delft3D/blob/5a4649830b1e5072caf019fb4850bbdefd9ad431/src/engines_gpl/dflowfm/packages/dflowfm_lib/include/bmi_get_var.inc#L173)의 원소 8개를 모두 복사했다. 값을 읽기 전후 엔진 시각은 같았다. 각 시각의 CLI 입력값과 원소별로 비교했고 공간 평균이나 관측점 출력은 사용하지 않았다. 허용 절대 오차는 사전에 정한 10⁻⁸ m였다.

| 입력 | 0초: 파일 계산값 → 초기화 직후의 엔진값 | 1–120초의 8개 측정 시각 | 전체 판정 |
| --- | --- | --- | --- |
| 선형: 0.20 → 0.60 → −0.20 m | 0.20 → 0.2100000024 m | 최대 오차 2.36 × 10⁻⁹ m | 0초 불일치 |
| 조화: 주기 1분, 진폭 0.10 m, 위상 60° | 0.05 → 0.0587785252 m | 최대 오차 6.25 × 10⁻¹⁷ m | 0초 불일치 |
| 양 끝값이 0.15 m인 선형 시계열 | 0.15 → 0.15 m | 모두 일치 | 통과. BC의 별도 `Function=constant` 시험은 아님 |

세 실행 모두 초기화·종료가 한 번씩 이뤄졌고, 원래 Job 핸들로 멤버 총 6개의 종료와 세 Job의 닫기를 확인했다. [재현 입력·시각·원시값·프로세스 기록의 지문](../../catalog/boundary-prescribed-array.json). 이 모델에서 변화하는 두 신호의 0초 배열은 각각 1초에 읽은 값과 같았다. 그 이유와 다른 계산 간격에서의 동작은 아직 확인되지 않았다. CLI는 파일 시계를 유지하며 0초 값을 대체하지 않는다.

독립 판독기도 보관된 216개 값 중 같은 16개(두 입력의 0초 × 8개 경계)를 불일치로 판정했다. 공개 소스에는 [모델 초기화 중 시간 단계 준비를 호출하는 곳](https://github.com/Deltares/Delft3D/blob/5a4649830b1e5072caf019fb4850bbdefd9ad431/src/engines_gpl/dflowfm/packages/dflowfm_kernel/src/dflowfm_kernel/prepost/flow_modelinit.F90#L517)과 [현재 시각에 내부 시간 간격을 더해 경계 시각을 갱신하는 곳](https://github.com/Deltares/Delft3D/blob/5a4649830b1e5072caf019fb4850bbdefd9ad431/src/engines_gpl/dflowfm/packages/dflowfm_kernel/src/dflowfm_kernel/compute/flow_initimestep.f90#L107)이 있다. 이는 다음 실험의 가설이다. #209의 MDU는 `DtInit`, `DtMax`, `DtUser`가 모두 1초여서 셋 중 무엇이 첫 값에 영향을 줬는지 구별할 수 없다.

<a id="native-213"></a>

**#213 · 초기화 직후 같은 값을 반복 조회한 결과.** 120초 모델에서 초기화와 첫 업데이트만 관찰하는 실험이다. 계산을 시작하기 전에 시간 간격 조합 8개와 허용 오차 1×10⁻⁸ m를 정했다. [검수한 실행기](../../experiments/B12-T0-RUNNER-V-20261105-02/verification.json)는 소유권을 확인하지 못하거나 한 경우가 실패하면 다음 모델을 시작하지 않는다.

| 실제 실행한 경우 | 원래 엔진 시계와 배열에서 본 결과 | 판정 |
| --- | --- | --- |
| A: `DtUser=DtMax=DtInit=1`초, 선형 신호 | 첫 업데이트 전 세 번 모두 시계는 0초, 경계값 8개는 각각 0.2100000023574103 m. 입력에서 계산한 0초 값은 0.2 m다. 이후 여덟 번의 업데이트에서 마지막 실제 시각은 11초였다. | 88개 값 중 현재 시각의 입력값과 64개가 일치했다. `max(DtInit, 현재 시각)`에서 계산한 입력값과는 88개 모두 일치. 한 조건에서의 관찰이며 원인이 확정되지는 않았다. |
| B: `DtUser=4, DtMax=DtInit=1`초, 같은 신호 | [원본 로그](../../experiments/B12-ENGINE-T0-G-native-213-01/linear_B/native.stdout.log)에 history 간격 10초가 4초의 배수가 아니라는 INFO 뒤에 ERROR가 기록됐다. ready 이벤트만 있고 초기화 완료·배열 측정은 없다. [고정 소스의 간격 검사](https://github.com/Deltares/Delft3D/blob/5a4649830b1e5072caf019fb4850bbdefd9ad431/src/engines_gpl/dflowfm/packages/dflowfm_kernel/src/dflowfm_data/unstruc_model.f90#L4214)와 진단 문구가 일치한다. | 초기화 실패. 이후 6건은 미실행. |

[원본 배치 기록](../../experiments/B12-ENGINE-T0-G-native-213-01/verification.json), [별도 배열·핸들 재판독](../../experiments/B12-ENGINE-T0-G-readback-213-01/verification.json). [독립 검증자의 부분 결과](../../experiments/B12-ENGINE-T0-V-array-reader-01/partial213-summary-01/verification.json)에서도 완료된 진단 1건, 초기화 실패 1건, 미실행 6건으로 구분한다. 두 사례의 원래 Job 및 멤버 핸들 4개의 종료를 확인했다. #209의 0초 불일치와 #213의 실패는 그대로 둔다. 다음 비교에서는 모든 복사본의 history·map 간격을 동일한 12초로 맞춘 뒤 같은 8가지 조건을 검증한다.
<a id="native-221"></a>

**#221 · 엔진 시계가 0초일 때 어떤 경계값이 들어 있는가?** 같은 48셀 수로에서 여덟 조건의 history·map 간격을 모두 12초로 고정하고, 실제 FM을 초기화한 뒤 BMI 시계와 처방 수위 배열 `zbndz`를 함께 읽었다. 아래에서 `F(t)`는 **해당 모델의 BC 파일**에서 시각 `t`에 계산한 값이다. GUI 표시나 관측점의 계산 수위가 아니다.

| 신호 · 조건 | DtUser / DtMax / DtInit (초) | F(0) → 실제 초기 수위 (m) | F(실제 시계)와 일치한 원소 / 88 |
| --- | --- | --- | ---: |
| 선형 A | 1 / 1 / 1 | 0.2000 → 0.2100 | 64 |
| 선형 B | 4 / 1 / 1 | 0.2000 → 0.2100 | 64 |
| 선형 C | 4 / 0.25 / 1 | 0.2000 → 0.2100 | 40 |
| 선형 D | 4 / 0.25 / 0.25 | 0.2000 → 0.2025 | 64 |
| 선형 E | 1 / 0.25 / 1 | 0.2000 → 0.2100 | 40 |
| 조화 C | 4 / 0.25 / 1 | 0.0500 → 0.058779 | 40 |
| 조화 D | 4 / 0.25 / 0.25 | 0.0500 → 0.052250 | 64 |
| 일정값 C | 4 / 0.25 / 1 | 0.1500 → 0.1500 | 88 |

각 조건에서 초기 시각을 세 번 읽고 여덟 번의 업데이트 직후에도 여덟 원소를 모두 읽었다. **704개 중 464개**가 `F(실제 시계)`와 일치했다. 미리 정한 다른 가설인 **`F(max(DtInit, 실제 시계))`는 704개 모두** 허용 오차 10⁻⁸ m 안에서 일치했다. 일정값 대조군은 시각 가설을 구별하지 못한다. 선형 C와 D는 사용자 간격과 최대 간격이 같아도 초기 간격만 바꾸면 초기 배열값이 달라지는 대조다.

공개 `boundary preview`는 요청한 시각의 **입력 신호**를 반환한다. 이 결과를 근거로 사용자의 시각에 오프셋을 더하지 않는다. 마지막 실제 시각은 조건에 따라 5초 또는 11초다. 120초 완주, 설치 DLL 내부 구현, 일반 경계나 공간 보간에 대한 증거는 아니다. #209의 초기 불일치와 #213의 출력 간격 오류도 그대로 유효하다.

[실행 전 입력·수치 기준](../../experiments/B12-ENGINE-T0-V-schedule12-01/final-reconciliation-02/verification.json),
[여덟 실제 실행](../../experiments/B12-ENGINE-T0-G-native-221-01/verification.json),
[BC·실제 시각·원소별 수치와 16개 멤버 종료 재판독](../../experiments/B12-ENGINE-T0-G-readback-221-01/verification.json).
[사전 고정한 독립 검증기의 원본 프레임 대조](../../experiments/B12-ENGINE-T0-V-schedule12-reader221-01/coordinator-consumption-01/verification.json)에서도 각 조건의 22개 이벤트와 실제 시계, 배열·종료 기록을 확인했다.
