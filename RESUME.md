# 작업 재개 지점

2026-11-05 사용자 요청으로 한도 소진에 대비해 중단한 뒤, 같은 날 사용자가
Herdr에서 명시적으로 재개했다. Claude Code Sonnet 5.5 high도 서브에이전트로
사용한다. 전체 로드맵은 미완료다.

[중단 체크포인트](research/checkpoints/20261105-quota-pause/README.md)에
현재 노드의 승인 범위, 미병합 코드·검증기, 실패 기록과 재개 순서를 보관했다.
현재 제품 소스는 기존 승인본이며, 체크포인트의 후보를 자동으로 병합하지 않는다.

당시 중단 지점은 공용 실행 후보 4의 **패키지 검수**였다. 실제 엔진 재시험은 미실행이다.
재개 이후 공개 오류 코드 호환성 검수는 아래와 같이 진행했다. 미동결 실행기·판독기
연결을 해결한 뒤 다음 검증으로 진행한다. 네이티브 슬롯 `idle228`은 실행 허가가 아니다.

재개 첫 노드 `HERDR-RESUME-G`: 실행 환경·에이전트 지정·현재 상태를 갱신한다.
`SHORT-CLOSE-COMPAT-I/V`는 새 후보에서 공개 오류 코드 호환성을 검토한다.
기존 체크포인트와 제품 소스는 검수 전까지 유지한다.

첫 재개 결과와 재현 명령은
[호환성 후보](research/proposals/short-close-compat/README.md)에 있다.
기존 CLI 4건을 포함한 최초 합성 14건은 통과했다. 후속 `SHORT-CLOSE-COMPAT-D1-I`
(`bdbe355`)는 독립 검토의 테스트 누락을 보완해 15건을 통과했다. `short` 조건을
제거하면 pump/weir 회귀가 드러나는 변형 검사도 포함한다.

`SHORT-CLOSE-COMPAT-PACK-I`(`1fce44d`)는 별도 wheel `e32bf84f…`를 만들었다.
원래 189파일을 보존하고 종료 모듈 두 개만 바꾸며, 명령 98개·프로토콜 2·manifest 3을
유지한다. [독립 실행·설치 검수](research/proposals/short-close-compat-review/EVIDENCE.md)는
실제 설치 코드에서 기존 CLI 4건, 관련 116·49·18건 묶음을 확인한다. 묶음 간 검사는
중복되므로 합산하지 않는다. [패키지 준비와 실패 이력](research/proposals/short-close-package/README.md)도 보존한다.
독립 노드 커밋은 `SHORT-CLOSE-COMPAT-RUNTIME-V`의 `1a1e5b6`과
`SHORT-CLOSE-COMPAT-PACK-V`의 `1f0acbd`다. 이는 합성·설치 검수 범위의 승인이다.

**이어서 진행한 오프라인 공정.** 독립 판독기 `NATIVE-READER-I`는 `46175a4`,
코디네이터의 독립 검증 `NATIVE-READER-V`는 `bcc8c16`이다.
[판독기 동결본](research/proposals/short-close-native-reader/HANDOFF.md)은
`980c9d91…`, 소스는 `ddf31bae…`다. 기존 107개를 포함한 작성자 215개 사례와
[별도 검증 19건](research/proposals/short-close-native-reader-review/verification.json)을 통과했다.
API는 raw-api-2를 유지하며 manifest 3, 원래 핸들 확보·종료, 실제 Job/수집기 닫기,
관찰 객체별 UTC/monotonic 순서를 구분한다. 대조군 관찰 묶음은 모두 합성이다.

첫 실행기 `5225b23`의 독립 검수 `66ea221`은
[48개 검사로 일곱 결함을 재현](research/proposals/short-close-native-adapter-review/HANDOFF.md)했다.
검사가 통과했다는 뜻은 결함 재현에 성공했다는 뜻이며 이 후보는 실행 허가용으로 반려했다.
원시 대조군 최종 묶음 저장 수정 `36aa833`과 정리 경로 수정 `a546eb6`을 각각 별도
후보로 보존했다. 현재 최종 검수 대상은
[실행기 후보 3](research/proposals/short-close-native-adapter-v3/README.md), 동결 `daffc237…`다.
자체 검사 29건·정확한 판독기 연결 13건·파일/허가 연결 22건을 독립 재실행했고,
[최종 독립 검수](research/proposals/short-close-native-adapter-final-review/HANDOFF.md)
`98eb5e7`의 48건도 통과했다. 일곱 수정 요구는 첫 후보에서 모두 실패하고 후보 3에서
모두 통과한다. 독립 검수 동결은 `33848a44…`다.

[코디네이터 오프라인 합류 검수](research/proposals/short-close-native-gates/composition-review.json)는
정확한 후보·판독기·독립 검수 동결, 체크포인트 343파일·기존 제품 191파일·설치 191파일,
준비 입력 40개와 선택한 엔진 파일을 확인했다. 이 영수증 자체는 실행 허가가 아니다.
다음 단계는 새 독점 임대와 정확한 실행 허가로 direct/DIMR의 12사례(최대 동시 소유 실행 2개),
600초·최종 restart·원본 191변수 대조를 실행한다. 600초는 실행 예약 제한이며
클라이언트 준비·요청·소유자 종료 대기·최종 정리는 각자 별도 제한을 가진다.
현재 실제 엔진 회귀는 0회, 슬롯은 여전히 `idle228`이며 제품 소스는 기존 승인본 그대로다.
