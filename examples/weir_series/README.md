# G16 · 가동보 마루 시계열 대조 입력

[model/model.mdu](model/model.mdu)는 48셀 합성 수로의 120초 입력이다.
모델 전체를 새 폴더에 복사해 사용한다. MDU의 `StructureFile` →
[structures.ini](model/structures.ini)의 `blocking_weir.crestLevel` →
[crest.tim](model/crest.tim)이 편집 대상이다. 보 위치, 경계 수위, 관측점과
관측 단면은 별도 파일이며 마루 높이 변경으로 달라져서는 안 된다.

| 입력 | 시각의 의미 | 높이 |
| --- | --- | --- |
| 기준 TIM | 2001-01-01 00:00 UTC부터 **분**: 0, 1, 1.1, 2 | 모두 −0.5 m |
| [raise.csv](raise.csv) | 같은 원점부터 **초**: 기존 66초와 120초 행만 선택 | 두 값 모두 +0.5 m |
| [restore.csv](restore.csv) | 같은 원점부터 **초**: 같은 두 행 | 두 값 모두 −0.5 m로 복원 |

CSV 자체에는 시간 단위·원점·높이 단위가 없다. 위 조건은 이 예제에
명시한 값이다. MDU의 `TUnit=S`를 TIM 열의 단위로 사용하면 60배 차이가 난다.

기준 입력 11개는 [엔진 실험 #185](../../research/notes/verification/weir-crest-series.md)의
`tim_low`와 같다. 그 실행의 0초 history에서 마루는 0 m, 1초부터는 −0.5 m였다.
#185의 변화 사례는 **높은 마루를 낮춘** 경우다. 여기의 두 CSV는 반대 방향
편집과 원복을 대조할 입력이며 GUI가 생성한 CSV가 아니다. [#211](../../research/notes/verification/weir-crest-series.md#native-211)에서는 마루를 올린 수동 입력과 CLI 입력의 120초 결과가 일치했다. 하류 수위 차이의 부호는 시각에 따라 달랐다.

저장소 루트에서 다음 PowerShell 명령으로 새 복사본을 편집한다. 대상 폴더는
없어야 한다. `series-import`는 지정한 시각이 이미 TIM에 있을 때만 값을
바꾸며, 미리보기와 적용 사이에 입력 파일이 달라지면 적용을 거부한다.

```powershell
$work = New-Item -ItemType Directory -Path weir-demo -ErrorAction Stop
Copy-Item -Recurse examples/weir_series/model -Destination $work.FullName
$opts = @("$work/model/model.mdu", '--id', 'blocking_weir', '--time-unit', 's', '--time-origin', '2001-01-01T00:00:00Z', '--height-unit', 'm')
dfm weir series-inspect @opts
$p = dfm weir series-import @opts --csv examples/weir_series/raise.csv | ConvertFrom-Json
if (!$p.ok) { throw $p.error.message }
dfm weir series-import @opts --csv examples/weir_series/raise.csv --apply --expect-sha256 $p.result.input_sha256
```

원복할 때는 `restore.csv`로 미리보기를 다시 받아 같은 순서로 적용한다.
`dfm weir series-export @opts --out "$work/export"`는 내보내기 미리보기다.
그 지문으로 적용하면 새 폴더에 `crest.csv`와 단위·원점이 담긴 `receipt.json`을 쓴다.
전체 입력 11개의 원복을 확인한 [설치본 검수](../../research/experiments/G16-SERIES-G-example-01/checked-01/verification.json).

편집한 복사본은 아래 명령으로 120초까지 계산할 수 있다. 필요한 것은 Windows용
D-Flow FM 설치와 CLI의 `run` 추가 패키지다. `--out`은 모델 폴더 밖의 새 경로를 쓴다.

```powershell
dfm run start "$work/model/model.mdu" --out "$work/run" --route direct --profile weir-series --timeout 120
dfm run status "$work/run"
```

설치 위치가 자동으로 선택되지 않으면 `--install '<suite-root>'`를 지정한다.
이 프로필은 이 예제의 48셀 수로와 보 하나, 두 수위 경계, 기존 TIM에 한정된다.
[실행 대조 #217](../../research/notes/verification/weir-crest-series.md#public-run):
history와 map은 0–120초의 121개 시각, restart는 0초와 120초다.
다른 격자, DIMR 또는 재시작 실행에 이 결과를 적용하지 않는다.
