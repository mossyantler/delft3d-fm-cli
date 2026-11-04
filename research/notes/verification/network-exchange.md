# 분기망과 1D–2D 교환 수지

분기망 3개와 1D–2D 혼합망 4개를 공개 CLI로 생성·검사하고 실제 direct FM으로 각각 120초 계산했다. 독립 시험 `NET-V-slot19-combined-20261104-181155-7aee63f4`와 통합자의 새 시험 `NET-G-branches-exchange-final-01`이 모두 통과했다. 통합 시험에서는 잘못된 입력 19종도 거부했다.

| 사례 | 원본 출력에서 확인한 물수지 |
| --- | --- |
| 세 가지가 만나는 분기망 | 정지 대조군은 변화가 0이었다. 유입 경계 시험에서 총 유입 9.600000 m³, 유출 11.730865 m³, 1D 저류 변화 −2.130863 m³였다. 가지의 입력 방향을 뒤집어도 같은 결과였다. 순간 유량을 정상상태로 가정하지 않고 각 셀·합류점의 시간별 저류 변화를 포함했다. |
| 1D–2D 정지·수위차 | 정지 시 저장량 변화와 교환량은 0. 수위차를 주면 2D 원본 저장량은 203.841614 m³ 증가했고 1D 순교환량은 −203.841637 m³였다. |
| 별도 형상과 역방향 | 다른 접촉 위치에서 2D 저장량 변화는 +248.853271 m³였다. 수위차를 뒤집고 접촉 길이 상한이 적용되는 형상에서는 2D −484.269531 m³, 1D +484.269539 m³였다. 이 마지막 사례에서 전 시각의 최대 절대 수지 잔차는 0.000657 m³ 미만(사전 허용오차 0.009060 m³)이었다. |

첫 분기 시험은 초기 과도응답을 정상류로 오인했고, 첫 혼합망 계산은 접촉부 저류 면적을 누락했다. 두 번째 형상의 약 2.195 m³ 차이는 엔진의 접촉 길이 상한을 빠뜨린 결과였다. [검증기](../../workflows/verification/verify_network_outputs.py)는 입력 꼭짓점·가지 길이·단면으로 접촉부 각 끝의 면적을 미리 계산한다. 고정 소스의 `flow_geominit.f90`, `getdxofconnectedkcu1.f90`, `addlink1d2dinternal.f90`가 근거이며, 설치본의 유효 설정은 별도로 .dia에서 확인했다. 마지막 역방향 사례의 예측은 계산 전에 기록했고, 마감 후에는 통합자가 실제 `mesh2d_vol1`·`mesh1d_cumulative_total_net_inflow_1d2d`를 직접 다시 읽었다.

재현: `python -m research.workflows.verification.verify_network --case branch_rest --case branch_flow --case branch_reversed --case exchange_rest --case exchange_head --case exchange_holdout --case exchange_reverse_cap --native-slot-granted --install <suite> --out <새-폴더>`. 통합 `verification.json`의 SHA-256은 `1c942fc91ad03b0677ad4b39709bb833d0f28b16ac0febe3272d3090ac2da21c`이다. 원본은 `research/experiments/`에 있다. 이 검수는 명시된 사각 단면·type-3 method-1 접촉의 합성 사례에 한정한다. 실측 수리 검보정, 모든 연결 형식 또는 GUI 편집·내보내기와의 일치를 입증하지 않는다.
