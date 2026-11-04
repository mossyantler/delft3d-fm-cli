# P01–P04: 콘솔에서 프로젝트 저장·재열기·내보내기

2026.02 OpenHMWQ의 **단일 FlowFM f34 복사본**에서 공개 CLI와 실제 `DeltaShell.Console.exe`의 파일을 대조했다. [E001/E002](../replay/export-experiment.md)는 GUI 프로세스에서 스크립트로 만든 프로젝트가 출발점이고, 이 기록은 그 프로젝트와 내보낸 MDU를 **CLI**에서 사용한 결과다. GUI 클릭과 solver 실행은 포함하지 않았다.

| 호출 | 읽는 파일 → 새 폴더에 쓰는 파일 | 판정 근거 |
| --- | --- | --- |
| `dfm project export PROJECT --install SUITE --out NEW` | 복사된 `.dsproj` + 동반 폴더 → `model/model.mdu`와 참조 9파일, `bridge-manifest.json` | 기존 GUI 프로젝트에서 내보낸 결과는 비교 기준과 비MDU 9파일의 바이트 및 MDU 키값이 같았다. 원 프로젝트는 그대로였다. |
| `dfm project import MDU --install SUITE --out NEW` | f34 MDU와 참조 9파일 → `project/model.dsproj`, `project/model.dsproj_data/`, 별도 엔진 입력 세트와 manifest | 가져오기 전 복사본의 `L1_0001` 750분 진폭을 **1.625 m**로 바꿨다. 새 DB의 SQLite 무결성 검사 결과는 `ok`(92개 테이블), 동반 입력은 10파일이었다. |
| 새 프로젝트를 다시 `project export` | 바로 위에서 저장한 DB + 동반 폴더 → 다른 폴더의 MDU와 참조 9파일 | 수정한 진폭까지 BC 값이 일치했고 MDU 키값의 추가·삭제·변경은 없었다. 비MDU 파일 중 **8개**가 바이트 일치했다. BC까지 같은 바이트로 보존한다는 뜻은 아니다. 저장 프로젝트는 이 작업으로 바뀌지 않았다. |

동반 폴더 누락, 참조 파일 누락, 이미 있는 출력 폴더, 콘솔 시간 초과도 구분해 거부했다. 성공은 종료 코드만으로 판단하지 않고 실행별 완료 표식·산출물·참조를 확인한다. [재현기](../../workflows/verification/verify_project.py)를 저장소 루트에서 실행한다.

```powershell
.venv/Scripts/python.exe -m research.workflows.verification.verify_project --baseline research/experiments/E001-E002-replay-20261103 --install '<suite-root>' --out '<new-folder>' --console-slot-granted
```

독립 기록은 `research/experiments/P-BRIDGE-V-native-20261104-165532-84b26434/verification.json`, 최종 대조 기록은 `research/experiments/P-BRIDGE-G-coordinator-final-01/verification.json` (SHA-256 `3372da1d3be0548bb042c4b07c20fb525873868857fba95cfb1dc6c7f19e40e0`)이다. 다중 모델 프로젝트, 임의 스크립트·외부 경로, GUI Run·Stop 동작, 계산 결과의 동등성은 이 실험으로 확인하지 않았다.
