# E015 기준 입력: 단독 실행과 계산 중 교환을 구별하기

**2026-11-04 네이티브 검수 상황.** RTC 두 구성과 RR 세 구성은 각각 다른 시험이다.

| 입력 | 실제로 관찰한 결과 | 아직 통과하지 않은 조건 |
| --- | --- | --- |
| 공식 예제 10의 FM–RTC 파생 입력 | #67 독립 시험과 #68 통합 시험에서 각각 기본·변경 제어곡선으로 600초까지 계산했다. 각 구성에서 FM 관측 수위 → RTC 수신·곡선 계산 → FM 마루 반영을 10회 확인했다. 원본 map과 마지막 restart는 2,500셀 수위·4,950개 링크 유량이 map 저장 정밀도로 일치했다. | **실행 중 교환·수리 반응은 이 사례에서 승인.** 마루 높이는 history에 11개 있으나 이 restart에는 없고, 제어 상태 복원은 미확인이다. [독립 시험](../../experiments/E015-RTC-V-native-slot67-20261104-01/slot67-released.json), [통합 시험](../../experiments/RTC-G-exchange-01/verification.json) |
| f152 RR–FM | [독립 시험 #71](../../experiments/RR-F152-V-native-slot71-20261104-01/verification.json)과 [통합 재현 #72](../../experiments/RR-G-f152-exchange-01/verification.json)에서 각각 강우·무강우·수리조건 변경 세 입력을 600초 계산했다. 두 교환 구간에서 각 방향 34개 ID의 송신값과 실제 수신값을 대조했고, 세 실행의 최종 restart와 실행별 두 프로세스 종료를 확인했다. | 이 사례의 수위·유량 교환을 승인한다. 절대 수직 기준, 현장 보정, 다른 RR 모델, GUI 프로젝트에서 같은 DIMR XML을 내보내는 작업은 미검증이다. |

[통합자가 원본 NetCDF에서 합산한 f152 결과](../../experiments/RR-G-f152-exchange-01/coordinator-raw.json): FM history의 측방 지점 99개에서 RR과 연결된 34개만 이름으로 골랐다. 강우와 무강우에서 FM에 들어간 부호 있는 체적은 각각 22,540.5133 m³와 1,486.1460 m³였으며 각 사례의 RR 유출 적분과 일치했다. 수리조건만 바꿨을 때 RR 수신 수위의 최대 차이는 0.00697517 m였다. DIMR 송신 기록은 0·300초, RR의 처리된 값은 300·600초다.

실패 기록도 보존한다. [#62](../../experiments/RR-G-native-init-01/wet-run/stdout.log)는 교량이 있는 구조물 파일의 버전 2.00을 FM이 거부했다. 양쪽 교량의 기존 `shift = 0.0`은 유지하고 버전만 3.00으로 바꾼 [#64](../../experiments/RR-G-v3-structure-01/wet-run/model/rr/sobek_3b.log)에서는 RR이 강우 파일에 필수인 `*Aantal stations` 표지를 찾지 못했다. 이를 보존한 #69에서는 강우 모델이 완료됐지만 자식 프로세스 종료를 개별 확인하지 못해 실행 소유권 검수에 실패했다.

[통합자가 원본에서 계산한 RTC 결과](../../experiments/RTC-G-exchange-01/coordinator-raw.json): 제어곡선의 높이만 0.25 m 올렸다. 600초의 변경군 − 기본군은 실제 보 마루 **+0.318014 m**, 상류 **+0.115318 m**, 하류 **−0.101581 m**였다. 선과 교차한 50개 링크를 위치로 찾고 부호를 적용해 합한 단면 유량 차이는 **−4,379.31226 m³/s**였다. 원본 보 유량 history의 결측(기본군 4개, 변경군 5개)은 그대로 남겼다. 각 DIMR Job의 두 프로세스는 모두 개별 핸들로 종료를 확인했다. 이 인공 사례의 유량 크기를 현장 보정값으로 쓰지 않는다.

**설치본 RTC 첫 실행:** `E015-RTC-V-native-slot50-20261104-01`에서 공식 10 기반 두 입력 중 첫 번째를 실제 DIMR로 시작했다. FM·RTC가 초기화됐고 0초 교환을 시작했으나 60초에 RTC 시계열 인덱스 0을 요청할 때 가능한 인덱스가 7·8·9뿐이라 종료 코드 1로 실패했다(`runs/positive/stdout.log`). 소유 job은 비었고 두 번째 입력은 실행하지 않았다. 설정 XML과 구성요소 주소가 유효하다는 사실만으로 제어 신호가 끝까지 전달됐다고 판정하지 않는다.

두 번째 RTC 시험 `E015-RTC-V-native-slot53-20261104-01`은 공식 예제의 `limitedMemory=true`를 유지했다. 이 모드에서는 각 BMI update가 RTC를 한 단계씩 진행하고, 실제 수신·출력값을 CSV로 쓴다. 첫 사례의 FM history·map·최종 restart는 600초에 도달했다. 그러나 자연 종료의 개별 핸들 증거가 manifest에 없어 독립 판정은 실패했다. 구조물 ID에는 6글자 뒤로 결측 문자 패딩이 있었고, 유량 시각 11개 중 4개는 실제 결측이었다. 둘을 구별해야 한다. 아직 다른 설정의 대조군을 실행하지 않았으므로 양방향 제어 영향은 미승인이다.

아래는 **입력 파일과 고정 소스를 확인한 결과**다. 예제 이름의 `sequential`만 보고 구성요소가 차례로 실행된다거나, XML을 읽을 수 있다는 이유로 결합 계산이 성공한다고 판정하지 않는다.

| 기준 입력 | 실제 설정 | 검수 때 따로 관찰할 값 |
| --- | --- | --- |
| [03 FM 수질 과정](https://github.com/Deltares/Delft3D/blob/5a4649830b1e5072caf019fb4850bbdefd9ad431/examples/dflowfm/03_dflowfm_dwaq_sequential/dimr_config.xml#L33) | XML은 DFlowFM 하나만 시작한다. [MDU의 processes](https://github.com/Deltares/Delft3D/blob/5a4649830b1e5072caf019fb4850bbdefd9ad431/examples/dflowfm/03_dflowfm_dwaq_sequential/dflowfm/f34_dynamo.mdu#L246)에 `dynamo.sub`, `dynamo.eho`, `DtProcesses=600`이 있다. | 물질 이름·단위·시각과 계산된 농도. 수리 출력 파일을 별도 WAQ 실행에 넘긴 증거가 되지는 않는다. |
| [07 Waves 단독](https://github.com/Deltares/Delft3D/blob/5a4649830b1e5072caf019fb4850bbdefd9ad431/examples/dflowfm/07_dwaves/dimr_config.xml#L33) | `wave` 라이브러리 하나와 MDW가 기준이다. | 웨이브 격자와 출력 변수·파라미터 단위·시각. FM–Waves 사례와 입력 조건이 다르면 같은 수치가 나올 것을 기대하지 않는다. |
| [08 FM–Waves](https://github.com/Deltares/Delft3D/blob/5a4649830b1e5072caf019fb4850bbdefd9ad431/examples/dflowfm/08_dflowfm_sequential_dwaves/dimr_config.xml#L11) | FM이 주 시계를 맡고 Waves는 3,600초 주기의 startGroup에 있다. 이 XML에는 명시적인 스칼라 coupler가 없다. | 두 구성요소의 실행뿐 아니라 교환 경로와 양방향 물리량을 확인한다. 작성한 짧은 모델은 실제로 Waves가 호출되는 구간을 포함해야 한다. |
| [10 FM–RTC–Waves](https://github.com/Deltares/Delft3D/blob/5a4649830b1e5072caf019fb4850bbdefd9ad431/examples/dflowfm/10_dflowfm_sequential_drtc_dwaves/dimr_config.xml#L12) | RTC 60초, Waves 3,600초. RTC 그룹은 `flow2rtc → RTC → rtc2flow` 순서다. [교환 항목](https://github.com/Deltares/Delft3D/blob/5a4649830b1e5072caf019fb4850bbdefd9ad431/examples/dflowfm/10_dflowfm_sequential_drtc_dwaves/dimr_config.xml#L47)은 관측 수위와 보 마루 높이다. | 같은 시각의 FM 관측 수위, RTC 입력/제어값, 실제 FM 보 높이. 변수명만 같다는 이유로 단위를 추정하지 않는다. |
| [RR–FM 기준 XML](https://github.com/Deltares/HYDROLIB-core/blob/48993b1c85d6237ba55de08a4b4fbf8cb7965b80/tests/data/input/e02/c11_korte-woerden-1d/dimr_model/dimr_config.xml#L35) | 60초마다 RR을 진행하고 `rr_to_flow`로 유역 유출량을 FM lateral에 전달한다. | 동일한 유역·측방 ID, 부호·유량 단위, 교환 전후의 실제 값. RTC의 수위–보 높이 제어 사례와 별개다. |
| [f152 FM–RR 양방향 XML](https://github.com/Deltares/HYDROLIB-core/blob/48993b1c85d6237ba55de08a4b4fbf8cb7965b80/tests/data/input/e02/f152_1d2d_projectmodels_rhu/c04_DHydamo-MGB-initialisation/dimr_config.xml) | `0 300 600` 그룹에서 `flow2rr → RR → rr2flow` 순서로, 수위 34쌍과 유량 34쌍을 명시한다. 예: `laterals/lat_1209/water_level`에서 같은 ID 유역으로 수위를 보내고 `water_discharge`를 돌려받는다. | RR 노드·링크 원본은 각각 11,195·5,541바이트다(c11의 동명 파일은 0바이트). 후속 파생 입력의 실제 송수신·단위·시각 검수는 위의 #71/#72를 참조. 원본 62파일과 지문은 `RR-G-f152-source-01/receipt.json`에 보존했다. |

첫 네 예제는 Delft3D 고정 커밋에서 추출한 149개 파일이다. 원본 경로·파일별 SHA-256·구성요소와 control은 로컬 `research/experiments/E015-coordinator-source-01/receipt.json`에, 같은 파일의 아카이브는 그 옆의 `examples.zip`에 있다. HYDROLIB-core의 RR 사례는 별도 고정 리비전에서 읽었다. 설치된 실행 파일의 커밋은 알 수 없다. 사용자의 프로젝트 대신 이 자료의 새 복사본에서 기간과 출력 간격을 정하고, 변경한 파일과 실제 엔진 결과를 함께 남긴다.

공개 CLI 검수: `dfm coupling inspect <dimr_config.xml>`로 03·07·08·10을 읽은 결과 `(구성요소, 명시적 coupler)`는 차례로 `(1,0)`, `(1,0)`, `(2,0)`, `(3,2)`였다. `dfm coupling prepare examples/coupling/waves.json --out <새 폴더>`의 미리보기는 폴더를 만들지 않았고, 지문을 지정해 적용한 복사본은 `dfm coupling validate`를 통과했다. 기록은 `research/experiments/E015-G-public-preflight-01/`의 `source-configs.json`, `preview.json`, `apply.json`, `validate.json`이다. 이 단계에서는 SWAN이나 RTC가 값을 계산·전달했는지 시험하지 않았다.

f152에서는 `dfm rr-f152 prepare examples/rr_f152/wet.json --out NEW`로 미리 본 뒤 `--apply --expect-sha256 HASH`로 적용하고 `dfm rr-f152 inspect NEW`로 다시 읽는다. `dry.json`, `hydraulic.json`도 별도 폴더를 쓴다. 통합자 `RR-G-f152-preparation-01`에서 세 경우 모두 원본 62파일을 보존했고 두 방향의 주소를 각 34쌍 확인했다. 입력을 만들었다는 결과와 실제 엔진이 수신한 유량·수위는 별도 판정이다.
