# Delft3D FM CLI 전체 구현 계획

현재 개발판에서는 [기존 3D 염분 경계 한 셀의 편집 → 20초 계산 → 결과 비교](research/notes/verification/layers.md#b13)까지 사용할 수 있다. [B12 경계 입력 미리보기](research/notes/verification/boundary-preview.md)도 공개했다. `boundary preview`는 지원점에 연결된 신호를 찾아 원래 행·보간·한 블록의 조화 성분 합을 구분한다. [설치 FM의 처방 수위 배열 대조](research/notes/verification/boundary-preview.md#native-209)에서는 변화하는 두 신호가 1–120초의 지정 시각에서 일치했지만 초기화 직후에는 달랐다. [후속 8개 조건 #221](research/notes/verification/boundary-preview.md#native-221)에서 실제 시계의 입력값은 배열 704개 중 464개, 초기 간격보다 이른 시각을 초기 간격에 맞춰 계산한 값은 704개 모두 일치했다. 공개 미리보기는 원래 요청 시각의 입력값을 반환한다. GUI 그래프와 공간적으로 다른 지원점의 보간도 미검증이다. 구현·독립 검증의 담당과 승인 여부는 [공정표](DELIVERY.md)에 둔다.

**M1–M5 통합 검수를 통과했다.** [네이티브 재현과 직접 대조 결과](research/notes/verification/roadmap-2d.md). [f34 콘솔 프로젝트 왕복](research/notes/verification/project-bridge.md)에도 별도 실측 기록이 있다. [재시작 첫 원본 대조](research/notes/verification/restart-trial.md)에서 최종 상태는 통과했지만 일부 history·map 진단값은 달랐다. 후속 `restart forecast`는 두 직렬 사례의 저장 예측값과 32개 변형 대조만 별도 승인했다. [로컬 MPI 두 rank](research/notes/verification/parallel-trial.md)는 120초 직렬 대조·restart 재조립·취소 격리를 통과했다. 후속 E012-R에서 조립본을 읽어 240초에 도달했지만 연속 계산의 전체 시계열과는 차이가 있었다. [1D 고정 보·측방 유입](research/notes/verification/network-structures.md)은 별도 통합 검수를 통과했다. [GUI·콘솔 작업 대응표](research/notes/collection/gui-workflows.md)는 작업별 근거를, [공정표](DELIVERY.md)는 독립 검증과 최종 승인 상태를 기록한다.

이 문서는 구현 순서와 완료 기준을 정한다. [구현·독립 검증 공정표](DELIVERY.md)에서 각 노드의 선행 조건, 파일 소유자와 통합 상태를 추적한다. 현재 사용 가능한 명령은 [README](README.md)와 `dfm schema inspect`, 파일 형식과 소스 진입점은 [기능표](research/notes/collection/capability-map.md), 실험 명령과 증거는 [실험 색인](research/notes/experiments.md)에서 관리한다. 아래 M1 이후의 명령명은 각 단계가 검수를 통과하기 전에는 제안이다.

**작업 상태를 읽는 기준:** [82개 작업 대응표](research/notes/collection/gui-workflows.md)의 GUI 조작·콘솔 조작·파일 편집·엔진 실행·결과 대조는 각각 별도로 승인한다. 상세 표의 ‘작업별 승인 기준’에 필요한 증거를 정리했다. 다음 기능을 구현하기 전에 작업 ID와 변경·보존 파일을 정하고, 현재 공개 명령과 시험 중인 후보를 구분한다. M1 이후 기록이 이미 있는 작업은 그 기록을 보존하며, GUI 관찰의 공백을 CLI 구현 완료로 채우지 않는다.

## 출발점: CLI 0.3.1

| 상태 | 확인된 범위 |
| --- | --- |
| 제품에서 사용 가능 | 설치 탐색·검사, 지원 범위 조회, MDU와 일부 참조 검사, 기존 설정 세 개(종료 시각·history/map 출력 간격)의 미리보기·적용, 직렬 실행·상태 조회·취소. JSON 프로토콜 2, manifest 3. |
| 실제 엔진으로 검증 | Windows 2026.02 OpenHMWQ의 f34 복사본에서 직접 FM과 단일 FM 구성 DIMR이 600초에 도달했고, 네 데이터셋의 변수 191개가 일치했다. 실패·타임아웃·취소 시 별도 실행의 생존도 검증했다. [실행 기록](research/notes/verification/cli-03.md) |
| 0.3.1 당시 연구에서만 재현 | f34의 GUI 프로젝트 저장·콘솔 재열기·엔진 입력 내보내기([E001/E002](research/notes/replay/export-experiment.md)), 콘솔에서 같은 FlowFM 모델 API로 바꾼 경계 진폭과 BC 셀 대응([E005](research/notes/replay/edit-experiment.md)). GUI 클릭은 미검증이며, 후속 M1에서 공개 CLI 직접 편집을 별도 검증했다. |
| 0.3.1 당시 미검증 | 새 현장의 격자·수심·초기장 구성, 장기·3D·MPI·재시작·결합 계산, 일반적인 프로젝트 왕복 변환. [큰 입력 측정](research/notes/verification/cli-scale-031.md)은 CLI 처리 성능에 한정된다. |

## M0 · GUI/콘솔에서 하는 일과 CLI의 경계

**작업 목록 재점검:** [이번 대조 기록](research/catalog/gui-workflows-audit-20261105T104929-inventory.json)에서 82개 작업의 필수 열·고유 ID, 고정 소스 28개 파일의 110개 위치, 표에 적힌 CLI 명령 80종과 로컬 링크를 다시 확인했다. 추가 구현의 출발점은 아래 대응표의 작업 ID와 미검증 항목이다. 이번 점검에서는 GUI·콘솔·엔진을 새로 실행하지 않았다.

**M0는 작업 목록과 근거 연결을 정리하는 단계다.** GUI 전체의 동작 검증 완료를 뜻하지 않는다. [2026-11-05 목록 대조](research/catalog/gui-workflows-audit.json)에서 82개 고유 ID와 다섯 필수 열, 고정 소스 28개 파일의 110개 위치, CLI 열에 기재한 현재 명령 80종을 확인했다. 공개 명령 전체 수나 GUI 지원률로 환산하지 않는다. 기존 M1–M5의 구현·검수 기록은 그대로 유지한다.

이후 작업은 반드시 **작업 ID → GUI/콘솔 조작 → 입력·출력 파일 → 고정 소스 → CLI 계약 → 재현 실험** 순서로 연결한다. 입력 변화는 무변경 export와 비교하고, GUI·콘솔에서 직접 확인하지 못한 파일 쓰기는 후보로 남긴다. 조회, 보존 편집, 계산 완료, 수치 비교를 각각 판정하며 하나의 통과 결과를 다른 작업 ID에 적용하지 않는다. 실험에는 버전·입력 해시·재현 명령·원본 diff/로그·비대상 파일 보존 결과를 남긴다.

[전체 대응표](research/notes/collection/gui-workflows.md)의 82개 작업을 아래 다섯 묶음으로 관리한다. 상세 행에는 **읽는 파일 → 바뀌는 파일, 고정 소스의 함수·행, 대응 CLI, GUI·콘솔·엔진 각각의 근거**가 있다. [f34 실측표](research/notes/collection/gui-workflows.md#f34-file-diffs)에서 프로젝트 저장, 모델 내보내기, 콘솔 설정·경계 편집이 실제로 바꾼 파일을 대조할 수 있다. 화면에서 항목을 본 것, 콘솔이 파일을 쓴 것, 엔진이 그 파일로 계산한 것은 서로 다른 검증이다.

| 상세 행 | 대표 파일과 엔진 경로 | CLI로 확인한 범위 | 다음에 확인할 차이 |
| --- | --- | --- | --- |
| [P01–P12 프로젝트·자동화](research/notes/collection/gui-workflows.md#projects) | 저장은 Shell의 `.dsproj` + 동반 폴더에서 끝난다. 엔진 export의 시작점은 별도 MDU → `readMDUFile`이다. | f34 `project import/export`로 저장·재열기·내보내기. FM 모델 exporter는 DIMR XML을 만들지 않았다. | 같은 프로젝트의 FM 입력(P04)과 DIMR 구성(P08)을 비교. 결과 포함 저장(P09), 영역 연결·해제(P10), 시나리오별 계산 후 저장(P11)은 별도 검증. 병렬 입력 exporter(P12)는 MPI 실행(R08) 전에 독립 비교 |
| [G01–G18 공간 자료](research/notes/collection/gui-workflows.md#geometry) | `NetFile`은 계산망, `ObsFile`은 관측점, `CrsFile`은 유량 관측 단면. [G05 도형별 표](research/notes/collection/gui-workflows.md#area-files)에서 표시용 육지선, 차수벽, 월류제, 건조점·영역을 구별한다. | `mesh build/inspect`·`model create`로 합성 망·바닥고를 검증했다. [관측점 XYN 왕복과 단면 방향 반전](research/notes/verification/spatial-transfer.md)은 수동 입력과 설치 CLI의 결과가 일치했다. | GUI의 G09 단면 CSV 가져오기, G10 이름 충돌, G11 추정 위치, G12 단면 방향을 확인한다. G13–G18은 GUI 대조가 남았다. 특히 구조물 파일 교환·보 마루 CSV·RGFGRID 왕복은 인접 CLI 명령으로 대체 검증할 수 없다. |
| [S01–S07, B01–B14 설정·경계·외력](research/notes/collection/gui-workflows.md#inputs) | MDU → 새 EXT → 위치 PLI + 신호 BC → FM 경계 초기화·EC의 함수 판독 | f34의 `boundary set`은 750분 성분의 진폭 한 숫자만 바꿈. [B09의 BC·CSV 신호 가져오기](research/notes/verification/boundary-import.md)는 수동 대조군과 120초 출력까지 비교했다. | [E014](research/notes/verification/fields.md)의 GUI 속성·단위와 파일 키 대조. GUI에서 B09 가져오기와 B10 지원점 비활성화·함수 전환을 각각 수행해 사라지는 신호를 기록한다. [B10의 CLI·엔진 시험](research/notes/verification/boundary-support.md)은 완료. B11 `boundary coefficients`는 [선형 수위 시계열의 설치 CLI·엔진 대조](research/experiments/B11-PUBLIC-G-native-169-01/verification.json)를 통과했다. GUI 속성표가 같은 헤더를 쓰는지는 미측정. B12는 입력 신호 미리보기, B13은 3D 경계의 높이별 값 편집이다. 각각 계산 후 수위(V01), 계산층 두께 설정(S06)과 구별한다. |
| [O01–O04, R01–R11, V01–V06 실행·출력·분석](research/notes/collection/gui-workflows.md#runs) | 출력 간격은 MDU, 실제 결과는 history/map/restart NC. O03 형상은 별도 shapefile, O04 수지는 history 변수다. DIMR은 XML로 FM을 초기화한다. | f34 직렬 direct/DIMR 600초·191변수 대조, 관측점·map 추출, 소유 실행 취소. 확장 직렬은 별도 수로 1,200초. E012는 로컬 두 rank의 조립·직렬 대조·취소를 확인했다. | **E007:** GUI Run 전후 파일·helper 인자·로그, GUI 시계·Stop 확인. 전체 모델 중지(R10), 검증 보고서(R11), 결과 지우기(V05), Shell 실행 보고서·세션 로그(V06), O03/O04의 GUI 옵션별 출력은 별도 대조가 필요하다 |
| [X01–X10 통합·선택 모듈과 외부 도구](research/notes/collection/gui-workflows.md#extensions) | DIMR component/coupler XML, 과정별 MDU·EXT·모듈 파일. OpenMI/OpenDA는 별도 호스트. | `coupling inspect`로 [공식 XML 네 개](research/notes/replay/coupling-cases.md)의 component/coupler를 판독했다. [07 단독 Waves](research/notes/verification/waves.md)에서 경계 파고를 1.5→0.75 m로 바꾼 두 실행의 3,600초 map·history를 확인했다. [08 결합 대조군](research/notes/verification/waves.md)에서 FM→Waves 및 Waves→FM 응답을 원본 map으로 확인했다. [03 내부 질산화](research/notes/verification/water-quality.md)에서는 같은 수리 조건에서 NH4 감소와 NO3 증가를 확인했다. 08에서 취소·타임아웃·실패 대상과 동일 바이너리 대조군의 격리도 확인했다. 별도 [06 오프라인 DELWAQ](research/notes/verification/water-quality.md)는 13개 시각의 농도·부피 적분을 대조했다. 공식 10의 RTC 실시간 수위·보 마루 교환과 수리 반응은 두 제어곡선에서 확인했다. f152의 두 방향 교환도 강우·무강우·수리조건 변경 3개 입력, 34개 연결점, 600초 범위에서 확인했다. GUI 결합 설정 export와 RTC 제어 상태 복원은 미확인이다. | E015: 조합별 단독 실행부터 교환량·단위·시계 대조. 기포막처럼 매뉴얼이 수동 편집을 명시한 기능은 GUI 대응률에서 제외 |

**M1의 기준은 B01 조회 → B02 한 셀 편집 → R02 실제 계산이다.** 기준 입력은 공식 예제를 처음 가져오기 전 파일이 아니라, [E001/E002에서 콘솔로 내보낸 f34](research/notes/replay/export-experiment.md)다. 가져오기 전 원본과 첫 GUI export를 비교하면 비MDU 9개는 같지만 MDU에는 키 12개가 추가되고 1개가 빠진다. 이 변환까지 M1 편집 차이로 세지 않는다. 같은 export를 두 벌 복사해 E005에서 식별한 `L1_0001`의 750분 진폭만 1.5 → 1.75 m로 바꾸고, BC의 그 숫자 외 모든 입력 바이트를 대조한다. [공개 CLI 검수](research/notes/verification/roadmap-2d.md)에서 이 보존 조건과 두 계산의 최종 600초를 확인했다. GUI 경계 편집기에서 같은 조작을 클릭한 기록은 없다.

**결과 조회·내보내기의 인수 기준(M2 및 병렬 확장).** [작업별 파일 대응표](research/notes/collection/gui-workflows.md#results-file-actions)에서 V01은 Shell 차트의 CSV, V02는 QUICKPLOT의 분할 지도 표시, R08은 실제 병합 NetCDF로 나눈다. V01은 같은 관측점·시각의 GUI CSV와 원본 history를 비교해 단위·결측 표기까지 기록한다. V02는 같은 두 rank의 지도를 하나씩, 그리고 함께 열어 같은 좌표의 수위와 열람 전후 파일 변화를 확인한다. R08의 48셀 병합본은 이때 쓸 대조 자료다. 병합이 성공해도 GUI가 어느 파일을 열거나 썼는지는 이 두 관찰 전까지 미검증으로 둔다.

GUI 쪽에서 다음으로 메울 세 가지 공백은 아래와 같다. 각 실험은 격리된 Windows 환경에서 같은 기준 프로젝트의 새 복사본과 무변경 대조군을 사용한다. 하나의 결과로 다른 행까지 승인하지 않는다.

| 우선 확인할 작업 | 같은 입력에서 비교할 것 | 해당 행을 ‘관찰’로 바꿀 근거 |
| --- | --- | --- |
| P08 · FM 모델 export와 DIMR 구성 export | 동일 프로젝트를 빈 폴더 두 곳으로 각각 내보냄 | MDU·동반 입력과 XML의 실제 생성 목록, XML의 구성요소별 작업 폴더·입력 경로와 파일 존재 여부. CLI가 생성한 XML은 비교 자료로만 사용 |
| R01/R04/R05 · GUI Run, 진행 시각, Stop (E007) | 자연 종료와 중간 중지를 별도 케이스에서 추적. 직접 FM·DIMR 기준 기록과 대조 | GUI가 시작한 프로세스·인자·작업 폴더, 실행 전후 파일, GUI/엔진 시각, 중지 뒤 해당 프로세스와 부분 결과의 상태 |
| S01/S03/S04 · GUI 속성과 MDU 키 (E014) | 초기 수위, Manning 조도, 최대 시간 간격을 각각 하나씩 변경한 뒤 무변경 export와 대조 | 내보낸 MDU 키·값·단위, 함께 바뀐 파일·서식, 재열기 후 값. [CLI 직접 편집 검수](research/notes/verification/fields.md)는 별도 근거 |

[경계 편집기와 프로젝트 트리의 작업별 표](research/notes/collection/gui-workflows.md#boundary-scopes)에서 M1의 한 셀 편집, 시간 행 추가, PLI 교체, BC 신호 병합과 분할 내보내기를 구분한다. 같은 이름의 PLI를 가져와 신호가 사라지는 경우는 입력 손실이므로, B04를 맡을 때는 BC 편집 시험(B02)과 별개의 수용 기준을 적용한다.

시간대가 있는 자료를 다룰 때는 모델 시계(S01)와 경계 편집기에 읽기 전용으로 표시되는 자료 시계(B03/B12)를 따로 검증한다. 동일한 물리 시각을 UTC와 오프셋이 있는 두 BC로 표현한 뒤, 원점·표시 시각·내보낸 값·실제 경계값을 대조하기 전까지 일반 시간대 변환은 지원 범위에 넣지 않는다.

B03 후속에서는 `boundary series-set`으로 기존 선형 수위 시계열의 여러 값을 변경하고, [두 수로의 6개 실행](research/notes/verification/boundary-series.md)에서 변경 효과와 무효과 대조군을 확인했다. B09 후속은 [BC·CSV에서 선택 경계의 신호 가져오기](research/notes/verification/boundary-import.md)를 승인했다. 세 모드에서 같은 BC를 공유하는 다른 선은 보존했고, CLI로 가져온 여섯 모델이 각각 손으로 쓴 같은 모드 모델과 120초 출력까지 일치했다. B04의 위치 PLI 교체, B10의 함수 전환과 실제 GUI 가져오기 대화상자는 별도다.

E014 조회는 [현재 MDU의 편집 가능 판정](research/notes/verification/fields.md)까지 검수했다. 원본 f34의 Chezy, Manning으로 바꾼 f34, 편집 가능한 48셀 수로에 같은 0.041을 요청해 차단과 미리보기 허용을 구별했다. GUI 속성의 소유관계·재내보내기는 이 결과에 포함되지 않는다.

B03의 [행 삽입·삭제](research/notes/verification/boundary-series.md)는 `boundary series-rows`로 한 지원점의 시간표를 바꾼다. 설치본을 사용한 삽입·삭제·교체·원복 네 경우 모두 수동 입력과 120초 결과를 대조했다. 별도 수로에서도 직선 보간을 유지한 경우와 처방값을 바꾼 경우를 구별했다. GUI가 시간 범위와 간격에서 표 전체를 자동 생성하는 동작은 별도다.

G06은 [`observation inspect/add/move`](research/notes/verification/observation-points.md)로 기존 XYN을 조회·편집한다. 설치 패키지에서 기준·이동·추가·셀 중심 밖 이동 네 경우를 각각 120초까지 계산했다. 저장 좌표와 실제 map 셀의 수위 13개를 구별해서 검증했다. [G12 단면 반전](research/notes/verification/section-orientation.md)은 수동 파일 변경 후 600초 계산으로 유량 부호를 검증했고, [공개 단면 반전·원복 및 관측점 파일 왕복](research/notes/verification/spatial-transfer.md)도 설치 패키지로 검증했다. G10의 3개 모델은 각각 입력 9개와 120초 출력 159변수, G12의 2개 모델은 각각 입력 10개와 600초 출력 191변수가 대응하는 수동 대조군과 일치했다. GUI의 이름 충돌 처리와 추정 레이어(G11)는 별도다. `run start`의 [FM 식별자 검사](research/notes/verification/fm-model-identity.md)는 새 형식과 구형 MDU의 판독 섹션을 구분하며, 이 변경 후에도 f34 direct/DIMR의 191개 출력 변수가 일치했다.

G11은 [실제 건조 다각형과 관측점 대조](research/notes/verification/spatial-transfer.md)에서 입력 망 48셀 중 한 셀이 계산망에서 제외되면 해당 점의 이름만 남고 수위 13개가 모두 결측임을 확인했다. 화면의 추정 레이어는 여전히 미확인이다. 개발판 `results stations RUN`은 실행 뒤 기록된 history·map·형상을 읽어 관측값의 결측과 실제 셀 배치를 구분한다([29개 사례의 설치본 재현](research/experiments/G11-ASSIGN-G-installed-02/verification.json)). GUI 추정 레이어를 확인하려면 같은 점의 화면 위치와 실제 계산 위치를 대조해야 한다.

O02 후속에서는 [restart 간격 편집과 출력 일정 검증](research/notes/verification/checkpoint-schedule.md)을 승인했다. 기본 실행은 최종 restart를 요구한다. 짧은 직렬 모델에서 `--restart-policy configured`를 지정하면 해당 MDU가 요청한 시각 집합을 검사하며, restart가 비활성인 경우도 구별한다.

O03/O04는 [기존 관측점 형상·수지 출력 토글](research/notes/verification/output-toggles.md)을 `model set`으로 각각 편집한다. 설치한 CLI의 600초 계산 세 번에서 수동 입력과 같은 파일·변수·관측점 좌표를 확인했다. 다른 형상 종류와 GUI 체크박스가 함께 바꾸는 키 집합은 아직 미확인이다.

B04의 [경계 신호 분할 내보내기](research/notes/verification/boundary-export.md)는 개발판에서 네 방식을 구현했다. 내보낸 파일을 3층 수로에 다시 연결한 네 계산이 각각 기준군의 190개 출력 변수와 일치했다. 게시 경합 수정 후 독립 검증과 통합 재현에서 다른 작성자의 파일이 남는 것도 확인해 이 범위를 승인했다. GUI의 과정 분류와 PLI 가져오기는 이 실험 범위 밖이다.

B04의 [PLI 가져오기와 명시적 수평 좌표 변환](research/notes/verification/boundary-locations.md)을 승인했다. 남길 두 지원점의 진폭을 다르게 주었을 때, BC 뒤에 삭제한 블록을 주석으로 남기던 버전은 수위를 0.182 m 바꿨다. 활성 BC에서 블록을 제거하고 원본을 보관한 뒤 같은 대조군과 변수 159개가 일치했다. 수로 망의 CRS와 변환한 좌표를 별도로 확인했다. B10의 [지원점 켜기·끄기와 선 단위 함수 전환](research/notes/verification/boundary-support.md)도 수동 입력 네 개와 공개 편집본 네 개를 120초 계산해 승인했다. 두 노드 모두 실제 GUI 대화상자 왕복은 미검증이다.

**다음 GUI 조사와 완료 기준** (공개 CLI의 엔진 시험과 별도로 판정):

| 순서 · 작업 | 한 복사본에서 할 조작 | 해당 작업을 확인했다고 기록할 조건 |
| --- | --- | --- |
| 1 · R01/R04, E007 | 사용자 설정과 로그까지 격리된 새 GUI 호스트에서 f34를 한 번 Run | 전후 파일 목록·해시, 생성된 XML, 실제 helper/인자 또는 프로세스 내부 호출 근거, GUI 표시 시각과 같은 시점의 엔진 시각을 확보. [사전 검사](research/assets/gui-activity-trace/README.md)만으로는 미완료 |
| 2 · R05, E007 | 별도 f34 복사본을 시작해 GUI Stop 한 번 | 대상 실행의 종료 방식, 남은 프로세스·부분 출력과 종료 시각을 정상 완료 대조군과 비교. CLI 강제 취소 결과로 GUI Stop을 대신 판정하지 않음 |
| 3 · S01/S03/S04, E014 | 초기 수위·Manning·최대 시간간격을 각각 새 복사본에서 한 개씩 변경한 뒤 export. f34 원본은 Chezy(65)이므로 Manning은 마찰식이 이미 Manning인 별도 대조 모델을 사용 | 각 경우 같은 마찰식의 무변경 export와 대조해 GUI 속성명·단위, 실제 MDU 키·값, 비대상 파일 변경을 기록. [CLI와 엔진 대조](research/notes/verification/fields.md)는 이미 별도 근거가 있음 |
| 4 · P04/P08 내보내기 비교 | 같은 f34 프로젝트 복사본에서 FM 모델과 DIMR 구성을 각각 빈 폴더로 내보냄 | FM 세트의 10파일을 대조군으로 삼아 XML·추가 파일과 폴더 배치를 기록. 매뉴얼 예의 `dimr_config.xml` + `dflowfm/` 배치를 가정하지 말고, 생성된 XML의 작업 폴더·입력 경로를 풀어 실제 파일과 대조 |
| 5 · R11 검증 보고서 | 정상 복사본과 참조 BC 하나가 빠진 복사본에서 각각 Validate | 두 GUI 보고서의 오류 위치·심각도, 생성·변경 파일을 `dfm model validate` 결과와 대조. 엔진을 초기화했는지는 따로 기록 |
| 6 · B09/B10, 경계 신호 보존 | 기존 신호·빈 지원점·가져올 파일에 없는 점을 준비하고, 각 가져오기 모드·비활성화·함수 전환을 별도 복사본에서 한 번씩 수행 | 각 점의 원래 이름·좌표와 모든 BC 블록·열을 대조한다. 삭제·빈 블록·불변을 구분하며, 한 셀 보존 검수(B02)로 대체하지 않는다 |
| 6b · B11, 경계선의 배율·오프셋 | 선 두 개·지원점 여러 개가 있는 선형 수위 시계열을 사용한다. 무변경 export, 한 선의 배율만 변경, 오프셋만 변경을 각각 새 복사본에 만든다 | EXT·BC 전체 diff로 어느 파일이 계수를 보관하는지 확인한다. 선택한 선과 다른 선의 신호·단위·시간축을 대조하고, 같은 유효 신호를 손으로 작성한 모델과 설치 엔진 결과를 비교한다. 조화 성분에는 별도 대조군이 필요하다 |
| 6a · B04, 경계선 및 신호 파일 가져오기·내보내기 | 같은 이름의 PLI 교체와 다른 이름의 선 추가를 별도 복사본에서 실행. BC 내보내기는 한 파일·경계별·과정별·물리량별을 따로 선택 | 원래 선의 좌표·이름·모든 신호와 다른 선의 불변 여부를 비교. 분할한 각 BC의 블록·열을 합쳐 원래 신호와 대조하고 EXT가 바뀌었는지 확인. 매뉴얼 설명만으로 파일 삭제나 자동 참조 갱신을 확정하지 않음 |
| 7 · P09, 계산 후 프로젝트 보관 | E007 정상 완료 복사본에서 저장한 뒤 별도 경로에 복사해 다시 연다 | 저장 직전·직후·재열기 직후의 DB/동반 폴더, restart ZIP 내부 목록·해시, GUI가 다시 여는 history/map 경로·최종 시각을 확인한다 |
| 8 · P10, 공유 영역 연결·해제 | 두 모델이 같은 영역을 쓸 수 있는지 먼저 확인한다. 가능하면 복사본에서 한 모델의 연결만 해제하고 저장·재열기·각 모델 export | 프로젝트의 연결 상태, 두 모델의 망·MDU 참조와 원자료 해시를 비교한다. 해당 모델에 메뉴가 없으면 그 사실을 기록한다 |
| 9 · P11, 스크립트 시나리오 계산·저장 | P09 확인 후, 경계값 두 개로 각각 계산해 별도 프로젝트로 저장한다 | 각 프로젝트를 다시 열어 자기 경계값·결과·최종 시각이 맞는지, 두 번째 계산이 첫 프로젝트나 기준 데이터를 바꾸지 않았는지 확인한다 |
| 10 · G09, 하천 단면 CSV | 지원되는 1D 모델 복사본에서 위치와 단위가 알려진 단면 하나를 가져온다 | 무변경 export와 비교해 단면 정의·위치 파일의 ID, 가지, 거리, 높이를 확인한다. 가져오지 않은 단면과 원본 CSV는 그대로여야 한다 |
| 11 · O03, 격자에 맞춰진 형상 | 관측점·단면이 있는 f34 복사본에서 Write Snapped Features만 켜고 내보내 계산한다 | GUI가 바꾼 MDU 키, 엔진이 실제 쓴 파일·좌표·대상 ID를 꺼진 대조군과 비교한다. 바이너리가 출력을 지원하지 않으면 진단과 미생성을 기록한다 |
| 12 · O04, 질량수지 history | 수지 출력이 켜진 f34를 기준으로 해당 체크만 끄고 내보내 같은 시각까지 계산한다 | MDU의 변경 키와 두 history의 변수 목록·단위·시간 축을 비교한다. 비대상 관측점 수위가 유지되는지도 확인한다 |
| 13 · G10, 관측점 파일 왕복 | f34에서 관측점만 빈 폴더로 내보낸다. 가져오기는 이름 충돌이 없는 파일과 중복 이름이 있는 파일을 다른 복사본에 적용한다 | 생성 목록, XYN 이름·좌표·순서, MDU·기존 입력의 해시를 비교한다. 가져온 뒤 모델을 다시 내보내 기존 점의 유지·대체·중복 또는 거부를 기록한다 |
| 14 · G11, 계산 전 배치 미리보기 | 건조 영역 안팎에 식별 가능한 점을 둔 복사본에서 추정 레이어만 켠다. 같은 입력의 별도 계산에서는 관측점 형상 출력을 켠다 | 화면에 표시한 점과 실제 shapefile의 위치를 ID별로 대조한다. 화면 전환 전후에 파일이 생기거나 바뀌었는지도 기록한다 |
| 15 · G12, 유량 관측 단면 방향 | 유량이 0이 아닌 기준 사례에서 단면 하나만 역순으로 그려 내보내고 두 입력을 같은 시각까지 계산한다 | 내보낸 선의 ID·꼭짓점 역순과 다른 선의 보존을 확인한다. 같은 시각의 단면 유량(m³/s)은 크기와 반대 부호를, 비대상 단면·관측점은 불변을 검사한다 |
| 16 · P12, GUI 병렬 입력 export | E012 수로의 복사본에서 두 구역을 선택해 빈 폴더로 내보낸다. R08의 실제 MPI 실행은 분리한다 | rank별 MDU의 망 경로·분할 수·전역 셀 소속, 공통 입력·XML의 생성 여부와 원본 해시를 기록한다. `parallel partition`과 분할 설정이 다르면 먼저 그 차이를 기록한다 |
| 17 · V06, Shell 실행 보고서 | E007의 완료·실패 복사본에서 보고서와 세션 로그를 각각 연다. 메시지 지우기는 또 다른 복사본에서 시도한다 | GUI 메시지 하나를 Shell 보고서·세션 로그·FM 진단에서 각각 찾아 출처와 시각을 비교한다. 목록에서만 사라졌는지 저장한 DB·로그도 바뀌었는지 확인한다 |
| 18 · G13, 펌프 방향 반전 | [3회 엔진 계산](research/notes/verification/pump-orientation.md)에서 선의 정점 순서를 뒤집어도 고정 단면의 동쪽 유량 4 m³/s는 변하지 않았다. GUI에서는 유량이 있는 펌프 모델 복사본에서 펌프 하나에만 Reverse line(s)를 적용하고 내보낸다 | 무변경 export와 비교해 방향을 보관한 파일·값을 찾는다. 같은 시각의 링크 유량과 양쪽 수위를 고정 좌표 기준으로 비교한다. `pump inspect`는 입력의 구조물 ID·용량·방향·위치선만 조회한다. [#177](research/notes/verification/pump-orientation.md)에서 고정된 선의 orientation 또는 용량 부호만 바꾸면 실제 방향이 뒤집혔지만 총유량 크기는 4 m³/s였다. [#183 단일 링크](research/catalog/pump-single-link-gates.json)는 같은 용량에서 총유량 1 m³/s, 120초 이동량 120 m³를 확인했다. 선만 반전하면 지리 방향은 유지됐다. GUI 매핑은 미검증. [공개 편집·실행 검수 #187](research/notes/verification/pump-orientation.md#public-pump): `pump set`으로 방향 또는 용량을 한 값씩 편집하고 `run start --profile pump-scalar --route direct`로 입력 6개를 모두 전달했다. 다섯 사례에서 각각 수동 대조군의 173개 변수와 일치했다. 다음 G13 실험은 GUI가 Reverse line(s)에서 실제로 바꾸는 파일·속성 확인이다. |
| 19 · G14, 프로젝트 점군 등록 | 같은 XYZ를 두 복사본에서 각각 프로젝트 독립 자료와 바닥고 입력(G02/G04)으로 가져온다. 무변경군도 함께 저장·재열기·export한다 | 각 경우 프로젝트 DB·동반 폴더에 무엇이 생겼는지, 독립 자료 등록만으로 FM 망이나 MDU가 바뀌었는지 비교한다. 원본 XYZ와 좌표계는 보존한다. |
| 20 · G15, 구조물 파일 교환 | 같은 보를 형상 PLI와 구조물 파일로 각각 내보내고, 각각 빈 복사본에 다시 가져온다. 수문·펌프·교각과 Shapefile은 별도 사례로 둔다 | 생성 파일 전체와 참조, 재내보낸 ID·좌표 순서·마루 높이·폭·시계열을 대조. 형상만 보존된 경우와 수리 속성까지 보존된 경우를 구별. [공개 `structure inspect`·`export`·`import`의 W2D 보·P2D 펌프 파일 교환](research/notes/verification/structure-transfer.md)은 독립 설치 검증 통과, 엔진·GUI 대조는 미측정 |
| 21 · G16, 가동보 마루 CSV | 상수 높이가 다른 대조군 두 개와, 같은 상수 또는 60–66초에 높이가 바뀌는 TIM 입력을 준비했다. GUI에서는 같은 보의 CSV를 내보내고 새 복사본에서 가져온 뒤 FM 입력을 내보낸다 | [엔진 5회 대조](research/notes/verification/weir-crest-series.md)에서 60–66초 마루 변경은 유량과 하류 수위를 바꿨다. TIM을 준 모델의 0초 마루가 0 m이고 낮은 상수 대조군과 초기 restart도 달라 전체 등가성은 미통과. [공개 CLI 파일 편집](research/notes/verification/weir-crest-series.md#public-editor)은 원래 TIM의 66·120초 값 두 개만 바꿨고 원복도 확인했다. [#211](research/notes/verification/weir-crest-series.md#native-211)에서 원본/무변경 및 마루 상승 수동/CLI 두 쌍은 각각 189개 변수가 같았다. 하류 수위 평균 감소 예측은 실패했다. [공개 실행 프로필 #217](research/notes/verification/weir-crest-series.md#public-run)은 네 개 120초 사례에서 각각 #211과 같은 값을 냈고, 공용 코드를 쓰는 기존 펌프 다섯 사례도 회귀 검사를 통과했다. 다음 GUI 시험은 CSV의 기준 시각·단위, 구조물 참조와 비대상 파일을 비교한다 |
| 22 · G17, 외부 격자 편집기 왕복 | 육지선이 있는 프로젝트를 복사해 RGFGRID를 열고, 무편집 복사본과 한 절점만 옮긴 복사본에서 각각 저장·닫기·FM export | 전달 파일과 반환 파일의 경로·해시를 분리해 기록. 반환망의 좌표·연결·CRS와 MDU 참조, FM 재열기 후 수정 유지 여부를 직접 확인 |
| 23 · [B12, 계산 전 경계 입력 신호 보기](research/notes/collection/gui-workflows.md#boundary-preview) | 한 지원점에 구별되는 두 신호를 둔 복사본에서 단일 물리량의 활성·전체 신호를 읽는다. 여러 물리량의 결합 보기는 따로 기록한다 | 같은 점·단위·시각에서 표시값과 입력 자료를 대조하고 보기 전후 프로젝트·엔진 입력의 해시를 비교한다. 결과 history(V01)는 이 작업의 대조 자료로 쓰지 않는다 [초기화 조건 8개 비교](research/notes/verification/boundary-preview.md#native-213)는 첫 조건만 측정했다. 10초 출력 간격이 4초 모델 시각과 맞지 않아 멈춘 기록을 유지하고, 같은 12초 출력 간격의 여덟 조건에서 [초기 배열을 재측정했다](research/notes/verification/boundary-preview.md#native-221). 이는 GUI의 표시 시각 대조와 별개다. |
| 24 · [B13, 3D 경계의 높이별 염분](research/notes/collection/gui-workflows.md#vertical-boundary) | 3층 수로에서 계산층과 PLI를 고정한다. 무변경 export와 서쪽 지원점 한 곳에서 중간 높이의 마지막 염분 값만 바꾼 export를 비교한다 | GUI 표시 높이(%)와 실제 BC의 위치 목록·열 번호·ppt 값을 대조한다. 저장 후 다시 열어 같은 셀을 확인하고, 다른 점·시각·수위 신호와 MDU·EXT·망도 비교한다. [기존 20초 엔진 실험](research/notes/verification/layers.md)은 별도의 대조 자료다 |
| 25 · [B06, 단일 방류점과 연결 취·방류](research/notes/collection/gui-workflows.md#source-sink) | 두 모델을 각각 새로 내보낸다. 각 모델에서 무변경 export와 염분 한 값만 바꾼 export를 비교한다. | 위치가 EXT 좌표인지 PLI인지, BC에 연결된 ID·단위와 EXT 키가 `salinity`인지 `salinityDelta`인지 기록한다. [#215 엔진 실측](research/notes/verification/source-sink.md)에서는 같은 유량의 단일점에서 두 키의 효과가 달랐고 여섯 PLI 입력은 초기화하지 못했다. [#223](research/notes/verification/source-sink.md#native-223)에서 머리 주석만 제거한 PLI와 EXT 좌표 표현을 대조했고, 열 사례가 120초에 도달했다. `salinityDelta`의 5→15 차이는 확인했지만 `salinity`는 증분 0 대조와 같았다. [#225](research/notes/verification/source-sink.md#public-225)에서 공개 `source inspect/add/set/forcing-create`로 만든 여섯 입력은 수동 기준의 각 170변수와 일치했다. 다음은 이 입력을 공개 `run start`로 실행하는 프로필과 GUI exporter 대조다. GUI exporter의 키는 별도 확인한다. 같은 유량에서 방류 농도 또는 옮긴 물에 더한 농도가 실제 계산에 반영돼야 해당 경우의 CLI 작성 기능을 승인한다. |
| 26 · [G18, 관측 단면 단독 교환](research/notes/collection/gui-workflows.md#section-transfer) | f34 복사본의 Observation cross-sections 노드에서 단면을 내보내고 다른 복사본에 가져온다. 새 이름과 같은 이름을 분리하고, 무변경군도 같은 방식으로 저장·재열기·FM export한다 | 단독 exporter의 실제 형식·생성 파일, ID·정점 순서·충돌 처리, MDU `CrsFile`과 나머지 입력의 전후 해시를 대조한다. 동일 형상을 보존한 경우 수동 대조군과 단면 유량의 부호·시계열까지 확인한다. 전체 모델 export나 G12 방향 반전으로 이 행을 승인하지 않는다. [공개 `section export`·`import`와 엔진 6회 대조](research/notes/verification/section-transfer.md)는 통과, GUI 단독 교환 대조는 미측정 |
| 27 · [B14, 조석 분조 일괄 지정](research/notes/collection/gui-workflows.md#tidal-constituents) | 같은 경계의 새 복사본에서 한 지원점과 모든 활성점에 A0·M2를 지정하고 각각 무변경 export와 비교한다 | BC의 점별 함수·성분 행·진폭·위상과 비대상 블록을 대조한다. harmonic 주파수와 astronomic 이름을 구별하고, 같은 시각의 처방값을 대조한다. B02에서 확인한 기존 진폭 편집과 별개다 |
| 28 · [S07, 풍속별 항력 계수](research/notes/collection/gui-workflows.md#wind-drag) | 같은 풍속·풍향 파일을 쓰는 두 복사본에서 두 기준점 중 한 항력 계수만 바꾸고 저장·재열기·export한다 | MDU의 항력식·기준 풍속·계수와 EXT·WND 해시를 대조한다. 두 기준 풍속 사이의 0이 아닌 바람에서 실제 응력 변화를 확인한 뒤 편집 범위를 정한다. [공개 `wind drag-set`과 엔진 7회 대조](research/notes/verification/wind-drag.md)는 통과, GUI 표 편집 대조는 미측정 |

R10과 V05는 단일 모델 시험 이후로 둔다. 여러 모델이 있는 폐기 가능한 프로젝트에서 전체 중지의 대상 범위와 출력 정리 전후 파일 차이를 각각 확인한 뒤 CLI 적용 여부를 결정한다.

**B13 구현 및 엔진 검수 완료(범위: 기존 T3D 염분 한 셀).** [3층 수로와 실제 관측값](research/notes/verification/layers.md#b13)에서 `boundary vertical-inspect/vertical-set`으로 한 점·한 높이·한 시각을 선택했다. 수동 대조군과 공개 CLI 입력 9개가 같았고 20초까지의 history/map 및 두 restart에서 변수 190개가 일치했다. [휴대 가능한 대조군 준비](research/notes/verification/layers.md#portable-b13)도 검수해 과거 실험 폴더 없이 세 복사본을 재생성할 수 있다. GUI 표의 높이 표시, 저장 후 재열기·export 대조는 위 24번에 남긴다.

**G15 구조물 교환 구현 착수.** [최종 계약 검수](research/experiments/G15-PROPOSAL-G-final-01/verification.json)를 통과해 별도 구현·독립 검증 노드를 배정했다. 첫 단계는 현대 구조물 형식의 단순 보·상수 펌프에 대해 조회, 형상/수리 속성 묶음 내보내기, 기존 한 파일 가져오기를 구현한다. 형상 메타데이터는 사용자 지정 연결이며 실제 대상 ID는 INI에서 확인한다. 수문·단계 펌프·교각·Shapefile·1D·3D·다중 파일 쓰기를 포함한 16개 범위 행은 계속 추적한다. 이 승인은 파일 계약에 한정되며 공개 CLI·엔진·GUI 대응 완료는 아니다. [공정표](DELIVERY.md)의 G15-TRANSFER 노드에서 담당과 통합 조건을 관리한다.

## 기본 2D 작업: 구현 순서와 인수 기준

[M0 표](research/notes/collection/gui-workflows.md)는 메뉴 수 대신 주요 작업군을 기준으로 삼는다. 아래 ID는 각 단계가 가져갈 부분이다. 한 행 안에서도 조회·편집·실행의 지원 여부가 다르다.

| 단계 | 대응표 ID | 이번 단계의 경계 |
| --- | --- | --- |
| M1 | B01 조회, B02, R02 | **승인.** E005의 BC 셀을 CLI로 바꾸고 실제 계산으로 검증. 경계선 생성·스냅, 다른 함수(B03), 경계 객체 가져오기(B04), 신호 병합·삭제(B09/B10), 높이별 염분(B13), 여러 점의 분조 일괄 지정(B14)은 별도. |
| M2 | G06, V01–V03 | **승인.** 관측점 식별 → history 값 추출 → 두 시나리오 비교부터. |
| M3 | P01/P04의 **엔진 파일** 쪽, G06, S01/S03, B01/B03/B04 | **승인(EPSG:32631 합성 수로).** 주어진 격자로 입력 세트를 작성. Shell 프로젝트 DB 작성까지 약속하지 않는다. |
| M4 | G01–G05 | **승인(평면 합성 수로).** E006에서 좌표·높이 기준과 실제 산출물부터 대조. |
| M5 | S01–S05 중 지원할 조합, B05–B07, O01/O02, R02–R06 | **승인(1,200초 수로).** 진행률은 E010, 이번에 추가할 입력 조합은 각각 단독 실험. GUI Run 경로(R01/E007)와 분리. |

프로젝트 브리지와 시나리오 관리는 P01–P11, 병렬 입력 export는 P12, 재시작·MPI 실행은 R07/R08, 1D·3D·구조물은 G07/G08/S06/B13, 실시간 제어·모듈 확장은 R09/X01–X10에서 추적한다. V04의 화면 배치는 제품 범위 밖이다.

| 단계 | AI가 할 수 있어야 하는 일 | 완료 판정 |
| --- | --- | --- |
| **M1 · 기존 경계 편집** | MDU에서 EXT → PLI/BC를 따라 지원점과 주기·진폭·위상을 읽고, 지정한 조석 성분의 진폭 하나를 바꾼다. | 아래 첫 작업의 보존·오류·실행 검사를 모두 통과한다. |
| **M2 · 시나리오 결과 비교** | 두 실행의 history에서 관측점과 변수를 선택해 시계열과 차이를 JSON/CSV로 얻는다. 이후 map의 변수 위치와 시각별 공간 자료를 내보낸다. | M1 대조군·변경군을 같은 시각·관측점·단위로 비교한다. 직접 읽은 NetCDF 값·마스크와 일치하고, 단위나 좌표가 맞지 않으면 이유를 반환한다. 결과가 같아도 그대로 보고한다. |
| **M3 · 입력 세트 생성** | 빈 폴더에 **주어진 격자**와 명시한 좌표계·높이 기준·기간을 사용해 MDU, 경계선, 경계 신호, 초기조건, 관측점 파일을 만든다. | f34 복사 외에 작은 수로 한 사례를 새로 구성한다. 다른 폴더로 옮겨도 참조가 풀리고, 누락 단위·중복 ID·부족한 경계 시간 범위를 잡아내며, 짧은 계산과 M2 결과 추출까지 성공한다. |
| **M4 · 격자와 공간 입력 생성** | 경계 좌표로 2D 격자를 만들거나 가져오고, 수심·초기 수위·조도를 적용한다. 그다음 국소 세분화와 품질 검사를 추가한다. | E006으로 좌표계·높이 기준·수심 부호를 확인한다. 알려진 바닥고의 합성 수로에서 좌표·셀 연결·보간·결측 처리를 독립 검사하고 M3의 입력 격자를 대체해 실행한다. |
| **M5 · 실무 규모의 직렬 실행** | 검증된 조합별로 MDU 및 forcing 설정을 늘리고, 더 긴 2D 계산의 실제 모의시각·로그·진단을 조회한다. | E010에서 진행 시각의 출처를 검증하고, 600초를 넘는 별도 기준 모델로 출력 주기·최종 시각·취소 후 부분 출력을 확인한다. 시간 제한 해제만으로 지원 처리하지 않는다. |

**첫 작업의 명세(M1).** 입력은 내보낸 f34의 복사본이다. 검증한 명령은 `dfm boundary inspect`와 `dfm boundary set`이다. 첫 버전은 새 EXT에 연결된 harmonic 수위 BC의 기존 진폭만 편집한다.

1. 조회 결과에 경계 식별자, PLI 지원점 이름, BC 블록, 성분 주기, 물리량·단위, 원본 파일·행을 반환한다. f34의 13개 PLI 점 중 실제 신호가 있는 세 점을 구별한다.
2. [E005 대조값](research/notes/replay/edit-experiment.md)을 사용한다. `L1_0001`, 주기 750분에서 진폭 1.5m → 1.75m를 미리 보고, 입력 지문이 일치할 때만 적용한다. BC의 해당 숫자 이외의 바이트와 MDU·EXT·PLI·격자의 해시는 그대로여야 한다.
3. 같은 이름·주기가 여러 개이거나 파일 참조·단위가 달라졌거나 지원하지 않는 함수이면 쓰기 전에 거부한다. 기준군·변경군을 각각 실제 FM으로 실행해 최종 출력 시각을 확인한다. 성공 로그만으로 경계 신호의 물리적 타당성을 선언하지 않는다.

## 확장 단계와 선행 조건

2026-11-04 통합 검수에서 새로 승인한 범위는 [08의 양방향 파랑 교환과 중단 격리](research/notes/verification/waves.md), [03의 질산화 대조와 공개 결과 비교](research/notes/verification/water-quality.md), [BMI 관측값·시계와 오류/중단 처리](research/notes/verification/live-worker.md)다. [유사 수지](research/notes/verification/morph-trial.md)는 두 형상(48셀·300초, 72셀·360초)의 이동·고정·운반 비활성·정지 사례에서 단면 누적량, 셀 저장량, 최종 restart를 대조해 승인했다. [48셀 수로 한 보의 BMI 마루 높이 제어](research/notes/verification/live-worker.md)도 격자 링크 유량과 대조해 승인했다. [06 오프라인 DELWAQ 소비자](research/notes/verification/water-quality.md)에서는 3,600초 세균 사멸과 구간별 농도·부피 총량도 대조했다. [공식 10 기반 RTC](research/notes/replay/coupling-cases.md)는 두 제어곡선의 수신·출력·실제 마루와 수리 반응까지 확인했다. [f152 RR–FM](research/notes/replay/coupling-cases.md)은 세 입력에서 양방향 수위·유량을 확인했다. 다른 구조물, RTC 제어 상태 재시작, 다른 RR 구성 및 GUI Run 추적은 미승인이다.

| 작업 | 시작 조건 | 별도로 통과할 검증 |
| --- | --- | --- |
| GUI 프로젝트 브리지 | E001/E002 증거가 있어 기본 2D 작업과 독립적으로 착수 가능. 우선 설치된 Delta Shell을 이용한 `.dsproj` → 엔진 입력 내보내기. | 프로젝트 데이터 디렉터리와 외부 참조까지 검사한다. 콘솔 종료 코드 0이어도 완료 표식·산출물·참조가 없으면 실패다. f34의 역방향 가져오기와 저장 후 재열기는 [별도 사례로 확인했다](research/notes/verification/project-bridge.md). 일반 프로젝트 왕복은 미검증이다. E007 GUI 실행 추적은 GUI와 실행 경로가 다른 원인을 확인할 때 쓴다. |
| 재시작·병렬 실행 | M2 결과 비교와 M5 직렬 대조군 확보. E013 재시작과 E012 MPI는 독립 단계. | 같은 격자의 연속 계산과 재시작 계산을 비교한다. MPI는 분할 수·rank·출력 조립·전체 소유 프로세스 종료를 검사하고 미리 정한 변수별 허용오차로 직렬 결과와 비교한다. |
| 1D·1D/2D·3D 및 구조물 | M3/M4의 파일 참조·공간 검사가 마련된 뒤 모델 종류별로 추가. | 단면·구조물·횡유입의 ID 및 연결, 1D/2D 교환, 3D 수직층·초기장·출력 위치를 각각 독립된 작은 모델로 검증한다. [합성 1D 고정 보와 측방 유입](research/notes/verification/network-structures.md)은 승인했다. [3층 염분 수로의 수직장과 경계 응답](research/notes/verification/layers.md)도 승인했다. [분기 방향·접촉 형상과 수위차를 달리한 7개 모델](research/notes/verification/network-exchange.md)에서 분기 수지 및 1D/2D 교환도 확인했다. 다른 접촉 형식과 현장 수리 검보정은 미검증이다. |
| DIMR 다중 모듈·실시간 제어 | 각 구성요소의 단독 기준 실행 및 M2 결과 비교 확보. | E015에서 FM–Waves, 수질, RTC/RR 등 필요한 조합을 하나씩 선정해 교환 변수·단위·시계·종료를 확인한다. 유사·지형변화도 전용 사례를 둔다. 실행 중 한 단계씩 진행하거나 값을 교환해야 할 때만 BMI/DIMR 전용 worker를 도입하고, 오류·취소 후 자원 반환을 검증한다. |

## 지원 범위를 넓히는 규칙

- **GUI 대응 범위는 작업별로 기록한다.** 새 GUI 작업을 조사하면 M0 표의 해당 ID에 읽기/쓰기 파일, 고정 소스 지점, 호스트 근거와 공개 CLI 상태를 함께 갱신한다. 표에 실렸다는 사실이나 엔진 코드에 키가 있다는 사실은 GUI 전수 검증 또는 CLI 지원을 뜻하지 않는다.
- **AI가 스스로 호출할 수 있어야 완료다.** 각 단계는 공개 명령, 기계 판독 가능한 인자·단위·제약, 성공/실패 예시와 종료 코드를 함께 제공한다. 편집은 기본 미리보기, 적용 시 입력 지문 검사, 모호한 입력에는 무변경 실패가 원칙이다. E014의 후보 키는 버전별 의미와 보존 검사가 끝난 것부터 공개한다.
- **제품과 검증기를 분리한다.** Python CLI와 네이티브 엔진을 유지한다. HYDROLIB-core, MeshKernel, 결과 분석 라이브러리는 해당 단계에서 정확성·보존성·설치 비용을 확인한 뒤 선택한다. 외부 라이브러리가 쓴 파일을 같은 라이브러리로 다시 열 수 있다는 것만으로 통과시키지 않는다.
- **단계 종료 시 근거를 갱신한다.** 작은 휴대용 테스트와 별도 복사본의 실제 엔진 실험을 남긴다. 파일 구문, 참조, 엔진 초기화, 계산 완료, 과학적 검증을 구별한다. 실행 방식을 바꿀 때는 소유 프로세스 취소와 출력 최종 시각을, 큰 파일 경로를 바꿀 때는 처리 시간과 최대 메모리를 다시 확인한다. 통과한 범위만 README·명령 스키마·실험 색인·이 계획에 반영한다.
