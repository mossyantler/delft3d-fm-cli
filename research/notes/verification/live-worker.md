# R09 · 라이브 BMI 세션과 보 높이 제어

**승인한 범위:** 48셀 합성 수로의 지정 관측 수위 읽기, 지정 보 하나의 마루 높이 쓰기, 정상 종료·중단·오류 후 격리. 2개 물리 대조 세션과 12개 수명 주기 세션을 같은 버전에서 재현했다. 다른 구조물이나 임의의 메모리 주소 쓰기는 검증하지 않았다.

`dfm bmi inspect MDU --controls FILE`은 모델과 허용할 관측점·제어값, 단위를 확인한다. `dfm bmi session`은 새 폴더의 worker가 실제 FM 라이브러리를 로드하도록 하고, 표준입출력으로 요청 ID가 있는 JSONL을 교환한다. 일반 명령의 JSON 결과와 달리 세션은 준비 이벤트·요청별 응답·마지막 CLI 결과를 구분한다. [프로토콜과 근거 ABI](../../../src/dfm_cli/bmi_contract.py). DLL·PID가 존재한다는 것만으로 동작을 승인하지 않는다.

통합자 사전 검사 `BMI-G-public-preflight-01`에서 48셀 수로 복사본의 `observations/centre/water_level`, `observations/upstream/water_level`을 확인했다. 첫 실제 세션 `BMI-G-native-clock-01`은 준비 단계에서 `bmi_worker_protocol`(종료 코드 5)로 거부됐다. Windows 가상환경 실행기의 PID와 별도 Python 자식이 같은 private Job에 있었고, 기존 검사는 실행기 PID와 worker가 보고한 PID가 같아야 했다. 보존한 manifest에서 두 프로세스의 종료와 빈 job을 확인했다. 이 시험에서 초기화·step·물리량 읽기/쓰기는 성공하지 않았다.

수정 후 `BMI-G-native-clock-02`에서는 Windows가 보고한 named-pipe 클라이언트를 인터프리터의 실행 파일 지문, 생성 시각, 보관한 핸들, 해당 job과 부모 PID로 확인했다. 새 48셀 수로에서 공개 JSONL로 초기화 → 시각/관측값 조회 → 60초씩 두 번 진행 → 정상 종료를 수행했다. `centre`의 0/60/120초 수위는 각각 0, 0.0118599434, 0.0222356202 m였다. 통합자가 원본 history의 관측점 ID·CF 시각·단위를 맞춰 세 값을 다시 읽었다. BMI는 배정밀도, history는 float32였고, 원래 정밀도에서의 최대 차이는 5.45×10⁻¹⁰ m였다. 기록 정밀도로 반올림한 세 값은 모두 정확히 일치했다. map·history·마지막 restart 시각과 입력 무변경도 확인했다. 근거는 `BMI-G-native-clock-02/{receipt,raw-comparison}.json`이다.

쓰기 경로는 별도다. `BMI-V-native-20261104-01`의 독립된 두 worker 모두 소유권 검사를 통과했지만, 첫 구조물 초기화에서 `weirs/blocking_weir/crest_level`에 요청한 0.5 m와 엔진에서 다시 읽은 0.0 m가 달랐다. CLI는 실패했고 두 job은 비었다. 출력에는 구조물 위치 키에 대한 경고도 남았다. 이 시험은 보 제어·물리 반응이나 계산 중 취소 격리를 입증하지 않는다. [실험 색인](../experiments.md).

두 번째 독립 시험 `BMI-V-native-20261104-02`는 `locationFile`과 명시적으로 선택한 DIMR 방식의 스칼라 주소 전달을 사용했다. 두 세션은 120초에 종료됐다. 기준군의 원본 history에서 마루 높이는 끝까지 0.5 m, 변경군에서는 최종 −0.5 m였다. 변경군 최종 보 유량은 42.20946 m³/s, 유효 단면적은 19.354534 m²였다. 다만 기준군 유량은 결측이고, 엔진이 기록할 처리 후 보 형상의 점 수와 좌표는 양쪽 모두 결측이었다. 입력 선의 두 점과 출력 배열의 길이만으로 실제 연결된 격자 링크를 확정할 수 없어 전체 쓰기 노드는 승인하지 않았다.

**중단·오류 검수는 통과했다.** 독립 검증과 통합 재현에서 각각 12개 별도 세션을 만들었다. abort 시 대상이 정리된 뒤에도 같은 실행 파일을 쓰던 다른 worker가 실제 모의시각 1→2초로 진행했고, 자기 보 높이 0.5 m를 읽고 부분 종료했다. 입력 스트림 EOF도 `aborted`, 지정 시간 만료는 `timed_out`이었다. 읽기 전용 값 쓰기, 선언하지 않은 이름, 잘못된 단위·간격, 종료 시각 초과, 초기화 전 호출·중복 호출, 잘못된 수치 입력은 각각 거절했다. 열어 둔 핸들과 빈 job으로 종료를 확인했다. 부분 종료를 120초 계산 완료로 기록하지 않는다.

통합 결과는 `BMI-G-lifecycle-01/verification.json` (SHA-256 `a1e55dd0684165cfc5806cc9a4b790ee5d635e85136a046c8845457153e054c2`)이다. [독립 재현기](../../workflows/verification/verify_bmi_native.py)의 `--phase lifecycle`은 실행 수명 주기만 검사하며, 전체 BMI 판정이나 처리 후 보 형상을 검증하지 않는다. 독립 시험은 `BMI-V-lifecycle-20261104-01`이다.

## 실제로 낮아진 보를 통과한 유량

`BMI-V-mapped-native-slot46-20261104-01`에서 검증자는 실행 전에 검사 방법을 고정했다. `BMI-G-all-mapped-01`에서 통합자가 새로 작성한 같은 입력의 두 세션으로 물리 반응과 수명 주기를 함께 재현했다. 두 세션 모두 지정한 `blocking_weir`가 0.5 m인 채로 시작했다. 30초에 한쪽만 −0.5 m로 바꿨다. 입력의 두 끝점과 map의 원본 격자 연결을 대조하면 이 선은 서쪽 셀에서 동쪽 셀로 향하는 네 링크(0부터 32·37·42·47)를 가로지른다.

| 120초 원본 출력 | 높은 보 대조군 | 30초에 낮춘 보 |
| --- | ---: | ---: |
| history 보 높이 (m) | 0.5 | −0.5 |
| map의 네 링크 유량 합 (m³/s) | 0 | 42.2094612 |
| history의 구조물 유량 (m³/s) | 결측 | 42.2094612 |
| 상류 / 하류 관측점 수위 (m) | 0.260799 / −0.176269 | 0.221816 / −0.181949 |

보를 연 뒤 40–120초의 모든 유효 구조물 유량이 링크 합과 맞았다. 양옆 10 m에 둔 단면들은 실제 보와 다른 유량을 보였다. map의 셀 저장량·외부 유입 수지도 검사했다. 원본 history의 처리 후 단면 형상은 여전히 결측이다. 높은 보의 유량 0은 map에서 측정한 값이며, history의 결측값을 0으로 바꾸지 않았다. 이전 문자 그대로의 형상 검사는 실패 기록으로 남겼다.

재현: `.venv/Scripts/python.exe -m research.workflows.verification.verify_bmi_native --phase all --physics-geometry mapped-links --install <suite-root> --out <new-folder> --native-slot-granted`. 통합 `verification.json`과 원본 NC·프로세스 기록을 다시 대조한 `coordinator-raw.json` 지문은 [모듈 검수 색인](../../catalog/module-gates.json)에 있다.
