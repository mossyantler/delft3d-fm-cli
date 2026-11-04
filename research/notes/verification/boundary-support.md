# B10 · 지원점 신호 켜기·끄기와 경계선 함수 변경

`boundary support`는 한 지원점의 수위 신호를 끄거나, 명시적으로 제공한 신호로 켠다. `boundary function-set`은 한 경계선의 **현재 활성 지원점 전부**를 지정한 함수의 신호로 교체한다. 어느 쪽도 단위·시간 원점을 추측하거나 조화성분을 시계열로 자동 환산하지 않는다. 이 범위는 새 EXT에 연결된 2D 수위 경계, 분·m·도의 harmonic 또는 명시적 UTC 원점의 선형 timeseries다.

```powershell
$p = dfm boundary support model.mdu --boundary east --point east_0002 --state disable | ConvertFrom-Json
$p.result.receipt.data_loss
dfm boundary support model.mdu --boundary east --point east_0002 --state disable --apply --expect-sha256 $p.result.input_sha256

# 켜려면 그 점의 전체 신호가 담긴 BC를 제공한다.
dfm boundary support model.mdu --boundary east --point east_0002 --state enable --signal enable-east2.bc
# 함수 변경은 모든 활성 점의 새 신호가 들어 있는 BC로 미리 본다.
dfm boundary function-set model.mdu --boundary east --function timeseries --signals east-linear.bc
```

적용 전에 빠지는 데이터의 바이트 범위·해시·원문을 응답에서 확인할 수 있다. 적용해도 원래 PLI 위치, EXT 참조, 공유 BC의 다른 경계 신호는 유지된다. 마지막 활성점 비활성화나 불완전한 교체 입력은 거부한다.

**실제 엔진이 요구한 수정.** [첫 편집본의 엔진 로그](../../experiments/B10-G-native-02/run-candidate-disable/stdout.log)에서는 비활성 신호를 BC 안에 주석으로 남겼더니, 파일 끝의 주석이 활성 조화성분의 숫자 행으로 읽히면서 초기화가 실패했다. 같은 대조군에서 수동으로 신호 블록을 뺀 모델은 끝까지 계산됐다. 수정본은 폐기한 내용을 응답으로 보관하고 활성 BC에서 해당 블록 전체를 제거한다.

| 48셀 수로에서 한 작업 | 같은 작업의 수동 대조군과 일치한 변수 | 최초 기준 모델 대비 후반 세 관측점의 최대 수위 차이 |
| --- | ---: | ---: |
| 동쪽 두 번째 점 끄기 | 159 | 0.054901 m |
| 두 번째 점 다시 켜기 | 159 | 0 m |
| 동쪽 선을 선형 시계열로 교체 | 159 | 0.041757 m |
| 시계열을 새 조화성분으로 교체 | 159 | 0.033316 m |

[공개 명령과 수동 대조군 8개 실행](../../experiments/B10-G-repaired-native-03/verification.json)에서 120초 history·map, 시작/최종 restart, 변수의 값·자료형·마스크·속성을 대조했다. [재현기](../../workflows/verification/verify_boundary_support_native.py)는 지역별 관측점 ID와 좌표까지 확인한다. 표의 수위 차이는 지정한 합성 수로의 반응이며 다른 수로에서 예상할 수치가 아니다. GUI 지원점 체크박스, 다른 BC 함수·물리량, 복합 경계는 별도다.

[독립 공개 명령 검사 39개](../../experiments/B10-SUPPORT-V-public-repair-frozen-05/independent-summary.json)의 구현 지문을 네이티브 비교 및 배포 wheel과 [최종 대조](../../experiments/B04-B10-G-release-01/verification.json)했다. 설치한 wheel로 지원점을 꺼서 만든 BC도 설치 엔진을 통과한 BC와 바이트 단위로 일치했다.
