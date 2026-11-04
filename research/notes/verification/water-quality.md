# E015 · FM 내부 수질 과정과 독립 DELWAQ 실행

공식 예제 03의 DIMR XML은 FM 하나를 시작한다. 수질 과정은 FM 안에서 진행된다. FM이 쓴 유동 파일을 별도의 DELWAQ 프로세스가 읽는 구성과는 입력도, 완료 판정도 다르다. [원본 예제와 설정](../replay/coupling-cases.md).

| 경로 | 공개 CLI로 확인한 것 | 네이티브 검증 상태 |
| --- | --- | --- |
| 예제 03: FM 내부 질산화 | `water-quality prepare/inspect`로 고정 예제의 70개 FM 입력에서 대조군을 만들었다. 공통 설정을 맞춘 뒤 두 경우의 물리적 차이는 `dynamo.sub`의 `RcNit` 하나(1/day 또는 0/day)다. `proc_def.dat`와 `proc_def.def`를 각각 복사하고 지문을 확인했다. 두 모델에 `coupling prepare`를 적용한 뒤 각각 새 폴더로 옮겨 참조와 DIMR XML을 검사했다. | 아래 독립·통합 실험에서 3,600초 원본 출력, native timer, 같은 수리 조건에서 NH4 감소·NO3 증가를 확인했다. 일반 사용자 모델과 별도 WAQ 소비자는 검증 범위 밖이다. |
| 독립 WAQ · 예제 06 | `waq-offline prepare/inspect/plan`은 고정 원본 28파일에서 양성·대조 입력을 별도 작성하고, `.inp`가 실제 소비하는 9개 참조와 `.hyd`의 모의시계를 확인한다. 기존 `water-quality review-offline`은 읽기만 한다. | 별도 소비자 2회 재현에서 전처리 및 양성·대조군 3,600초 완료. 원본 map·history·구간 부피·MON 기록과 대조했다. 첫 출력 판독 실패는 아래에 보존했다. |

통합자 기록 `E015-G-processes-preflight-01/positive-preview.json`은 초기 DIMR 설정 직렬화 오류를 보존한다. 수정 후 독립 검증자의 `E015-WQ-V-readiness-20261104-185101-42afd4e9`와 통합자의 새 `E015-G-water-quality-portable-01` 모두 같은 단계까지 통과했다. 마지막 폴더의 `verification.json`은 입력별 지문·재배치·부모 환경 불변과 `native: not_requested`를 함께 기록한다. `predeclared-oracle.json`에는 실행 전 정한 원본 출력 단위·시간·농도차 기준이 있다.

재현: 저장소 루트에서 `.venv/Scripts/python.exe -m research.workflows.verification.verify_water_quality --out <새-폴더> --install <설치-루트>`. [검증기](../../workflows/verification/verify_water_quality.py)는 기본적으로 네이티브 엔진을 실행하지 않는다. 공개 입력 명세는 [examples/water_quality](../../../examples/water_quality/README.md)에 있다.

## 03 네이티브 판정

첫 대조군은 정상 완료됐지만 초기 검증기가 같은 이름의 timer 두 줄을 중복으로 판단해 중단했다. `E015-WQ-V-slot34-20261104-190126-5a52748b`의 초기화·최종 timer를 고정 소스와 대조한 결과, 서로 다른 호출 문맥이었다. 두 줄을 단순 합산하거나 한 줄을 버리지 않고 초기화 시점부터 동일한 timer ID를 추적했다. 수정된 독립 시험 `E015-WQ-V-slot36-20261104-190531-100a4c19`과 통합자 시험 `E015-G-nitrification-01` 모두 통과했다. 양쪽 모델에서 초기화 1회와 정규 과정 60회를 구별했고, 두 원본 map 모두 0–3,600초에 300초 간격의 13개 시각이 있었다. 개별 60회의 타임스탬프를 추적한 것은 아니다.

| 마지막 시각, 활성 − 비활성 | 원본 변수의 단위 | 유효 표본 평균 차이 |
| --- | --- | ---: |
| `mesh2d_NH4` | g/m3 | −0.00819905 |
| `mesh2d_NO3` | gN/m3 | +0.00819652 |
| `mesh2d_OXY` | gO2/m3 | −0.03719749 |

통합자는 두 map의 단위·마스크·시간과 초기값 일치를 확인하고, 마지막 시각의 **222개 면, 유효한 면–층 조합 1,731개**에서 단순 표본 평균을 다시 계산했다. 수위는 모든 시각에 같았다. 다른 과정과 열린 경계도 있으므로 이 값을 총질량·단일 반응의 화학양론으로 해석하지 않는다. 통합 `verification.json`의 SHA-256은 `482f6d92b9b4ebc7f33448670b7abda87dd92ba874ea368389143403a84d44b4`, 두 원본 map과 timer를 직접 읽은 결과는 같은 폴더의 `coordinator-raw.json`이다. 결과 대조를 별도 설치의 사용자 모델 또는 오프라인 DELWAQ에도 적용할 수 있다는 뜻은 아니다.

같은 검사를 공개 명령으로 요청할 수 있다. 두 인자는 각각 **활성 실행 폴더, 비활성 실행 폴더**이며, 원래 `water-quality prepare`가 만든 묶음을 함께 지정한다.

```powershell
dfm water-quality compare POSITIVE_RUN CONTROL_RUN --bundle BUNDLE --samples-per-time 1
```

이 명령은 엔진을 다시 실행하지 않는다. 묶음·기록·원본 파일을 대조하고, 각 출력 시각의 유효 표본 수, 농도 차이의 최소·평균·최대와 탐지 판정을 반환한다. 통합 시험 `E015-G-public-chemistry-01/verification.json`은 독립적으로 직접 읽은 3개 물질 × 13개 시각의 통계·개수와 일치했다. 역할을 바꾼 호출은 종료 코드 6, `water_quality_compare_role`로 거절했다. 비교 전후 원본 map 지문은 그대로였다. [독립 공개 명령 검증기](../../workflows/verification/verify_water_quality_compare.py)도 별도 폴더에서 같은 계약을 검사한다.

## 별도 DELWAQ 소비자: 초기 출력 판독 실패

`WAQ-G-interface-preflight-01`에서 공개 `waq-offline prepare`의 미리보기는 디렉터리를 만들지 않았다. 그 지문으로 적용하고 양성·대조군을 각각 `inspect`, `plan`으로 다시 확인했다. 두 입력은 원본에 시간대가 없는 지역 모의시계를 따른다. 12:30부터 13:30까지 공통 60초 계산 간격, 300초 출력 간격을 쓰며 사망률 입력 `RcMrtEColi`만 0.8/day와 0/day로 다르다. FM 내부의 03 질산화 실험과 별도다.

첫 네이티브 독립 시험 `WAQ-offline-V-slot49-20261104-194920-fe9af87b`에서는 전처리 전용 호출이 종료 코드 0·`Normal end`와 listing을 남겼다. 이어서 실행한 0/day 대조군도 실제 엔진이 정상 종료했지만 CLI는 출력 헤더의 중복 변수명을 거부했다. 원본 `.map`은 26열이고 비대상 일별 `daily_EColi` 통계 이름이 세 번 쓰였다. 원본 열의 순서와 위치를 보존해야 하며, 물리량 이름이 중복될 때 임의로 첫 열을 고르면 안 된다. 두 job이 비었음을 확인한 뒤 중단했으므로 이 기록에는 양성군이 없다.

**수정 후 독립·통합 재현.** `WAQ-offline-V-slot51-20261104-195742-ebd15791`과 `WAQ-G-offline-consumer-01`에서 각각 전처리와 두 개의 실제 소비자 실행을 마쳤다. 공개 `waq-offline compare POSITIVE_RUN CONTROL_RUN`은 1,130개 구간의 map, 20개 위치의 history에서 모의시각 45,000–48,600초(12:30–13:30), 300초 간격의 13개 기록을 읽었다. 원본 시간대는 명시되지 않았다. 초깃값 이후 `MrtToEColi` 차이는 `0.8 × 1.07^(18−20) = 0.69875098/day`와 최대 `1.45×10⁻⁶/day` 이내였다. Salinity·IM1은 두 map의 모든 값이 같았다. 대조군에도 UV·염분에 의한 사멸이 남는다.

| 13:30 E. coli | 0.8/day − 0/day |
| --- | ---: |
| 구간 농도의 단순 평균 차이 | −9.93547 MPN/m³ |
| 각 구간 농도 × 해당 시각 구간 부피의 합 차이 | −29,512,360,749 MPN |

통합자가 새 map·원본 부피 파일을 직접 읽어 13시각 모두의 총량을 대조했다. 엔진 MON 총량과 독립 적분은 출력 정밀도 기준을 통과했다. 이 검증은 모든 소스·외부 경계·반응별 flux ledger의 완전 폐합을 뜻하지 않는다. 두 역할을 거꾸로 넘긴 공개 비교는 종료 코드 6으로 거절했다. 원본 지문·검수 보고서 위치는 [모듈 색인](../../catalog/module-gates.json)에 있다.

재현: `.venv/Scripts/python.exe -m research.workflows.verification.verify_water_quality_offline_replay --out <fresh-folder> --install <suite-root> --native-slot-granted <slot> --with-preprocessor`. [`offline_ecoli.json`](../../../examples/water_quality/offline_ecoli.json)의 `source_root`에는 잠금 커밋의 `examples/delft3d4/06_delwaq` 원본 28파일이 필요하다.

**실패·취소·타임아웃은 각각 판정한다.** 복사한 과정 라이브러리의 헤더만 손상시킨 독립 시험 #58과 통합 시험 #60에서 DELWAQ는 `process_library/proc_def.dat`를 열 수 없다는 NEFIS 진단과 종료 코드 1을 냈다. 같은 바이너리의 정상 대조 프로세스가 대상 종료 시점에 살아 있었고, 48,600초에 도달했다. 두 Job이 빈 것을 확인했다. [통합 시험의 원본 진단과 종료 기록](../../experiments/WAQ-G-failed-input-01/verification.json), [재현기](../../workflows/verification/verify_water_quality_offline_lifecycle_failed.py).

독립 시험 #55에서는 실제 실행 중인 대상을 취소하고 대조군의 정상 종료를 확인했다. 같은 시험의 timeout에서는 소유자의 강제 종료 증거가 있었지만 독립 `status`가 생존 구간을 포착하지 못했다. 통합 시험 #59에서는 취소 대상과 대조군이 **모두 자연 종료**했다. 빠른 계산에 같은 요청을 반복해 성공 횟수만 세지 않는다. 취소·타임아웃을 재현하려면 더 긴 실제 계산과 실행 중 관찰 시점을 사전에 정해야 한다.

**후속 중단 시험(dt=1초).** [명시적인 lifecycle 전용 명세](../../../examples/water_quality/offline_lifecycle_dt1.json)는 동일한 유동 파일·3,600초 기간·300초 출력 간격을 유지하고 실제 DELWAQ 계산 간격만 60초에서 1초로 바꾼다. 이 입력은 화학 A/B 결과 비교에 쓸 수 없다. [통합 정상 실행](../../experiments/WAQ-G-dt1-natural-01/coordinator-raw.json)에서 엔진 실행 구간은 3.034초였으며, map과 history 원본 모두 모의시각 45,000–48,600초의 13개 기록이 있었다.

독립 시험 #66과 [통합 시험 #70](../../experiments/WAQ-G-dt1-stops-01/verification.json)에서 각각 취소·타임아웃을 별도 대조군과 한 번씩 시험했다. 두 프로그램의 실제 PID·생성 시각·이미지와 공개 상태를 중단 전에 관찰했고, 각 대상의 Job 멤버 핸들 종료를 확인했다. 같은 실행 파일을 쓰는 대조군은 그 시점에 살아 있었고 둘 다 자연 종료해 48,600초에 도달했다. [통합자가 대조한 manifest와 결과](../../experiments/WAQ-G-dt1-stops-01/coordinator-audit.json). 정상적 native 종료나 중단 도중의 화학 상태 보존을 뜻하지 않는다.
