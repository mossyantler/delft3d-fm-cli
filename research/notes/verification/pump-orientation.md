# G13 · 펌프 선을 뒤집으면 물은 반대로 이동하는가?

**이 4링크 모델에서 위치선만 뒤집으면 펌프가 보고하는 부호는 바뀌지만 물은 계속 같은 쪽으로 이동한다.** FM 매뉴얼 §7.4.2.8(인쇄 p.80, PDF p.106)은 지도에서 펌프 선을 뒤집는 작업을 설명한다. §12.9.2(PDF p.227)와 부록 C.12.5(PDF p.480)는 선의 방향, `orientation`, 용량을 구별한다. 펌프를 기준으로 표시한 양의 유량만으로는 서쪽 물이 동쪽으로 갔는지 알 수 없다.

| 복사본 | 실제로 다른 파일 | 설치 엔진에서 확인할 예측 |
| --- | --- | --- |
| 기준 | MDU의 `StructureFile = structures.ini`, 그 안의 `locationFile = pump.pli`. 남쪽→북쪽 선, `orientation = positive`, 용량 1 m³/s | 고정된 동서 단면에서 동쪽으로 이동. 서쪽 저장량 감소, 동쪽 증가 |
| 선 반전 | `pump.pli`에서 두 좌표 행만 역순. 구조물 설정·관측 단면·망은 원본과 동일 | 같은 단면에서 서쪽으로 이동. 양쪽 저장량 변화의 부호도 뒤집혀야 함 |
| 정지 대조 | 기준 선 그대로, `structures.ini`의 `capacity = 1`만 `0`으로 변경 | 같은 기간 유량·저장량 변화가 없어야 함 |

[입력 대조](../../experiments/G13-PUMP-G-input-review-01/verification.json)에서 원래 망의 셀 정점을 읽어 각 측의 면적 2,400 m²와 경계를 가로지르는 링크 네 개를 확인했다. 120초 내내 총 1 m³/s를 보낸다면 이동 체적은 120 m³, 각 측의 평균 수위 변화 크기는 0.05 m다. 이는 계산 결과가 아니라 [실행 전에 고정한 예측](../../experiments/G13-PUMP-G-input-review-01/prelaunch-geographic-plan.json)이다.

[고정 소스의 펌프 계산](<https://github.com/Deltares/Delft3D/blob/5a4649830b1e5072caf019fb4850bbdefd9ad431/src/engines_gpl/dflowfm/packages/dflowfm_kernel/src/dflowfm_kernel/compute/oned_functions.f90#L655>)은 링크 방향, 양수측의 사용 가능 체적, 링크별 재분배를 별도로 다룬다. [준비 기록](../../experiments/G13-PUMP-I-20261105-031310-1da415d6/prepared-final/preparation.json)에는 링크 부호·면적 처리에 관한 의문도 남겼다. 설치 엔진의 정확한 소스 개정은 알 수 없다. 실제로 확인할 항목은 펌프 하나의 출력 부호, 고정 단면의 유량·누적량, 네 링크의 지리적 방향별 유량, 양쪽 셀의 저장량, 종료 시각과 restart다. 서로 모순되면 원본 차이를 보존한다.

**설치 엔진 측정 (#175).** 세 복사본을 각각 직접 FM으로 120초 계산했다. 아래에서 양수는 펌프 방향이 아니라 **고정 좌표의 서→동**이다. 유량은 1–120초 모두 같은 값이었다. 저장량은 셀의 마지막 체적에서 첫 체적을 빼서 구했다.

| 경우 | 입력 용량 (m³/s) | 펌프 기준 최종 보고 (m³/s) | 고정 단면 실제 유량 (m³/s) | 동쪽 누적 (m³) | 서쪽 / 동쪽 저장량 변화 (m³) |
| --- | ---: | ---: | ---: | ---: | ---: |
| 기준 | 1 | +4 | +4 | +480 | −480.00012 / +480 |
| 선만 반전 | 1 | −4 | +4 | +480 | −480.00012 / +480 |
| 용량 0 | 0 | 0 | 0 | 0 | 0 / 0 |

[독립 검증기의 사전 기준](../../experiments/G13-PUMP-V-frozen-01/predeclared.json) 중 총유량 크기와 선 반전의 방향은 [원래 판정에서 미통과](../../experiments/G13-PUMP-V-G-native-175-01/verification.json)했다. 단순히 출력 필드가 없어서 생긴 실패는 아니다. [통합자 원자료 재판독](../../experiments/G13-PUMP-G-raw-175-01/readback.json)에서는 `mesh2d_edge_faces` 양쪽 셀의 x좌표와 `mesh2d_q1`의 양의 방향 속성으로 네 링크를 다시 골랐다. 입력 용량이 1인 두 경우 모두 **각 링크에서 동쪽으로 1 m³/s**였다. 기준군과 선 반전군의 네 링크 유량, 모든 셀의 수위·체적, 고정 단면의 유량·누적량, 두 관측점의 수위는 121개 시각 전체에서 각각 정확히 같았다. 각 측의 최종 평균 수위는 서쪽 −0.20 m, 동쪽 +0.20 m다. history의 단면 누적량과 map 저장량 차이의 최대 잔차는 0.000245 m³ 미만이었다. restart도 0·120초 자료의 실제 좌표로 map과 대조했다.

[실행 증거](../../experiments/G13-RUNNER-I-G-native-175-01/verification.json): 각 실행은 보존된 여섯 입력을 사용했고, 세 루트가 모두 자연 종료 코드 0을 반환했다. 원래 Job의 멤버 핸들과 빈 Job을 확인했다. 진단 로그에는 사용되지 않은 출력 키와 입력 망 면 중심 좌표 읽기 경고가 남아 있다. [휴대 가능한 결과·원본 해시](../../catalog/pump-orientation-gates.json)는 이 모델과 설치 바이너리에 한정된다. 이 결과만으로 다른 펌프의 용량을 교차 링크 수로 나누는 규칙을 만들 수 없다.

[독립 검증자의 전체 변수 대조](../../experiments/G13-PUMP-V-results-175-01/verification.json)에서도 두 활성 사례의 map 변수 35개, 초기·최종 restart 변수 각각 25개는 값·마스크·변수 속성까지 같았다. history에서는 78개 변수가 같고 10개가 달랐다. 달라진 항목에는 펌프 유량의 상대 부호, 상·하류 수위 및 수두, 위치선 관련 좌표가 있다. 따라서 전체 history가 같다거나 표시 부호 한 필드만 달라졌다는 뜻은 아니다.

원본을 다시 읽으려면 저장소 루트에서 다음을 실행한다. 세 엔진 계산을 다시 시작하지 않으며, 새 결과 폴더가 필요하다. 원래의 물리 예측이 기각됐으므로 같은 자료에 대한 검증기 종료 코드 1이 예상된다.

```powershell
.venv/Scripts/python.exe -B -m research.workflows.verification.verify_pump_orientation --predeclared research/experiments/G13-PUMP-V-frozen-01/predeclared.json --runs research/experiments/G13-RUNNER-I-G-native-175-01/runs.json --out research/experiments/G13-PUMP-V-NEW
```

기존 공개 `model inspect`는 이 입력에서 `geometry/structurefile`을 지원하지 않는다고 보고하고 여섯 파일 중 네 파일만 열거한다. 따라서 현재 직렬 프로필로 복사된 모델을 펌프 실험의 입력으로 사용하지 않는다. GUI의 Reverse line(s)가 바꾸는 파일, 실제 양수 방향, 공개 펌프 편집은 각각 별도 검증 대상이다.

**공개 조회 명령.** `dfm pump inspect MODEL.mdu --id transfer_pump`는 MDU의 `StructureFile` → 구조물 파일의 `locationFile` → PLI 좌표 행을 따라간다. 정확한 구조물 ID, 선언한 용량과 방향, 좌표 순서와 파일 해시를 반환한다. 모호한 참조 또는 범위 밖 입력은 오류로 구분한다. [독립 시험 18개](../../experiments/G13-READ-V-EIN-corrected-results-20261105-040103-51b9468e/verification.json)와 [제품 명령 재현](../../experiments/G13-READ-G-root-01/verification.json)을 통과했다. 범위는 3.01 구조물 파일·상수 용량·단계 제어와 감쇠가 없는 2D XY 펌프다. 이 명령은 엔진을 호출하지 않는다.

선만 뒤집어도 물이 반대로 이동한다는 예측은 이 모델에서 기각했다. 사용자 용량을 링크 수로 자동 보정하지 않는다.

**같은 위치선에서 `orientation`과 `capacity`를 각각 바꾸면? (#177)** [통합자 입력 대조](../../experiments/G13-DRIVE-G-input-review-01/verification.json)에서 #175의 실제 기준 입력과 18개 파일을 비교했다. 각 변경군은 구조물 파일의 값 하나만 다르다. 세 모델 모두 120초를 자연 종료했다. [독립 검증기](../../experiments/G13-DRIVE-V-G-native-177-01/verification.json)와 [통합자 원본 판독](../../experiments/G13-DRIVE-G-raw-177-01/readback.json)에서 같은 지리적 방향을 확인했다.

| 위치선 고정, 변경한 속성 | 동서 단면 유량¹ (m³/s) | 펌프 기준 보고 `pump_discharge_dir` (m³/s) | 누적 동쪽 이동 (m³) | 서쪽 / 동쪽 저장량 변화 (m³) |
| --- | ---: | ---: | ---: | ---: |
| 기준: `positive`, 용량 1 | +4 | +4 | +480 | −480.00012 / +480 |
| `orientation=negative`만 변경 | −4 | +4 | −480 | +480 / −480.00012 |
| `capacity=-1`만 변경 | −4 | −4 | −480 | +480 / −480.00012 |

¹ 양수는 동쪽이다. 초기 이후 120개 시각 모두에서, 각 링크는 기준 +1, 변경군 −1 m³/s였다. 두 변경군은 네 링크 유량뿐 아니라 모든 셀의 체적과 수위, 관측점 수위, 단면 유량과 누적량 시계열까지 서로 정확히 같았다. 새 기준군도 같은 항목에서 #175 기준군과 정확히 일치했다. 두 변경군의 120초 restart는 map과 같은 서쪽 유량을 보였고, 각 측의 평균 수위는 서쪽 +0.20 m, 동쪽 −0.20 m였다.

[원본 NetCDF 전체 대조](../../experiments/G13-DRIVE-V-results-177-01/verification.json)에서는 #175와 #177 기준군의 변수 173개(값·마스크·변수 속성)가 모두 같았다. #177의 두 음수 설정끼리 비교하면 map과 두 restart는 전부 같고, history에서 다른 값은 `pump_capacity`와 `pump_discharge_dir`뿐이다. 생성 일시와 UUID 등 파일 전체 속성은 이 동등성에 포함하지 않았다.

따라서 **이 사례에서 물을 반대로 보낸 설정은 각각 확인했지만, 총유량을 |용량| = 1 m³/s로 맞춘 경우는 없었다.** 관측된 유량을 사용한 각 측 물수지의 최대 잔차는 0.000245 m³ 미만이다. [비교 수치·12개 원본 파일의 지문](../../catalog/pump-drive-gates.json). 단일 링크의 별도 결과는 아래와 같다. GUI의 Reverse line(s)가 어느 속성을 바꾸는지는 아직 실측하지 않았다.

**교차 링크를 하나로 줄인 계산 (#183).** 같은 120 × 40 m 수조를 12 × 1셀로 나눴다. 중앙 단면을 가로지르는 계산 링크는 하나이고, 동·서쪽 면적은 각각 2,400 m²다. [계산 전 독립 검증 기준](../../experiments/G13-SINGLE-RUNNER-V-predeclared-20261105-02/predeclared.json)과 [5개 모델의 원본 출력 검수](../../experiments/G13-SINGLE-RUNNER-V-G-native-183-01/verification.json)를 연결했다.

| 바꾼 입력 | 동쪽 기준 단면 유량 (m³/s) | 펌프 기준 보고 (m³/s) | 120초 누적 동쪽 이동 (m³) |
| --- | ---: | ---: | ---: |
| 기준: 양의 방향, 용량 +1 | +1 | +1 | +120 |
| 위치선 정점 순서만 반전 | +1 | −1 | +120 |
| 방향 속성만 음수 | −1 | +1 | −120 |
| 용량만 −1 | −1 | −1 | −120 |
| 용량만 0 | 0 | 0 | 0 |

다섯 경우 모두 실제 링크 유량, 고정 단면, 양쪽 저장량과 관측 수위를 121개 시각에서 대조했다. 활성 사례에서 120 m³를 받은 쪽의 평균 수위는 0.05 m 올라갔다. [원본 NetCDF 별도 판독](../../experiments/G13-SINGLE-G-raw-183-01/readback.json)에서 0·120초 restart와 map이 일치했고 각 측 물수지 잔차는 최대 0.000245 m³ 미만이었다. 선만 뒤집은 경우 두 모델의 셀 수위·저장량·실제 유량 시계열이 같았다. **이 단일 링크에서 명시 용량과 실제 유량 크기는 일치했다.** 네 링크의 총유량 4 m³/s와 함께 기록하되, 두 이산화 사례에서 모든 격자에 적용할 환산식을 추론하지 않는다. [20개 NetCDF 지문과 판정](../../catalog/pump-single-link-gates.json).

**편집기 단독 시험.** [스테이징에서 설치한 wheel](../../experiments/G13-EDIT-G-staged-wheel-02/verification.json)로 방향·용량을 하나씩 바꾼 두 복사본과 무변경 대조군의 여섯 파일을 수동 #177 입력과 대조했다. [Windows 권한 대조](../../experiments/G13-EDIT-V-installed-20261105-051042-7a65ac49/verification.json)에서 보호된 ACL은 쓰기 전에 거부했고 일반 상속 권한은 적용 뒤 유지됐다. 이 결과는 파일 편집에 한정된다. 후속 공개 명령의 계산 결과는 아래와 같다.

<a id="public-pump"></a>

**공개 명령으로 편집하고 실행한 결과 (#187).** [예제 모델](../../../examples/pump/model.mdu)을 복사한 뒤 `pump set`으로 기존 방향 또는 용량 중 하나를 바꾼다. 미리보기의 `result.sha256`을 같은 요청의 `--apply --expect-sha256`에 전달한다. `run start --profile pump-scalar --route direct`가 MDU·망·구조물 정의·펌프 위치선·관측점·고정 단면을 실행 폴더로 복사한다. DIMR와 기본 short 프로필은 이 모델을 받지 않는다.

| 공개 명령에 준 모델 | 고정 단면의 동쪽 유량 (m³/s) | 120초 이동량 (동쪽 +, m³) |
| --- | ---: | ---: |
| 4링크 기준, 용량 +1 | +4 | +480 |
| 4링크, 방향 속성만 negative | −4 | −480 |
| 4링크, 용량만 −1 | −4 | −480 |
| 1링크 기준, 용량 +1 | +1 | +120 |
| 1링크, 미리 뒤집어 둔 위치선 | +1 | +120 |

[설치본 실행](../../experiments/G13-INTEGRATION-REPLAY-I-G-native-187-01/verification.json)과 [독립 판독](../../experiments/G13-INTEGRATION-REPLAY-V-20261105-01/native-readback-G-187-01/verification.json)을 대조했다. 다섯 건 모두 기준 모델과 실행 입력 6개가 같았다. history·map은 0–120초에 1초 간격, restart는 0·120초였다. 사례당 173개 변수의 값·마스크·변수 속성이 수동 대조군과 일치했다. 동서 유량은 펌프 표시 부호로 추정하지 않고 망의 링크 유량과 양쪽 저장량으로 확인했다. 이산화에 따른 자동 용량 보정이나 GUI에서 그리는 선의 반전 기능은 제공하지 않는다.

종료 판정은 별도다. 다섯 실행 각각에서 원래 Job의 두 멤버가 종료하고 Job이 비었으며 원래 핸들을 닫았음을 확인했다. [독립 오류 주입 44건](../../experiments/G13-RUN-LIFECYCLE-V-terminal-05/verification.json)에는 완료 manifest 교체 직후 오류를 내는 경우가 있다. 디스크에 요청한 최종 기록이 정확히 남았을 때만 성공으로 응답한다. 다른 실행의 기록·오래된 시각·누락된 종료 증거는 덮어쓰거나 성공으로 인정하지 않는다. [입력 검사 77건](../../experiments/G13-RUN-PROFILE-V-final-10/verification.json)은 경로 재배치와 별칭, 낡은 입력, 격자·시각 범위 거부를 별도로 다룬다.

**같은 모델에서 완료와 중단이 경합한 경우.** [#195](../../experiments/G13-PUBLIC-G-stop-195-01/verification.json)에서는 0.25초 제한을 둔 실행이 자연 종료했다. 별도 실행에서는 `running`을 보고 취소 CLI를 시작했지만, 요청을 처리할 때 이미 `completed`여서 `run_not_active`가 반환됐다. 두 경우 모두 최종 결과를 보존했다.

[25 ms 시간 초과 #197](../../experiments/G13-PUBLIC-G-warm-stop-197-01/timeout-run/manifest.json)와 [미리 로드한 CLI의 취소 #199](../../experiments/G13-PUBLIC-G-warm-cancel-199-01/cancel-run/manifest.json)에서는 원래 Job에 실제 종료 요청이 전달됐다. 두 경우 모두 FM은 요청 당시 실행 중이었지만 자식 `cmd.exe`는 이미 종료 신호가 나 있었다. 마지막에는 두 멤버의 보관 핸들에서 모두 종료를 확인했고 Job의 활성 멤버 수는 0, 원래 Job 핸들을 닫은 결과도 성공이었다. 그러나 두 멤버 **모두가 요청 당시 살아 있었다는 증거**는 없다. 이 버전은 `cleanup_failed`와 원래 사유 `run_timeout` 또는 `run_cancelled`를 함께 남겼다. 취소 접수나 종료된 프로세스의 수를 강제 종료 성공으로 세지 않는다.

**중단 사유와 핸들 정리의 분리.** 위 두 manifest의 옛 메시지는 성공한 핸들 닫기까지 미확인으로 표시했다. 새 펌프 기록은 `ownership.pump_lifecycle.close_assessment`에서 원래 Job과 수집기의 핸들을 닫았는지 보고하고, `exit_evidence`에서 종료 증거를 별도로 판정한다. [기존 사실을 재생한 독립 시험](../../experiments/G13-PUBLIC-STOP-V-patch-01/REPORT.md)에서 #197·199는 여전히 `cleanup_failed`이고 두 핸들 정리 판정만 성공으로 바뀌었다. 당시 기록 자체는 수정하지 않았다.

[수정본을 설치해 실제로 실행한 #201](../../experiments/G13-STOP-G-native-201-01/verification.json)에서는 자연 종료한 두 멤버의 종료 코드가 모두 0이었다. 25 ms 제한을 둔 별도 실행에서는 요청 당시 FM 한 프로세스만 Job에 속했고 살아 있었다. 같은 핸들에서 종료 코드 1, 활성 멤버 0, 원래 Job 닫기를 확인해 `timed_out`과 `run_timeout`을 기록했다. 같은 25 ms 제한에서도 #197과 결과가 다른 것은 요청 시점의 멤버와 확인할 수 있던 증거가 달랐기 때문이다.
