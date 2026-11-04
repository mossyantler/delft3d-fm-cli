# B09 · 경계 하나에 BC 또는 CSV 신호 가져오기

개발 명령은 `dfm boundary import MODEL.mdu --boundary east --source SOURCE --format bc --mode replace`다. 기본은 미리보기다. CSV는 `--format csv --mapping mapping.json`으로 시간 열과 지원점별 값 열을 지정한다. 결과의 `actions`에서 각 점이 추가·교체·삭제·보존 중 무엇인지 확인한다. 적용 시 같은 인자에 `--apply --expect-sha256 <input_sha256>`를 붙인다. 점의 위치 PLI를 가져오거나 함수 종류를 바꾸는 명령은 아니다.

예를 들어 동쪽 경계의 1번·3번 점에 신호가 있고 2번 점은 비어 있다고 하자. 1번과 2번 신호만 담은 파일을 가져온 결과는 아래와 같다. 세 모드 모두 같은 BC 파일을 쓰는 서쪽 경계에는 손대지 않는다.

| 모드 | 동쪽 1번 | 동쪽 2번 | 동쪽 3번 |
| --- | --- | --- | --- |
| `replace` | 새 값으로 교체 | 추가 | 기존 신호 보존 |
| `extend` | 기존 신호 보존 | 추가 | 기존 신호 보존 |
| `overwrite-all` | 새 값으로 교체 | 추가 | 기존 신호 비활성화 |

CSV 열 매핑 예:

```json
{"version":1,"time_column":"t","time_unit":"seconds since 2001-01-01 00:00:00 +00:00","value_unit":"m","columns":{"east_0001":"south","east_0002":"middle"}}
```

시간은 선언한 UTC 원점에서의 경과 시간이다. 기존 메타데이터와 맞지 않는 단위·원점을 자동 변환하지 않는다. BC 입력은 새 EXT가 연결한 2D 수위 경계의 선형 시계열에 한한다. 지우는 모드도 대상 밖의 경계, 지원점 이름·좌표, 모델의 다른 파일은 보존해야 한다. GUI의 CSV 대화상자·클립보드나 보정 신호 가져오기를 시험했다는 뜻은 아니다. [GUI 작업과 매뉴얼 근거](../collection/gui-workflows.md#boundary-scopes).

**파일과 계산 대조:** [사전 선언 및 수동 모델 4개](../../experiments/B09-G-3point-01/manual-native.json)에서 48셀 수로를 120초 계산했다. 기준군 대비 동쪽 끝 네 셀의 최종 평균 수위는 replace +0.05932 m, extend +0.03344 m, overwrite-all +0.06873 m였다. [공개 CLI로 만든 여섯 입력](../../experiments/B09-G-3point-01/product-01/native-comparison.json)을 같은 모드의 수동 작성본과 각각 비교하니 history 57개, map 34개, 초기·최종 restart 각각 34개 변수의 자료형·마스크·값·변수 속성이 일치했다. 범용적인 GUI 동등성이나 다른 현장의 수위 예측 정확도를 의미하지 않는다.

[통합 재현기 10회](../../experiments/B09-G-frozen-modes-01/verification.json)에서도 같은 결과를 얻었으며, [최종 코드로 다시 생성한 여섯 입력 세트](../../experiments/B09-G-final-files-02/coordinator-equivalence.json)는 해당 실행의 입력과 파일 아홉 개가 모두 바이트 단위로 같았다. 독립 검증자는 [별도 수로의 세 계산](../../experiments/B09-V-canonical-native-slot-95-01/native-verification.json)에서 수동 작성·BC·CSV의 관측 수위, map과 최종 restart를 대조했다. 두 비교의 최대 절대 수위 차이는 모두 0 m였다. [NetCDF 없는 wheel 검사](../../experiments/B09-G-installed-wheel-02/verification.json)도 외부 BC의 BOM이 목적지로 옮겨지지 않고 목적지 자체의 BOM은 보존·진단되는 것을 확인했다.

**발견한 결함:** [초기 구현의 실패 기록](../../experiments/B09-V-stale-mesh-failure-01/independent-finding.json). 격자가 바뀐 후 예전 미리보기를 써도 BC가 덮어써졌다. 위 수치 대조와 오래된 미리보기 거부 검사는 별도의 승인 조건이다.

수정 후 [독립 검증](../../experiments/B09-V-public-portable-04/verification.json)은 격자와 기상 파일의 크기와 수정 시각을 복원해도 변경을 검출했다. [실제 격자 절점 좌표를 0.01 m 바꾼 통합 시험](../../experiments/B09-G-stale-netcdf-01/verification.json)도 종료 코드 4를 반환하고 BC를 보존했다. 33,560,644바이트 NetCDF로 같은 미리보기·적용을 각 세 번 측정하니 [수정 전](../../experiments/B09-G-fingerprint-io-01/measurement.json)과 [수정 후](../../experiments/B09-G-fingerprint-io-02/matched-warm.json)의 격자 전체 읽기는 각각 3→1회, 4→2회였다. 중앙값은 미리보기 145→83 ms, 적용 182→122 ms였다. [별도 프로세스 측정](../../experiments/B09-G-fingerprint-io-02/measurement.json)에서 수정 후 작업 집합 최대치의 중앙값은 각각 23.3 MiB와 23.4 MiB였다. 읽기 비용을 측정하기 위해 48셀 NetCDF에 계산에 쓰지 않는 변수를 추가했으며 엔진 계산 시간은 포함하지 않았다.

**BC 인코딩:** [같은 파일의 앞 세 바이트만 바꾼 실제 엔진 대조](../../experiments/B09-G-BC-BOM-01/verification.json)에서 설치된 FM `1.2.184.Unknown`은 UTF-8 BOM(`EF BB BF`)이 붙은 `[General]`을 알 수 없는 블록으로 보고 초기화 중 종료 코드 1을 반환했다. 나머지 바이트와 모든 참조 파일을 그대로 두고 그 표식만 뺀 복사본은 120초를 완료했다. 파일 편집이 보존에 성공하는 것과 해당 엔진이 그 파일을 읽을 수 있는 것은 별도 판정이다.

재현은 [세 모드 통합 재현기](../../workflows/replay/boundary_import_modes.py)를 쓴다. 기준 입력은 `M3-G-coordinator-final-01/relocated inputs`다. 파일 시험은 `python -m research.workflows.replay.boundary_import_modes --baseline <M3-입력> --out <새-폴더>`로 실행한다. native 비교에는 공정표의 `B09-G-replay` 실행 차례에서 `--install <suite> --native-slot <번호>`를 추가한다. [독립 검증기](../../workflows/verification/verify_boundary_import.py)는 다른 지원점·시계와 실패 사례로 검사한다.
