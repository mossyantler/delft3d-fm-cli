# 짧은 직렬 실행의 종료 기록 보강

2026-11-05, **공용 종료 모듈 두 개 제품 반영**. 개별 I/V·설치 검수, 정확한 실행기/판독기
합류, 실제 엔진 회귀와 원시 자료 독립 재판독을 거쳤다. 아래 초기 결함·반려·#227 실패는
역사 기록이며 현재 승인과 구별한다. [공정표](../../../DELIVERY.md)의 SHORT-CLOSE 노드다.

## 현재 구현과 검수

검증한 wheel `e32bf84fe092b1ea5a68db6f2405cd6566d27dd4b1131a498d6871f5bb53b3e6`와
제품 191파일이 일치한다. `runs.py`와 `run_pump_lifecycle.py` 두 파일만 바꾸며 189파일은
기존 승인본을 보존했다. 원래 멤버의 수명 종료, 양방향 알림 대응, 원래 Job·수집기 닫기
영수증을 최종 상태 게시 전에 보관한다. 실제 닫기나 저장 실패를 성공으로 처리하지 않으며
게시 실패 때문에 이미 닫힌 원래 Job을 다시 종료하지 않는다.

`short`의 수명 근거만 부족하고 실제 닫기가 확인됐을 때는 기존 공개 오류
`termination_unconfirmed`를 유지한다. 상태는 `cleanup_failed`다. 실제 Job/수집기 닫기
실패·불확실성은 `short_cleanup_failed`가 우선하며 pump/weir는 각 가족 오류 코드를 유지한다.
[전체 회귀와 제품 동일성 기록](../../proposals/short-close-native-gates/root-verification.json),
[독립 통합 검수](../../proposals/short-close-root-review/VERIFICATION.json)를 참조한다.
CLI의 명령 98개·프로토콜 2·manifest 3과 기본 모델 프로필은 유지한다.

<a id="native231"></a>
## 실제 회귀 #231

실행기는 [후보 6](../../proposals/short-close-native-adapter-v6/README.md) 동결 `53a1db83…`,
별도 원시 판독기는 동결 `980c9d91…`, 사전 계획은 `d5427cb0…`를 사용했다.
원래 관찰 소스와 독립 수치 판독기의 고정 경로·해시는 유지했다. [정확한 오프라인 합류 검수](../../proposals/short-close-native-gates/composition-review231.json)
후 새 임대 231·새 폴더에 사례별 한 번씩 실행했다. 최대 동시 소유 실행은 2개다.

| 경로별 사례 | 공개 상태 | 독립 판독 |
| --- | --- | --- |
| 정상 | `completed` | 원래 전체 수명·Job·수집기 닫기, CF history/map 0–600초와 최종 restart |
| 잘못된 mesh / 빈 BC | 각각 `failed` | 실제 입력 오류 진단과 원래 전체 닫기 |
| timeout / cancel | `timed_out` / `cancelled` | 원래 전체 닫기와 별도 같은 실행 파일 대조군의 생존 |
| 대조군 정리 | `cancelled` | 생존 관찰 뒤 명시적 정리와 원래 전체 닫기 |

[독립 사후 판독 37항목](../../proposals/short-close-native231-review/RELEASE_VERDICT.md)
`3851697`은 Job·수집기 12개, 보유 멤버 종료 24개, 관찰 핸들 12개, 공개 클라이언트
16개의 종료/닫기와 네 대조군 원시 묶음을 확인했다. 원본 NetCDF 네 쌍을 다시 읽어
restart 34+34, history 68, map 55개의 **191변수**가 값·mask·단위·차원까지 같음을 확인했다.
[해제와 합류 승인](../../proposals/short-close-native-gates/release231.json) `2af0673` 이후
슬롯은 `idle232`다. 해제 상태는 다음 실행의 허가가 아니다.

범위는 f34 2D UTC cold-start `short` 600초, direct FM 및 단일 FM DIMR다. 강제 종료의
인과 귀속·정상 마무리·사용 가능한 restart, 보정/물리 타당성, 다른 모델·CRS·MPI·결합·GUI
동등성을 새로 입증하지 않는다. B06·B14·S07 등 미병합 제품은 별도 관문을 유지한다.

## 실제 회귀 #229와 실행기 보완

첫 재개 실행은 direct 여섯 사례 뒤 대조군 두 관찰이 같은 monotonic tick을 가져 거부됐다.
당시 Python 3.12 `GetTickCount64()` 해상도는 15.625ms였다. 원래 trial `NOT_ACCEPTED`와
192파일을 보존하며, DIMR·191변수 비교는 하지 않았다. [해제 전용 독립 검수](../../proposals/short-close-native229-review/RELEASE_VERDICT.md)
`152dfe4`는 여섯 원래 Job·수집기와 멤버 12개, 관찰 핸들 6개·클라이언트 8개의 종료를
확인했으며 원래 trial을 승인하지 않았다.

같은 보유 관찰 핸들에서 다음 실제 tick을 얻는 제한된 재관찰을 추가했다. 정식 임대와
허가의 해시·경로·출력 폴더도 정확히 연결했다. 원시 시각을 만들거나 판독 조건을 낮추지
않았다. [독립 시계/허가 검수](../../proposals/short-close-native-clock-auth-review/VERIFICATION.json)
`ed1456b`는 54건과 기존 일곱 결함 재현 대조를 통과했다. 수정은 연구 실행기/허가에 한정되며
같은 wheel·판독기·모델 입력으로 새 #231을 실행했다.

## 확인한 문제 (수정 전)

S07의 공개 `run start --profile short` 준비에서 수정 전 `runs.start`는 `completed`를 저장한 뒤 `finally`에서 `OwnedJob.close()`를 호출하고 반환을 버리는 것으로 확인됐다. 같은 원래 Job의 실제 닫기 결과와 수집기 종료를 최종 상태에 반영할 수 없는 순서다.

| 재현 | 관찰 결과 | 근거의 범위 |
| --- | --- | --- |
| CloseHandle의 성공·실패·예외 세 경우 | 세 경우 모두 닫기 전에 디스크에 `completed`가 기록됐다. 반환값 0도 호출자는 completed를 받았고, 예외가 나면 예외와 completed 기록이 함께 남았다. | [통합자 재현](../../experiments/SHORT-CLOSE-G-reproducer-01/evidence/verification.json). 실제 `runs.start`·`OwnedJob.close`를 사용하되 앞선 실행 단계와 OS 호출만 대체. 실제 엔진/Job 실행 없음. |
| 기존 #219 종료 기록의 복사본에 미대응 또는 중복 프로세스 알림을 추가 | 두 변형 모두 현재 `natural_exit`가 통과시켰다. 이벤트에서 알림으로의 연결만 확인하고 역방향과 중복을 검사하지 못했다. | [통합자 변형 대조](../../experiments/SHORT-CLOSE-G-notifications-01/verification.json). 원래 기록은 그대로 보존됐고 원래 기록 자체도 통과했다. |
| 단순 사후 JSON 저장 패치와 S07 판독기 | 독립 안전성 검사 19개 중 14개 실패, 테스트 오류 없음. 추가 6개 알림 검사 중 3개가 잘못 통과했다. bool 반환 코드, 수집기의 종료 시도, 잘못된 Job, 저장 실패 경로도 수정 대상이다. | [독립 반려 기록](../../experiments/S07-RUN-CLOSE-V-20261105-01/final-review-01.json). 합성 오류 주입·기존 원자료의 복사본만 사용. |

이 결과는 과거 정상 계산의 출력 배열을 부정하는 판정이 아니다. 종료 실패와 모순된 관측값을 처리하는 경로의 별도 결함이다. 네이티브 종료 증거와 수치 결과는 각각 원래 실험 범위로 유지한다.

## 수정 계약과 선행 관계

`short`의 모델 검증·물리 프로필과 공용 종료 판정을 분리한다. 공통 종료 판정은 원래 보유한 root/member HANDLE의 종료와 Job 계수, 원시 알림↔식별 이벤트의 양방향 일치, 원래 Job 및 수집기 닫기 결과를 요구한다. 중복·미대응 프로세스 알림은 거부하고 정당한 Job 전체 알림은 따로 판정한다. PID 소실이나 조회 실패로 빈칸을 채우지 않는다.

완료 기록은 종료 근거와 실제 닫기 결과를 보존한 다음 게시한다. 닫기가 실패하거나 확인되지 않으면 `cleanup_failed`에 원래 중단 사유를 남긴다. 기록 실패 때문에 이미 닫힌 Job을 다시 종료하거나 이미 게시된 최종 상태를 다른 결과로 덮어쓰지 않는다. 예외 뒤에도 `close_result`의 원시 반환·오류를 보존한다.

공용 알림 판독 수정은 pump/weir/source-sink가 함께 사용할 하나의 구현으로 검수한다. 기존 가족별 오류 코드·근거 이름은 유지한다. B06-RUN-PROFILE의 실행 전 검증과 source-sink 프로필 등록은 별도 변경이며 공용 `runs.py` 병합은 통합자만 수행한다.

## 후보 2의 검수 이력

수정 후보 2의 [독립 검수](../../experiments/SHORT-CLOSE-V-20261105-02/final-review-01.json)는 현재 계약에 맞춘 오류 주입 19개와 추가 22개, 알림 6개·강제 종료 연결 5개·원본 기록 판독 12개를 통과했다. 구형 sidecar 제안용 테스트의 실패 기록은 삭제하지 않았으며, 원시 반환을 manifest에 보관하는 계약에 맞춰 바꾼 주입 위치와 기대 경로 5개를 명시했다. 기존 네이티브 기록은 수정하지 않았다.

[통합자 재검사](../../experiments/SHORT-CLOSE-G-frozen-review-03/verification.json)는 정확한 후보 2의 동결 파일 36개와 원래 pump/weir 기록 9건을 확인했다. 중복·미대응 알림, bool 반환 코드, 불일치 시각, PID가 붙은 Job 전체 알림, 종료 시도 플래그를 거부했다. `ABNORMAL_EXIT_PROCESS=8`은 충분한 수명 종료 근거가 있어도 계산 성공은 거부한다. 선택적 강제 종료 trace 역시 원래 요청의 Job과 보유 멤버 생성 시각 집합에 연결해야 한다. 이 결과는 설치 패키지·새 엔진 실행·제품 병합의 승인이 아니다.

1. 수정 후보에서 기존 반례, 원래 양성 기록, 종료·취소 경합 및 기록 실패 검사를 다시 통과한다.
2. 최종 패키지의 실제 코드·공개 명령·프로필별 등록을 확인한다. 이전 패키지의 통과 기록을 새 코드에 전용하지 않는다.
3. f34 direct/DIMR의 600초와 191변수, E009/E011의 오류·타임아웃·취소 및 같은 실행 파일 대조군 생존을 새 실행으로 확인한다. 공용 판독기를 쓰는 pump/weir의 원래 근거도 대조한다.
4. 통합자가 원래 실행 소유권과 모든 핸들·수집기 종료를 확인한 뒤 S07의 일곱 풍응력 사례와 B06의 direct/DIMR 공개 실행 검수로 진행한다.

실제 GUI Run/Stop, 다른 실행 프로필의 전면 개편, 과학적 유효성은 이 수정의 완료 판정에 섞지 않는다.

## 설치 패키지와 실제 엔진 #227

깨끗한 `.[run]` 설치본 `23f9daa7…c02e5d`는 [통합자 검사](../../experiments/SHORT-CLOSE-G-package-01/verification.json)에서 제품 191파일 중 기존 189파일 보존과 수정 2파일 일치, 명령 98개, 실제 설치 코드를 사용하는 93개 검사를 통과했다. [독립 패키지 검사](../../experiments/SHORT-CLOSE-PACK-V-20261105-01/audit-02/verification.json)는 원본 wheel·설치 RECORD·모듈 위치와 B06의 기존 네 입력 작성 경로를 대조했다. 이 결과만으로 실제 종료 경합이 검증된 것은 아니다.

[사전 계획](../../experiments/SHORT-CLOSE-G-native-plan-01/predeclared.json)은 direct/DIMR 각각 정상·잘못된 망·빈 BC·대조군·타임아웃·취소를 한 번씩, 최대 12실행/동시 2개로 제한했다. [원래 실행 결과](../../experiments/SHORT-CLOSE-G-native-227-01/verification.json)는 다음 다섯 사례에서 멈췄다. 자동 재시도나 기존 기록 수정은 하지 않았다.

| 실제 실행 | 디스크 상태 | 확인한 사실 |
| --- | --- | --- |
| direct 정상 | `completed` | 원래 멤버 종료·Job/수집기 닫기, history/map 최종 600초와 최종 restart |
| direct 잘못된 망 / 빈 BC | 각각 `failed` | 강제 종료하지 않은 실제 입력 오류와 진단, 원래 멤버·Job 닫기 |
| direct 타임아웃 | `cleanup_failed`, 원래 사유 `run_timeout` | root는 요청 직전 생존했고 종료 요청 후 같은 보유 핸들에서 종료 확인. `cmd.exe` 자식은 요청 전에 이미 종료됨 |
| direct 대조군 정리 | `cleanup_failed`, 원래 사유 `run_cancelled` | 별도 Job의 같은 실행 파일. 타임아웃 대상의 마지막 종료 확인 0.686422초 뒤에도 대조군의 원래 핸들이 생존을 나타냈고, 그 뒤 의도적으로 중지함 |

두 강제 종료 기록에서 이미 끝난 자식은 처음 생존 중에 확보한 이미지·생성 시각·Job 소속과 보유 핸들이 남아 있다. 중지 직전 같은 핸들의 대기 결과는 종료였고 생성 시각과 소속 조회도 성공했지만, 이미지 재조회는 Win32 오류 31로 실패했다. 기록자는 이 때문에 `prospective_qualified: false`, 전체 `prospective_handle_coverage_complete: false`를 남겼다. 후보 2의 공용 판정은 이를 수명 종료 근거 부족으로 처리했다. **조회 실패 자체는 종료 증거가 아니며, 이미 끝난 자식을 이번 요청으로 죽였다고 판정해서도 안 된다.** 후보 3은 실제 보유 핸들의 수명 종료와 강제 종료 귀속을 분리하는 계약부터 검토한다. 필요한 최초 확보 근거가 없는 기존 반례를 통과시키는 방식으로 고치지 않는다.

[원래 기록의 해제 검수](../../experiments/SHORT-CLOSE-G-native227-readback-01/verification.json)는 다섯 원래 Job과 보유 멤버 10개의 종료 및 수집기 닫기를 확인했다. 이는 다음 실행을 위해 독점 임대를 해제하는 근거이며 제품의 `cleanup_failed`를 성공으로 바꾼 것이 아니다. [부분 결과 판독](../../experiments/SHORT-CLOSE-G-native227-readback-01/partial-outcomes.json)은 정상 direct의 출력 시각과 대조군 생존의 정확한 관측 위치를 남긴다. 의도한 취소 대상과 DIMR 여섯 사례는 실행되지 않았고, 경로 간 191변수 비교도 하지 않았다. 임대는 #228 idle로 반환했으며 새 후보·새 검수·새 실행 폴더가 준비될 때까지 제품 병합과 후속 S07/B14/B06 실행을 보류한다.
