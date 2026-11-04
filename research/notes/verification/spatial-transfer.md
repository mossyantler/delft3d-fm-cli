# 관측점 파일 왕복과 관측 단면 반전

관측점 파일은 MDU `[output] ObsFile`이 가리키는 XYN이다. `CrsFile`은 유량을 합산할 관측 단면의 PLI다. 두 명령은 서로 다른 파일을 편집하며, 실행 전에는 계산망에서 실제 관측한 위치나 유량을 보고하지 않는다.

| 작업 | 공개 명령 (`dfm` 뒤에 사용) | 파일에 대한 약속 |
| --- | --- | --- |
| 관측점 파일 추출 | `observation export MODEL.mdu --out C:/survey/stations.xyn` | 모델 밖의 **새 파일**에 해당 XYN을 바이트 그대로 기록한다. 기존 파일은 덮어쓰지 않는다. 망이 없어도 추출할 수 있다. |
| 관측점 추가 또는 교체 | `observation import MODEL.mdu --source C:/survey/incoming.xyn --mode append --crs EPSG:32631 --unit m` | `append`는 기존 이름과 겹치면 거부한다. `replace-all`은 XYN 전체를 교체하므로 미리보기의 `identity_disclosure`에서 없어질 점을 확인한다. 두 모드 모두 원래 점과 새 점의 좌표를 검사한다. |
| 유량 관측 단면 조회·반전 | `section inspect MODEL.mdu`, `section reverse MODEL.mdu --id Entrance` | 단면 ID를 정확히 선택한다. 해당 단면의 꼭짓점 행을 역순으로 배치한다. 다른 단면·입력·각 행 위치의 줄바꿈을 보존한다. 단면적·유량은 계산 후 결과에서 읽는다. |

쓰는 명령은 먼저 미리보기를 반환한다. 같은 인자에 `--apply --expect-sha256 <result.input_sha256>`를 붙여 적용한다. 관측점 가져오기는 `geo` 추가 의존성과 미터 단위 투영망이 필요하다. 경계 위의 점, 중복 이름, 빈 가져오기, 모호한 참조를 거부한다. 좌표를 보정하거나 가장 가까운 셀로 옮기지 않는다. 파일 내보내기와 단면 반전은 기본 설치에서도 동작한다.

| 설치 패키지로 수행한 대조 | 공개 명령으로 얻은 입력 | 직접 FM 결과 |
| --- | --- | --- |
| [G10: 수로의 추가·삭제·이동](../../experiments/G10-PUBLIC-G-native-161-01/verification.json) | 한 행을 추가했고, 별도 두 사례에서는 실제 XYN export를 `replace-all`로 가져왔다. 각각 수동 대조군의 입력 9개와 바이트가 일치했다. | 세 사례 모두 120초. history/map 각 13시각과 시작·최종 restart를 포함한 **159개 변수**가 각각 같은 수동 사례와 일치했다. |
| [G12: f34의 Entrance 반전·원복](../../experiments/G12-PUBLIC-G-native-161-01/verification.json) | 8개 꼭짓점을 뒤집은 파일이 수동 반전본과 일치했고, 두 번 적용한 입력 10개는 모두 원본과 일치했다. | 반전·원복 모두 600초. 두 경우 각각 history/map 11시각과 시작·최종 restart를 포함한 **191개 변수**가 해당 대조군과 일치했다. [별도 물리량 대조](section-orientation.md)에서 마지막 유량은 +45.723354 → −45.723354 m³/s, 단면적은 그대로였다. |

비교기는 배열의 차원·자료형·마스크·값과 변수 속성을 읽는다. 파일 생성 시각·UUID 등 출처 메타데이터는 별도로 다룬다. [패키지 검사](../../experiments/PKG-G-spatial-01/verification.json)는 추가 의존성이 없는 새 환경에서 실행했고, 이후 같은 패키지에 `geo`를 설치해 네이티브 실험을 수행했다. 원본 입력·수동 대조군은 덮어쓰지 않았다.

재현: `python -m research.workflows.verification.verify_installed_spatial_transfer section --dfm <설치한-dfm> --install <suite-root> --out <새-폴더>`. 관측점에는 `observation`을 사용한다. 기본은 파일 대조이고, 실제 계산은 할당된 실행 슬롯에서 `--execute --native-slot-granted <번호> --lease-owner <소유자>`를 추가한다. GUI의 중복 이름 정책, 지도에서 뒤집기, 계산 전 추정 레이어는 이 실험 범위 밖이다.

**여러 점의 좌표 확인 비용.** 48셀에서 32점을 각각 기존 단일점 판정기로 확인하면 망을 64번 열고 품질 검사를 32번 했다(2.575초). 같은 좌표를 한 묶음으로 확인하면 열기 2번·품질 검사 1번이었다(0.081초). 두 번째 열기는 독립된 CRS 확인에 필요하다. 4,096셀의 128점 묶음은 0.717초였다. 같은 큰 망에서 단일점 반복은 20.495초 동안 28점만 측정했으므로 전체 128점의 배속은 제시하지 않는다. 이 수치는 엔진 시간이 아닌 **한 번의 좌표 검사 측정**이다. [분리 측정한 시간·메모리·판정 결과](../../experiments/G10-BATCH-V-live-02/verification.json). [공개 명령을 세 번씩 실행한 별도 측정](../../experiments/G10-XYN-V-stage-01/integration-01/public-benchmark-01/verification.json)에서는 4,094행 가져오기의 미리보기 중앙값이 0.973초, 적용이 1.075초였다. 후속 CRS 판독기는 지문만 필요할 때 망을 64 KiB씩 읽고, 실제 입력 크기보다 큰 버퍼를 미리 요청하지 않는다. [동일한 128점 가져오기 미리보기](../../experiments/CRS-IO-G-batch-01/verification.json)에서 Python 할당 최고치는 48셀 **256.58→1.88 MiB**, 4,096셀 **258.89→11.37 MiB**였다. 계산한 셀, NetCDF 열기 2회·품질 검사 1회는 같았다. 프로세스 RSS나 엔진 메모리 측정은 아니다. [독립 무결성·경합 검사](../../experiments/CRS-IO-V-before-after-03/independent-summary.json)에서 원본 교체와 같은 크기·시각의 내용 변경도 거부했다.

**입력 망에 들어 있어도 실제 관측값이 없을 수 있다(G11).** 48셀 수로에 같은 건조 다각형 파일을 지정하고 위치만 바꿨다. 두 모델 모두 관측점 입력은 같고, 영역 밖 관측점 삭제는 꺼져 있다. `DryPointsFile=.pol`은 이 MDU 항목에서만 불투명한 입력으로 허용한다. 정적 검사가 다각형의 내용이나 효과를 검증하지는 않는다.

| 120초 출력 | 다각형을 망 밖에 둔 대조군 | 다각형이 관측점 셀 하나를 덮은 경우 |
| --- | --- | --- |
| 실제 map과 `centre` | 48셀. 원래 요청 좌표 (500061.25, 5700018.75)가 중심 (500065, 5700015)인 셀에 연결됐고, history 수위 13개가 그 셀의 map과 일치 | 47셀. 해당 셀이 없어졌으며, history의 `centre` 이름은 남아도 **13개 수위가 모두 결측**이었다. snapped SHP/DBF에는 해당 점이 없고 FM 진단에도 셀을 찾지 못했다는 메시지가 있었다. |
| 다른 점 `upstream` | 자기 map 셀에 연결됐고 유효한 수위 13개 | 자기 map 셀에 계속 연결됐고 유효한 수위 13개. 다각형이 수리에 영향을 주므로 두 실행의 수위가 같을 필요는 없다. |

[첫 검증기](../../experiments/G11-DRY-I-offline-163-01/verification.json)는 JSON에서 읽은 좌표 목록과 메모리의 튜플을 비교해 습윤 대조군부터 거부했다. [표현만 맞춰 다시 판독한 기록](../../experiments/G11-DRY-I-rerated-offline-163-01/representation-rerating.json)과 [별도의 NetCDF·SHP·DBF 판독](../../experiments/G11-DRY-V-raw-review-20261105-023908-a669b026/review/verification.json)이 같은 원출력에서 위 결과를 확인했다. 재계산이나 허용오차 변경은 없었다. 모든 결측값의 원인을 건조 셀로 단정하거나, GUI의 계산 전 추정 레이어도 같은 셀을 표시한다고 해석해서는 안 된다.

[패키지·원자료·검수 기록의 SHA-256 색인](../../catalog/spatial-transfer-gates.json). 같은 패키지에서 f34 직렬 direct/DIMR은 600초·191변수, E009/E011은 오류·취소 17개 검사군을 통과했다.

**실행 뒤 실제 관측점 배치 조회:** `dfm results stations RUN`은 실행 폴더를 읽고 JSON만 반환한다. 예를 들어 습윤 대조군의 `centre`는 입력 셀 18, 출력 map 셀 24(각각 0부터 센 번호)이며 13시각의 수위와 마스크가 일치했다. 건조 다각형을 옮기면 같은 ID가 history에 남고 모두 결측이며 형상에 해당 점이 없어 배치는 `unknown`이다. `upstream`은 두 경우 모두 입력 셀 25, map 셀 7로 확인했다. 형상 세 파일 전체가 없으면 판정 불가, 일부만 있거나 이름이 모호하면 데이터 오류다. 잘못된 기존 지문은 종료 코드 3, 읽는 도중 파일이 바뀌면 4로 구별한다.

[독립 검증 29건](../../experiments/G11-ASSIGN-V-stage-01/PUBLIC_REPORT.md)을 [설치 wheel](../../experiments/G11-ASSIGN-G-installed-02/verification.json)로 다시 실행했다. 정상·판정 불가·거부 응답 전체와 종료 코드가 일치했고 파일 내용과 수정 시각을 보존했다. `run` 추가 의존성만 설치했으며 pyproj는 없었다. GUI의 계산 전 추정 레이어와 결측 원인 추론은 이 결과에 포함되지 않는다.
