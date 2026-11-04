# FM MDU의 Program 판정

[기계 판독용 검수 결과](../../catalog/fm-identity-gate.json)는 14개 입력의 정적 판정·설치 엔진 결과와 원자료의 SHA-256을 담는다.

`model validate`의 `fm_model_identity`는 FM이 어느 섹션에서 어떤 프로그램 이름을 읽을지 검사한다. 섹션·키의 대소문자는 구별하지 않고 값의 대소문자는 구별한다. 일반 파일 조회와 값 편집은 그대로 가능하다. `run start`는 식별자를 확인할 수 없으면 설치를 고르거나 실행 폴더를 만들기 전에 거부하고, 실행 직전에는 복사된 MDU를 다시 확인한다. 입력에 누락된 키를 자동으로 넣지 않는다.

| 입력 | 정적 판정 | 설치본 근거 |
| --- | --- | --- |
| `[General] FileVersion=1.09`와 `Program` | `D-Flow FM`, `D-Flow Flexible Mesh`, `Unstruc`, `UNSTRUC`를 허용 | 같은 48셀 수로에서 네 표기 모두 직접 FM 120초, history·map과 restart 두 개 생성. 섹션·키의 대소문자를 섞은 사례도 완료 |
| Program 누락·빈 값·잘못된 대소문자 | `fm_model_identity_invalid` | 검사 도입 전에는 각각 엔진 초기화에서 실패했다. 같은 이름의 키를 둘 넣은 두 대조군은 당시 CLI가 먼저 거부했으므로 엔진의 중복 처리 규칙은 알 수 없다 |
| General/FileVersion이 없거나 비어 있음 | `[model] Program`을 검사한다. 어느 섹션을 사용할지 판독하지 못한 버전 표기는 명시적으로 거부한다 | [설치본의 세 대조군](../../experiments/MDU-ID-V-stage-01/native-slot-155-01/verification.json): FileVersion이 없는 모델은 유효한 구형 Program으로 120초 완료. General의 값만 맞고 구형 값이 틀리면 실패. 반대로 1.09 형식에서는 구형 값만 틀려도 완료 |
| FileVersion=9.99, Program은 정상 | Program과 파일 버전의 호환 여부는 별개다 | 설치본은 지원하지 않는 버전이라는 진단을 쓰고 종료 코드 1로 끝났다. Program 통과는 실행 가능 보장이 아니다 |

[11개 대조군의 실행 기록](../../experiments/MDU-ID-V-stage-01/native-slot-153-01/verification.json)에는 엔진을 시작한 9회와 시작 전에 거부한 2회가 구별되어 있다. [판독 분기와 Program 비교](https://github.com/Deltares/Delft3D/blob/5a4649830b1e5072caf019fb4850bbdefd9ad431/src/engines_gpl/dflowfm/packages/dflowfm_kernel/src/dflowfm_data/unstruc_model.f90#L786)는 수집한 소스 기준이며 설치 엔진의 소스 SHA는 알 수 없다. 이 검사는 다른 DIMR 구성요소의 입력 파일에 FM 규칙을 적용하지 않는다.

[설치한 CLI의 14개 입력 검사](../../experiments/MDU-ID-G-public-01/verification.json)에서는 잘못되거나 모호한 식별자 6개를 직접 FM과 DIMR 양쪽에서 실행 폴더 생성 전에 거부했다. 검사 전후 MDU 바이트는 그대로였다. [같은 패키지로 재실행한 f34](../../experiments/MDU-ID-G-f34-156-01/verification.json)에서는 두 경로 모두 600초 최종 시각과 restart를 확인했다. 네 NetCDF 파일의 변수 191개 값이 일치했고 두 실행 모두 소유 프로세스가 종료됐다.
