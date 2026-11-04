# E014 · 실제 MDU 키의 근거 조회와 제한된 스칼라 편집

`dfm model fields MODEL.mdu`는 **실제 파일에 있는 항목**을 원래 순서대로 돌려준다. 키, 값, 줄·바이트 위치, 같은 키의 몇 번째 항목인지, 고정 소스와 도우미 라이브러리에서 찾은 근거를 분리한다. 정적 색인에는 672개 주소가 있다. 353개는 FM 주 판독/쓰기 코드와 HYDROLIB 양쪽에서, 274개는 FM 쪽에서만, 45개는 HYDROLIB 쪽에서만 찾았다. 알려지지 않은 키는 그대로 보인다. 색인 수를 설치본의 지원 필드 수 또는 GUI에서 편집할 수 있는 필드 수로 해석하지 않는다.

**이 모델에서 편집이 가능한가?** 조회의 `editor_available`은 해당 주소를 다루는 편집기의 존재만 뜻한다. `edit_eligibility.state`가 `unsupported`면 편집기가 없고, `blocked`면 MDU 본문만으로도 거부할 이유가 있다. `requires_preview`이면 값과 단위 및 연결 파일을 아직 확인해야 한다. 세 경우 모두 조회의 `editable`은 false다. 성공한 `field-set` 미리보기에서만 `evidence.edit_support=preview_validated`와 적용에 쓸 `input_sha256`을 얻는다. 이 판정은 엔진 초기화나 과학적 검증이 아니다.

| 검수 입력 | Manning 계수 조회 | 같은 값 0.041, 같은 단위로 미리보기 |
| --- | --- | --- |
| 원본 f34 (Chezy, 65) | `blocked`: 마찰식과 바닥고 모드 모두 대상 밖 | 거부. 파일 불변 |
| f34 파생본 (Manning, 0.023) | 마찰식은 맞지만 바닥고 모드는 여전히 `blocked` | 거부. 파일 불변 |
| 48셀 합성 수로 (Manning, 0.023) | `requires_preview` | 연결된 격자·기준면·후보값 검사 후 허용. 미리보기이므로 파일 불변 |

[독립 검증기](../../workflows/verification/verify_field_edit_eligibility.py)는 원본과 변형 복사본에서 공개 명령 75회를 검사했다. NetCDF 열기와 과학 라이브러리 import를 막고도 조회·스키마가 작동했고, 중복 키·단위 오류·바뀐 참조 파일의 편집을 거부했다. 통합자는 설치본과 개발본을 별도로 호출해 [세 입력의 실제 결과](../../experiments/E014-G-eligibility-public-01/verification.json)를 대조했다. [새 wheel](../../experiments/PKG-G-field-eligibility-01/verification.json)은 NetCDF 없이 설치했다. 재현 명령: `python -m research.workflows.verification.verify_field_edit_eligibility --out <새-폴더>`.

| 명령 | 검수한 범위 |
| --- | --- |
| `dfm model fields MODEL.mdu --section physics --key uniffrictcoef` | 선택한 키의 모든 실제 항목을 조회한다. Manning 단위 표시는 명시적인 마찰식과 함께 판단한다. |
| `dfm model field-set MODEL.mdu geometry/waterlevini 0.25 --unit m` | 지원 프로필의 기존 균일 초기 수위 한 값을 미리 본다. 적용에는 `--apply --expect-sha256 <input_sha256>`가 필요하다. 지문에는 연결 파일도 포함된다. |
| `physics/uniffrictcoef`, `time/dtmax` | 같은 명령에서 Manning 계수(`--unit "s m-1/3"`)와 최대 시간 간격(`--unit s`)을 지원한다. 단위, 수직 기준, 초기 수위·바닥고 또는 계산 간격의 제약은 `dfm schema inspect`의 `field_edits`에서 확인한다. |

통합 시험 `research/experiments/E014-G-public-edit-01/`에서 48셀 수로 복사본의 실제 38개 항목을 읽었다. 잘못된 단위(cm)와 미리보기 뒤 BC가 바뀐 경우 모두 쓰기 전에 종료 코드 4로 거부했다. 정상 적용은 MDU의 목표 숫자 외에 한 바이트도 바꾸지 않았다. 이 시험은 엔진을 시작하지 않았다. GUI의 표시값과 내보낸 값이 같은지 확인한 사례는 별도의 [history 간격 실험](../replay/edit-experiment.md)이다.

설치 검수는 `research/experiments/PKG-coordinator-fields-preview-01/`에 있다. 개발판 wheel을 새 환경에 설치해 저장소 밖에서 NetCDF 없이 실제 MDU 필드를 읽었다. 패키지 안의 색인 바이트가 빌드 입력과 같았고 CLI·패키지 메타데이터 버전 모두 `0.4.0.dev1`이었다. 이 wheel의 소스 스냅샷과 지문은 `verification.json`에 있다.

**실제 엔진 통합 검수.** 초기 검증기는 주소·줄·alias는 일치하지만 중첩 함수·닫는 괄호 등 358개 Fortran 인자 표현이 잘못 추출됐음을 찾아냈다. 생성기를 고친 색인 SHA-256은 `d7b6f67ee06976f1b223fbc40fea6c55cc7057de2560565eecde0c702125315c`이며, 고정 소스 독립 대조에서 672개 주소의 줄/alias 및 변수 표현 차이는 모두 0개였다. 이전 wheel 검수는 패키지 포함·읽기에 대한 기록이지 수정된 파일 지문의 증거가 아니다.

같은 48셀 수로를 기준군과 세 변경군에서 새로 실행했다. 초기 수위 0→0.25 m는 실제 48셀의 `mesh2d_s1` 첫 시각에서, Manning 0.023→0.041은 유효 링크의 `mesh2d_cfu`와 마찰식 1에서, `DtMax` 1→0.25초는 `timestep` 출력에서 각각 구별됐다. `timestep`은 출력 순간의 계산 간격으로, 중간의 모든 내부 스텝을 기록한 값은 아니다. 네 사례 모두 history/map과 최종 restart가 120초를 가리켰고 원본 입력은 그대로였다. 이 세 설정에 대한 엔진 확인을 672개 주소로 일반화하지 않는다. 독립 `E014-V-native-20261104-01`은 수치 실험 통과·옛 색인 불일치를 함께 보존했다. 수정 뒤 통합 기록은 `E014-G-coordinator-final-01/verification.json`, SHA-256 `abe83db0df78883152677312753e5c942464d5ff02a6a334e477080f3b1501e2`다.

GUI 대조 입력을 고를 때는 활성 마찰식을 먼저 읽는다. [원본·별도 대조 입력의 지문과 네 설정](../../experiments/E014-G-source-controls-01/verification.json)에서 f34 내보내기와 저장 프로젝트의 동반 MDU는 모두 초기 수위 1.9 m, `DtMax=30`초, `UnifFrictType=0`(Chézy), 계수 65였다. M3 수로는 `UnifFrictType=1`(Manning), 계수 0.023이다. f34 격자가 필요한 시험용으로 마찰식·계수 두 항목만 바꾼 별도 사본도 준비했다. 두 법칙의 계수가 같은 물리량이라는 주장이나 GUI에서 해당 속성이 다시 저장됐다는 증거는 아니다.

재현: `python -m research.workflows.verification.verify_fields --baseline <M3-수로-입력-폴더> --out <새-폴더> --native --install <suite> --native-slot <할당한-번호>`. GUI에서 세 설정을 변경해 내보내는 시험은 별도로 남아 있다.

**콘솔 실험 준비:** [f34 실험 번들의 독립 검사](../../experiments/E014-GUI-G-pinned-oracle-03/verification.json)에서 실제 설치본의 속성 표와 형식, 원본 프로젝트 및 두 마찰식의 입력을 대조했다. 정적 소유자 후보는 `model.ModelDefinition.GetModelProperty(...).Value`이며 세 속성의 설치 스키마 형식은 `System.Double`이다. 콘솔은 시작하지 않았다. 이 실험은 FM 필드 하나를 바꾸고 그대로 내보낸 대조군과 비교하며 별도 DIMR exporter를 실행할 필요가 없다. 실제 게스트에서는 Manning 원본의 마찰식 1·계수 0.023이 저장·재열기 후에도 유지되는 것을 먼저 확인해야 한다. [격리·실행 절차](../../assets/fields-project-export/instructions.md).

수정 색인은 [배포 파일 검증기](../../workflows/verification/verify_wheel.py)로 다시 빌드했다. `PKG-G-corrected-field-registry-01`의 wheel SHA-256은 `dfa62efb5c2ca35ae642ae1c9e88ecddf8ccb26ea63039bca738a0d1d90d90f0`이고, 압축 내부의 색인은 위의 수정 지문과 같다. BedlevType=1처럼 셀 바닥을 따로 읽는 경우에는 유효한 노드 높이가 있어도 이 편집 프로필을 쓰지 않는다. `E014-G-unsupported-bed-01/refusal.json`에서 실제 무변경 거부를 확인했다.
