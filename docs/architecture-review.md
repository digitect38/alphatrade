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

## 5. Verification

리팩토링 후 검증:
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

## 6. 문서 산출물

리팩토링 과정에서 생성할 문서:
1. `docs/architecture.md` — 전체 아키텍처 설명
2. `docs/api-reference.md` — 32개 엔드포인트 API 문서
3. `docs/deployment.md` — 배포 가이드
4. `docs/trading-strategy.md` — 전략 알고리즘 설명
5. `CLAUDE.md` — 프로젝트 컨벤션 (코딩 스타일, 커밋 규칙)
