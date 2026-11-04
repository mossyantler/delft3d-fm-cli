# 3D 염분: 세 층의 위치와 경계 신호를 따로 검증한 수로

<a id="portable-b13"></a>

**새 체크아웃에서 B13 대조 입력 준비.** [모델 명세](../../../examples/layers/vertical-cell.json)와 [기대 바이트·해시](../../../examples/layers/vertical-cell.expected.json)를 사용한다. `run` 의존성을 갖춘 별도 venv에 로컬 wheel을 설치하고, 그 설치를 마친 시점에 원본 wheel과 생성된 `dfm.exe`의 SHA-256을 기록해 둔다. 이후 검수 때 임의 실행 파일의 현재 해시를 새 기준으로 채택하지 않는다. 세 복사본을 준비하는 명령은 다음과 같다.

```powershell
python -m research.workflows.replay.vertical_boundary_fixture prepare --dfm $installedDfm --expect-wheel-sha256 $wheelHash --expect-launcher-sha256 $launcherHash --out B13-new
```

출력은 새 폴더여야 한다. `cases/baseline`, `cases/manual`, `cases/public`에 각각 엔진 입력 9개를 쓴다. 수동 대조군과 CLI 편집본은 모두 같고 기준군과는 BC의 두 바이트짜리 값 `20` → `22`에서 마지막 한 바이트만 다르다. [독립 검수](../../catalog/vertical-boundary-portability.json)는 이전 재현기가 없는 체크아웃의 실제 CLI 호출과 잘못된 설치·출력 경로 25건을 대조했다. 준비 단계는 엔진을 시작하지 않는다. 아래 20초 계산의 증거와 당시의 `vertical_boundary_cases` 진입점은 그대로 보존했다.

<a id="b13"></a>

**B13 · 기존 3D 경계에서 한 점·한 시각·한 높이만 변경.** [공개 명령 예시](../../../README.md)로 `west_0001`의 20초, `percBed=0.4` 값을 20→22 ppt로 바꿨다. 높이를 열 순서로 추정하지 않고 `VertPositionIndex=2`인 열을 찾는다. [실제 입력 대조](../../experiments/B13-EDIT-G-example-01/verification.json)에서 `boundaries.bc` 35행의 바이트 [636,638)만 달라졌다. 다른 서쪽 점, 동쪽 점, 다른 높이·시각과 나머지 엔진 입력 8개는 같았다. 작성 명세·출처 파일도 다시 쓰지 않았다. 기존 두 지점의 여러 값을 함께 바꾼 시험은 아래에 별도로 기록한다.

[무변경·수동·CLI 세 실행](../../experiments/B13-RUN-G-native-203-01/runs.json) 모두 실제 직접 FM으로 20초에 도달했다. [독립 판독](../../experiments/B13-RUN-V-native203-20261105-01/verification.json)에서 history/map은 0·10·20초, restart는 0·20초였다. 수동 편집과 CLI 편집의 4개 데이터셋에서 190개 변수(66+46+39+39)의 자료·마스크와 변수 속성이 같았다. 전역 생성 시각 등 실행 출처는 별도로 비교했다. 이는 출력 파일 전체의 바이트가 같다는 의미가 아니다.

| 20초 관측 염분 차이: 변경군 − 기준군 (출력 단위 `1e-3`) | 아래층 | 중간층 | 위층 |
| --- | ---: | ---: | ---: |
| near_west | +0.0146923 | +0.1300392 | +0.0407743 |
| centre | 0 | +0.00000381 | +0.00000191 |

세 실행 모두 FM `1.2.184.Unknown`에서 같은 경고가 남았다. MDU의 `vertadvtypsal`은 폐기 예정 키이고 엔진은 입력망에서 면 중심의 x좌표를 읽지 못했다고 보고했다. 작성한 망에는 절점 좌표와 면 연결 정보가 있다. 실제 출력의 좌표·층 위치는 독립 판독했지만, 수동/CLI 결과가 같다는 이유로 이 입력 경고를 지우지 않는다. [설치본 지문과 사례별 경고](../../catalog/vertical-boundary-gate.json).

경계 입력이 2 ppt 변해도 관측층의 염분이 그대로 2만큼 변하지 않는다. 위 값은 이 20초 수로의 결과다. 임의의 성층 모델, GUI 편집기의 높이 표시·저장 방식과의 동등성, 현장 모델 검정까지 확인한 것은 아니다. [실행 감시 기록](../../experiments/B13-RUN-G-supervision-203-01/supervision.json)은 바깥 연구 Job의 26개 멤버 전부에서 보관 핸들로 종료를 확인했다. 각 안쪽 layers Job의 핸들 닫기까지 기록했다는 뜻은 아니다.

같은 합성 수로를 두 번 만들고 서쪽 경계의 `t3D` 염분 값만 바꿨다. 두 사례 모두 실제 2026.02 OpenHMWQ의 direct FM을 실행했다. 초기 수위는 0.5 m이고 층 두께 비율은 바닥부터 0.2, 0.3, 0.5다. 초기 염분은 z=−6 m의 30 ppt에서 z=0.5 m의 5 ppt까지 선형으로 분포한다.

| 검수 | 관측한 결과 |
| --- | --- |
| 입력 보존 | 기준·변경 모델에서 엔진에 주는 파일 중 `boundaries.bc`만 달랐다. 바뀐 신호는 서쪽 경계의 수직 염분 프로필이다. |
| 수직 출력과 시계 | history의 `salinity(time, station, laydim)`은 3시각 × 2지점 × 3층이다. 독립 검증기가 map의 실제 셀과 층 중심·경계 높이, 초기 염분을 따로 계산해 대조했다. history/map은 0·10·20초, 최종 restart는 20초다. |
| 경계 변경의 효과 | 서쪽에 가까운 관측점에서 마지막 시각의 변화량은 바닥층부터 **+0.182751, +0.295036, +0.079561 ppt**였다. 통합자가 두 원본 history를 다시 읽어 최대 절대 차이 0.29503631591796875 ppt를 확인했다. 미리 정한 반응 기준은 0.0002 ppt였다. |

첫 시험에서 검증기가 고정 길이 관측점 이름의 끝을 채운 NUL을 결측으로 잘못 해석했다. 원본 `station_id`는 두 지점을 구별했다. 이름 내부의 손상과 끝 패딩을 구별한 뒤, 같은 물리량 허용오차로 새 기준군·변경군을 재실행했다. 첫 시험은 `3D-V-native-20261104-01`, 수정 뒤 독립 시험은 `3D-V-native-20261104-02`다. 통합 시험은 `research/experiments/3D-G-coordinator-final-01/verification.json`(SHA-256 `a762354e8382f1793801f73e4232c8022ff01709b56ddac2bf06cde60ccf7199`)이다.

```powershell
dfm layers create examples/layers/vertical-cell.json --out <new-inputs>
dfm layers inspect <new-inputs>/model.mdu
dfm run start <new-inputs>/model.mdu --profile layers --route direct --install <suite> --out <new-run>
dfm layers verify <new-run>/model/model.mdu
```

승인 범위는 이 3층 sigma 수로의 초기장·수위 및 염분 경계·출력이다. z층, 온도, 장기 성층 수송, 다른 좌표계의 현장 보정은 검증하지 않았다. [독립 네이티브 재현기](../../workflows/verification/verify_layers_native.py): `python -m research.workflows.verification.verify_layers_native --out <new-folder> --install <suite> --native-slot-granted`.
