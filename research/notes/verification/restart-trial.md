# E013: 재시작은 됐지만 모든 출력이 연속 계산과 같지는 않았다

**저장된 예측값 비교(E013-F).** 기본 `restart compare`는 여전히 종료 코드 6과 원본 필드별 차이를 반환한다. `dfm restart forecast FULL FIRST RESUMED --cold-control COLD --tolerances POLICY --contract saved-forecast-v1`은 같은 파일을 읽어 원본 판정과 별도의 결과를 함께 반환한다. 고정한 직렬 엔진·동일 격자의 사례에 한해 절단 시각의 진단 세 개, 시간 경계, 원점이 바뀌는 물수지 다섯 변수를 구분한다. 그 이후의 비누적 변수·결측 마스크와 최종 restart에는 오차를 허용하지 않는다. 숨은 내부 상태나 다른 물리 모형의 동등성은 검증하지 않는다.

독립 검수 `E013-V-forecast-public-20261104-05`와 통합 검수 `E013-G-forecast-public-01`가 각각 두 네이티브 원본과 32개 의도적 변형 복사본을 읽었다. 두 원본은 **예측값 계약 통과 / 원본 비교 실패**였고, 변형본 32개 모두 해당 변형 때문에 거부됐다. 통합자가 원본 NetCDF를 따로 열어 두 사례의 240초 restart 34개 변수 및 마스크가 모두 정확히 같고, cold 대조군과 재시작 초기 수위가 다름을 확인했다. [공개 명령 검수](../../experiments/E013-G-forecast-public-01/verification.json), [통합 원자료 대조](../../experiments/E013-G-forecast-public-01/coordinator-raw.json), [재현기](../../workflows/verification/verify_restart_diagnostics_cli.py).

**첫 네이티브 시험의 엄격한 판정은 실패다.** 2026.02 OpenHMWQ에서 합성 수로를 직접 FM으로 0–240초 연속 계산하고, 별도로 0–120초의 최종 restart를 사용해 120–240초를 계산했다. 계산은 모두 끝났다. 같은 시각부터 cold start한 대조군과 재시작의 초기 수위 차이는 최대 0.0447178 m였다. 단순히 시계만 이어진 것이 아니다.

| 독립 확인 | 첫 시험 결과 |
| --- | --- |
| 시간과 최종 상태 | 두 구간의 CF 시각은 120초에서 연결되고 240초에 끝났다. 최종 restart 34개 변수 모두 사전에 정한 비교 기준을 통과했다. |
| history | 57개 중 6개 변수가 미통과였다. `tausx`는 중복되는 절단 시각에서 달랐다. 물수지 누적 유입·유출·합계·저류·체적오차는 이어진 구간에서도 달랐다. 최대 유입 차이는 약 1,146.99 m³였다. |
| map | 34개 중 `mesh2d_viu`만 두 구간의 절단 시각에서 달랐다(최대 절대 차이 0.000675). 첫 구간의 120초를 남겨 연결한 전체 map 시계열에서는 이 차이가 사라진다. 원본 두 시각을 각각 비교하면 여전히 다르다. |
| 중단 경로 | 별도 재시작의 timeout·cancel은 각각 `timed_out`·`cancelled`였다. 대상 취소 뒤 같은 실행 파일의 대조 실행이 살아 있었고, 별도로 종료했다. |

원본 구간을 덮어쓰거나 누적값·절단 시각을 제외해 통과시키지 않는다. 이 결과는 정확한 재시작 시각과 상태 입력을 확인한 증거이며, history/map 전체의 무손실 연속성이나 다른 모델의 재시작 동등성을 입증하지 않는다.

공개 명령으로 같은 세 실행의 기록과 NetCDF를 다시 검사할 수 있다. `--atol`과 `--rtol`은 명시적으로 지정한다. 아래는 독립 실험의 변수별 허용오차와 구별되는, 통합자의 **오차 0** 대조다.

```powershell
$r = 'research/experiments/E013-restart-native-20261104-01/runs'
dfm restart compare "$r/continuous" "$r/first" "$r/resumed" --atol 0 --rtol 0
```

통합 대조도 종료 코드 **6**, JSON 오류 `restart_numerical_mismatch`를 반환했다. `error.details`에는 history 57개, map 34개, 최종 restart 34개의 필드별 결과가 있다. 2차원 CF 시간 경계 배열과 1차원 시간 좌표를 구별한다. 오차 0에서도 최종 상태는 통과했다. 원 명령, 종료 코드와 stdout은 `research/experiments/E013-G-public-comparison-01/`에 있다.

별도로 통합자가 새 모델·실행 폴더에서 연속·분할·cold 대조군과 실패/취소 대조군을 모두 다시 계산했다. `research/experiments/E013-G-coordinator-native-01/verification.json`도 같은 사전 기준에서 history/map은 실패, 최종 상태는 통과였다. 한 번 저장된 결과만 다시 읽어 얻은 판정이 아니다.

재현기는 [verify_restart.py](../../workflows/verification/verify_restart.py)다. 저장소 루트에서 `python -m research.workflows.verification.verify_restart --help`로 옵션을 조회한다. 원본 실패·변수별 오차·허용오차 선언은 각각 `research/experiments/E013-restart-native-20261104-01/{verification,comparison,tolerances.predeclared}.json`에 보존했다. 첫 verification.json의 SHA-256은 `276a342d13bdf6c899eadbeb6ba42fd14cf86c32bdc0698070e0110d0fd88af0`다.

**구간 경계와 누적 물수지의 후속 대조.** `dfm restart compare`에 `--tolerances FILE`로 변수별 허용오차를 지정할 수 있다. `--continuity join`은 원본 판정을 유지하고 별도의 파생 시계열을 비교한다. 절단점은 첫 구간의 마지막 행을 쓰고, 소스에서 구간 누적으로 확인된 변수에만 `첫 구간 마지막 값 − 재시작 첫 값`을 더한다. 연속 계산의 값을 이 보정에 쓰지 않는다.

새 native 통합 시험의 세 실행에 같은 사전 기준을 적용했다. raw에서는 위의 6개 history 물리량 외에 **시간 구간 변수 `time_bds`**도 절단점에서 달랐다. NetCDF에서 직접 읽은 120초의 구간은 연속/첫 구간이 `[110,120]`, 재시작 첫 행이 `[120,120]`초였다. 파생 대조에서 map 전체와 시간 구간은 일치했지만 history의 누적 유입·유출·합계·저류는 허용오차 밖이었다. 누적 유입 최대 잔차는 0.000366211 m³다. 두 명령 모두 종료 코드 6이었고 최종 restart 34변수는 통과했다. 세 manifest와 검사 전후 모든 원본 NetCDF 지문이 같았다. 전체 JSON·명령·지문은 `research/experiments/E013-G-derived-continuity-01/`에 있다.

[독립 파생 시계열 검증기](../../workflows/verification/verify_morph_restart_join.py)는 제품 비교기를 가져오지 않고 같은 잔차 네 개와 map 통과를 재현했다. 보고서는 `E013-derived-join-independent-20261104-03/verification.json`이다.
