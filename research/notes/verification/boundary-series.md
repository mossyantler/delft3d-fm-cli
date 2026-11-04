# B03 · 기존 수위 시계열의 값과 시간 행 편집

`dfm boundary series-inspect MODEL.mdu --point east_0001`는 새 EXT가 가리키는 PLI에서 지원점을 찾고, 연결된 BC의 시간 원점·단위·보간 방식과 실제 데이터 행을 읽는다. `series-set`은 같은 점의 **기존 시각**을 지정해 값만 바꾼다. 시간을 삽입·삭제하거나 다른 기준시각으로 변환하지 않는다.

**시간 행을 바꿀 때는 `boundary series-rows`를 쓴다.** 기존 선형 수위 BC 한 지원점에 대해 `insert`에는 명시적 시각·값을, `delete`에는 지울 시각을 쓴다. 배열 두 개가 모두 필요하다. 시각의 단위와 원점은 기존 BC와 같아야 한다. 최종 시간표는 두 행 이상이어야 하고 모의 시작부터 끝까지 덮어야 한다. 기존 시각을 이 명령으로 덮어쓰거나 같은 시각을 동시에 넣고 지우지는 않는다. 삭제하려는 숫자 행에 주석이 붙어 있으면 쓰기 전에 거부한다.

[예제 요청](../../../examples/channel/rows.json)은 [예제 수로](../../../examples/channel/model.json)의 2026년 시간 원점용이다. 다른 모델에서는 먼저 `series-inspect`로 단위를 확인한다.

```powershell
$p = dfm boundary series-rows model.mdu --point east_0001 --rows rows.json | ConvertFrom-Json
if ($p.ok) { dfm boundary series-rows model.mdu --point east_0001 --rows rows.json --apply --expect-sha256 $p.result.input_sha256 }
```

[새 예제 모델의 설치본 재현](../../experiments/B03-ROWS-G-example-01/verification.json)에서 목표 시각이 2개에서 4개가 됐다. 미리보기의 `receipt`에는 삭제되는 실제 행과 원래 바이트, 추가되는 시각·값과 변경 전후 BC 해시가 담긴다. 요청 파일이나 연결된 입력이 바뀌면 새 미리보기가 필요하다. 자동으로 시각·값을 생성하거나 GUI 표 편집기를 호출하지 않는다.

**2001년 독립 수로 대조.** [수동 BC와 120초 결과 네 벌](../../experiments/B03-ROWS-G-controls-01/verification.json)은 `east_0001`에 30초/0.20 m와 60초/−0.06 m를 넣은 경우, 그중 첫 행을 삭제한 경우, 첫 행을 45초/0.14 m로 교체한 경우, 무변경군이다. 두 관측점과 13개 시각에서 무변경군 대비 최대 절대 수위 차이는 각각 0.09120, 0.01427, 0.05329 m였다. [설치본을 통한 네 편집과 실제 계산](../../experiments/B03-ROWS-G-public-native-01/verification.json)은 각 수동 입력과 아홉 파일의 바이트가 같았고, 네 NetCDF에 저장된 변수 159개의 값·단위·차원·마스크도 각 쌍에서 일치했다. 추가한 두 행을 모두 지우면 원래 모델로 돌아왔다. 매번 최종 120초 restart와 소유 프로세스 종료를 확인했다. [재현기](../../workflows/verification/verify_installed_series_rows.py)는 `--install`·`--slot`을 생략하면 설치본의 입력 비교만 수행한다.

위 행 편집의 [통합 승인 기록](../../experiments/B03-ROWS-G-public-native-01/release.json)은 [독립 공개 검사](../../experiments/B03-ROWS-V-stage-01/verification.json)와 설치 wheel의 소스 지문을 연결한다. 공개 호출 186회에는 거부·무변경 검사도 포함된다. 설치본의 독립 테스트 23개는 모두 통과했다. 관련 기존 테스트 97개 중 Windows 심볼릭 링크 생성 권한이 필요한 한 건은 건너뛰었다.

2026년 별도 수로의 첫 두 시도는 기준 입력 자체의 진단이다. [첫 시도](../../experiments/B03-ROWS-2026-V-20261105-011213-056e8727/verification.json)는 실행 프로필의 `WaveModelNr` 검사에서 멈춰 엔진을 시작하지 않았다. [두 번째](../../experiments/B03-ROWS-2026-V-derivative-20261105-011733-3d6564e7/verification.json)는 프로필을 통과했지만 실제 FM이 기준 MDU의 `[General] Program` 누락으로 종료 코드 1을 반환했다. 어느 쪽도 경계 시간표의 결과로 세지 않는다.

**2026년 수로의 보간·변화 대조.** 실행에 필요한 모델 식별자와 비활성 과정 설정을 동일하게 보완한 [다섯 새 복사본](../../experiments/B03-ROWS-2026-V-native-identity-20261105-012630-66fb054b/verification.json)은 모두 120초에 도달했다. 기준 시간표, 직선 위의 시각만 바꾼 시간표, 한 시각의 처방값을 높인 시간표를 비교했다. [통합자의 원시 배열 재판독](../../experiments/B03-ROWS-G-2026-raw-01/verification.json)에서 직선 위 편집은 세 관측점의 저장 수위를 바꾸지 않았다. 처방값을 높인 경우 30–120초 기준군 대비 최대 절대 수위차는 `east_south` 0.03565 m, `east_north` 0.01796 m, `west` 0.00726 m였다. 두 편집 모두 설치 CLI로 작성한 모델과 손으로 쓴 같은 시간표 모델은 각 쌍에서 네 NetCDF의 변수 159개가 정확히 일치했다. 이는 해당 모델의 시간 보간과 반응을 확인한 것이며 현장 모델의 수위 정확도 검증이 아니다.

**기존 값만 편집하는 예.** 아래는 2001년 M3 수로 복사본의 요청 파일이다. 다른 모델에서는 조회 결과의 `time_unit`과 `value_unit`을 그대로 사용한다.

```json
{"time_unit":"seconds since 2001-01-01 00:00:00 +00:00","value_unit":"m","changes":[{"time":"0","value":"0.04"},{"time":"120","value":"0.18"}]}
```

```powershell
$preview = dfm boundary series-set .\model.mdu --point east_0001 --values .\changes.json | ConvertFrom-Json
dfm boundary series-set .\model.mdu --point east_0001 --values .\changes.json --apply --expect-sha256 $preview.result.input_sha256
```

지문은 연결된 경계 입력과 요청 파일의 경로·바이트, 선택한 점을 묶는다. [통합 시험](../../experiments/B03-G-channel-edit-01/coordinator-raw.json)에서 요청 끝에 줄바꿈만 추가해도 이전 미리보기의 적용은 거부됐다. 원래 요청을 적용한 뒤에는 직접 두 숫자만 바꾼 대조 모델과 입력 파일 전체가 바이트 단위로 같았다.

| 별도 시험 | 바꾼 입력 | 설치된 FM에서 확인한 결과 |
| --- | --- | --- |
| 통합자 · 2001년 48셀 수로, 세 번의 직접 실행 | 원래 상태, 공개 CLI로 두 값 편집, 독립적으로 같은 두 값을 작성 | 120초까지 편집군과 수동 대조군의 13개 history/map 수위 및 최종 restart 수위가 저장 정밀도로 정확히 일치했다. 원래 경계와 비교한 동쪽 끝 4셀의 최종 평균 수위 차이는 +0.0834603 m였다. |
| [독립 검증자](../../experiments/B03-V-native-slot77-20261104-212609-c9f856ee/verification.json) · 2026년 수로, 세 번의 직접 실행 | 모든 지원점이 0인 기준군, 한 점의 20·120초 값을 0.12 m로 바꾼 모델, 240초 값만 바꾼 모델 | 120초 모의에서 활성 구간을 바꾼 모델의 경계 근처 관측 수위 차이는 후반 평균 +0.0772314 m였다. 모의가 끝난 뒤의 값만 바꾼 경우에는 기준군 대비 차이가 사전에 정한 0.000001 m 이내였다. |

[독립 실행의 종료 기록](../../experiments/B03-V-native-slot77-20261104-212609-c9f856ee/slot-closure.json)에는 각 실행의 루트 종료와 빈 Job이 남았다. 당시 직렬 경로에서는 누적 프로세스 2개 중 1개의 종료 핸들만 보존했으므로, 이 물리량·파일 보존 시험을 모든 자식의 개별 종료 증거로 쓰지 않는다.

[독립 재현기](../../workflows/verification/verify_boundary_series.py)의 기본값은 작성·검사만 수행한다. 네이티브 재현에는 빈 결과 폴더, 설치 경로와 배정된 전용 실행 슬롯이 필요하다. 범위는 명시적인 UTC 원점과 m 단위를 쓰는 2D 선형 수위 시계열이다. GUI의 BC 가져오기 모드(B09), 함수 전환(B10), 천문분조·수위–유량표 및 현장 검보정은 이 시험에서 다루지 않았다.
