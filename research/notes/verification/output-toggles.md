# O03/O04 · 관측점 형상과 수지 시계열을 쓰는 MDU 키

Windows 2026.02 OpenHMWQ의 직접 FM으로 같은 f34를 세 번 계산했다. 기준 입력 열 개를 복사해 각각 MDU 값 한 개만 바꿨다. 세 경우 모두 600초에 도달하고 소유 Job이 비었다. [실행 기록](../../experiments/O03-O04-I-native-20261105-02/verification.json)과 [통합자가 원본 SHP·SHX·DBF와 NetCDF를 직접 대조한 결과](../../experiments/O03-O04-G-raw-01/verification.json)를 구별해 보관한다.

| MDU에서 바꾼 값 | 실제 파일 차이 | 무변경군과 비교 |
| --- | --- | --- |
| `[output] Wrishp_obs` 0 → 1 | `output/snapped/f34_snapped_obs.shp`, `.shx`, `.dbf` 생성 | 관측점 W1–W5의 DBF 원래 좌표는 history 관측점 좌표와 같았다. SHP의 좌표는 DBF가 가리키는 1부터 센 셀 번호 26·71·113·157·192의 map `FlowElem_xcc/ycc`와 각각 정확히 같았다. history·map·두 restart의 변수 191개 값과 마스크는 그대로였다. |
| `[output] Wrihis_balance` 1 → 0 | `f34_his.nc`의 변수 68개 중 `water_balance_*` 36개가 빠짐 | history의 나머지 32개와 map·두 restart를 합쳐 공통 변수 155개의 값과 마스크가 같았다. 별도 BC나 관측점 파일을 쓸 필요는 없었다. |

[독립 검증기 결과](../../experiments/O03-O04-V-independent-20261104-01/verification.json)는 세 실행의 원자료, GIS 속성과 공통 출력 비교를 기록한다. [첫 시도의 실패](../../experiments/O03-O04-I-native-20261104-01/verification.json)는 계산 실패가 아니었다. history의 1차원 `time`과 구간 경계 `time_bds(time,two)`가 같은 표준 이름을 썼고 검증기가 이를 중복 시계로 판정했다. [보관된 결과에서 수정한 판독을 검사](../../experiments/O03-O04-I-offline-preflight-20261105-01/verification.json)한 뒤 세 모델을 새로 실행했다.

위치는 격자에 맞춰진 관측점에 한정된다. 다른 지물이나 다른 설치의 shapefile 지원, GUI의 **Write Snapped Features** 체크박스가 몇 개의 MDU 키를 바꾸는지, 또는 모델 수지가 과학적으로 타당한지는 이 시험으로 판정할 수 없다.

**공개 편집기.** 기존 MDU의 `[output] Wrishp_obs`와 `Wrihis_balance`를 각각 0 또는 1로 바꿀 수 있다. 다음 예시는 관측점 형상을 켠다. 수지 출력을 끄려면 두 호출에서 주소와 값을 `output/Wrihis_balance 0`으로 바꾼다.

```powershell
$preview = dfm model set f34.mdu output/Wrishp_obs 1 | ConvertFrom-Json
if ($preview.ok) { dfm model set f34.mdu output/Wrishp_obs 1 --apply --expect-sha256 $preview.result.before_sha256 }
```

기존 값과 요청 값은 모두 ASCII `0` 또는 `1`이어야 한다. 주소가 없거나 대상 키가 여러 번 나오면 쓰지 않는다. `model fields`의 `model_set_preview`는 이 명령을 찾는 단서다. 미리보기의 지문은 MDU 전체 바이트를 대상으로 한다. 다른 설정·참조 파일까지 과학적으로 검증했다는 뜻은 아니다.

[최종 검수](../../experiments/O03-O04-PUBLIC-G-native-01/release.json)에서 독립 테스트 19개(공개 호출 218회)와 관련 회귀 87개를 확인했다. 두 설정 각각을 원래 값으로 돌리면 f34 파일 10개의 바이트가 모두 복원됐다. 이는 실행 뒤 결과 파일을 되돌린다는 뜻은 아니다.

[설치 wheel](../../experiments/PKG-G-output-toggles-02/verification.json)에서 공개 명령으로 준비한 f34 세 벌과 [수동 대조군](../../workflows/replay/output_toggle_controls.py)을 비교했다. [통합 검수 원자료](../../experiments/O03-O04-PUBLIC-G-native-01/verification.json)에서 각 쌍의 입력 10개가 같았고, 실제 직접 FM 세 번 모두 600초·최종 restart·소유 프로세스 종료를 확인했다. 무변경군과 형상 출력군은 각각 변수 191개, 수지 해제군은 155개의 차원·단위·마스크·값이 대응하는 수동 입력의 결과와 일치했다. 형상 출력군의 W1–W5 다섯 레코드도 별도로 비교했다. 결과 NC 전역의 생성 시각과 UUID 등은 달라질 수 있다. 입력과 원출력을 다시 확인하는 코드는 [설치본 검수기](../../workflows/verification/verify_installed_output_toggles.py)에 있다.
