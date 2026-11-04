# G16 · 파일로 준 보 마루 높이는 상수 설정과 같은가?

<a id="public-run"></a>

**#217 · 공개 CLI로 실행한 120초.** `dfm run start … --route direct --profile weir-series`로
기준, CLI 무변경, 수동 상승, CLI 상승 모델을 별도 폴더에 실행했다. 각 케이스의 원본 입력 11개와
실행 폴더의 사본을 해시로 대조했다. 네 번 모두 history·map 0–120초(각 121개 시각), 처음·끝 restart가
있었다. 대응하는 #211의 연구용 실행과 비교한 **189개 변수(86 + 35 + 34 + 34)**의 저장값·해석값,
마스크, 변수 속성이 각 케이스에서 일치했다. 파일의 생성 시각·UUID는 수치 비교와 분리했다.
네 manifest 모두 원래 Job에 속한 두 프로세스의 종료와 Job 핸들의 닫힘을 기록했으며,
공개 `run status`도 완료 상태를 반환했다. DIMR 선택은 엔진 실행·출력 폴더 생성 전에 거부했다.

[실행 명령·stdout·stderr](../../experiments/G16-RUN-PROFILE-G-native-217-01/calls),
[사전 비교 기준](../../experiments/G16-RUN-PROFILE-V-20261105-01/public-predeclared-01/predeclared.json),
[독립 검증](../../experiments/G16-RUN-PROFILE-V-public217-01/verification.json) 및
[통합자 재판독](../../experiments/G16-RUN-PROFILE-V-coordinator-readback-217-01/verification.json).
공유하는 실행 코드를 바꿨으므로 [기존 펌프 다섯 사례](../../experiments/G16-PUMP-REGRESSION-G-native-219-01/verification.json)도
다시 실행했다. 사례당 173개 변수가 #187과 같고 단면 유량·양쪽 저류량·소유 프로세스 종료 검사를 통과했다.
[복사 가능한 모델과 명령](../../../examples/weir_series/README.md). [제품 wheel·manifest·검증 결과 지문](../../catalog/weir-run-profile-gate.json).
이 승인은 입력·실행·출력 동등성에 한정한다. #211에서 실패한 평균 하류 수위의 부호 예측,
GUI CSV 교환 및 재시작으로 보 상태를 복원하는 기능은 승인 범위 밖이다.

<a id="public-editor"></a>

**기존 보의 입력값 조회·교환.** `weir series-inspect`는 모델이 지정한 보와 TIM의 원래 값을 읽는다. `series-export`는 새 폴더에 표와 단위·시각 원점 기록을 쓰고, `series-import`는 기존 시각의 높이 숫자만 미리보기·적용한다. [11개 입력과 실행 예시](../../../examples/weir_series/README.md). 단일 2D·UTC 모델의 현대식 보 구조물과 독립 TIM이 대상이다. 상수를 TIM으로 바꾸거나 시각을 삽입하는 기능은 없다.

[설치본 독립 검증](../../experiments/G16-SERIES-V-20261105-01/installed-rev03-public-01/verification.json)에서 21건·명령 70회를 대조했다. [통합자 검수](../../experiments/G16-SERIES-G-example-01/checked-01/verification.json)에서는 0·60·66·120초를 내보내고, 뒤의 두 높이만 −0.5→+0.5 m로 바꿨다. 파일 10개와 TIM의 나머지 바이트는 같았다. 원복 후 입력 11개 해시가 모두 일치했다. 미리보기 뒤 CSV 또는 TIM이 바뀌면 둘 다 적용하지 않았다. 이 검수는 계산이나 GUI를 실행하지 않았다.

<a id="native-211"></a>

**#211 · CLI로 마루를 올린 모델과 손으로 편집한 모델.** 공개 명령으로 만든 입력을 연구용 direct FM 실행기로 계산했다. 48셀·120초·직렬인 같은 수로에서 ① 원본, ② 높이를 그대로 가져온 입력, ③ 수동으로 마루를 올린 입력, ④ 공개 CLI로 마루를 올린 입력을 비교했다. 두 쌍 모두 입력 11개가 짝끼리 같았다. 각 쌍의 history 86개, map 35개, 0초·120초 restart 각 34개, 총 **189개 변수**의 값과 결측 마스크가 같았다. 비교에는 0초가 포함된다. 네 번 모두 원래 Job의 멤버 2개씩 종료 확인 후 Job을 닫았다.

| 마루를 올린 경우 − 낮게 둔 경우 | 66초 | 90초 | 120초 | 80~120초 평균 |
| --- | ---: | ---: | ---: | ---: |
| 보 위치 고정 단면의 동쪽 유량 (m³/s) | −39.276 | −40.824 | −40.484 | −40.466 |
| 하류 관측점 `below_weir` 수위 (m) | −0.19288 | +0.10939 | −0.14013 | **+0.06663** |

0~60초의 history·map과 초기 restart는 변화군과 기준군이 같았다. 마루를 올린 뒤 동쪽 유량은 줄었다. 하류 수위 차이는 80~120초의 41개 시각 중 26개에서 양수, 15개에서 음수였다. [실행 전 판정 기준](../../experiments/G16-SERIES-REPLAY-oracle-freeze-20261105-01/predeclared.json)은 **평균 유량과 평균 수위가 모두 감소**할 것을 요구했다. 따라서 전체 물리 가설은 **미통과**다. 마지막 시각만 골라 승인하지 않는다. [독립 원시 배열 대조](../../experiments/G16-SERIES-REPLAY-oracle-G211-01/verification.json), [통합자의 별도 NetCDF·핸들 재판독](../../experiments/G16-SERIES-G211-readback-01/review.json), [wheel·원본 근거 해시](../../catalog/weir-series-public-gate.json). 이 실험에서 GUI CSV 가져오기나 공개 `run start` 경로를 시험하지 않았다.

**#185 · 상수 마루와 TIM 마루를 비교한 별도 수동 실험.**

**이 48셀 수로에서 TIM은 계산 중 마루 높이를 바꿨지만, 상수 마루와 완전히 같은 결과를 만들지는 않았다.** 설치된 FM `1.2.184.Unknown`의 직접 실행 다섯 건이 모두 120초에 도달했다. TIM을 준 세 경우에는 원본 history의 `weirgen_crest_level`이 첫 시각에 결측이 아닌 **0 m**였다. 지정값 ±0.5 m로 대체하지 않았다. [계산 전 독립 판정 기준](../../experiments/G16-CREST-V-frozen-01/predeclared.json), [실제 미통과 기록](../../experiments/G16-CREST-V-G-native-185-01/verification.json).

| 구조물 파일의 `crestLevel` | history 마루 0초 / 1초 / 120초 (m) | 120초 동쪽 고정 단면 유량 (m³/s) |
| --- | --- | ---: |
| 상수 +0.5 m | +0.5 / +0.5 / +0.5 | 0 |
| 상수 −0.5 m | −0.5 / −0.5 / −0.5 | 40.48394 |
| TIM으로 +0.5 m 유지 | **0** / +0.5 / +0.5 | 0 |
| TIM으로 −0.5 m 유지 | **0** / −0.5 / −0.5 | 40.48394 |
| TIM으로 60~66초에 +0.5 → −0.5 m | **0** / +0.5 / −0.5 | 40.43063 |

모델의 기준 시각은 2001-01-01 00:00 UTC다. 연구용 CSV의 초 단위 시각 0·60·66·120을 `crest.tim`에 분 단위 0·1·1.1·2로 작성했다. FM은 CSV를 입력으로 받지 않았다. [입력 독립 검사](../../experiments/G16-CREST-G-input-review-01/verification.json)에서 구조물 참조·높이·시각과 전체 입력을 확인했다. 이 경로는 [현대식 보 판독 및 TIM 등록](../collection/gui-workflows.md#weir-csv)을 근거로 정했다. 설치 바이너리의 소스 커밋은 확인되지 않았다.

[원본 history·map·양 끝 restart 재판독](../../experiments/G16-CREST-G-raw-185-01/readback.json)에서 각 상수와 같은 높이를 유지한 TIM을 비교하면, 고정 단면 유량·하류 관측점 수위·map 셀 수위는 121개 시각에서 각각 같았다. 반면 낮은 상수/TIM 쌍은 history의 보 유량 마스크와 초기 restart의 `hu`에서도 차이가 났다. 두 쌍의 최종 restart는 독립 검증기의 전체 변수 비교를 통과했다. 낮추는 TIM과 높은 TIM의 수위·단면 유량은 59초까지 같았고, 80~120초의 하류 관측점 수위 차이는 최대 0.13885 m였다. 첫 시각의 차이가 초기화 순서 때문인지, 출력 시점 때문인지는 이 계산으로 구분할 수 없다.

[모든 변수·마스크를 다시 비교한 기록](../../experiments/G16-CREST-V-results-185-01/verification.json)에서 상수와 같은 높이를 유지한 TIM의 차이는 **0초에 한정**됐다. 높은 쌍은 history 변수 하나, 낮은 쌍은 history 변수 8개와 초기 restart의 `hu`가 달랐다. 비교한 map과 두 쌍의 최종 restart에서는 변수 차이가 없었다. 초기 restart의 차이까지 포함한 완전한 동등성은 여전히 성립하지 않는다.

[원본 출력 20개의 SHA-256과 실패한 비교](../../catalog/weir-crest-series-gates.json). 계산 전 시각 0을 포함한 판정 기준은 그대로 유지한다. GUI 편집기에서 CSV를 내보내고 다시 가져오는 동작과, 그 결과 FM의 `crestLevel`에 실제로 무엇을 쓰는지는 별도 실험이다.
