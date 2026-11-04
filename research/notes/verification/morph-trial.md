# 유사 이동: 경계 통과량, 저장량, 최종 재시작 상태

**통합 승인 범위:** 합성 수로 두 개에서 각각 이동 모래, 고정 바닥(`MorFac=0`), 운반 비활성(`Bed=0`), 정지 유동을 실행했다. 독립 시험 8건과 별도 통합 재현 8건 모두 지정 시각에 도달했다. 두 수로 모두 같은 한 종류 모래의 소류사 공식(MPM)을 썼으며, 두 번째 수로는 형상·입도·건조밀도·강제력과 모의기간을 달리했다.

| 이동 모래 사례 | 출력 시각 | 단면으로 나간 순질량 | 셀의 건조 저장량 변화 | 전 시각의 열별 수지 잔차 절댓값 합 최댓값 |
| --- | --- | ---: | ---: | ---: |
| 48셀 | 0–300초, 1초 간격 | 36.973368745 kg | −36.973368745 kg | 3.81×10⁻⁹ kg |
| 72셀 | 0–360초, 1초 간격 | 31.346354198 kg | −31.346354199 kg | 5.70×10⁻⁹ kg |

두 형상 모두 단면의 방향을 뒤집으면 누적량 부호도 반대였다. `MorFac=0`은 바닥 갱신을 멈추지만 엔진은 운반량을 계속 기록했다(각각 36.97298, 31.34620 kg). 이 값을 0으로 덮어쓰지 않았다. `Bed=0`과 정지 유동에서는 순유출과 저장량 변화가 모두 0이었다. 통합 재현은 8건 모두 마지막 map과 restart의 실제 시각, 셀 좌표, `FlowElem_bl`(m)·`bodsed`(kg/m²) 값을 대조했다. 각 형상에서 `morph compare`로 이동/고정, 이동/운반 비활성 두 쌍도 확인했다. 기본절점 관계·`Morphopol` 등 엔진 경고는 원본 manifest에 남아 있다. 부유사, 혼합 입도와 현장 검보정은 이 사례의 범위 밖이다.

[고정 입력](../../assets/morph-exchange/)과 다음 두 명령으로 새 폴더에서 재현한다. 첫 명령은 8개 입력을 작성하고, 두 번째 명령만 엔진을 시작한다.

```powershell
.venv/Scripts/python.exe -m research.workflows.verification.verify_morph_exchange prepare --active-spec research/assets/morph-exchange/active.spec.json --heldout-spec research/assets/morph-exchange/held-out.spec.json --out <new-inputs>
.venv/Scripts/python.exe -m research.workflows.verification.verify_morph_workflow --prepared <new-inputs> --install <suite-root> --out <new-runs> --native-slot-granted
```

독립 기록은 `MORPH-V-exchange-native-slot44-20261104-01`, 통합 기록은 `MORPH-G-exchange-final-02`이다. [검수 지문](../../catalog/module-gates.json). 첫 통합 기록 `MORPH-G-exchange-final-01`은 작성 전용 `morph-spec.json`도 FM 작업 폴더에서 찾으려 한 검증기 오류다. 수정 후 작성 원본 전체와 실제 엔진 입력 11파일을 따로 대조했다.

## 초기 실패와 단일 사례 측정

공개 `morph create`와 `run start --profile morph`로 48셀 수로의 이동 모래·고정 바닥(MorFac=0)·정지 유동·이동 비활성(Bed=0)을 따로 실행했다. 첫 시험 `MORPH-V-native-20261104-01`에서는 네 엔진 모두 종료 코드 0과 60초 출력을 남겼지만 **네 실행 모두 물리량 검증에 실패했다**.

이동 사례에서 바닥고 최대 변화가 0.000728085 m였고 다른 세 사례에서 변화가 0이었다. 그러나 원본 map의 시작 바닥은 작성한 둔덕이 아니라 전 셀 **−5 m**였다. 제품 검증기와 독립 검증기 모두 이를 잡아냈다. 입출력 대조와 고정 엔진 소스 조사에서 원인은 `BedlevType=1` 셀 바닥고를 읽을 때 참조하는 `mesh2d_face_z`의 `_FillValue` 속성 누락으로 좁혀졌다. 초기 건조 유사량은 1 m × 1,600 kg/m³ = 1,600 kg/m²로, 입자 밀도 2,650 kg/m³와 구별했다. 세부 근거는 `MORPH-V-native-diagnosis-20261104-01/verification.json`에 보존했다.

이동 여부만으로 유사 수지가 맞는다고 판정하지 않는다. 수정본은 실제 엔진에서 작성한 초기 바닥 형상을 먼저 확인한 뒤, 경계 물질량·셀 저장량·운반량·최종 restart를 독립 대조해야 한다. 이 사례와 달리 M3·M4·3층 수로 및 검수한 1D–2D 수로는 `BedlevType=3`이며, 각 원본 map에서 의도한 초기 바닥을 다시 확인했다. [독립 재현기](../../workflows/verification/verify_morph_native.py)는 명시적 native 슬롯 없이 엔진을 시작하지 않는다.

두 번째 독립 시험(`MORPH-V-native-20261104-02`)에서 명시적 `_FillValue`가 있는 격자를 쓰자 실제 초기 바닥은 −2.99659~−2.80341 m였고 자료의 둔덕과 일치했다. 고정 바닥·정지 유동·운반 비활성 대조군은 통과했다. 이동 사례의 60초 기준 침식은 최대 0.000637894 m였지만 최대 퇴적은 0.000008566 m로, 사전 기준 0.000010 m에 못 미쳤다. 이 실행과 허용오차를 보존하고 새 형상·구동 조건은 별도 입력으로 시험한다.

새 300초 이동 사례 `MORPH-G-counter-pilot-01`에서는 입력에 방향이 있는 15개 단면을 추가해 경계 운반량을 직접 측정했다. 원본 history의 `cross_section_bedload_sediment_transport`와 모래 분획 누적값(kg)이 같았고, 같은 단면을 뒤집으면 부호가 반대였다. 원본 map의 셀당 `mesh2d_bodsed`(kg/m²) 변화에 48개 셀 면적을 각각 곱해 더하면 저장량은 **36.97336874475 kg 감소**했다. 서쪽 순유출은 0, 동쪽 순유출은 **36.97336874462 kg**였다. 301개 출력 시각 전체에서 저장량 변화와 순유출을 합한 최대 절대 잔차는 `7.89e-10 kg` 이하였다. 입력 지문과 실제 map/history 지문·수치는 `plan.json`, `raw-budget.json`에 남겼다. 이는 하나의 이동 사례로, 다른 형상과 재료에서 같은 방법이 맞는지와 대조군 세 종류는 독립 검수 대상이다.
