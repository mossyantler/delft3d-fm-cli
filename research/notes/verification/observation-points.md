# G06 · 기존 관측점을 옮기거나 하나 더 기록하기

[기계 판독용 검수 결과](../../catalog/observation-point-gate.json)에 공개 명령의 입력별 최종 시각·변수 수, 셀 중심 밖 좌표, 256/257바이트 대조와 원자료의 SHA-256을 기록했다.

2001년 합성 48셀 수로의 MDU는 `ObsFile=observations.xyn`을 가리킨다. [수동 대조 설계](../../experiments/G06-OBS-I-prepared-20261105-01/predeclared.json)에서는 좌표계가 명시된 이 모델에서 XYN만 바꾼다. 여덟 동반 파일과 각 실행의 시작·종료 시각은 같다. 좌표는 EPSG:32631의 미터이고 아래 인덱스는 이 모델의 원출력 map에서 **0부터** 센다.

| 입력 | 바꾼 점 | 비교할 map 셀 |
| --- | --- | --- |
| 기준 | `centre` (500065, 5700015), `upstream` (500015, 5700025) | 각각 24, 7 |
| 이동 | 이름을 유지한 채 `centre`의 X만 500025로 변경 | 8. `upstream`은 여전히 7 |
| 추가 | 기존 두 점 뒤에 `east_probe` (500095, 5700025) 한 행 추가 | 39. 원래 두 점은 각각 24, 7 |

[첫 실행](../../experiments/G06-OBS-I-native-slot145-20261105-01/verification.json)에서 기준군과 이동군은 120초에 도달했다. 두 history에서 `centre`의 최대 수위 차이는 0.01454 m였고, `upstream`은 같았다. map과 두 restart의 102개 변수도 일치했다. 이동하면 history 안의 형상 좌표 자체가 바뀐다. 실제 `station_geom`의 `node_count`는 `station_geom_node_count`를, `node_coordinates`는 X·Y 배열을 가리킨다. 이 배열의 차원 이름은 `station`이 아닌 `station_geom_nNodes`였다. 첫 검증기는 이를 일반 수리 변수로 잘못 분류해 이동군에서 멈췄고 추가군은 그때 실행하지 않았다.

이 수동 실험은 관측점 이름·원좌표·실제 셀의 시계열을 연결하는 검사다. GUI 지도에서 점을 옮겼을 때의 export와 관측 단면(`CrsFile`)은 별도다.

**공개 CLI.** `observation inspect`는 MDU가 참조한 XYN에서 이름·좌표와 원본 바이트 위치를 읽는다. `observation move/add`는 평면 좌표계가 확인된 2D 망에서 단일 셀 내부의 점만 받는다. 좌표 변환과 스냅은 하지 않는다. 미리보기 지문은 요청과 연결된 입력을 포함한다. 이동은 좌표 토큰만 바꾸고, 추가는 기존 파일 끝에 새 행을 붙인다.

[설치 패키지로 네 번 계산한 결과](../../experiments/G06-OBS-PUBLIC-G-slot156-01/verification.json), 기준·이동·추가 세 입력은 각각 수동 입력 9파일과 바이트 단위로 일치했다. 각 120초 실행의 history·map·restart 두 개에서 변수 159개의 차원·자료형·속성·마스크·유효 값이 해당 수동 실행과 일치했다. 네 번째 사례는 셀 중심 (500065, 5700015)에서 벗어난 **(500061.25, 5700018.75)**를 요청했다. 원본 history에는 요청 좌표가 그대로 기록됐고, 수위 13개는 map 셀 24(0부터 셈)의 값과 일치했다. 그 사례의 history 대조값은 기준군의 저장 좌표만 바꿔 구성했다. 이 결과를 격자 경계 위, 건조 영역, 1D 네트워크에 일반화하지 않는다.

[별도 두 입력](../../experiments/G06-OBS-G-width154-01/verification.json)은 따옴표로 감싼 ASCII 이름의 끝 위치만 1바이트 다르다. 닫는 따옴표가 XYN 행의 256번째 바이트이면 실제 이름이 history에 보존됐고, 257번째이면 FM은 X·Y·이름을 읽다가 초기화에 실패했다. 그래서 편집기는 이름 길이만 검사하지 않고 **좌표·공백·닫는 따옴표까지의 바이트 수**를 기존 행과 편집 결과 양쪽에서 확인한다. 이 검사는 모든 문자 인코딩·주석 형식의 엔진 호환성을 보장하지 않는다.

[독립 공개 명령 검사 57개](../../experiments/G06-OBS-PUBLIC-V-stage-01/integration-02/public-01/verification.json)와 [설치한 CLI의 영구 테스트 19개](../../experiments/CLI-G-G06-MDU-regression-157-01/observation-public.log)가 통과했다. 입력 지문, 경계 위·밖 좌표, CRS·단위, 편집 전후 바이트와 긴 이름을 포함한다. 첫 독립 실행은 검증 도중 제품 소스가 바뀌어 동결된 버전의 결과로 쓰지 않았다.

[독립 검증 기록](../../experiments/G06-OBS-V-combined145-149-20261105-07/verification.json)은 세 실행의 파일을 원래 위치에서 열어 입력·형상·시간·수위를 대조했고 원자료를 바꾸지 않았다.

[수정한 판독기로 기준·이동군의 원출력을 재검사](../../experiments/G06-OBS-I-offline-geometry-20261105-01/verification.json)한 뒤, [추가군만 새로 계산](../../experiments/G06-OBS-I-add-only-native-slot149-20261105-01/verification.json)했다. 입력·셀·허용 오차는 첫 시험과 같다. [통합자가 세 모델의 원출력을 직접 대조한 결과](../../experiments/G06-OBS-G-raw-01/verification.json), 추가한 `east_probe`는 셀 39와 13개 시각의 수위가 같았고 기존 두 점의 수위는 그대로였다. 새 점과 원래 `centre`의 최대 차이는 0.01113 m였다. 이동·추가 어느 쪽도 map이나 두 restart의 변수 102개를 바꾸지 않았다. 세 실행 모두 120초와 최종 restart에 도달했고 소유 프로세스의 종료를 확인했다.
