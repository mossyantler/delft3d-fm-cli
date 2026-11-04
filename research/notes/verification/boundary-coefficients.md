# B11 · 경계선 전체의 수위 배율과 오프셋

한 PLI 선의 모든 **활성** 지원점에 같은 절대 배율 또는 오프셋을 지정한다. 원래 수위·시각 행은 편집하지 않는다. 대상은 새 EXT가 참조하는 선형 2열 수위 시계열이고, `boundary set`으로 한 조화 성분의 진폭을 변경하는 것과 다르다.

```powershell
$mdu = 'C:/models/copy/model.mdu'
$line = @('--boundary', 'east', '--quantity', 'waterlevelbnd')
dfm boundary coefficients $mdu @line
$preview = dfm boundary coefficients $mdu @line --offset 0.125 --unit m | ConvertFrom-Json
dfm boundary coefficients $mdu @line --offset 0.125 --unit m --apply --expect-sha256 $preview.result.input_sha256
```

배율만 바꾸려면 `--factor 2`로 별도 미리보기를 만든다. 값은 누적하지 않는다. 계수가 생략된 경우 배율 1, 오프셋 0으로 읽으며, 변경한 계수 하나만 첫 `Quantity` 앞에 넣는다. 이미 있으면 그 숫자만 교체한다. 다른 선, 미선택 계수, 주석과 데이터 행은 보존한다. 중복되거나 늦게 나온 계수는 거부한다. 함수·물리량·단위를 추정하지 않는다.

| 시험 | 결과 |
| --- | --- |
| [8개 직접 FM 계산](../../experiments/B11-COEFF-G-raw-167-02/verification.json) | 두 경계선이 있는 48셀 수로에서 8개 모두 120초. 명시/암시 기본값, 배율 2/직접 환산 수위, 오프셋 +0.125 m/직접 환산 수위, 뒤에 놓은 각 계수/무변경의 **5쌍**에서 history 57·map 34·restart 34×2개 변수의 값과 마스크가 같았다. |
| 경계가 실제 수위를 바꿨는가 | 기본값과 비교한 동쪽 관측점의 최대 절대 수위 차이는 배율 변경 0.01355 m, 오프셋 변경 0.12507 m였다. 계산된 반대편 수위까지 불변이어야 하는 것은 아니다. |
| [설치 CLI → 직접 FM](../../experiments/B11-PUBLIC-G-native-169-01/verification.json) | 기존 배율 수정·기존 오프셋 수정·생략된 오프셋 삽입의 세 경우에서 BC가 예상 바이트와 일치했고 다른 8개 입력 보존. 각각 수동 모델과 120초까지 159변수 일치. |
| [오판 대조](../../experiments/B11-COEFF-G-challenge-01/verification.json) | history 복사본에서 값(1 ULP), 단위, 마스크를 따로 바꾸자 세 경우 모두 해당 이유로 비교 실패. 최초 원자료 검사에서 manifest 키를 잘못 읽은 [실패 기록](../../experiments/B11-COEFF-G-raw-167-01/verification.json)도 보존했다. `command`를 v3의 `argv`로 고친 뒤 동일한 출력으로 재판정했다. |

[고정 소스와 매뉴얼 근거](../../experiments/B11-COEFF-I-20261105-024319-28b59c47/source-evidence.json): EC 판독기는 첫 물리량 선언 전에 전역 계수를 읽으며 이 스칼라 분기에서 유효 수위는 원래 값 × 배율 + 오프셋이다. FM 매뉴얼 §7.4.8.4(인쇄 p.106, PDF p.132)는 GUI 경계 속성표에 계수를 명시한다. 이 실험으로 GUI가 계수를 어떤 파일에 저장하는지, 조화·다층 경계에서 결과가 같은지는 확인하지 않았다.

재현은 [계수 입력 준비](../../workflows/replay/boundary_line_coefficients.py) → [원자료 판정 기준 고정](../../workflows/verification/verify_boundary_coefficient_gate.py) → [실행 소유권을 확인하는 순차 실행](../../workflows/replay/run_boundary_line_coefficients.py) 순이다. [설치 CLI 검사기](../../workflows/verification/verify_installed_coefficients.py)는 기본적으로 파일만 편집한다. 직접 계산에는 실행 슬롯이 따로 필요하다. [패키지와 증거 지문](../../catalog/coefficients-stations-gates.json).
