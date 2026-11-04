# B06 · 취·방류의 유량과 염분 입력

GUI에서 물을 넣는 점 하나를 그리는 작업과, 두 점을 연결해 물을 옮기는 작업은 구분해야 한다. [작업표 B06](../collection/gui-workflows.md#source-sink)에는 GUI 매뉴얼과 소스 경로가 있다. 아래는 손으로 만든 입력을 설치 FM에서 실행한 결과다. GUI나 콘솔이 같은 파일을 내보낸다는 증거는 아니다.

**#215 (2026-11-05).** 48셀의 닫힌 수로에 유량 0.1 m³/s를 120초간 지정했다. 초기 염분은 10 ppt, 물의 부피는 14,400 m³다. 중립 대조군만 유량을 0으로 뒀다. 입력은 `model.mdu → sources.ext → source.bc`이고, 위치는 EXT 좌표 또는 별도 PLI다. 아래 수치는 마스크 없는 48개 셀의 map 부피와 염분을 읽어 `Σ(volume × salinity)`의 처음과 끝을 뺀 값이다. 단위는 ppt·m³이며 질량(kg)이 아니다.

| 위치·입력 | 실제 부피 변화 (m³) | 염분×부피 변화 (ppt·m³) | 판독 결과 |
| --- | ---: | ---: | --- |
| 단일점, EXT 좌표, `salinityDelta` 5 / 15 | 각각 +12.00003 | +60.00043 / +180.00018 | history의 지정 염분도 각각 5 / 15. 두 입력을 구분했다. |
| 단일점, EXT 좌표, `salinity` 5 / 15 / 키 생략 | 각각 +12.00003 | 세 경우 모두 +0.00027 | 실제 누적 유량은 12 m³지만 history의 지정 염분은 모두 0. 이 세 입력에서 접미사 없는 키의 값에 따른 염분 반응은 없었다. |
| 연결된 두 점, EXT 좌표, `salinityDelta` 5 | −0.00003 | +59.99974 | 영역 안에서 물이 이동했다. 두 점의 15 ppt 좌표 대조군은 이 실행에 없다. |
| 중립 단일점, 유량 0, `salinityDelta` 5 | 0 | 0 | 지정 염분이 history에 있어도 유량이 0이면 총량은 바뀌지 않았다. |
| 별도 PLI를 참조한 여섯 입력 | — | — | 모두 초기화 중 종료 코드 1. 첫 줄이 `#`인 이 PLI에서 엔진은 행·열 수를 찾다가 블록 이름을 읽었다. PLI 형식 전체에 대한 판정은 보류한다. |

7개 완료 사례에서 history와 map의 0–120초 121개 시각, 처음·끝 restart의 시각을 직접 대조했다. 실패 6개를 포함한 13개 작업은 원래 Job과 26개 멤버의 종료 기록이 남았다. [사전 수용 기준](../../experiments/B06-SOURCES-V-preflight-01/predeclared.json), [사례별 원본 기록](../../experiments/B06-SOURCES-RUNNER-I-native-215-01/verification.json), [좌표·PLI 입력 원본](../../experiments/B06-SOURCES-V-inputs-03/input-manifest.json), [집계와 종료 근거](../../experiments/B06-SOURCES-G215-readback-01/verification.json), [원자료를 다시 읽는 코드](../../experiments/B06-SOURCES-G215-readback-01/review.py). [첫 독립 검증](../../experiments/B06-SOURCES-V-native-215-01/verification.json)은 성공 사례에서도 관측점 식별자의 마스크 처리에서 멈췄다. [관측점 문자열 처리 수정 후 독립 재판독](../../experiments/B06-SOURCES-V-native-215-schema-followup-03/verification.json)에서도 접미사 없는 5/15 두 사례는 지정한 염분 반응을 통과하지 못했다. PLI 여섯 건을 포함해 전체 판정은 미승인이다.

**제품 판정:** 아래 #225를 통과한 `source inspect/add/set/forcing-create`를 개발판에 통합했다. 작성은 inline XY 한 점/두 점, 2D UTC, 운동량 면적 0, 선형 discharge/salinityDelta BC에 한정한다. 전용 공개 실행 프로필, PLI 작성과 GUI의 무변경·변경 export 대조는 별도 후속 작업이다.

공개 편집 후보 1은 실제 오류를 발견해 병합을 보류했다. [별도 복사본에 대한 명령 검수](../../experiments/B06-PUBLIC-G-input-text-01/review.json)에서 JSON 이름의 `\\u0000`을 넣은 `source set`이 성공을 반환했고, [적용 결과](../../experiments/B06-PUBLIC-G-input-text-01/nul-apply.json)에는 EXT에 실제 NUL 바이트가 들어갔다. 수정본은 이 입력을 쓰기 전에 거부하고 원래 EXT·다른 입력 전체를 보존해야 한다. [후보 2의 설치 명령 독립 검수](../../experiments/B06-V-public-install-results-01/verification.json)는 312회 호출·158개 검사를 통과했다. 심볼릭 링크 세 조건은 이 Windows 사용자의 생성 권한이 없어 미검증으로 남겼다. [통합자의 별도 21회 명령 검사](../../experiments/B06-PUBLIC-G-rev02-01/verification.json)에서도 잘못된 텍스트 9종의 미리보기·적용을 거부하고 한글 이름만 정확히 바꿨다. [공개 명령으로 준비한 여섯 입력](../../experiments/B06-PUBLIC-G-inputs-01/input-manifest.json)은 무변경·기존 연결 수정·새 취방류 추가를 단일점과 두 점에 각각 적용한 것이다. 이 여섯 입력의 계산 결과는 아래 #225에서 별도로 판정했다.

<a id="native-223"></a>

## #223 · PLI 판독과 성분 키의 분리 대조

실패했던 PLI 여섯 개에서 맨 앞의 `# B06…` 주석 한 줄만 제거했다. 좌표·순서·블록 이름은 보존했다. 두 점을 연결한 네 사례는 같은 좌표를 EXT 안에 직접 적어 표현만 비교했다. 유량·초기 조건·120초 종료 시각은 #215와 같다. PLI 내부 이름 `not-the-source-ID`와 EXT/BC의 연결 ID `intake-A.1`을 다르게 유지했다. **열 사례 모두 실제 120초에 도달했다.** 따라서 이전 초기화 실패를 PLI 위치 표현 전체의 미지원으로 일반화할 수 없다.

| 대조 | 부피 변화 (m³) | 염분×부피 변화 (ppt·m³) | 확인한 범위 |
| --- | ---: | ---: | --- |
| 단일점 PLI, `salinityDelta` 5 | +12.00003 | +60.00043 | #215의 같은 EXT 좌표 단일점과 history/map/초기·최종 restart의 변수·마스크가 일치 |
| 연결 쌍 PLI, `salinityDelta` 0 / 5 / 15 | 각각 −0.00003 | −0.00031 / +59.99974 / +179.99982 | 5→15 변경의 차이는 +120.00008. 유량을 고정한 성분 입력 차이를 구분 |
| 연결 쌍 EXT 좌표, `salinityDelta` 5 / 15 | 각각 −0.00003 | +59.99974 / +179.99982 | 같은 값의 PLI 사례와 네 데이터셋의 변수·마스크가 일치 |
| 연결 쌍 PLI/EXT 좌표, `salinity` 5 / 15 | 네 사례 모두 −0.00003 | 네 사례 모두 −0.00031 | 지정 염분 증분은 0. 5/15 두 경우와 `salinityDelta=0`의 출력이 같음. 요청한 농도 효과의 검증은 **실패** |

각 사례에서 history/map의 0–120초 121개 시각, restart의 0·120초, 유량 0.1 m³/s와 누적 12 m³를 원자료로 확인했다. 성분·수량 예측은 실행 전에 고정했고, 절대 농도 키의 실패를 성공 판정으로 바꾸지 않았다. 출력의 염분 단위 `1e-3`와 입력 ppt, 부피 m³를 명시적으로 대조했다. 총량 대조는 과학적 보정이나 다른 지형·수직 분포의 검증을 뜻하지 않는다.

보존 조건은 **PLI 머리 주석 한 줄 외 바이트 유지**, 위치 표현을 바꿀 때 **취수→방류의 좌표 순서 유지**, EXT ID와 BC Name의 정확한 연결, 물리량·단위·시간 원점·비대상 신호 유지다. PLI 이름에 지원점 접미사를 붙여 BC 이름을 추정하거나 `salinity`를 `salinityDelta`로 자동 치환하지 않는다. PLI 작성은 별도 제품 검수 전까지 지원하지 않는다. GUI·콘솔이 실제로 고르는 위치 표현과 성분 키는 여전히 미측정이다.

[수동 입력과 원본 해시](../../experiments/B06-V-PLI-inputs-01/input-manifest.json), [사전 기준](../../experiments/B06-V-PLI-stage-01/predeclared.json), [실제 실행 10건](../../experiments/B06-PLI-RUNNER-I-native-223-01/runs.json), [독립 변수·총량 대조](../../experiments/B06-V-PLI-results223-01/verification.json), [통합자의 동일 판독 재현](../../experiments/B06-V-PLI-results223-G01/verification.json), [별도 총량 계산](../../experiments/B06-PLI-G-readback-223-01/verification.json). 원래 Job 10개·멤버 20개의 종료와 collector 종료는 [원본 핸들 기록 재검수](../../experiments/B06-PLI-G-readback-223-01/terminal-verification.json)로 확인했다. 첫 실행기 후보는 손상된 종료 증거를 받아들여 거부했고, 수정본의 독립 37개와 작성자 27개 검사를 통과한 뒤에만 실행했다. 프로세스 종료 확인과 물리량 판정은 별개다. 실행 뒤 독립 검증자가 [추가 오류 두 건](../../experiments/B06-PLI-RUNNER-V-20261105-01/rejected-candidate-02.json)을 찾았다. 실행 당시 판정기는 멤버 이벤트에서 원시 알림으로 가는 연결만 검사하고, 반대로 남는 알림은 거부하지 않았다. #223의 원본을 새 판정기로 다시 읽은 [추가 검수](../../experiments/B06-PLI-G-readback-223-01/bidirectional-verification.json)에서 40개 프로세스 알림과 40개 식별 이벤트가 일대일로 대응했고 열 Job 모두 통과했다. 이는 사후 증거 검사이며, 실행에 새 판정기를 사용했다는 뜻이 아니다. 후속 실행은 수정본을 사용한다.

<a id="public-225"></a>

## #225 · 공개 입력 명령 → 실제 계산 → 수동 기준 대조

설치한 wheel `eedd753e…`의 명령으로 여섯 입력을 만들었다. 단일점과 연결 쌍마다 무변경 편집, 새 15 ppt BC에 기존 객체 연결, 빈 SourceSink 목록에 같은 객체 추가를 각각 수행했다. 마지막 경우에만 실험 준비 과정에서 복사본의 기존 블록 하나를 제거했고, 그 바이트도 보관했다. 이후 입력 작성은 실제 공개 `dfm` 명령으로 수행했다. 새 BC와 EXT 연결은 서로 다른 미리보기·해시·적용 절차다.

| 사례 | 실제 부피 변화 (m³) | 염분×부피 변화 (ppt·m³) | 수동 기준과 일치한 변수 |
| --- | ---: | ---: | ---: |
| 단일점 무변경 5 | +12.00003 | +60.00043 | 170 |
| 단일점 기존 연결 수정 15 / 새 객체 추가 15 | 각각 +12.00003 | 각각 +180.00018 | 각각 170 |
| 연결 쌍 무변경 5 | −0.00003 | +59.99974 | 170 |
| 연결 쌍 기존 연결 수정 15 / 새 객체 추가 15 | 각각 −0.00003 | 각각 +179.99982 | 각각 170 |

여섯 사례 모두 history/map의 0–120초 121개 시각과 restart의 0·120초를 확인했다. 변수 집합·차원·자료형·단위·변수 속성·마스크와 모든 유효값을 수동 기준의 네 데이터셋과 대조했다. 독립 판독기는 전역 생성 시각·history·UUID 차이만 출처 정보로 따로 남기며, 그 외 속성 차이는 허용하지 않았다. 15 입력을 새로 추가한 결과와 기존 객체를 수정한 결과도 일치했다. 기준값 5와의 총량 차이 및 수신 지점의 염분 반응을 포함한 독립 비교 12건을 통과했다.

무변경은 원본 전체 바이트가 같고, 수정은 EXT 연결 두 값과 새 `replacement.bc`만 달라졌다. 격자·관측점·단면·MDU와 기존 `source.bc`는 보존됐다. 새 BC에 연결된 네 사례에서 기존 BC는 비활성 동반 자료로 유지했다. 실제 엔진 의존 파일은 사례당 6개, 보존한 입력은 총 40개다. 원래 Job 6개와 멤버 핸들 12개, 수집기의 종료도 원본 기록으로 확인했다.

[공개 입력과 명령 결과](../../experiments/B06-PUBLIC-G-inputs-01/input-manifest.json), [실행 전 기준](../../experiments/B06-V-public-install-science-01/predeclared.json), [실제 실행](../../experiments/B06-PUBLIC-RUNNER-I-native-225-01/runs.json), [독립 판독](../../experiments/B06-V-public-install-native225-01/verification.json), [같은 판독기의 통합자 재현](../../experiments/B06-V-public-install-native225-G01/verification.json), [통합자의 별도 원자료 계산](../../experiments/B06-PUBLIC-G-native-readback-01/results225-01/verification.json).

네 파일 명령과 보존·오류·오래된 미리보기·파일 저장 실패를 검사하는 portable 테스트 30개를 통합했다. 제품 파일 191개는 검증된 wheel과 정확히 같으며, 명령은 총 98개다. [통합 기록](../../experiments/B06-PUBLIC-G-merge-01/verification.json). [전체 회귀 검사](../../experiments/B06-PUBLIC-G-merge-01/regression.json)는 1,697건 중 1,661건 통과, 36건 건너뜀, 실패·오류 0건이다. 건너뛴 항목은 선택 `geo` 의존성이 필요한 33건과 Windows 심볼릭 링크 생성 권한이 필요한 3건이다. [사용 예제](../../../examples/source_sink/README.md).

이 결과는 연구 실행기를 통한 한 격자의 짧은 직렬 검증이다. 전용 `run start` 프로필, 다른 지형·유량 부호·수직 범위·성분, GUI 내보내기와 과학적 보정을 승인하지 않는다.

