# G12 · 유량 관측 단면을 반대 방향으로 그리면 무엇이 달라지는가

대상은 f34의 유량 관측 단면 `Entrance`다. 하천의 깊이·폭을 정하는 1D 단면이나 좌표계 파일이 아니다. FM은 MDU의 `CrsFile`이 가리키는 [PLI를 읽고](https://github.com/Deltares/Delft3D/blob/5a4649830b1e5072caf019fb4850bbdefd9ad431/src/engines_gpl/dflowfm/packages/dflowfm_kernel/src/dflowfm_kernel/prepost/m_monitoring_crosssections.f90#L294) [흐름 링크의 방향](https://github.com/Deltares/Delft3D/blob/5a4649830b1e5072caf019fb4850bbdefd9ad431/src/engines_gpl/dflowfm/packages/dflowfm_kernel/src/dflowfm_kernel/prepost/m_monitoring_crosssections.f90#L35)을 반영한다. 매뉴얼의 GUI 조작과 이 파일 경로의 관계는 [G12 작업표](../collection/gui-workflows.md#geometry)에 기록했다.

| 비교 대상 | 변경 결과를 보기 전에 정한 기준 |
| --- | --- |
| 입력 10개 | `f34_crs.pli` 중 `Entrance`의 좌표 8행만 역순. 이름·행 수·각 좌표의 표기·다른 단면 및 나머지 입력 9개 보존 |
| history의 형상 | 같은 단면 이름에 대해 해당 좌표 배열만 역순. 다른 단면의 좌표와 ID 보존 |
| history의 물리량 | 11개 시각에서 지정 단면의 유량(m³/s)·누적 통과 체적(m³)·평균 유속(m/s)은 부호 반전, 단면적(m²)은 유지. 0이 아닌 값의 부호를 별도로 검사하고 float32 저장값 기준 2 ULP 이내. 다른 관측점·단면은 그대로 |
| map·restart | 기준군과 변경군 모두 600초에 도달하고, map과 0초·600초 restart는 대응 파일끼리 변수 값을 대조. 단면 관측을 바꿔 수리 상태가 달라지면 실패 |

[기준군만 보고 고정한 판정과 지문](../../experiments/G12-ORI-V-predeclared-20261105-01/predeclared.json), [독립 검증기의 사전 검사](../../experiments/G12-ORI-V-predeclared-20261105-01/readiness.json). GUI에서 직접 그리거나 뒤집어 내보낸 파일은 아직 확인하지 않았다.

**설치 엔진 결과:** [무변경·반전 두 실행](../../experiments/G12-ORI-I-native-159-02/slot-159/verification.json)이 모두 600초에 도달했고 소유 프로세스가 종료됐다. [고정한 독립 검증기로 원출력을 대조](../../experiments/G12-ORI-G-159-01/verification.json)했다. 600초의 유량은 **+45.723354 → −45.723354 m³/s**, 누적량은 **+13,380.925781 → −13,380.925781 m³**였고 단면적은 두 실행 모두 **37,106.859375 m²**였다. 세 부호 있는 변수와 단면적은 11개 시각 모두 예상값과 저장 정밀도에서 정확히 같았다. 다른 단면·관측점, map과 두 restart의 비대상 값도 같았다. [변수별 수치와 원자료 해시](../../catalog/section-orientation-gate.json). 이 검수는 기존 PLI를 직접 바꾼 사례이며 공개 편집기 검수와 구분한다.
