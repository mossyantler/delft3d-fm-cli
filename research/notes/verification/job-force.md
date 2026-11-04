# E011 후속 · 누가 종료됐는지 확인하는 기준

Job의 멤버 목록에 있던 PID를 열 수 없거나, 그 PID로 연 핸들이 다른 프로세스를 가리키면 원래 멤버의 종료는 **미확인**이다. 종료 요청은 최초에 만든 비공개 Job에만 보낸다. `termination.json`의 `termination_request`는 호출 사유·시각·실제 Win32 반환값을, `member_exit_confirmations`는 멤버별 확인 결과를 담는다. 최초 조회에서 보인 멤버의 종료와 실행 시작부터 추적한 모든 멤버의 수명은 별개다.

| Windows 통합 시험 | 관찰 |
| --- | --- |
| [수정 전](../../experiments/JOB-FORCE-G-before-01/observation.json) | 같은 Python 실행 파일의 부모·자식과 Job 밖 대조 프로세스를 띄웠다. 자식 PID를 여는 호출 하나만 대조 프로세스의 핸들을 돌려주도록 바꿨다. 기존 코드는 이 핸들이 Job 멤버가 아닌데도 자식 확인과 트리 종료를 모두 `true`로 기록했다. OS가 실제로 PID를 재사용했다는 주장은 아니다. |
| [수정 후](../../experiments/JOB-FORCE-G-release-race-01/observation.json) | 같은 조건에서 두 판정이 모두 `false`였다. 독립 관찰자가 처음부터 보관한 자식 핸들은 종료 신호를 받았다. 대조 프로세스는 Job 종료 후까지 살아 있었고 자체 종료 코드 0을 반환했다. 실제로 종료됐더라도 소유자가 그 사실을 확인하지 못했다면 성공으로 보고하지 않는다. |
| [direct FM·DIMR 실패/취소](../../experiments/JOB-FORCE-G-release-failure-01/verification.json) | 복사한 f34에서 초기화 실패·타임아웃·취소·자손 종료·제어자 소실을 두 경로로 재현했다. 17개 결과군에서 원본 입력이 보존됐고 같은 실행 파일의 대조 실행이 살아 있었다. |
| [정상 경로 회귀](../../experiments/JOB-FORCE-G-release-serial-01/verification.json) | 두 경로 모두 1990-08-05 00:10 UTC(600초)까지 계산하고 최종 restart를 썼다. 독립 비교기에서 출력 변수 191개가 일치했다. |

**실행 파일 경로를 나중에 조회하는 데도 한계가 있었다.** 실제 [direct FM 타임아웃 원자료](../../experiments/JOB-FORCE-G-release-failure-01/runs/timeout-direct/termination.json)에서 루트 핸들은 요청 전에 실행 중이었고 이후 종료 코드 1, 짧게 실행된 자손 핸들은 이미 종료됐고 코드 0이었다. 종료 후 실행 파일 경로 재조회는 오류 31을 냈다. 재조회 실패는 그대로 남기되, 같은 핸들에서 얻은 생성 시각·대기 결과·종료 코드를 버리지 않는다. 모든 멤버가 강제 종료 시점에도 실행 중이었다거나 종료 코드만으로 개별 종료 원인을 알았다고 보고하지 않는다.

[최종 검수 기록](../../experiments/JOB-FORCE-G-accepted-01/verification.json)에는 독립 검증과 통합 재현 파일의 해시가 있다. [재현기](../../workflows/replay/job_member_race.py)는 배정된 전용 슬롯과 새 결과 폴더를 요구한다. 이 시험이나 E009/E011은 실제 GUI의 Stop 동작을 검증하지 않는다. P08/E014 게스트의 강제 종료는 별도 수명 주기 시험으로 판정한다.

**게스트 실행기의 Windows 대체 시험.** 원래 #97에서는 강제 종료 후 모든 EXIT 알림을 확보하지 못했다. 이 실패 기록은 그대로 두었다. 별도 계약에서는 시작부터 보유한 핸들의 PID·생성 시각·종료 코드, 실제 Job 종료 호출의 반환값, 빈 Job과 대조 프로세스의 생존을 각각 확인한다. [독립 #116 및 통합 #117 원자료 대조](../../experiments/GUEST-FORCED-G-accepted-01/verification.json)에서 정상 종료, 일부 멤버 수집 실패 주입, 강제 타임아웃을 각각 두 번 확인했다. 멤버 수집에 실패한 사례는 정상 증명으로 채택하지 않았다. 두 타임아웃 모두 부모·자식 종료 코드가 1이었고, Job 밖 대조 프로세스는 Job을 닫은 뒤에도 살아 있다가 코드 0으로 종료했다. 누락된 EXIT 알림은 여전히 누락으로 기록한다. 시험 대상은 Python 프로세스였으며 Delta Shell, 모델 exporter, 실제 게스트 환경의 검증은 아니다.
