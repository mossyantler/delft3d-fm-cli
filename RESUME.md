# 작업 재개 지점

2026-11-05 사용자가 Herdr에서 명시적으로 재개했고, Claude Code Sonnet 5.5 high를
추가 작업자로 허용했다. 중단됐던 공용 `short` 종료 처리 공정을 이어서 검수했다.
전체 제품 로드맵은 미완료다.

[중단 체크포인트](research/checkpoints/20261105-quota-pause/README.md)의 343파일과
실패 기록은 보존한다. 새 후보를 따로 만들어 검수했으며 체크포인트를 제품 디렉터리로
일괄 복사하지 않았다. 이후 과정은 [공정표](DELIVERY.md)에 단계별로 남긴다.

## 현재 승인 범위

[독립 실제 회귀 검수](research/proposals/short-close-native231-review/RELEASE_VERDICT.md)
`NATIVE231-RELEASE-V` (`3851697`)는 37항목을 통과했다. 실제 회귀 #231의 direct/DIMR
각 여섯 사례, 원래 멤버 24개의 종료, Job·수집기 12개와 관찰 핸들 12개·공개 클라이언트
16개의 닫기/종료, 네 대조군 생존 묶음을 확인했다. 두 정상 실행은 600초와 최종 restart를
확인했고 원본 NetCDF 네 데이터셋 쌍의 191변수(34+34+68+55)가 값·mask·단위·차원까지 일치했다.

[합류 승인과 임대 해제](research/proposals/short-close-native-gates/release231.json)
`NATIVE231-REPLAY-G` (`2af0673`)에 따라 슬롯은 `idle232`다. 이는 새 실행 허가가 아니다.
검증된 wheel `e32bf84f…`의 종료 모듈 두 개만 제품에 반영하며, 제품 191파일 전부를
그 wheel과 일치시킨다. 원래 98명령·프로토콜 2·manifest 3과 기본 물리 프로필은 유지한다.

제품 통합은 `SHORT-CLOSE-ROOT-G` (`df447d8`)다. [독립 통합 검수](research/proposals/short-close-root-review/REVIEW.md)
`0ceb728`의 27항목은 제품 동일성과 기존 단언 보존, 공개 오류 코드 조건 변형을 확인했다.
[전체 회귀 기록](research/proposals/short-close-native-gates/root-verification.json)은
1,715개 중 1,679통과·기존 환경 조건 36건 건너뜀과 이후 추가한 호환성 3건 통과를
기록한다. 새 지속 회귀는 종료 계약 18건과 오류 코드 3건이며 합성 검사다.
`compileall`과 실제 `schema inspect`도 통과했다.

## 보존한 거부와 수정

첫 실제 회귀 #229는 direct 여섯 사례 뒤 대조군 관찰 두 개가 같은 monotonic tick을
가져 거부됐다. `NOT_ACCEPTED` 원본 192파일을 그대로 두며 DIMR·191변수 비교를 했다고
해석하지 않는다. [독립 해제 검수](research/proposals/short-close-native229-review/RELEASE_VERDICT.md)
`152dfe4`로 원래 소유자의 종료를 확인한 뒤 해제했다.

Python 3.12의 실제 monotonic 시계 해상도 15.625ms를 고려해 같은 보유 관찰 핸들에서
다음 실제 tick을 얻는 제한된 재관찰을 추가했다. 정식 임대와 허가의 해시·경로·실행 폴더도
정확히 연결했다. 판독기 조건이나 원시 시각은 고치지 않았다. 후보 6 동결은 `53a1db83…`,
[독립 시계/허가 검수](research/proposals/short-close-native-clock-auth-review/VERIFICATION.json)
`ed1456b`는 54건, [오프라인 합류 검수](research/proposals/short-close-native-gates/composition-review231.json)
`43ec11f`는 정확한 소스·wheel·40입력·선택 엔진을 확인했다.

## 이어서 할 공정

공용 종료 처리는 이번 f34 2D UTC cold-start 600초, direct 및 단일 FM DIMR 범위다.
강제 종료의 인과 귀속·정상 마무리·사용 가능한 restart, 다른 모델·CRS·MPI·결합·GUI 동등성을
새로 승인하지 않는다. 체크포인트의 B06·B14·S07·G15·G18 후보는 각각 독립 검수와 합류
관문을 유지한다. 다음 대상은 B06 공개 기록 판독기의 사전 오류 70개·정상 6개 독립 검수다.
다음 작업은 [체크포인트의 노드별 표](research/checkpoints/20261105-quota-pause/README.md#중단-시점)와
[공정표](DELIVERY.md)의 선행 조건을 읽고 새 후보·새 검수 단위로 진행한다.

Herdr 재접속 시 현재 호출 pane과 실제 에이전트 상태를 다시 확인한다. Claude는
`--model claude-sonnet-5-5 --effort high` 시작 배너와 응답을 확인하고, 각 배정에서
AGENTS.md를 읽는다. 공유 Git의 staging/commit/push와 네이티브 임대는 코디네이터가 직렬 처리한다.
