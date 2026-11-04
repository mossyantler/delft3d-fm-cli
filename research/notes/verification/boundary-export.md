# B04 · 경계선 위치와 신호를 별도 파일로 내보내기

개발 명령 `dfm boundary export`는 새 폴더에 PLI(위치), BC(신호), `collection.json`(원본과의 대응)을 작성한다. 기존 모델의 EXT를 고치지 않는다. 콘솔에서 프로젝트를 열어 MDU와 의존 파일 전체를 내보내는 `project export`와 용도가 다르다.

```powershell
$p = dfm boundary export model.mdu --out export-01 --group-by quantity | ConvertFrom-Json
dfm boundary export model.mdu --out export-01 --group-by quantity --apply --expect-sha256 $p.result.input_sha256
```

기본은 미리보기다. `--out`은 아직 없는 폴더여야 한다. `--boundary west`를 지정하면 PLI 내부 이름이 정확히 일치하는 경계만 선택한다. `process`에는 `--process-map`이 필요하다. EXT에서 GUI의 과정 분류를 알아낼 수 없기 때문에, 요청자가 물리량마다 과정 이름과 분류 근거를 선언한다. 원래 활성 BC 블록은 단위·공백·수직 위치 인덱스까지 그대로 복사한다. 각 출력 BC의 General 헤더는 새로 작성한다.

| 분할 방식 | 2개 경계, 3개 물리량, 활성 신호 12개의 파일 대조 |
| --- | --- |
| `all` | BC 1개, 신호 12개 |
| `boundary` | 서쪽과 동쪽 BC에 각각 6개 |
| `process` | 선언한 흐름 과정에 수위 신호 4개, 수송 과정에 염분·온도 신호 8개 |
| `quantity` | 수위·염분·온도 BC에 각각 4개 |

[혼합 입력 파일 시험](../../experiments/B04-EXPORT-G-mixed-02/verification.json)에서 내보낸 BC·PLI 바이트를 원본과 대조했다. 온도는 파일 분류를 구별하기 위해 추가한 것으로, 온도 계산을 검증한 것이 아니다.

**엔진에서 읽히는지도 별도로 확인했다.** 이미 검수한 [3층 수위·염분 수로](layers.md)의 원본과 네 분할 방식을 비교했다. 통합 검증기가 별도 복사본의 EXT를 내보낸 BC에 직접 연결한 뒤, 그 복사본에서 예전 BC를 제거했다. 다섯 번의 direct FM 계산 모두 20초에 도달했다. history·map·초기/최종 restart의 **190개 변수**가 네 비교에서 각각 기준군과 일치했다(차원, 자료형, 값, 마스크, 변수 속성). [최종 소스 실측 결과](../../experiments/B04-EXPORT-G-release-layers-01/verification.json) · [독립적으로 재연결하는 재현기](../../workflows/replay/boundary_export_layers.py). 이 결과는 한 수로의 파일 소비를 검증한다. GUI의 파일명·분류 규칙이나 다른 함수의 수치 동등성까지 입증하지 않는다.

**게시 경합은 별도 판정이다.** [첫 통합 반례](../../experiments/B04-EXPORT-G-stage-before-01/verification.json)에서는 임시 폴더가 이동한 직후 다른 작성자가 같은 이름으로 만든 파일이 삭제됐다. 성공·실패 두 경로 모두 재현했다. 기존 결과 폴더를 덮어쓰지 않는 검사는 이 문제를 잡지 못한다. 수정 뒤 [통합 재현](../../experiments/B04-EXPORT-G-release-stage-01/verification.json)에서는 두 경로 모두 다른 작성자의 파일이 남았다. [독립 검수 28개](../../experiments/B04-EXPORT-V-final-frozen-01/verification.json)와 [설치한 wheel](../../experiments/PKG-G-export-force-02/verification.json)의 소스 해시까지 대조해 네 가지 분할 내보내기를 승인했다. 위치 PLI 가져오기·좌표 변환과 실제 GUI 대화상자도 별도 작업이다.
