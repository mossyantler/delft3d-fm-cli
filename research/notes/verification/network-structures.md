# 1D 고정 보와 측방 유입: 닫힌 보를 물이 통과하지 않는가

단면과 보, 측방 유입이 있는 **합성 1D 수로**를 새 폴더에 작성해 2026.02 OpenHMWQ에서 직접 FM으로 실행했다. 유입이 없는 대조군과 유입만 준 경우를 나눴다. 이 검수는 `network-structures` 프로필의 해당 사례에 한정된다.

| 실제 NetCDF에서 확인한 값 | 정지 대조군 | 측방 유입군 |
| --- | ---: | ---: |
| 120초간 유입하도록 지정한 체적 | 0 m³ | 0.02 m³/s × 120 s = 2.4 m³ |
| 처음과 끝의 `mesh1d_vol1` 합계 차이 | 0 m³ | 2.399993896484375 m³ |
| 보 위치 링크의 최대 절대 유량 `mesh1d_q1` | 0 m³/s | 0 m³/s |
| 시작·최종 restart의 실제 시각 | 0초, 120초 | 0초, 120초 |

통합자가 두 map을 다시 열어 보 위치(x=500055 m)의 링크를 찾아 위 수치를 재계산했다. 유입량과 저류량의 오차는 사전 기준 0.002 m³ 이하다. 두 실행 모두 원본 입력 지문이 같았고 사본에서 실행했다. 잘못된 입력 19개도 재현기에서 거부를 확인했다.

```powershell
dfm network create examples/network/weir-lateral.json --out <new-inputs>
dfm network validate <new-inputs>/model.mdu
dfm run start <new-inputs>/model.mdu --profile network-structures --route direct --out <new-run> --install <suite>
```

[독립 검증기](../../workflows/verification/verify_network.py)는 제품의 계산값을 정답으로 사용하지 않는다. 재현: `python -m research.workflows.verification.verify_network --case structure_rest --case structure_inflow --native-slot-granted --install <suite> --out <new-folder>`. 독립 기록은 `NET-V-structures-20261104-173154-143dd1d4`, 통합 기록은 `NET-G-structures-coordinator-final-01/verification.json`(SHA-256 `ace5db11ddc1bd54614c738ebf1320679c2756d56e12eef9210b6b1dcad02146`)이다. 원본 경로는 모두 `research/experiments/` 아래다.

이 시험은 보의 월류 곡선, 펌프·수문 제어, 일반 분기망 또는 1D–2D 교환 수지에 대한 검증이 아니다. 분기 유량과 1D–2D 교환은 각각 별도 대조군·수치 기준을 통과해야 한다.
