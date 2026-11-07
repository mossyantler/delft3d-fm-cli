# 취·방류 입력 조회와 작성

`inline-outfall-5`는 단일 방류점, `inline-intake-outfall-5`는 순서가 있는 취수·방류 두 점이다. 두 예제의 유량은 0.1 m³/s, 초기 염분은 10 ppt이며 2001-01-01 00:00:00–00:02:00 UTC를 사용한다. 수평 좌표는 예제 격자의 좌표계 그대로다. BC의 `Name`은 EXT의 `id = intake-A.1`과 연결하며, 경계 지원점 접미사 `_0001`을 붙이지 않는다.

새 복사본에서 기존 입력을 조회한다.

```powershell
Copy-Item -LiteralPath examples/source_sink/inline-outfall-5 -Destination source-case -Recurse
dfm source inspect source-case/model.mdu --id intake-A.1
```

아래는 염분 입력을 15 ppt로 선언한 새 BC를 만든 뒤 기존 방류점에 연결하는 두 번의 편집이다. 각 미리보기 내용을 확인한 후 같은 요청과 해시로 적용한다. 각 단계의 종료 코드와 JSON `ok`를 확인한다.

```powershell
$spec = 'examples/source_sink/specs/replacement-forcing.json'
$p = dfm source forcing-create --spec $spec --out source-case/replacement.bc | ConvertFrom-Json
if ($LASTEXITCODE -ne 0 -or -not $p.ok) { throw 'Forcing preview failed' }
$p.result
dfm source forcing-create --spec $spec --out source-case/replacement.bc --apply --expect-sha256 $p.result.sha256

$links = 'examples/source_sink/specs/link-replacement.json'
$p = dfm source set source-case/model.mdu --id intake-A.1 --spec $links | ConvertFrom-Json
if ($LASTEXITCODE -ne 0 -or -not $p.ok) { throw 'Source preview failed' }
$p.result
dfm source set source-case/model.mdu --id intake-A.1 --spec $links --apply --expect-sha256 $p.result.sha256
```

`forcing-create`는 새 BC 하나를 쓰며, `set`은 EXT 하나만 바꾼다. 두 단계는 하나의 원자적 변경이 아니다. 연결을 바꾼 뒤에도 기존 `source.bc`는 그대로 남는다. 다른 객체가 참조할 수 있으므로 자동 삭제하지 않는다. 새 SourceSink는 `source add MODEL.mdu --spec SPEC`으로 추가하며 기존 ID와 중복될 수 없다. [새 연결 쌍의 JSON 예제](specs/add-pair.json)는 같은 ID가 아직 없는 모델에만 적용한다. 필요한 BC를 먼저 작성하고, `add`도 별도 미리보기·해시·적용 순서를 따른다.

지원하는 작성 범위는 2D·명시적 UTC·운동량 면적 0·EXT 안의 XY 한 점 또는 두 점·선형 discharge/salinityDelta BC다. PLI 작성, 수직 범위, 운동량, 다른 성분과 단위 변환은 지원하지 않는다. `salinity`는 `salinityDelta`의 별칭이 아니다. 좌표를 쓰는 데 성공해도 격자 안의 위치나 과학적 타당성이 검증된 것은 아니다.

[실제 계산 대조 #225](../../research/notes/verification/source-sink.md#public-225)에서 단일점/연결 쌍의 무변경·수정·추가 여섯 사례가 각각 수동 기준의 170개 변수와 일치했다. 이 명령들은 입력 파일 작업이며, 해당 실험은 별도의 연구 실행기를 사용했다. 만든 모델은 `dfm run start model.mdu --profile source-sink --route direct|dimr --install '<suite root>' --out NEW --timeout 120`으로 실행한다. [공개 실행 프로필 4회 실행](../../research/notes/verification/source-sink.md#public-run)은 #225와 정확히 일치했다. GUI 내보내기는 아직 검증하지 않았다.
