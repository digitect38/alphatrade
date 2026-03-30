# AlphaTrade 전체 아키텍처 리뷰 & 리팩토링 계획

## Context
Phase 0~7 빠르게 구현 완료. 기능은 동작하지만, 코드 품질/테스트/보안/아키텍처에 심각한 기술 부채 누적. 프로덕션 배포 전 체계적 리팩토링 필요.

---

## 1. 현재 상태 종합 평가

| 영역 | 점수 | 핵심 문제 |
|---|---|---|
| **아키텍처** | 5/10 | 전역 싱글톤, 의존성 주입 없음, 관심사 미분리 |
| **코드 품질** | 4/10 | 50줄+ 함수 12개, 하드코딩 설정, 중복 코드 |
| **테스트** | 3/10 | 580건 통과하나 라우트 0%, 통합 테스트 0% |
| **보안** | 4/10 | 하드코딩 비밀번호, Rate Limit 없음, 인증 없음 |
| **프론트엔드** | 4/10 | 인라인 스타일 600줄+, 미완성 i18n, 에러 처리 부재 |
| **인프라** | 7/10 | Docker 잘 구성, 단 Grafana/n8n 미완성 |
| **계획 준수** | 6/10 | n8n 워크플로우 1/10, Grafana 대시보드 미비 |

---

## 2. 핵심 문제 (Critical Issues)

### 2.1 전역 싱글톤 패턴 (Anti-Pattern)
```python
# 현재: 모든 서비스가 모듈 수준 싱글톤
kis_client = KISClient()      # services/kis_api.py
dart_client = DARTClient()     # services/dart_api.py
broker_client = BrokerClient() # execution/broker.py
risk_manager = RiskManager()   # execution/risk_manager.py
notifier = NotificationService() # services/notification.py
```
**문제**: 테스트 불가, 상태 누수, 설정 변경 불가
**해결**: FastAPI `Depends()` 기반 의존성 주입으로 전환

### 2.2 거대 함수 (50줄 초과)
| 함수 | 파일 | 줄 수 |
|---|---|---|
| `run_morning_scan()` | scanner/morning.py | 179 |
| `run_trading_cycle()` | trading/loop.py | 169 |
| `execute_order()` | execution/order_manager.py | 114 |
| `api_sector_trends()` | routes/index.py | 107 |
| `check_order()` | execution/risk_manager.py | 101 |

### 2.3 하드코딩된 설정 값
- 리스크 한도 (MAX_TOTAL_CAPITAL=500K, STOP_LOSS=-3%)
- 전략 가중치 (momentum=30%, sentiment=25%)
- 스캐너 임계값 (GAP_THRESHOLD=2%, VOLUME_SURGE=3x)
- 캐시 TTL (60s)

### 2.4 테스트 커버리지 갭
- **라우트 테스트**: 11개 라우터, 0% 테스트
- **통합 테스트**: 0건
- **서비스 테스트**: KIS/Naver/Notification 미테스트
- **백테스트 로직 테스트**: 0건

### 2.5 에러 처리 패턴
```python
# 현재: 모든 에러를 삼키는 catch-all
except Exception as e:
    errors.append(f"Failed: {e}")
```
**문제**: 재시도 없음, 트랜잭션 관리 없음, 부분 실패 상태 방치

### 2.6 프론트엔드 문제
- 600줄+ 인라인 스타일 (CSS 파일 없음)
- `fetch()` 직접 호출 10곳 (useApi 훅 미활용)
- i18n 40개 문자열 미번역
- 에러 발생 시 사용자 피드백 없음 (console.error만)

---

## 3. 리팩토링 계획

### Phase R1: 코드 구조 정리 (1주)

**R1.1 의존성 주입 전환**
- FastAPI `Depends()` 패턴으로 서비스 주입
- 파일: `main.py`, `database.py`, 모든 `routes/*.py`

**R1.2 설정 외부화**
- 모든 하드코딩 값 → `config.py`의 `Settings` 클래스로 이동
- 리스크 한도, 전략 가중치, 캐시 TTL, 스캐너 임계값
- 파일: `config.py`, `risk_manager.py`, `ensemble.py`, `morning.py`, `position_sizer.py`

**R1.3 함수 분리**
- 50줄 초과 함수 12개를 각각 20~30줄 단위로 분리
- 파일: `trading/loop.py`, `scanner/morning.py`, `execution/order_manager.py`

**R1.4 중복 코드 통합**
- 거래량 급증 판단 로직 → `analysis/volume.py` 단일 함수로 통합
- 기술적 지표 계산 → `analysis/technical.py` 공유 유틸로 통합

### Phase R2: 에러 처리 & 로깅 (1주)

**R2.1 구조화된 에러 처리**
- 커스텀 예외 클래스: `APIError`, `BrokerError`, `DataError`
- 재시도 로직: 네트워크 오류 시 3회 재시도
- 트랜잭션 관리: 주문 실행 시 DB 트랜잭션

**R2.2 구조화된 로깅**
- JSON 로깅 포맷
- 요청 상관 ID (correlation ID)
- 성능 로깅 (응답 시간, DB 쿼리 수)

**R2.3 Prometheus 메트릭 실제 연동**
- 현재 정의만 있고 미들웨어 없음 → FastAPI 미들웨어 추가
- 비즈니스 메트릭 추가: 거래 건수, 시그널 수, 포트폴리오 가치

### Phase R3: 테스트 강화 (2주)

**R3.1 라우트 통합 테스트**
- FastAPI TestClient로 모든 32개 엔드포인트 테스트
- 파일: `tests/test_routes_*.py`

**R3.2 서비스 모킹 테스트**
- KIS API, DART API, Naver News 모킹
- httpx mock으로 외부 API 응답 시뮬레이션

**R3.3 트레이딩 루프 E2E 테스트**
- 전체 사이클 테스트: 수집→분석→시그널→주문→스냅샷
- DB 상태 검증

**R3.4 커버리지 도구 설정**
- pytest-cov 설정, 최소 60% 커버리지 목표

### Phase R4: 프론트엔드 리팩토링 (1주)

**R4.1 스타일링 시스템 도입**
- CSS Modules 또는 디자인 토큰 파일로 인라인 스타일 대체
- 색상/간격/폰트 일관성 확보

**R4.2 API 통합 정리**
- 모든 `fetch()` → `useApi` 훅으로 전환
- 에러 토스트 알림 시스템 추가

**R4.3 i18n 완성**
- 나머지 40개 하드코딩 문자열 번역
- 날짜/숫자 포맷 로케일 대응

**R4.4 컴포넌트 분리**
- Dashboard.tsx (340줄) → 7개 서브 컴포넌트로 분리
- 공통 컴포넌트: Card, MetricCard, DataTable, Toast

### Phase R5: 보안 강화 (3일)

**R5.1 인증 미들웨어**
- 대시보드/API에 기본 인증 추가 (API Key 또는 JWT)

**R5.2 Rate Limiting**
- FastAPI 미들웨어로 엔드포인트별 Rate Limit

**R5.3 비밀번호 정리**
- config.py 기본값에서 하드코딩 제거
- .env.example만 유지, .env는 배포 시 생성

### Phase R6: 인프라 보완 (3일)

**R6.1 Grafana 대시보드 확장**
- 포트폴리오 성과 대시보드
- API 응답 시간 대시보드
- 거래 실행 대시보드

**R6.2 DB 스키마 보강**
- CHECK 제약 조건 추가 (score -1~1, status ENUM 등)
- 누락 인덱스 추가

**R6.3 Redis 설정 정리**
- 미사용 redis.conf 삭제 또는 docker-compose에서 활용

---

## 4. 우선��위 정리 (2026-03-30 완료)

| 순위 | 작업 | 상태 | 주요 성과 |
|---|---|---|---|
| 1 | 의존성 주입 전환 | ✅ 완료 | 전체 라우트 + 내부 모듈 Depends() 패턴, 싱글톤 제거 |
| 2 | 하드코딩 설정 외부화 | ✅ 완료 | 15개 설정 추가 (initial_capital, timeout, sizing 등) |
| 3 | 거대 함수 분리 | ✅ 완료 | 8개 함수 서브함수로 분리 |
| 4 | 에러 처리 체계화 | ✅ 완료 | 재시도 유틸, DB 트랜잭션, ExternalAPIError 활용 |
| 5 | Prometheus 메트릭 | ✅ 완료 | HTTP + 비즈니스 메트릭 6종 실시간 수집 |
| 6 | 테스트 강화 | ✅ 완료 | 784 테스트, 72% 커버리지 (목표 60% 초과) |
| 7 | 프론트엔드 i18n | ✅ 완료 | 40+ 문자열 번역, fetch→apiGet 전환 |
| 8 | 보안 강화 | ✅ 완료 | CORS, 엔드포인트별 Rate Limit, 보안 헤더 4종 |
| 9 | Grafana 대시보드 | ✅ 완료 | 비즈니스 메트릭 패널 5개 추가 |
| 10 | DB 제약/인덱스 | ✅ 완료 | CHECK 제약 8개, 인덱스 2개 추가 |
| 11 | 종목 검색 | ✅ 완료 | /market/search API + StockSearch 자동완성 컴포넌트 |
| 12 | 전 종목 적재 | ✅ 완료 | KRX KOSPI 837 + KOSDAQ 1,782 = 2,619종목, /collect/stocks 매일 자동 업데이트 |
| 13 | 시장 변동 알림 | ✅ 완료 | /alert/scan — 가격급변/뉴스급증/주요공시 감지 → 카카오톡+텔레그램 알림 |

---

## 5. 외부 감사 결과 (2026-03-30)

두 건의 독립 감사를 받았으며 (`docs/plan-audit/` by Claude, `plan_audit_gemini/` by Gemini),
리팩토링 전후 상태를 교차 검증하였다.

### 5.1 두 감사 공통 합의 사항

| 항목 | 양쪽 평가 | 현재 상태 |
|---|---|---|
| Core Engine (37 엔드포인트) | Match | ✅ 완료 |
| Docker 인프라 (8 서비스) | Match | ✅ 완료 |
| DB 스키마 + 제약조건 | Match | ✅ 완료 |
| Redis Pub/Sub 발행 | Match | ✅ 동작 |
| React 대시보드 | Match | ✅ 완료 |
| **n8n 워크플로우 (1/10)** | **Gap** | ❌ 최대 갭 |
| **WebSocket 실시간** | **Gap** | ❌ 미구현 |
| NLP 센티먼트 경로 | Partial | ⚠️ Python 직접 호출 (계획: n8n AI Node) |

### 5.2 두 감사가 다른 부분

| 항목 | Claude 감사 (리팩 전) | Gemini 감사 (리팩 후) | 현재 실제 |
|---|---|---|---|
| Grafana 대시보드 | Gap (empty JSON) | Match (20+ panels) | ✅ 20+ 패널 동작 |
| 인라인 스타일 | heavy inline | Match (CSS) | ✅ 206→44 (78% 감소) |
| i18n | Partial | Match | ✅ 157개 번역 키 |
| 전체 완성도 | 수치 없음 | 65% | **~75%** (자체 평가) |

### 5.3 완성도 자체 평가

| 영역 | 완성도 | 근��� |
|---|---|---|
| Core Engine | 95% | 37 엔드포인트, DI, 재시도, 트랜잭션, 784 테스트, 72% 커버리지 |
| Infrastructure | 90% | 8 서비스 healthy, Prometheus 수집, DB 제약 |
| Dashboard | 85% | 6 페이지, i18n, CSS 클래스, StockSearch |
| Monitoring | 75% | Grafana 20+ 패널, n8n 메트릭 대시보드 부족 |
| Security | 80% | CORS, Rate Limit, 보안 헤더 (JWT 미구현) |
| **n8n Workflows** | **10%** | 1/10 워크플로우 |
| **실시간 시세** | **5%** | REST 폴링만, WebSocket 미구현 |

---

## 6. 실시간 주가 수신 현황 분석

### 6.1 현재 구조 (REST 폴링)

```
KIS REST API ←── get_current_price() ←── n8n (1분 스케줄) 또는 수동 버튼
      │
      ├── TimescaleDB 저장
      ├── Redis Pub/Sub 발행 (ohlcv:{code}) ← 소비자 없음
      │
Dashboard ─── 60초 setInterval 또는 수동 ─── GET /market/prices
```

### 6.2 컴포넌트별 상태

| 구성요소 | 상태 | 설명 |
|----------|------|------|
| KIS REST 시세조회 | ✅ 동작 | `get_current_price()` — 요청당 1건 조회 |
| KIS WebSocket 실시간 | ❌ 미구현 | `wss://` 연결, 종목 구독, 틱 수신 없음 |
| Redis Pub/Sub 발행 | ✅ 동작 | `ohlcv:{code}` 채널에 가격 발행 |
| Redis Pub/Sub 구독 | �� 미구현 | 발행된 메시지를 소비하는 코드 없음 |
| FastAPI WebSocket | ❌ 미구현 | nginx `/ws` 프록시만 설정, 핸들러 없음 |
| 프론트엔드 WebSocket | ❌ 미구현 | useApi는 fetch 기반 |
| 프론트엔드 자동갱신 | ⚠️ 부분 | Market.tsx 60초 polling |
| config WS URL | ❌ 없��� | `KIS_WEBSOCKET_URL` 미정의 |

### 6.3 실시간 구현 필요 작업

```
KIS WebSocket (wss://) ──→ 백그라운드 태스크 ──→ Redis Pub/Sub
                                                       │
                                    ┌──────────────────┘
                                    ▼
                          FastAPI WebSocket /ws ──→ 프론트엔드 실시간 갱신
```

| 순서 | 작업 | 설명 |
|------|------|------|
| 1 | KIS WebSocket 클라이언트 | `wss://` 연결, 종목 구독, 틱 파싱 |
| 2 | 백그라운드 스트리밍 태스크 | lifespan에서 asyncio.create_task 상시 실행 |
| 3 | Redis → WebSocket 브릿지 | Pub/Sub 구독 → 연결 클라이언트 broadcast |
| 4 | FastAPI `/ws` 엔드포인트 | WebSocket 연결 관리 + 종목 필터링 |
| 5 | ���론트엔드 `useWebSocket` 훅 | 실시간 가격 반영 |
| 6 | config 확장 | `KIS_WEBSOCKET_URL`, 구독 코드 추가 |

---

## 7. 잔여 과제 (우선순위)

| 순위 | 과제 | 영향도 | ��태 |
|---|---|---|---|
| 1 | 실시간 주가 수신 (KIS WebSocket) | 핵심 기능 | ❌ 미구현 |
| 2 | n8n 워크플로우 확장 (9개) | 자동화 | ❌ 1/10 |
| 3 | 카카오톡 알림 실전 연동 | 사용자 경험 | ⚠️ API 구현됨, 토큰 관리 필요 |
| 4 | WebSocket 대시보드 실시간 | 사용자 경험 | ❌ 미구현 |
| 5 | JWT 인증 (API Key→JWT) | 보안 | ⚠️ 선택 |
| 6 | 센티먼트 경로 결정 | 아키텍처 | ⚠️ Python 직접 vs n8n |

---

---

## 8. 상용 준비도 평가 (Commercial Readiness)

외부 감사 `docs/commercial-readiness-report/`에서 10개 핵심 갭을 식별하였다.
현재 구현 상태를 대비하여 정직하게 평가한다.

### 판정: **상용 불가, 소액 파일럿 조건부 가능**

| 목적 | 판정 |
|------|------|
| 프로토타입 / 연구 / 페이퍼 트레이딩 | ✅ 충분 |
| 소액 실전 파일럿 (엄격 한도 내) | ⚠️ 조건부 — 아래 Phase A 완료 필요 |
| 상용급 자동매매 | ❌ 불가 — 아래 전체 로드맵 필요 |

### 8.1 핵심 갭 10가지 vs 현재 상태

| # | 갭 | 심각도 | 현재 상태 | 대응 |
|---|---|--------|----------|------|
| 1 | **리스크 정책 미정의** | 🔴 Critical | RiskManager에 한도 있으나 정책 문서/킬스위치 없음 | Phase A |
| 2 | **주문 상태 조정(Reconciliation) 없음** | 🔴 Critical | 주문 저장+포지션 갱신은 트랜잭션이나, 브로커 상태 확인/복구 없음 | Phase A |
| 3 | **내구성 이벤트 아키텍처 없음** | 🟠 High | Redis Pub/Sub만 사용 (fire-and-forget), 주문 이벤트 재생 불가 | Phase B |
| 4 | **데이터 품질 거버넌스 없음** | 🟠 High | 체감 검증 없음: 미수신/잘못된 가격/종목 변경/기업 이벤트 | Phase B |
| 5 | **재해 복구(DR) 미설계** | 🟠 High | 백업 없음, RTO/RPO 미정의, 페일오버 없음 | Phase B |
| 6 | **감사 추적(Audit Trail) 없음** | 🟠 High | orders 테이블에 기록하나 변조 방지/불변 로그 없음 | Phase A |
| 7 | **컴플라이언스 레이어 없음** | 🟡 Medium | 보존 정책/배포 승인/변경 관리 없음 | Phase C |
| 8 | **로컬 워크스테이션 의존** | 🟡 Medium | MacBook M1에서 전체 스택 실행 중 (Docker) | Phase A: VPS 이전 |
| 9 | **LLM 가드레일 없음** | 🟡 Medium | Claude/OpenAI 직접 호출, 타임아웃/비용 상한/폴백만 있음 | Phase C |
| 10 | **상용급 테스트 전략 없음** | 🟡 Medium | 784 테스트 72% 커버리지이나, 브로커 장애/세션 시뮬/카오스 테스트 없음 | Phase B |

### 8.2 상용화 로드맵 (3단계)

#### Phase A: 최소 실전 통제 패키지 (실전 배포 전 필수)

| # | 작업 | 설명 |
|---|------|------|
| A-1 | 리스크 정책 문서화 | 노출 한도, 손실 한도, 집중도 한도, 세션 제한을 코드에 강제 적용 |
| A-2 | 주문 상태 기계 (FSM) | created→submitted→acked→filled→cancelled 명확 정의, 멱등키 |
| A-3 | EOD 포지션/현금 조정 | 브로커 잔고 vs 내부 상태 일치 확인 자동화 |
| A-4 | 불량 데이터 차단 | 미수신/지연/이상 가격 감지 시 매매 차단 |
| A-5 | 킬 스위치 | 자동(일간 손실 초과) + 수동(API/대시보드) 긴급 정지 |
| A-6 | 불변 감사 로그 | 모든 매매 결정/브로커 응답/수동 조작을 append-only 저장 |
| A-7 | 버전 고정 | Docker 이미지, 의존성, LLM 모델 버전 핀 |
| A-8 | VPS 실행 분리 | 실전 매매는 MacBook이 아닌 전용 서버에서 실행 |

#### Phase B: 운영 경화

| # | 작업 |
|---|------|
| B-1 | 백업/복원/RTO/RPO 정의 및 테스트 |
| B-2 | 주문/포지션 이벤트 내구성 저장 (Redis → Redis + WAL/DB) |
| B-3 | 장애 대응 런북 (브로커 장애, 데이터 장애, 중복 주문, 재시작 복구) |
| B-4 | 시크릿 로테이션, RBAC, 이미지 스캔, 의존성 취약점 관리 |
| B-5 | 전략/코드 릴리즈 배포 승인 게이트 |

#### Phase C: 연구 거버넌스

| # | 작업 |
|---|------|
| C-1 | 전략 프로모션 기준: 연구→페이퍼→섀도우→소액→증액 |
| C-2 | Walk-forward 검증, 레짐 테스트 |
| C-3 | 슬리피지/회전율/지연/용량을 전략 메트릭으로 추적 |
| C-4 | LLM 프롬프트/결과 버전 관리, 비용 상한, 프로바이더 장애 폴백 |

### 8.3 현실적 권고

> **현재 시스템은 "잘 만들어진 프로토타입"이다.**
> 소액 실전 파일럿(Phase A 완료 후)까지는 가능하지만,
> 상용급 자동매매를 주장하려면 Phase A-B-C 전체와 별도 법률/규제 검토가 필요하다.

핵심 아키텍처 가정 변경 필요:
- `MacBook 실행` → **서버 우선 실행**
- `Redis Pub/Sub만` → **Redis + 내구성 이벤트 저장**
- `대시보드 모니터링` → **모니터링 + 런북 + 자동 세이프가드**
- `리스크 엔진 언급` → **리스크 정책 정의/인코딩/테스트 완료**
- `페이퍼→실전` → **페이퍼→섀도우→소액→증액 단계적 이행**

---

## 9. 통합 우선순위 (잔여 과제 + 상용화)

| 순위 | 과제 | 분류 | 영향도 |
|---|---|---|---|
| 1 | 실시간 주가 수신 (KIS WebSocket) | 기능 | 핵심 기능 갭 |
| 2 | 킬 스위치 (자동+수동) | 상용 A-5 | 🔴 안전 |
| 3 | 리스크 정책 문서화 + 강제 적용 | 상용 A-1 | 🔴 안전 |
| 4 | 주문 FSM + 브로커 조정 | 상용 A-2,3 | 🔴 안전 |
| 5 | n8n 워크플로우 확장 (9개) | 자동화 | 아키텍처 갭 |
| 6 | 불변 감사 로그 | 상용 A-6 | 🟠 추적 |
| 7 | 불량 데이터 차단 | 상용 A-4 | 🟠 안전 |
| 8 | WebSocket 대시보드 실시간 | 기능 | 사용자 경험 |
| 9 | 버전 고정 + VPS 분리 | 상�� A-7,8 | 🟡 운영 |
| 10 | 백업/복원/DR | 상용 B-1 | 🟡 운영 |

---

## 10. Verification

리팩토링 후 검증 (2026-03-30 전체 통과):
```bash
# 1. 전체 테스트 통과
pytest tests/ -v --cov=app --cov-report=term-missing

# 2. 커버리지 60% 이상
pytest --cov=app --cov-fail-under=60

# 3. Docker 전체 기동
docker compose up -d && docker compose ps

# 4. 트레이딩 사이클 정상 동작
curl -X POST http://localhost:8000/trading/run-cycle

# 5. 대시보드 접속
curl -sf https://alphatrade.visualfactory.ai

# 6. 보안 테스트 (인증 없이 접근 차단)
curl -sf http://localhost:8000/order/execute  # → 401
```

---

## 11. 문서 산출물

리팩토링 과정에서 생성할 문서:
1. `docs/architecture.md` — 전체 아키텍처 설명
2. `docs/api-reference.md` — 32개 엔드포인트 API 문서
3. `docs/deployment.md` — 배포 가이드
4. `docs/trading-strategy.md` — 전략 알고리즘 설명
5. `CLAUDE.md` — 프로젝트 컨벤션 (코딩 스타일, 커밋 규칙)
