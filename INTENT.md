> **에이전트는 이 문서 대신 [[COORDINATOR]]를 먼저 읽는다.** COORDINATOR.md는 이 문서의 에이전트용 요약본이며, 규칙이 충돌하면 이 문서가 우선한다. 이 문서를 수정하면 COORDINATOR.md도 함께 확인한다.

# Herdr + Beads 기반 멀티에이전트 개발 시스템 개선 계획

## 1. 프로젝트 목표

현재 `delft3d-fm-cli` 프로젝트에서 운영하는 멀티에이전트 개발 시스템을 최적화한다.

기존 시스템은 다음 구조를 따른다.

**DAG 공정표 → 구현(I) → 독립 검증(V) → 통합 검수(G)**

이 구조의 독립 검증과 승인 체계를 유지하면서 다음 문제를 개선한다.

1. 공정표를 Markdown 전체 문서에 의존하여 관리하는 문제
    
2. 오케스트레이터가 전체 공정표와 긴 작업 기록을 반복적으로 읽는 문제
    
3. 여러 에이전트가 동시에 작업할 때 발생하는 파일·Git·실행 자원 충돌
    
4. 작업 상태, 선행 조건, 완료 기준이 서로 불일치하는 문제
    
5. 에이전트별 작업 컨텍스트가 과도하게 커지는 문제
    
6. 구현과 검증 과정에서 발생하는 불필요한 LLM 호출
    
7. 작업 중단 및 재개 시 상태를 복원하기 어려운 문제
    
8. 역할별 모델 배정과 토큰 소비를 최적화하기 어려운 문제
    

**최종 목표는 최소한의 토큰 소비로, 여러 에이전트가 충돌 없이 병렬 작업하고, 검증된 결과만 다음 공정에 전달하는 개발 시스템을 구축하는 것이다.**

---

## 2. 적용 대상과 기본 원칙

### 2.1 대상 프로젝트

- 저장소: [https://github.com/mossyantler/delft3d-fm-cli](https://github.com/mossyantler/delft3d-fm-cli)
    
- 에이전트 실행 환경: Herdr
    
- 코딩 에이전트: Codex 및 Claude Code
    
- 기존 공정표: `DELIVERY.md`
    
- 개발 규칙: `AGENTS.md`
    
- 작업 재개 정보: `RESUME.md`
    
- 검증 자료: `research/notes/verification/`, `research/experiments/`
    
- 공정표 관리 시스템: Beads (`bd` CLI)
    

현재 저장소와 Herdr의 실제 실행 상태를 확인한 후 작업한다.

2026년 11월 6일 설계 시점에 확인된 저장소 기록에서는 `SHORT-CLOSE` 공용 종료 처리의 제품 통합이 승인된 상태다. B06, B14, S07, G15, G18 등에는 별도 검증 또는 통합 절차가 남아 있다.

이 기록을 고정된 현재 상태로 가정하지 말고, 실행 직전 최신 공정표와 승인 근거를 다시 대조한다.

### 2.2 변경하지 않을 사항

- 기존 Herdr 실행 환경
    
- 기존 I/V/G 독립 검증 체계
    
- Delft3D Native 실행에 대한 승인 및 자원 소유권 규칙
    
- 기존 검증 결과와 체크포인트
    
- 공용 Git 작업의 중앙 관리 원칙
    
- 승인된 제품 코드 및 기존 회귀 테스트
    

새로운 시스템 도입을 이유로 과거 작업을 재실행하거나, 미승인 코드를 자동 병합하지 않는다.

---

## 3. 최종 시스템 아키텍처

### 3.1 채택할 구성요소

|구성요소|담당 역할|
|---|---|
|Beads|작업 그래프, 의존성, 진행 상태, 작업 소유권|
|Herdr|에이전트 세션 실행, 관리, 작업 분배|
|Coordinator Agent|공정표 조회, 작업 할당, 모델 선택, 충돌 검사|
|Codex / Claude Code|구현, 독립 검증, 오류 분석, 통합 판단|
|Git Worktree|작업별 코드 변경 공간 격리|
|Python Validation Gate|계약·테스트·검증 근거의 결정론적 검사|
|GitHub|코드 버전, Commit, 변경 이력|
|Artifact Storage|실험 결과, 원시 로그, 검증 영수증 보존|

### 3.2 초기에는 도입하지 않을 시스템

- Dagu
    
- LangGraph
    
- 별도의 외부 Coordinator 서버
    
- 별도 SQLite 작업 데이터베이스
    
- Langfuse
    
- 새로운 커스텀 Web GUI
    

Beads는 기존 Herdr 내부에서 CLI로 사용한다.

초기에는 새 인프라를 최소화한다. 이후 실측 결과로 필요성이 확인된 구성요소만 추가한다.

### 3.3 핵심 역할 구분

**Beads는 무엇을 해야 하는지 관리한다.**

**Herdr는 어떤 에이전트가 작업을 실행하는지 관리한다.**

**Git Worktree는 각 에이전트의 코드 변경을 격리한다.**

**Validation Gate는 완료 조건을 확인한다.**

**Integrator는 최종 승인 여부를 결정한다.**

GitHub와 Artifact 저장소는 그 판단의 재현 가능한 근거를 보관한다.

이 책임을 서로 중복시키지 않는다.

---

## 4. Beads 기반 공정표 관리

### 4.1 공정표의 Single Source of Truth

활성 작업의 상태와 의존성은 Beads를 기준으로 관리한다.

`DELIVERY.md`는 기존 연구·개발·승인 기록을 보존하는 문서로 유지한다.

새 공정 관리 시스템이 안정화된 이후에는 Beads 상태로부터 진행 현황 보고서를 생성하는 방식을 검토한다.

동일한 작업 상태를 Beads와 Markdown에서 독립적으로 수정하지 않는다.

### 4.2 작업 계층 구조

각 기능을 다음 계층으로 나눈다.

**Epic — 기능 단위**

예시: B06 Source/Sink

**Task — 구체적 작업 단위**

- B06-Contract: 인터페이스 및 완료 기준 확정
    
- B06-I: 구현
    
- B06-V-Plan: 독립 검증 설계
    
- B06-V-Run: 독립 검증 실행
    
- B06-G: 통합 검수
    

기능이 크다면 I 또는 V 아래에 더 작은 Task를 둘 수 있다.

Beads의 실제 Issue ID는 자동 생성된 고유 식별자를 사용한다. `B06-I` 같은 프로젝트상의 작업 코드는 제목이나 메타데이터에 유지한다.

### 4.3 DAG 의존성 규칙

기본 관계는 다음과 같다.

1. Contract가 확정되면 I와 V-Plan이 실행 가능해진다.
    
2. I와 V-Plan은 병렬로 진행할 수 있다.
    
3. V-Run은 I와 V-Plan의 산출물이 준비된 후 실행한다.
    
4. G는 독립 검증과 필수 자동 Gate가 통과한 후 시작한다.
    
5. 다음 공정은 필요한 G 승인이 완료된 뒤 시작한다.
    

Beads의 `blocks` 의존성을 명시적으로 사용한다.

상위 Epic의 존재만으로 하위 작업의 순차 실행을 추정하지 않는다.

**다음 공정을 차단하는 기준은 구현 완료가 아니라 해당 공정에 필요한 통합 승인이다.**

### 4.4 작업 상태

Beads의 기본 작업 상태를 우선 사용한다.

- Open: 아직 착수하지 않은 작업
    
- In Progress: 현재 담당자가 수행 중인 작업
    
- Blocked: 선행 조건이 완료되지 않은 작업
    
- Deferred: 실행을 연기한 작업
    
- Closed: 해당 Task의 완료 조건이 충족된 작업
    

`APPROVED` 같은 별도 의미는 G Task의 완료 여부와 검증 근거를 통해 표현한다.

I 또는 V가 Closed라고 해서 Epic이 최종 승인된 것으로 판단하지 않는다.

### 4.5 Beads 명령 활용

초기에는 다음 명령을 사용한다.

```
# 사용 가능한 다음 작업
bd ready --json

# 작업을 시작하지 못하는 이유
bd ready --explain

# 차단된 작업 조회
bd blocked

# 작업 상세 정보
bd show <issue-id>

# 작업 의존성 확인
bd dep tree <issue-id>

# DAG 순환 오류 검사
bd dep cycles

# 전체 그래프 검사
bd graph check
```

Coordinator는 원칙적으로 전체 공정표 대신 `bd ready`와 해당 작업의 상세 정보만 읽는다.

작업 상태 수정은 Coordinator에 집중시켜 중복 할당과 경쟁 상태를 방지한다.

---

## 5. Herdr 내부의 에이전트 구성

### 5.1 Coordinator Agent

기존 Herdr 안에 중앙 Coordinator 역할을 GPT 6.1 sol high로 둔다.

별도 Python Coordinator 서버나 새로운 LLM 프레임워크를 만들지 않는다.

Coordinator가 담당하는 작업은 다음과 같다.

1. Beads에서 실행 가능한 Task 조회
    
2. Task의 Contract 및 선행 조건 확인
    
3. 파일·Git·실행 자원 충돌 확인
    
4. 역할과 위험도에 따른 모델 선택
    
5. 적절한 Herdr 작업자에게 Task 할당
    
6. 실행 상태와 결과 확인
    
7. Validation Gate 실행 요청
    
8. 실패 시 수정 작업 또는 재검증 지시
    
9. G 승인 후 Beads 상태 갱신
    
10. 다음 실행 가능 Task 확인
    

단, Coordinator가 확인할 수 없는 작업을 임의로 완료 처리하지 않는다.

서브에이전트 생성과 에이전트 간 통신은 §15의 11번 지침(Herdr 환경 확인 후 herdr 스킬 사용)을 따른다.

### 5.2 구현 에이전트 I

구현자는 다음 책임만 갖는다.

- 담당 Contract 이해
    
- 허용된 파일 범위 안에서 코드 구현
    
- 필수 로컬 테스트 수행
    
- 실패 시 원인 분석과 수정
    
- 변경 파일, Diff, 테스트 결과 제출
    
- 최종 구현 후보 동결
    

구현자는 자신의 변경을 독립 검증 완료라고 선언하거나, 최종 승인 없이 제품 브랜치에 병합하지 않는다.

### 5.3 독립 검증 에이전트 V

검증자를 두 단계로 구분한다.

**V-Plan**

- Contract를 독립적으로 해석
    
- 정상 사례, 실패 사례, 경계 사례 설계
    
- 기준 데이터와 예상 결과 정의
    
- 검증 스크립트 준비
    

**V-Run**

- 동결된 구현 후보 검증
    
- 기존 회귀 테스트
    
- 변경 범위 및 파일 보존 검사
    
- 필요한 경우 Delft3D 엔진 결과 대조
    
- 독립 검증 결과 제출
    

검증자는 구현자의 자체 평가를 검증 기준으로 사용하지 않는다.

### 5.4 Integrator G

G의 책임은 다음과 같다.

- 구현·검증 결과의 일치 여부 확인
    
- Contract 변경 사항 검토
    
- 공용 모듈 충돌 검토
    
- 검증 근거의 완전성과 독립성 확인
    
- 필요한 통합 테스트 수행
    
- 승인 또는 반려
    
- 승인 후 코드 병합
    

반려된 작업은 실패 원인을 구조화하여 담당 구현자에게 돌려보낸다.

---

## 6. 모델 배정 및 비용 최적화 정책

### 6.1 목표와 단일 원본

모델 선택의 목표는 특정 모델의 사용 비율이 아니라 **요구되는 검증 수준을 만족하면서 승인된 Task 하나를 완성하는 총비용을 낮추는 것**이다.

- **정책의 단일 원본(SSOT)은 6.8의 YAML이다.** 모델 후보, 풀, effort 기본값, 제한은 YAML에서만 정의한다. 이 절의 나머지는 YAML이 담지 못하는 이유와 운영 규칙만 설명하며, 같은 값을 다른 곳에 다시 쓰지 않는다.
- 모델명은 운영 정책상의 후보명이며, 모델 간 절대 성능 순위나 가격 동등성을 뜻하지 않는다.
- 모든 Task를 Sol·Sonnet으로 시작하지 않고, 모든 고위험 Task를 Opus·Astra로 시작하지도 않는다. 작업 범위, 결과를 확인할 기준, 실패 시 영향, 기존 평가 결과를 함께 본다.

### 6.2 모델 클래스와 운영상 위치

| 클래스 | OpenAI | Anthropic | 맡기는 일 | 맡기지 않는 일 |
|---|---|---|---|---|
| 규칙 기반 | Python·CLI | Python·CLI | 상태·의존성 조회, 형식 검사, 테스트 실행, 결과 파싱 | (LLM 호출 없음) |
| 경량 | Luna | Haiku | 범위가 좁고 결과를 검사할 수 있는 탐색·추출·로그 분류·Task Packet 초안·반복 테스트·작은 수정 | 경계조건의 물리적 타당성, 프로세스 종료 확인, 검증 누락 판정, 통합 승인 |
| 시각·문서 | Terra | Haiku·Sonnet | GUI·도면·차트 정보 추출, 조작 절차 문서화, 설명 문서 | 추출한 값의 과학적 의미 판단 |
| 일반 | Sol | Sonnet | 구현, 다중 파일 수정, Contract 설계, 독립 테스트 설계, 디버깅, 작업 분할, 통합 검수 | 정형 데이터 변환·단순 정리(경량으로) |
| 프리미엄 | Astra | Opus | 일반 모델이 해결하지 못한, 범위가 분명한 설계 검토·반례 탐색 | 상시 작업, 전체 재검토, 이후 단계 전체 수행 |
| 예외 | — | Fable | 별도 승인된 예외적 장기 분석 | 기본 비활성 |

운영 해석:

- **경량 모델은 요약 전용이 아니다.** 변경 범위가 작고 테스트로 확인되는 구현은 배정 후보다. 단, 경량 모델이 쓴 테스트를 유일한 검증 기준으로 쓰지 않고, 통과 선언만으로 승인하지 않는다.
- **Terra는 저렴한 범용 코딩 모델로 취급하지 않는다.** 시각 정보를 읽는 일과 그 의미를 판단하는 일을 분리한다(예: Terra가 화면의 수위·단위·시각을 추출하면, Contract 일치 여부는 코드 또는 별도 검증자가 확인). GUI 조작은 실제로 연결된 Computer Use 도구와 권한이 있을 때만 가능하다.
- **Sol과 Sonnet은 동등한 후보다.** 구현자는 항상 Sonnet, 검증자는 항상 Sol 같은 식으로 역할을 고정하지 않고, 작업 유형별 실제 성과로 양방향 배정한다.
- **Opus와 Astra는 선택적 프리미엄 후보다.** Sol·Sonnet 다음에 반드시 거치는 중간 승격 단계가 아니며, Opus 이후 Astra로 이어지는 연속 승격도 하지 않는다. 문제에 맞는 하나만 고르고, 제한이 약한 Opus를 먼저 검토한다.
- 구형 모델은 호환성, 실측된 비용·성공률 우위, 기존 검증 환경 재현이 필요할 때만 추가한다. 모델 수를 늘리는 것을 최적화로 보지 않는다. 이미지 생성·음성·Embedding 모델은 해당 기능이 필요한 작업에서만 쓴다.

### 6.3 실제 사용 전 확인

배정 전에 설치된 실행기와 공식 안내로 다음을 확인한다. 확인되지 않은 모델은 자동 배정 대상에서 제외한다(`availability_verified: false`).

- 모델 제공 여부, 계정 접근 권한, 정확한 모델 ID
- Codex CLI·Claude Code에서의 사용 가능 여부와 지원 effort
- 필요한 도구·이미지 입력·Computer Use 지원
- API 요금 또는 구독 사용량 정책, 자동 Fallback·기본 모델 설정

이전 대화에 나온 모델 ID·가격·지원 범위를 검증된 설정으로 복사하지 않는다. API 가격과 구독 한도는 같은 기준으로 취급하지 않고, 구독 사용량을 근거 없이 API 금액으로 환산하지 않는다. 가격은 실행 시점의 공식 가격표로 확인하며, 미확인 가격을 라우팅 설정에 고정하지 않는다.

**실행 기록.** 작업 시작 시 요청 모델·실제 실행 모델 ID, 요청 effort·실제 적용 effort, 실행기와 버전, 인증·과금 방식, Fallback 발생 여부를 기록한다. `default`·`sonnet`·`haiku` 같은 별칭이 모든 환경에서 같은 모델이라고 가정하지 않으며, 재현성이 필요한 작업은 확인된 구체 ID를 쓴다. Herdr가 띄운 CLI의 기본값·환경 변수·Fallback 설정이 정책을 덮어쓰지 않는지도 확인한다.

### 6.4 선택 규칙

#### 선택 순서

1. 코드로 처리 가능한가? → LLM을 호출하지 않는다.
2. 범위가 좁고 결과를 명확히 검증할 수 있는가? → 해당 작업 유형에서 검증된 경량 모델.
3. 시각·GUI·문서 작업인가? → Terra 또는 적합한 Claude 모델.
4. 설계·다중 파일 구현·독립 판단이 필요한가? → Sol·Sonnet.
5. 일반 후보의 성능 부족이 확인됐거나 처음부터 예외적 판단이 필요한가? → 문제를 좁히고 프리미엄 승인을 요청한다.

"저렴한 모델부터 순서대로 전부 호출"하는 운영은 금지한다. 명백히 어려운 문제에 경량 모델을 반복 투입하지 않는다. 역할마다 에이전트를 하나씩 만들지 않고, 필요한 역할만 분리한다.

#### 동등 후보 간 선택

| 기준 | 적용 |
|---|---|
| 작업 유형별 검증 성과 | 오류·재작업이 적었던 모델 우선 |
| 필요한 도구와 실행 환경 | 실제 지원되는 후보만 |
| 검증 독립성 | 가능하면 구현자와 다른 계열 |
| 사용 가능 한도 | 계정·CLI의 현재 한도 |
| 컨텍스트 재사용 | 같은 Task의 짧은 수정은 기존 세션 유지 검토 |
| 총비용 | 구현뿐 아니라 검증·재작업 포함 |

회사별 사용 비율을 강제하지 않는다. 혼합 운영은 목적에 맞는 모델을 고르기 위한 수단이다.

#### Verifier-Run과 LLM의 몫

Verifier-Run에서 테스트를 실제로 실행하는 일은 코드가 한다. 테스트 명령마다 검증 LLM을 새로 호출하지 않는다. LLM은 테스트 설계, 실패 원인 해석, 검증 범위 누락 확인, 충돌하는 결과 분석에만 쓴다.

### 6.5 effort 정책

- 모델이 높은 effort를 지원한다는 것과 작업에 필요하다는 것은 다르다. 같은 `medium`·`high`도 모델별로 토큰 소비와 성능이 다르다.
- 실행 환경이 지원함을 확인한 effort만 적용한다. 지원하지 않는 값을 임의로 전달하거나, 설정이 무시된 채 진행하지 않는다.
- 기본값은 YAML의 `effort_policy`를 따른다. 자동 배정의 상한은 `high`이며, 그 이상은 별도 평가로 이점이 확인된 경우에만 정책에 추가한다. **Astra의 `high` 상한은 어떤 예외로도 해제하지 않는다.**
- `high`는 고정 토큰 예산이 아니다. 비용 관리에서는 실제 모델, effort, 별도 추론·서비스 모드, 출력 토큰 한도, 호출·재시도 횟수, 세션·Task 누적 사용량을 함께 본다. 고비용 추론 모드는 자동 활성화하지 않는다.

### 6.6 실패 처리, 프리미엄 호출, 독립 검증

#### 실패 처리

환경 설정·파일 누락·권한 부족·잘못된 실행 명령은 모델을 바꾸지 말고 해당 원인부터 해결한다. 최초 시도 이후 동일 원인의 수정 재시도는 최대 2회다. 해결되지 않으면 다음을 재점검한다: Task 분할, 입력 자료 충분성, Contract 모순, 테스트 기대값, 환경·권한 문제, 다른 모델의 판단 필요성.

모델을 바꿀 때 기본 전달 정보는 현재 Contract와 후보 Commit, 재현 가능한 실패, 실패한 접근의 짧은 요약, 필요한 코드·증거 참조, 새 모델에게 맡길 구체적 질문뿐이다. 기존 세션의 긴 대화 전체는 전달하지 않는다.

#### 프리미엄 호출 (Opus·Astra 공통)

호출 전에 해결할 질문, 기존 접근의 한계, 필요한 입력 범위, 예상 호출 범위, 사용 예산 상한, 결과 검증 방법을 기록하고 사용자 승인을 받는다.

- 부적절한 요청: "전체 저장소를 다시 검토하고 모든 문제를 찾아라."
- 적절한 요청: "이 종료 영수증 두 개가 충돌하는 원인과 현재 판정 규칙에서 누락된 조건을 검토하라."
- 결과를 받은 뒤 구현과 회귀 검사는 일반 모델이 수행한다. 프리미엄을 불렀다는 이유로 남은 단계를 같은 모델로 계속하지 않는다.
- Astra·Opus를 쓸 수 없다고 자동 대체하지 않는다. Fable은 기본 비활성이며 별도 승인이 있을 때만 후보가 된다.
- Astra: 기본 배정 비활성, 자동 승격 금지, 사용자 승인 필요, effort 상한 `high`, `xhigh`/`max` 금지.

#### 독립 검증과 모델 혼합

모델 계열이 달라도 검증의 독립성은 별도로 확보한다. 같은 Task의 구현과 검증은 별도 세션에서 하고, V-Plan은 가능하면 구현 결과를 보기 전에 Contract만으로 기준을 설계한다.

| 위험도 | 운영 |
|---|---|
| 저위험 | 해당 작업 유형 평가를 통과했다면 경량 모델을 구현·검증 후보로 사용 가능. 단 자동 테스트, 변경 범위 확인, 원본 대조를 함께 요구하고 경량 검증자의 통과 선언만으로 승인하지 않는다. |
| 일반 | Sol 구현→Sonnet 검증, Sonnet 구현→Sol 검증을 모두 허용. |
| 고위험 | 두 모델이 동의했다는 사실을 근거로 삼지 않는다. 별도 세션, 독립 테스트 기준, 동결된 후보 Commit 또는 파일 지문, 원시 데이터 직접 확인, 필수 회귀 테스트, 필요한 Native 검증, 기존 G 승인 절차를 요구한다. |

**통합 검수 G**는 매번 프리미엄 모델을 부르는 단계가 아니다. Coordinator가 자동 Gate와 독립 검증 결과를 확인하고 남은 판단만 수행한다. Coordinator가 직접 구현했다면 별도 독립 검증을 유지하고, 이해충돌이 있거나 새 관점이 필요한 고위험 변경은 G도 별도 세션에 배정할 수 있다.

#### 운영 예시

| 예시 | 구성 | 요점 |
|---|---|---|
| A. 도움말 수정·작은 보완 | I: Luna `high`/Haiku `medium` → 기존 테스트·Diff 비교 → V: 다른 계열 경량 또는 일반 모델 → G: Coordinator | Sol·Sonnet·Opus를 모두 부르지 않는다. 경량 처리 범위는 대표 사례로 먼저 평가하고, 불충분하면 일반 모델로 보완한다. |
| B. BC 파서 확장 | 매뉴얼 조건 추출: 경량 → Contract: Sol/Sonnet → I: Sol/Sonnet `medium/high` → V: 다른 계열 Sol/Sonnet → 실행: Python → G: Coordinator | 경량 모델의 문서 요약은 참고 자료일 뿐 원문 확인을 대체하지 않는다. |
| C. 프로세스 종료·소유권 | I·V: Sol/Sonnet `high`로 시작. 설계가 매우 불명확하거나 해당 유형의 성능 부족이 확인됐다면 승인 후 Opus 또는 Astra의 제한된 설계 검토를 먼저 수행 | 고위험에 무조건 가장 싼 모델도, 무조건 가장 비싼 모델도 배정하지 않는다. Native 실행 허가·원시 결과 확인·G 승인 조건은 모델과 무관하게 유지한다. |

### 6.7 컨텍스트·비용 관리와 평가

**경량 모델에도 필요한 정보만 전달한다.** 기본 입력은 공통 핵심 규칙, Task 목표, 승인된 Contract, 필요한 코드·자료 참조, 기준 Commit, 완료 조건, 결과 제출 형식이다. 추가 정보는 선택적으로 조회한다. 단, 비용 때문에 필수 Contract나 검증 근거를 빼지 않는다.

**총비용의 정의.**

```text
승인된 Task당 총비용
= 구현 + 독립 검증 + 통합 검수 + 실패·재작업 + 도구 실행 비용
```

API 비용을 측정할 수 없는 구독 실행에서는 사용량, 실행 시간, 호출·재시도 횟수, 독립 검증 실패, 최종 승인 여부를 따로 기록한다. 싼 모델이 재작업을 늘려 총비용이 커졌다면 최적화로 보지 않는다. 호출 수가 줄었다는 이유만으로도 성공으로 보지 않는다.

**초기 적용은 비율이 아니라 비교 평가로 한다.** 대표 작업을 유형별로 나눠 동일한 Contract·기준 코드·테스트로 후보를 비교한다.

| 평가 유형 | 비교 후보 |
|---|---|
| 작은 코드 수정·반복 테스트 | Luna vs Haiku |
| GUI·시각·문서 정리 | Terra vs 적합한 Claude 모델 |
| 일반 구현·버그 수정 | Sol vs Sonnet (`medium`) |
| 복잡한 검증·다중 모듈 | Sol vs Sonnet (`high`) |
| 일반 후보로 해결 안 된 문제 | 승인 후 Opus 또는 Astra |

평가 항목: 요구사항 충족, 독립 검증 통과, 놓친 오류 종류, 재시도 횟수, 입력·출력 토큰, 비용 또는 구독 사용량, 소요 시간, 원본·비대상 파일 보존, 지침·권한 준수.

결과 반영: 경량 모델의 검증 누락이 반복되면 해당 유형을 일반 후보군으로 올리고, Sol·Sonnet이 과도하게 추론하는 작업은 범위를 좁혀 경량으로 내린다. 프리미엄 검토가 전체 재작업을 줄였는지도 별도로 평가한다.

**잠정 운영(평가 전).** 평가 결과가 나오기 전인 Phase 3~4에서는 후보 풀을 단순화한다: 규칙 기반 / 일반(Sol·Sonnet `medium`, 복잡 시 `high`) / 승인형 프리미엄. 경량·시각 풀은 6.7의 평가를 통과한 유형부터 켠다.

### 6.8 정책 YAML

이 YAML은 **우리 시스템의 논리적 정책**이다. Herdr나 Beads가 그대로 인식하는 형식이 아니므로 Coordinator 지침 또는 별도 검증 코드가 해석하게 구현한다. `model_id`는 설치된 실행기에서 실제 사용 가능 여부를 확인한 뒤 채우며, `availability_verified: false`인 모델은 배정하지 않는다. 제한은 프롬프트에 적는 것만으로 강제되지 않으므로 모델 선택, effort 상한, Fallback, 예산을 실행기 또는 호출 전 검증 단계에서 검사한다. 특히 Astra의 `high` 상한은 호출 설정 검사에서도 강제한다.

```yaml
model_policy:
  version: 4
  objective: minimize_cost_per_accepted_task

  models:
    luna:   {display_name: "GPT-6 Luna",       provider: openai,    class: lightweight,    model_id: null, availability_verified: false}
    haiku:  {display_name: "Claude Haiku 5.5", provider: anthropic, class: lightweight,    model_id: null, availability_verified: false}
    terra:  {display_name: "GPT-6.1 Terra",    provider: openai,    class: visual_document, model_id: null, availability_verified: false}
    sol:    {display_name: "GPT-6.1 Sol",      provider: openai,    class: general,        model_id: null, availability_verified: false}
    sonnet: {display_name: "Claude Sonnet 5.5", provider: anthropic, class: general,       model_id: null, availability_verified: false}
    opus:   {display_name: "Claude Opus 5.5",  provider: anthropic, class: premium,        model_id: null, availability_verified: false}
    astra:
      display_name: "GPT-6 Astra"
      provider: openai
      class: premium
      model_id: null
      availability_verified: false
      policy_allowed_efforts: [low, medium, high]
      hard_max_effort: high
    fable:
      display_name: "Claude Fable 5.1"
      provider: anthropic
      class: exceptional
      model_id: null
      availability_verified: false
      enabled_by_default: false

  # 풀 -> 후보. 두 회사 모델은 기본/대안 관계가 아닌 동등 후보.
  candidate_pools:
    extraction_and_summary: [luna, haiku]
    bounded_low_risk_code:  [luna, haiku]
    visual_inspection:      [terra, haiku, sonnet]
    documentation:          [terra, haiku, sonnet]
    general_implementation: [sol, sonnet]
    planning_and_contracts: [sol, sonnet]
    complex_verification:   [sol, sonnet]
    integration_review:     [sol, sonnet]
    approved_deep_review:   [opus, astra]

  # 역할 -> 풀 + effort (동일 모델이라도 effort는 역할별로 다름)
  role_defaults:
    log_classification:      {pool: extraction_and_summary, effort: low_or_medium}
    code_doc_search:         {pool: extraction_and_summary, effort: medium}   # Luna는 medium/high
    task_packet_draft:       {pool: extraction_and_summary, effort: medium}
    coordinator_judgment:    {pool: general_implementation, effort: medium}
    planning_task_split:     {pool: planning_and_contracts, effort: medium_or_high}
    contract_design:         {pool: planning_and_contracts, effort: high}
    bounded_low_risk_impl:   {pool: bounded_low_risk_code,  effort: {luna: high, haiku: medium}}
    general_impl:            {pool: general_implementation, effort: medium}
    complex_impl_debug:      {pool: general_implementation, effort: high}
    independent_verification:{pool: complex_verification,   effort: high}
    visual_doc_work:         {pool: visual_inspection,      effort: medium}
    integration_review:      {pool: integration_review,     effort: medium_or_high}
    exceptional_design_review: {pool: approved_deep_review, effort: {opus: medium_then_high, astra: "<=high"}}

  routing:
    deterministic_first: true
    require_verified_model_availability: true
    require_task_class_evaluation: true
    select_by: capability_then_total_cost
    prefer_cross_provider_verification: true
    enforce_provider_ratio: false
    preserve_independent_verification: true
    max_repairs_after_initial_attempt: 2
    prohibit_sequential_model_sweeps: true

  effort_policy:
    require_runtime_support_check: true
    automatic_max_effort: high
    hard_limits: {astra: high}

  premium_policy:
    models: [opus, astra]
    default_assignment: false
    automatic_escalation: false
    require_user_approval: true
    require_scoped_question: true
    require_usage_budget: true
    continue_regular_work_on_general_models: true
    prefer_opus_over_astra_when_both_fit: true

  exceptional_policy:
    models: [fable]
    default_enabled: false
    automatic_fallback: false
    require_separate_user_approval: true

  execution:
    verify_actual_model_and_effort: true
    prohibit_unapproved_premium_fallback: true
    prohibit_automatic_high_cost_modes: true
    log_auth_and_billing_mode: true
    log_actual_model: true
    log_actual_effort: true
    preserve_existing_validation_gates: true
```

### 최종 운영 원칙

**Python이 규칙적인 일을 처리하고, Luna·Haiku가 좁은 실제 작업을 수행하며, Terra가 시각·문서 작업을 담당한다. Sol·Sonnet은 핵심 개발과 판단을 맡고, Opus·Astra는 필요한 문제에만 제한적으로 참여한다. Astra의 effort 상한은 항상 `high`다.**

최적화의 기준은 가장 저렴한 호출이 아니라, 기존 검증 품질을 유지하면서 승인된 결과를 만드는 총비용이다.

## 7. 작업 충돌 방지

### 7.1 Git Worktree 분리

각 구현 작업에 독립 Worktree를 배정한다.

독립 검증에도 별도 Worktree를 사용한다.

예시 구조:

```
delft3d-fm-cli/
├── main/
├── worktrees/
│   ├── B06-I/
│   ├── B06-V/
│   ├── B14-I/
│   └── G-integration/
```

이 구조는 개념적 예시이며 실제 경로는 기존 저장소 및 Git Worktree 배치에 맞춰 결정한다.

모든 Worktree는 하나의 Git 저장소와 연결될 수 있지만, 각 작업은 별도의 작업 디렉터리와 브랜치에서 진행한다.

Beads는 동일 저장소의 Worktree에서 공유 공정표를 발견하도록 구성한다.

### 7.2 파일 소유권

각 Task에 수정 가능한 파일 범위를 기록한다.

다음 사항을 검사한다.

- 서로 다른 구현자가 동일한 공용 파일을 동시에 변경하는지
    
- 검증자가 제품 코드를 임의로 변경하는지
    
- 기존 승인 파일이 예상하지 못하게 변경됐는지
    
- 다른 Task의 실험 결과를 덮어쓰는지
    

공용 명령 등록, 패키징, 공정표 등 충돌 위험이 높은 파일은 통합 담당자에게 소유권을 집중한다.

Worktree가 달라도 공유 Git 작업 및 외부 실행 자원에는 별도의 충돌 관리가 필요하다.

### 7.3 실행 자원 소유권

다음 자원은 별도 Lock 또는 임대 방식으로 관리한다.

- Delft3D Native 실행 슬롯
    
- 공통 모델 입력
    
- 실험 출력 디렉터리
    
- 동일 실행 파일을 사용하는 공유 프로세스
    
- 공용 Git 병합 작업
    
- 공유 테스트 Fixture
    

기존 Native 실행 승인 규칙을 그대로 적용한다.

Beads의 작업 완료 상태나 Herdr의 세션 상태를 Native 실행 허가로 대체하지 않는다.

---

## 8. 토큰 최적화 전략

### 8.1 Task Packet 기반 작업 전달

각 에이전트에게 전체 개발 이력 대신 다음 정보만 전달한다.

- Task ID와 역할
    
- 작업 목표
    
- Contract 참조
    
- 선행 작업의 승인된 결과
    
- 기준 Commit SHA
    
- 수정 가능한 파일
    
- 필요한 검증 자료
    
- 완료 조건
    
- 결과 제출 형식
    

공통 규칙은 기존 `AGENTS.md`를 참조하도록 한다.

작업별로 무관한 프로젝트 문서 전체를 전달하지 않는다.

### 8.2 Private State와 Shared State 분리

**Private State**

- 구현 중 임시 분석과 시행착오
    
- 디버깅 과정
    
- 세션별 작업 메모
    
- 반복 수정 기록
    

**Shared State**

- 작업 상태
    
- 최종 Artifact 참조
    
- Contract 변경 사항
    
- 검증 결과
    
- 차단 사유
    
- 승인 상태
    

다른 에이전트에게 Private State 전체를 전달하지 않는다.

다만 실패 재현과 감사에 필요한 원본 증거는 별도로 보존한다.

### 8.3 Pass-by-Reference

긴 코드, 로그, 테스트 출력은 프롬프트에 반복 삽입하지 않는다.

다음 참조를 전달한다.

- 파일 경로
    
- Commit SHA
    
- Artifact ID
    
- 검증 결과 JSON
    
- 필요한 Diff
    
- 간결한 실패 요약
    

필요한 경우에만 실제 파일을 읽는다.

### 8.4 Coordinator의 LLM 호출 최소화

다음 작업은 LLM 없이 처리할 수 있는지 우선 검토한다.

- Beads 작업 조회
    
- 의존성 확인
    
- 작업 상태의 형식 검사
    
- 파일 소유권 충돌 검사
    
- 테스트 결과 파싱
    
- 검증 영수증의 필수 필드 확인
    
- 다음 실행 가능 작업 판별
    

초기에는 Herdr Coordinator가 이 작업을 수행하되, 반복 호출 비용이 큰 것으로 확인되면 해당 기능만 Python 스크립트로 분리한다.

전체 Coordinator를 처음부터 새로 개발하지 않는다.

### 8.5 컨텍스트 재사용

동일 구현 Task의 짧은 수정 루프에서는 기존 에이전트 세션을 재사용할 수 있다.

반면 다음 경우에는 새 세션을 사용한다.

- 독립 검증 시작
    
- 완전히 다른 Task로 이동
    
- 이전 작업의 맥락이 새로운 판단을 오염시킬 가능성이 있는 경우
    
- 기존 컨텍스트가 과도하게 커진 경우
    

Prompt Caching 지원 여부를 확인하고, 변하지 않는 공통 지침과 작업별 동적 정보를 분리한다.

---

## 9. Validation Gate

### 9.1 자동 검사

LLM이 수행할 필요가 없는 검사는 Python으로 처리한다.

- Syntax 검사
    
- JSON/YAML Schema 검사
    
- 정적 분석
    
- 단위 테스트
    
- 회귀 테스트
    
- CLI 출력 형식 검증
    
- 변경 파일 범위 검사
    
- 파일 SHA-256 비교
    
- Contract 필수 조건 검사
    

도구 도입 시에는 기존 프로젝트의 테스트 프레임워크와 의존성을 우선 사용한다.

### 9.2 Delft3D 특화 검증

다음 검증 계층을 유지한다.

- 입력 파일의 문법과 참조
    
- 원본 및 비대상 데이터 보존
    
- 시간 단위와 기준 시각
    
- 물리량 및 좌표계
    
- Delft3D 엔진 초기화
    
- 실제 계산 완료 여부
    
- NetCDF 시각과 변수
    
- 독립 기준군과 계산 결과 비교
    
- 실패·취소·프로세스 종료
    
- 실행 소유권과 대조군 생존
    

**Python 테스트 통과와 실제 수치모델 검증 통과를 구분한다.**

실제 엔진 실행이나 검증 범위 확장에는 기존 승인 절차를 따른다.

### 9.3 검증 결과 형식

각 작업은 다음 정보를 포함하는 구조화된 결과를 제출한다.

```
{
  "task_code": "B06-V",
  "outcome": "completed",
  "verdict": "pass",
  "candidate_sha": "<commit-sha>",
  "contract_sha": "<contract-sha>",
  "evidence_refs": [
    "research/experiments/<run-id>/verification.json"
  ],
  "native_verification": "not_requested",
  "integrated": false,
  "approved": false
}
```

위 데이터는 형식 예시다.

독립 검증 통과, Native 검증, 제품 병합, 최종 승인을 별도 상태로 관리한다.

---

## 10. Beads 상태 기록 정책

### 10.1 단일 Writer 원칙

초기에는 Coordinator만 Beads의 작업 상태를 수정한다.

다른 에이전트는 자신의 Task 정보를 조회할 수 있지만, 임의로 공정표의 다른 작업을 완료하거나 의존성을 변경하지 않는다.

작업자가 새로운 문제를 발견하면 Coordinator에게 신규 Task 등록을 요청한다.

이 제한은 지침만으로 강제되는 보안 기능이 아니므로, 필요하면 실행 도구의 권한이나 Wrapper에서도 제한한다.

### 10.2 Beads 저장 방식

현재 Beads의 기본 저장소는 Dolt 기반이다.

별도 SQLite를 추가하지 않는다.

초기에는 Embedded Mode와 Coordinator 단일 Writer 방식을 우선 검토한다.

여러 프로세스가 동시에 Beads에 직접 기록해야 할 필요가 명확해지면 Dolt Server Mode를 검토한다.

### 10.3 Worktree와 Beads

하나의 Git 저장소에 속한 Worktree들이 동일한 Beads 작업 공간을 공유하도록 구성한다.

별도의 Beads 데이터베이스를 Worktree마다 만들지 않는다.

공통 Beads 데이터가 여러 클론이나 컴퓨터에 분산되는 경우에만 Dolt Remote 동기화를 검토한다.

Dolt 데이터 동기화와 Git 코드 병합은 별개의 작업으로 취급한다.

### 10.4 이력 보존

다음 기록을 삭제하거나 압축하지 않는다.

- 미승인 후보의 실패 근거
    
- 원시 Native 실행 기록
    
- 기존 검증 체크포인트
    
- 승인된 제품 기준 Commit
    
- 실험 재현에 필요한 원본 데이터
    

Beads의 Compaction이나 Cleanup 기능을 사용하기 전에 데이터 보존 정책을 별도로 검토한다.

---

## 11. 실패 및 복구 정책

### 11.1 실패 분류

실패를 다음과 같이 구분한다.

|실패 유형|처리|
|---|---|
|구현 오류|기존 구현자에게 수정 요청|
|테스트 실패|원인과 실패 증거 전달|
|Contract 불일치|Architect 재검토|
|파일 충돌|Coordinator가 작업 격리 재조정|
|독립 검증 불일치|G가 검증 기준과 증거 재검토|
|Native 실행 불확실성|기존 실행 승인·소유권 절차 적용|
|에이전트 세션 종료|결과 영수증 확인 후 복구 여부 결정|
|반복 실패|상위 모델 또는 사용자 검토 요청|

### 11.2 복구 절차

에이전트가 중단되면 다음 순서로 복구한다.

1. Beads의 현재 Task 상태 조회
    
2. Herdr의 실제 세션 상태 확인
    
3. 작업 Worktree의 변경 상태 확인
    
4. 마지막 후보 Commit 및 Artifact 확인
    
5. 원본 검증 근거 확인
    
6. 진행 중인 Native 프로세스 확인
    
7. 복구 가능한 지점에서 작업 재개
    

세션이 종료됐다는 이유만으로 동일 작업을 처음부터 재실행하지 않는다.

기존 실행이 살아 있는 상태에서 중복 실행을 시작하지 않는다.

### 11.3 승인된 상태만 후속 공정으로 전달

I 완료는 구현 산출물이 준비되었음을 뜻한다.

V 완료는 명시한 검증 범위가 통과했음을 뜻한다.

G 완료는 해당 Contract와 증거에 대한 통합 승인이다.

후속 작업에 필요한 승인 범위를 만족한 경우에만 해당 작업의 의존성을 해제한다.

---

## 12. 단계별 도입 계획

### Phase 0 — 현황 점검

- 최신 `AGENTS.md`, `DELIVERY.md`, `RESUME.md` 확인
    
- 활성 Task와 승인 Task 분리
    
- Herdr 실행 환경 및 사용 가능한 모델 확인
    
- Git Worktree 사용 현황 확인
    
- 공용 파일 및 Native 자원 소유권 정리
    
- 현재 검증 Gate 목록 작성
    

**완료 조건:** 기존 개발 상태와 새 시스템에서 변경하면 안 되는 범위를 문서화한다.

### Phase 1 — Beads 시험 환경 구축

- Beads 버전 및 명령 지원 확인
    
- 독립 시험 디렉터리에 초기화
    
- 기존 지침·Git Hooks를 변경하지 않는 옵션 확인
    
- 모의 Epic / I / V / G Task 작성
    
- 의존성 및 병렬 착수 가능 여부 확인
    
- `bd ready`, `bd blocked`, `bd dep cycles` 검증
    
- Worktree에서 공통 Beads 작업 공간 조회 확인
    

시험 환경에서는 필요에 따라 다음 명령을 사용한다.

```
bd init --quiet --skip-agents --skip-hooks
bd doctor
bd ready --json
bd graph check
```

프로젝트 원본에 적용하기 전에 변경될 파일과 설정을 검사한다.

**완료 조건:** 실제 프로젝트 코드와 공정표를 변경하지 않고 Beads의 작동을 확인한다.

### Phase 2 — 실제 공정표 이관

- 활성 Epic 식별
    
- 기존 승인 작업 및 이력 분리
    
- Task 단위 및 선행 조건 구성
    
- 고유 Beads Issue ID와 기존 작업 코드 연결
    
- I / V-Plan / V-Run / G 구분
    
- 승인된 선행 조건 보존
    
- 차단 상태와 다음 착수 가능 작업 검증
    
- 기존 `DELIVERY.md`와 교차 검수
    

**완료 조건:** 현재 실제 공정의 상태와 Beads가 제시하는 Ready/Blocked 결과가 일치한다.

### Phase 3 — Herdr Coordinator 통합

- Coordinator의 Beads 사용 규칙 작성
    
- 작업 배정과 소유권 정책 정의
    
- 역할별 모델 선택 정책 적용
    
- 작업별 Task Packet 형식 통일
    
- Herdr 세션과 Beads Task 연결
    
- 결과 영수증 수집
    
- 단일 Writer 정책 적용
    
- 반복 실패 및 중단 복구 시험
    

**완료 조건:** 별도 오케스트레이션 서버 없이 Herdr 안에서 한 Task를 할당하고 결과를 관리할 수 있다.

### Phase 4 — 작업 격리와 독립 검증

- I/V 작업별 Worktree 구성
    
- 파일 소유권 검사
    
- 공용 Git 작업 직렬화
    
- 결정론적 Validation Gate 연결
    
- I와 V-Plan 병렬 실행 검증
    
- V-Run의 독립성 확인
    
- G 승인 후 병합 조건 검증
    
- 실패·중복 실행·파일 충돌 반례 시험
    

**완료 조건:** 저위험 시험 작업에서 I/V/G 전체 공정을 충돌 없이 완료한다.

### Phase 5 — 토큰 및 실행 효율 최적화

- 노드별 입력·출력 토큰 수집
    
- 모델별 실행 시간 수집
    
- Task Packet 전달 적용
    
- 불필요한 전체 문서 로딩 제거
    
- 파일 참조 기반 결과 전달
    
- 모델별 비용과 승인 성공률 비교
    
- 반복 실패 시 모델 승격
    
- 최적화 전후 성능 비교
    

**완료 조건:** 검증 품질을 유지하면서 승인 Task당 비용과 실행 시간을 정량적으로 비교할 수 있다.

---

## 13. 성과 평가 기준

다음 지표로 개선 효과를 평가한다.

|지표|목적|
|---|---|
|승인 Task당 총토큰|실제 토큰 효율|
|승인 Task당 총비용|모델 비용 효율|
|Task당 실행 시간|개발 속도|
|반복 실패 횟수|작업 품질|
|파일 소유권 충돌 건수|병렬 작업 안정성|
|중복 실행 건수|오케스트레이션 신뢰성|
|검증 실패 탐지율|검증 체계 유효성|
|근거 없는 승인 건수|승인 체계 신뢰성|
|중단 후 복구 성공률|상태 관리 안정성|
|불필요한 Coordinator 호출|컨텍스트 관리 효율|

측정 이전에 특정 토큰 절감률을 보장하거나 목표 달성을 선언하지 않는다.

최적화 전후에는 비슷한 종류와 난도의 Task를 비교하고, 모델 비용과 검증 범위 차이를 구분한다.

---

## 14. 선택적 향후 확장

초기 시스템이 안정화되면 다음 기능을 검토한다.

**Langfuse**

실제 모델 호출 Trace와 토큰 사용량을 수집할 수 있는 경우에 도입한다.

**DAG GUI**

Beads CLI만으로 공정표를 파악하기 어려울 때 오픈소스 GUI를 연결한다. 기존 Beads 데이터를 그대로 읽는 도구를 우선한다.

**Python Coordinator Helper**

규칙적인 조회, 충돌 검사, 상태 전이에 반복적으로 많은 LLM 비용이 발생할 때만 추가한다.

**Dagu**

주기적으로 실행할 고정된 테스트·배포·검증 파이프라인이 많아질 때 별도로 도입한다.

**Beads Formula/Molecule**

I/V/G와 같은 반복 공정을 템플릿화할 필요가 생기면 사용을 검토한다.

---

## 15. 실제 에이전트에게 전달할 실행 지침

이 문서를 읽은 Coordinator는 다음 원칙을 따른다.

1. 먼저 기존 시스템과 실제 저장소 상태를 확인한다.
    
2. 기존 공정표 및 승인 결과를 임의로 수정하지 않는다.
    
3. Beads를 새로운 실행 엔진이 아니라 작업 상태 및 의존성 관리 도구로 사용한다.
    
4. Herdr의 기존 에이전트 실행 및 I/V/G 분담을 유지한다.
    
5. 작업자가 수행할 수 있는 파일과 외부 실행 자원을 명확하게 제한한다.
    
6. 전체 공정표와 긴 대화 기록을 작업자에게 무조건 전달하지 않는다.
    
7. 검증자에게 구현자의 자체 평가를 독립 검증 기준으로 전달하지 않는다.
    
8. Python으로 판단할 수 있는 단순한 상태·검증 작업에 LLM을 반복 사용하지 않는다.
    
9. 실패 시 재실행보다 기존 원인과 산출물 확인을 우선한다.
    
10. 승인된 근거 없이 Beads Task나 제품 코드를 최종 완료 처리하지 않는다.
11. 서브에이전트를 생성하거나 다른 에이전트와 통신하기 전에 먼저 `HERDR_ENV=1`로 Herdr 환경인지 확인한다.
    - Herdr 환경이면 herdr 스킬을 사용한다. 이 문서가 해당 스킬 사용에 대한 명시적 허가다.
    - Herdr 환경이 아니면 내장 서브에이전트 등 사용 가능한 방식으로 대체할 수 있다. 이때도 Worktree 격리, 파일·자원 소유권, 단일 Writer, 모델 정책(§6)은 동일하게 적용한다.
    - 생성·통신은 Coordinator만 수행한다. 작업자는 필요를 Coordinator에게 요청한다.
    - 생성 시 §6.3의 실행 기록(요청·실제 모델과 effort, Fallback 여부)을 남긴다.
    

### 최초 작업 범위

**우선 Phase 0과 Phase 1부터 수행한다.**

기존 저장소와 Herdr의 운영을 중단하지 않고 Beads를 격리된 환경에서 검증한다.

이후 실제 공정표 이관에 앞서 다음을 보고한다.

- 확인된 현재 개발·승인 상태
    
- 기존 시스템과의 충돌 가능성
    
- Beads 도입 시 변경될 파일
    
- 실제 작업 분배와 상태 관리 방법
    
- 새로 추가해야 할 최소한의 설정·스크립트
    
- 자동 검증 범위
    
- Phase 2 진행을 위한 선행 조건
    

기존 제품 코드의 변경, Native 실행, 승인되지 않은 병합 또는 원격 동기화는 이 문서만으로 허가된 것으로 간주하지 않는다.

**최종 원칙: Beads가 공정표의 상태와 의존성을 관리하고, Herdr가 작업을 실행하며, 독립 검증과 G 승인이 실제 완료 여부를 결정하는 구조를 유지한다.**