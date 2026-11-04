# B04 · 경계 위치 PLI 가져오기

**파일 끝에 있는 신호를 해제할 때의 수정:** [첫 반례](../../experiments/B04-PLI-G-east-contrast-02/verification.json)에서는 남겨야 할 서쪽 두 지원점의 진폭을 0.05 m와 0.25 m로 다르게 주었다. 동쪽 신호를 주석 처리한 모델과 수동으로 제거한 모델 모두 120초를 완주했지만 관측 수위가 최대 0.181693 m 달랐다. BC만 수동 대조군의 BC로 교체하면 차이는 0이었다. 수정본은 해당 블록을 활성 BC에서 제거하고 원문을 보관한다. [같은 입력을 다시 계산](../../experiments/B04-PLI-G-east-repair-03/verification.json)하자 차이는 0 m였고 네 데이터셋의 159개 변수가 일치했다.

`dfm boundary location-import`는 원본 모델을 그대로 두고 **새 작업 폴더**에 위치를 가져온다. 위치만 있는 새 선은 계산 경계로 연결하지 않는다. 기존 PLI와 파일명·내부 선 이름이 모두 같으면 좌표를 교체하고 **그 선에 연결된 모든 물리량의 신호를 해제한다**. 좌표만 옮기면서 이전 신호를 유지하려는 작업에는 이 명령을 사용하지 않는다.

```powershell
$p = dfm boundary location-import model.mdu --source survey.pli --out case-02 --coordinates as-is | ConvertFrom-Json
$p.result.removed_forcing_blocks
$p.result.disconnected_EXT_boundaries
dfm boundary location-import model.mdu --source survey.pli --out case-02 --coordinates as-is --apply --expect-sha256 $p.result.input_sha256
```

- 새 선: 원래 엔진 입력은 그대로 두고 새 PLI와 작성 기록을 `.dfm-boundary-locations/` 아래에 둔다. 여기에 PLI가 존재한다는 사실은 FM이 그 선을 사용한다는 뜻이 아니다.
- 기존 선: 해당 EXT 경계 블록과 BC 신호를 비활성화하고, 변경 전 파일과 들어온 PLI를 별도로 보관한다. 다른 선과 공유하는 BC에서도 다른 선의 신호는 남는다. 마지막 경계 해제로 EXT에 General만 남으면 MDU의 해당 참조도 비운다.
- `as-is`: XY 두 열의 값을 그대로 사용한다. 수평 CRS 일치나 높이 기준을 추정하지 않는다. 입력 지문은 모델, 들어온 파일, 모드와 목적 경로를 묶는다. 미리보기에서 해제될 신호를 확인한 뒤 같은 요청의 지문으로 적용한다.

**파일 변화와 계산 효과를 따로 확인했다.** [공개 명령과 수동 모델 네 개의 실제 실행](../../experiments/B04-PLI-G-release-native-01/verification.json)에는 48셀 수로의 history, map, 시작·종료 restart가 있다. 네 경우 모두 120초에 도달했다.

| 공개 명령에서 가져온 위치 | 원본 9개 파일 중 달라진 파일 | 수동 대조군과의 결과 |
| --- | --- | --- |
| 새 `survey.pli` | 없음. 새 선은 별도 기록에만 존재 | 원본과 네 데이터셋의 변수 159개가 같고 서쪽 네 셀의 최종 평균 수위는 0.043976 m |
| 기존 `boundary_west.pli` 교체 | 서쪽 PLI, 공유 `boundaries.ext`, 공유 `boundaries.bc` | 서쪽 경계 신호만 제거한 수동 모델과 변수 159개가 같고 최종 평균 수위는 0 m |

위치가 계산에 쓰이지 않는 두 경우이므로 출력이 일치한다는 사실만으로 좌표의 정확성을 검증할 수 없다. [통합 재현기](../../workflows/verification/verify_location_import_native.py)는 실제 작성한 PLI의 이름·점 수·각 XY와 보관된 원본 해시를 **실행 전에** 독립 대조한다. 대상 모델은 `M3-G-coordinator-final-01/normalized_replay`, 모드는 `--coordinates as-is`이며, 새 출력 폴더와 조정자가 할당한 실행 번호가 필요하다.

**원좌표 모드 승인.** [첫 반례](../../experiments/B04-PLI-G-corrupt-inventory-01/stdout.json)에서 기존 작성 기록의 경로에 `./`를 붙이면 내부 오류 70이 발생했다. 수정 후 [잘못된 기록 네 종류](../../experiments/B04-PLI-G-corrupt-inventory-final-03/verification.json)는 원본 변경이나 출력 생성 없이 데이터 오류 3으로 거부됐고 정상 기록은 재사용됐다. [독립 공개 명령 검사 63개](../../experiments/B04-PLI-V-inventory-final-public-cli-01/verification.json), [수정본의 실제 계산 네 건](../../experiments/B04-PLI-G-repaired-native-01/verification.json), [옵션 패키지 없는 wheel](../../experiments/PKG-G-pli-repair-02/verification.json)을 같은 소스 해시로 [최종 대조](../../experiments/B04-PLI-G-accepted-01/verification.json)했다.

**다른 수평 좌표계에서 가져오기.** `pip install -e '.[geo]'`로 선택 라이브러리를 설치한다. 다음은 실제 수로 망의 `NetFile`이 EPSG:32631·미터로 선언돼 있고, 새 위치가 EPSG:4326의 경도·위도 순서일 때의 미리보기다.

```powershell
dfm boundary location-import model.mdu --source survey.pli --out projected-copy --coordinates transform --source-crs EPSG:4326 --source-unit degree --target-crs EPSG:32631 --target-unit m
```

같은 인자에 `--apply --expect-sha256 <미리보기 지문>`을 붙여 적용한다. 요청과 실제 망 메타데이터가 모순되거나 필요한 변환을 오프라인에서 이용할 수 없으면 거부한다. 변환 경로·실행 버전·좌표와 원본 PLI 바이트를 구분해 보관하며, 높이 기준은 바꾸지 않는다. [좌표 계산 검증](../../experiments/B04-CRS-V-extended-20261104-234041-d134f010/verification.json)은 독립 UTM 공식·축·단위·역변환을 확인했다. [실제 공개 명령과 엔진 대조](../../experiments/B04-CRS-G-public-native-01/verification.json)에서는 경도·위도에서 변환한 각 점이 수동 대조 좌표와 0.13 mm 이내였고, 원본·수동 해제·공개 추가·공개 교체 네 모델의 120초 비교도 통과했다. 이 수치는 해당 합성 수로의 오차이며 일반 좌표 변환 정확도나 GUI와의 일치를 뜻하지 않는다.
