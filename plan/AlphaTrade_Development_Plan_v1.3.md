# ALPHATRADE — AI Quantitative Trading System

## AI 기반 주식 자동매매 시스템 개발 계획서

**Hybrid Architecture: Custom Code + No-Code/Low-Code Tools**

- 문서 버전: v1.3 (Post-Refactoring + Commercial Readiness)
- 작성일: 2026-03-30 (v1.3 업데이트)
- 작성자: digitect38@gmail.com
- 분류: Confidential

---

## 목차

1. [v1.1 변경 요약](#1-v11-변경-요약)
2. [설계 철학: Code vs Tool 판단 기준](#2-설계-철학-code-vs-tool-판단-기준)
3. [도구 생태계 상세](#3-도구-생태계-상세)
4. [Hybrid Architecture 상세 설계](#4-hybrid-architecture-상세-설계)
5. [인프라 구성 (Docker Compose)](#5-인프라-구성-docker-compose)
6. [수정된 개발 일정](#6-수정된-개발-일정)
7. [n8n ↔ 커스텀 코드 연동 패턴](#7-n8n--커스텀-코드-연동-패턴)
8. [비용 분석](#8-비용-분석)
9. [도구 선택 의사결정 매트릭스](#9-도구-선택-의사결정-매트릭스)
10. [툴 도입 관련 위험 요소 및 완화](#10-툴-도입-관련-위험-요소-및-완화)
11. [배포 환경: MacBook M1 Pro](#11-배포-환경-macbook-m1-pro)
12. [도구 비용 종합 비교](#12-도구-비용-종합-비교)
13. [n8n 경쟁 도구 비교](#13-n8n-경쟁-도구-비교)
14. [v1.3 리팩토링 성과 및 현재 상태](#14-v13-리팩토링-성과-및-현재-상태) *(New)*
15. [실시간 주가 수신 아키텍처](#15-실시간-주가-수신-아키텍처) *(New)*
16. [상용 준비도 평가 및 로드맵](#16-상용-준비도-평가-및-로드맵) *(New)*
17. [통합 우선순위 (Next Actions)](#17-통합-우선순위-next-actions) *(New)*
18. [문서 이력](#18-문서-이력)

---

## 1. v1.1 변경 요약

v1.0의 순수 코드 기반 설계에서 n8n, Grafana, TradingView 등 No-Code/Low-Code 툴을 통합한 Hybrid Architecture로 전환한다. 핵심 분석 엔진은 커스텀 Python 코드로 유지하되, 데이터 수집, 알림, 모니터링, 리포트 생성 등의 영역은 적절한 툴로 대체하여 개발 속도와 유지보수성을 크게 향상시킨다.

| 변경 영역 | v1.0 (순수 코드) | v1.1 (Hybrid) |
|---|---|---|
| 데이터 수집/파이프라인 | Python cron + asyncio | n8n 워크플로우 + Python 코어 엔진 |
| 뉴스 크롤링 | Python 크롤러 직접 구현 | n8n HTTP Request + RSS 노드 |
| 알림/통보 | Telegram Bot API 직접 연동 | n8n Telegram/Slack/Email 노드 |
| 시스템 모니터링 | Custom logging | Grafana + Prometheus |
| 시각화 대시보드 | React 전체 커스텀 | React(분석 대시보드) + Grafana(운영 모니터링) |
| 리포트 생성 | Python 스크립트 | n8n 워크플로우 (LLM 요약 + 이메일 발송) |
| 차트 신호 수신 | - | TradingView Webhook → n8n → 전략 엔진 |
| 배치 파이프라인 | cron + systemd | n8n Schedule Trigger + Airflow(선택) |

---

## 2. 설계 철학: Code vs Tool 판단 기준

모든 기능을 코드로 작성하는 것도, 모든 것을 No-Code 툴로 해결하려는 것도 최적이 아니다. 본 프로젝트에서는 아래의 기준으로 커스텀 코드와 툴 사용을 구분한다.

| 기준 | 커스텀 코드 (Python/React) | No-Code/Low-Code 툴 (n8n, Grafana 등) |
|---|---|---|
| 성능 요구 | 밀리초 단위 처리, 대량 연산 필요 | 초~분 단위 처리로 충분 |
| 비즈니스 로직 | 복잡한 알고리즘, 통계 모델 | 단순 조건 분기, 데이터 전달 |
| 확장성 | 비정형 요구사항, 잦은 변경 | 안정적인 파이프라인, 적은 변경 |
| 유지보수 | 테스트 코드 필수, 디버깅 복잡 | 비주얼 편집, 즉시 확인 |
| 예시 | 지표 계산, 전략 엔진, 백테스트, 주문 FSM | 뉴스 수집, 알림, 리포트, 모니터링 |

> **핵심 원칙**: "투자 판단에 직접 영향을 미치는 분석 엔진은 반드시 커스텀 코드로 구현하고, 그 주변의 운영/통합 작업은 툴로 빠르게 처리한다."

---

## 3. 도구 생태계 상세

### 3.1 n8n — 워크플로우 자동화 허브

n8n은 오픈소스 워크플로우 자동화 플랫폼으로, 1,100개 이상의 커넥터와 비주얼 노드 기반 에디터를 제공한다. 셀프호스팅이 가능하여 데이터 주권을 유지할 수 있으며, AI 노드(OpenAI, Anthropic 연동), HTTP Request, 코드 실행 노드 등을 통해 유연한 확장이 가능하다.

#### 3.1.1 활용 영역별 워크플로우 설계

| Workflow | 트리거 | 처리 흐름 | 출력 |
|---|---|---|---|
| **WF-01: 뉴스 수집** | Schedule (1분) | RSS Feed → HTTP Request(네이버 금융) → HTML Extract → Code(전처리) → DB Insert(TimescaleDB) | 정규화된 뉴스 데이터 저장 |
| **WF-02: 공시 수집** | Schedule (1분) | HTTP Request(DART API) → Code(공시 파싱) → IF(주요공시 필터) → DB Insert + Webhook(전략 엔진 트리거) | 공시 이벤트 저장 + 전략 트리거 |
| **WF-03: 센티먼트 분석** | Webhook (WF-01 후) | DB Read(새 뉴스) → AI Node(Claude/GPT: 감성 분석) → Code(점수화) → DB Update(센티먼트 점수) | 종목/섹터별 센티먼트 스코어 |
| **WF-04: 시세 수집** | Schedule (1분, 장중) | HTTP Request(증권사 API) → Code(정규화) → DB Insert → Redis Publish | 실시간 OHLCV 데이터 저장 |
| **WF-05: 매매 알림** | Webhook(전략 엔진) | IF(신호 유형) → Switch → Telegram(체결) / Email(손절) / Slack(시스템) | 다채널 알림 발송 |
| **WF-06: 일일 리포트** | Schedule (매일 16:30) | DB Read(일간 성과) → AI Node(성과 요약) → Code(HTML 리포트) → Email + Telegram | AI 요약 포함 일간 성과 리포트 |
| **WF-07: 시스템 건강체크** | Schedule (5분) | HTTP Request(API 헬스체크) → IF(장애) → Telegram(경고) + Grafana(어노테이션) | 장애 조기 감지 |
| **WF-08: TradingView 신호** | Webhook(TradingView Alert) | Code(신호 파싱) → HTTP Request(전략 엔진 API) → IF(실행결과) → Telegram | TradingView 차트 신호 → 전략 트리거 |
| **WF-09: 주간 전략 리뷰** | Schedule (토요일 09:00) | DB Read(주간 성과) → AI Node(전략별 성과 분석) → Code(Markdown) → Email + Google Sheets | 주간 전략 성과 분석 리포트 |
| **WF-10: 유니버스 갱신** | Schedule (매일 16:00) | DB Read(전 종목) → Code(필터링 로직) → DB Update(유니버스) → Telegram(변경사항) | 다음 거래일 매매 후보 종목군 |

#### 3.1.2 n8n 배포 및 운영

| 항목 | 사양 |
|---|---|
| 배포 방식 | Docker Compose (self-hosted), PostgreSQL 백엔드 |
| 하드웨어 요구 | 4 CPU cores, 8GB RAM, 50GB SSD (프로덕션 기준) |
| 워크플로우 관리 | Git 기반 버전 관리 (n8n CLI export/import) |
| 모니터링 | n8n 실행 이력 + Grafana 연동 (워크플로우 성공/실패율) |
| 보안 | API 키 암호화 저장, 내부 네트워크만 접근 허용 |
| 장애 대응 | 워크플로우 실패 시 자동 재시도 (3회), 실패 지속 시 Telegram 알림 |

#### 3.1.3 n8n Code 노드 활용 패턴

- **n8n Code 노드**: 데이터 변환, 필터링, 포맷팅 등 경량 처리
- **n8n Execute Command**: Python 스크립트 호출 (지표 계산, NLP 분석 등 복잡 처리)
- **n8n HTTP Request**: 커스텀 전략 엔진 REST API 호출 (FastAPI 기반)
- **n8n AI Agent 노드**: Claude/GPT를 활용한 센티먼트 분석, 리포트 생성

### 3.2 Grafana — 운영 모니터링 대시보드

Grafana는 시계열 데이터 시각화에 특화된 오픈소스 플랫폼이다. 투자 분석 대시보드는 React로 커스텀 구축하되, 시스템 운영 모니터링은 Grafana로 분리하여 각각의 강점을 활용한다.

| Grafana 대시보드 | 주요 패널 | 데이터 소스 |
|---|---|---|
| 시스템 헬스 | CPU/RAM 사용량, 디스크 I/O, 네트워크 트래픽, 컨테이너 상태 | Prometheus (node_exporter) |
| API 모니터링 | 증권사 API 응답 시간, 요청 성공/실패율, Rate Limit 상태 | Prometheus (custom exporter) |
| n8n 워크플로우 상태 | 워크플로우별 실행 횟수, 성공/실패율, 평균 실행 시간 | n8n Metrics + Prometheus |
| 트레이딩 성과 | 일간 수익률, 누적 수익 곡선, MDD 추이, Sharpe Ratio | TimescaleDB |
| 주문 실행 품질 | 체결율, 평균 슬리피지, 주문 처리 지연, 미체결 비율 | TimescaleDB |
| 알림 이력 | Grafana Alert Rules: API 장애, 손절 발동, MDD 초과 등 | Prometheus Alertmanager |

**Grafana Alert Rules 예시:**
- API 응답 시간 > 3초 → Warning
- API 연속 3회 실패 → Critical + Telegram 알림
- 일간 손실 > -2% → 거래 중단 및 관리자 알림

### 3.3 TradingView — 차트 분석 및 Webhook 신호

TradingView는 Pine Script 기반 커스텀 지표/전략 작성과 Webhook Alert 기능을 제공한다. 전략 엔진의 보조 신호 소스로 활용하여, 차트 패턴 기반 신호를 n8n을 거쳐 전략 엔진에 전달한다.

| 활용 영역 | 설명 | 연동 방식 |
|---|---|---|
| Pine Script 커스텀 지표 | 복잡한 차트 패턴(컨플루언스, 하모닉스 등) 작성 | TradingView 내부 |
| Webhook Alert | Pine Script 조건 충족 시 JSON 페이로드 전송 | TradingView → n8n Webhook → 전략 엔진 |
| 차트 이미지 분석 | 차트 스크린샷을 LLM Vision으로 분석 | Chart-Img API → n8n → Claude Vision |
| 멀티 타임프레임 | 일봉/주봉/월봉 동시 감시 및 Alert 설정 | TradingView Alert → n8n |

> **주의**: TradingView Webhook → n8n → 전략 엔진 파이프라인은 보조 신호로만 활용하며, 최종 매매 판단은 반드시 자체 전략 엔진의 앙상블 결과에 의해 결정된다.

### 3.4 기타 도구

| 도구 | 역할 | 적용 시점 | 대안 |
|---|---|---|---|
| Prometheus | 메트릭 수집 및 저장, Alert Rules | Phase 0부터 | - |
| Redis | 실시간 시세 캐시, 모듈간 Pub/Sub 메시지 버스 | Phase 1부터 | - |
| TimescaleDB | 시계열 데이터 저장 (OHLCV, 성과) | Phase 1부터 | InfluxDB |
| Jupyter Notebook | 전략 탐색/프로토타이핑, EDA | 전 Phase | VS Code + Python |
| Apache Airflow | 복잡한 데이터 파이프라인 오케스트레이션 (DAG) | Phase 3+ (선택적) | n8n으로 충분하면 불필요 |
| Google Sheets | 간단한 데이터 기록, 수동 종목 관리 | Phase 1부터 | Airtable, Notion DB |
| Portainer | Docker 컨테이너 관리 UI | Phase 0부터 | Docker Desktop |
| Uptime Kuma | 서비스 가용성 모니터링 | Phase 5부터 | Grafana 헬스체크 |

---

## 4. Hybrid Architecture 상세 설계

### 4.1 전체 시스템 구성도

시스템은 3개의 주요 영역으로 구분된다: **n8n 워크플로우 자동화 영역**, **커스텀 코어 엔진 영역**, **모니터링/시각화 영역**이다.

| 영역 | 구성 요소 | 도구/기술 | 역할 |
|---|---|---|---|
| ① 데이터 수집 (n8n) | WF-01~04, Schedule/Webhook Triggers | n8n + HTTP Request + Code Node | 시세, 뉴스, 공시, TradingView 신호 수집 |
| ② 분석 엔진 (Python) | 기술적 분석, 섹터 분석, 상관/인과, 거래량 | Python + FastAPI + scipy/numpy | 다차원 시장 분석, 특징 추출 |
| ③ NLP 센티먼트 (Hybrid) | n8n WF-03 + KoBERT 모델 | n8n AI Node + Python | n8n으로 트리거/라우팅, Python으로 분석 |
| ④ 전략 엔진 (Python) | 앙상블 신호 생성, 백테스트 | Python + vectorbt | 복합 전략 신호 → BUY/SELL/HOLD |
| ⑤ 실행 엔진 (Python) | 주문 FSM, 리스크 관리 | Python + XState-py or custom FSM | 주문 생성/실행/관리, 손절/익절 |
| ⑥ 브로커 연동 (Python) | 한국투자증권 OpenAPI Gateway | Python + httpx | 실제 주문 전송/체결 확인 |
| ⑦ 알림/리포트 (n8n) | WF-05~09 | n8n + Telegram + Email + AI Node | 다채널 알림, AI 요약 리포트 |
| ⑧ 모니터링 (Grafana) | 시스템/API/성과 대시보드 | Grafana + Prometheus | 운영 모니터링, 알러트 |
| ⑨ 분석 대시보드 (React) | 투자 분석 UI | React + Recharts + TailwindCSS | 기술적 분석, 시그널, 포트폴리오 |

### 4.2 모듈간 통신 방식

| 통신 경로 | 방식 | 설명 |
|---|---|---|
| n8n → 분석 엔진 | HTTP Request (동기 REST API) | n8n이 수집한 데이터를 FastAPI 엔드포인트로 전달 |
| 분석 엔진 → n8n | Webhook Trigger (비동기) | 전략 엔진이 시그널 생성 시 n8n Webhook 호출 |
| 분석 엔진 ↔ DB | SQL (asyncpg) | TimescaleDB 직접 접근 |
| 모듈간 실시간 | Redis Pub/Sub | 실시간 시세, 시그널 이벤트 발행/구독 |
| React 대시보드 ↔ 백엔드 | WebSocket + REST API | 실시간 차트 업데이트, 전략 파라미터 조작 |
| Prometheus → Grafana | PromQL 스크레이핑 | 메트릭 수집 → Grafana 시각화 |

---

## 5. 인프라 구성 (Docker Compose)

전체 시스템은 Docker Compose로 통합 관리하며, 각 컨테이너는 독립적으로 시작/정지/재시작이 가능하다.

| 컨테이너 | 이미지 | 포트 | 의존성 |
|---|---|---|---|
| timescaledb | timescale/timescaledb:latest-pg16 | 5432 | - |
| redis | redis:7-alpine | 6379 | - |
| n8n | n8nio/n8n:latest | 5678 | timescaledb, redis |
| core-engine | custom (Python 3.12 + FastAPI) | 8000 | timescaledb, redis |
| dashboard | custom (React + Nginx) | 3000 | core-engine |
| prometheus | prom/prometheus:latest | 9090 | core-engine, n8n |
| grafana | grafana/grafana:latest | 3001 | prometheus, timescaledb |
| portainer | portainer/portainer-ce | 9000 | - |

- 전체 컨테이너는 동일한 Docker 네트워크(`alphatrade-net`)에 속하며, 컨테이너명으로 서비스 디스커버리가 가능하다.
- 외부 접근은 Nginx 리버스 프록시를 통해 통제한다.
- 증권사 API 키 등 민감 정보는 Docker Secrets 또는 `.env` 파일로 관리한다.

---

## 6. 수정된 개발 일정

n8n 등 툴 도입으로 일부 Phase의 개발 기간이 단축된다. 특히 데이터 수집, 알림, 리포트 관련 작업이 크게 간소화된다.

| Phase | 기간 | 주요 작업 | 툴 활용 |
|---|---|---|---|
| **P0. 환경 구축** | 1~2주차 | Docker Compose 구성, DB 스키마, API 키, n8n 설치 | Docker, n8n, Portainer, Grafana 초기 설정 |
| **P1. 데이터 파이프라인** | 3~4주차 (−2주) | WF-01~04 구축, 데이터 정규화 | n8n 워크플로우로 빠른 구축 |
| **P2. 분석 엔진 Core** | 5~9주차 | 기술적 지표, 거래량, 섹터 분석 | Python 코어 (변경 없음) |
| **P3. 분석 엔진 Advanced** | 10~13주차 (−1주) | NLP 센티먼트, 상관/인과, 신호처리 | n8n AI Node로 센티먼트 파이프라인 간소화 |
| **P4. 전략 엔진 + 백테스트** | 14~17주차 | 앙상블, 백테스트, TradingView 연동 | n8n WF-08(TradingView Webhook) |
| **P5. 실행 엔진 + 리스크** | 18~20주차 (−1주) | 주문 FSM, 리스크, 브로커 연동 | n8n WF-05(알림) 바로 연동 |
| **P6. 대시보드 + 알림** | 21~22주차 (−2주) | React 분석 대시보드, Grafana 운영 대시보드 | Grafana 함께 사용으로 React 개발량 감소 |
| **P7. 모의투자** | 23~34주차 | 실전 데이터 모의매매, 성과 측정 | n8n WF-06,09(자동 리포트), Grafana |
| **P8. 실전 투입** | 35주차~ | 소액 실전 매매, 점진적 증액 | 전체 툴 스택 운영 |

> **전체 개발 기간**: v1.0 대비 약 6주 단축 (24주 → 22주). n8n으로 데이터 수집, 알림, 리포트 개발 기간이 크게 단축되며, Grafana 도입으로 운영 대시보드 개발을 별도로 할 필요가 없어진다.

---

## 7. n8n ↔ 커스텀 코드 연동 패턴

### 7.1 FastAPI 코어 엔진 API 설계

n8n에서 호출할 커스텀 분석 엔진 API 엔드포인트를 정의한다. FastAPI 기반으로 구현하며, n8n의 HTTP Request 노드에서 호출한다.

| 엔드포인트 | 메서드 | 설명 | 호출원 |
|---|---|---|---|
| `POST /analyze/technical` | POST | 종목 기술적 지표 산출 | n8n WF-04 후 또는 주기적 |
| `POST /analyze/sentiment` | POST | 뉴스 텍스트 센티먼트 분석 | n8n WF-03 |
| `POST /analyze/correlation` | POST | 종목간 상관/인과 분석 | n8n 일간 배치 |
| `POST /strategy/signal` | POST | 앙상블 시그널 생성 | n8n Schedule / Webhook |
| `POST /order/execute` | POST | 주문 생성 및 실행 | 전략 엔진 내부 |
| `GET /portfolio/status` | GET | 현재 포트폴리오 상태 | React 대시보드 |
| `GET /metrics` | GET | Prometheus 메트릭 노출 | Prometheus |
| `POST /webhook/tradingview` | POST | TradingView Alert 수신 | n8n WF-08 경유 |

### 7.2 n8n ↔ Python 스크립트 연동 패턴

n8n 내부에서 Python 스크립트를 호출하는 3가지 패턴을 상황에 따라 사용한다.

| 패턴 | 사용 시나리오 | 장점 | 단점 |
|---|---|---|---|
| **패턴 A: HTTP Request → FastAPI** | 복잡한 분석, 상시 구동 서비스 | 성능 최고, 비동기 처리, 확장성 | 별도 서버 필요 |
| **패턴 B: Execute Command** | 단발성 스크립트 (배치 분석) | 간편, n8n 컨테이너 내 실행 | 동기 실행, 타임아웃 주의 |
| **패턴 C: n8n Code Node + npm** | 경량 데이터 변환 | 빠른 실행, 추가 의존성 없음 | JS만 가능, 복잡한 분석 불가 |

> **권장 조합**: 분석 엔진은 패턴 A (FastAPI 상시 구동)를 기본으로 사용하고, 일간 배치 작업(상관 행렬 재계산 등)은 패턴 B로 보조한다.

---

## 8. 비용 분석

전체 시스템을 셀프호스팅으로 운영할 경우 예상 비용이다.

| 항목 | 월간 비용 | 비고 |
|---|---|---|
| 서버 (VPS/NAS) | ₩30,000~50,000 | 4 Core, 16GB RAM, 200GB SSD 기준 |
| n8n | 무료 (Self-hosted) | 오픈소스 라이선스 |
| Grafana | 무료 (Self-hosted) | 오픈소스 |
| TimescaleDB | 무료 (Self-hosted) | 오픈소스 |
| TradingView | ₩15,000~30,000 | Pro/Pro+ 플랜 (Webhook Alert 필요) |
| 한국투자증권 API | 무료 | API 이용료 무료, 거래 수수료 별도 |
| LLM API (Claude/GPT) | ₩10,000~30,000 | 센티먼트 분석 + 리포트 생성 사용량 기준 |
| DART API | 무료 | 공시 데이터 |
| Telegram Bot | 무료 | 무제한 |
| **월간 총 예상** | **₩55,000~110,000** | 성격에 따라 변동 |

---

## 9. 도구 선택 의사결정 매트릭스

새로운 기능이 필요할 때, 커스텀 코드로 구현할지 n8n 워크플로우로 처리할지를 판단하는 기준이다.

| 판단 질문 | Yes → | No → |
|---|---|---|
| 처리 지연 100ms 이하 필요? | 커스텀 코드 | 다음 질문 |
| 복잡한 수학/통계 연산? | 커스텀 코드 (Python) | 다음 질문 |
| 외부 API 연동 + 조건 분기? | n8n 워크플로우 | 다음 질문 |
| 스케줄 기반 반복 작업? | n8n Schedule Trigger | 다음 질문 |
| 알림/통보 발송? | n8n Telegram/Email 노드 | 다음 질문 |
| 메트릭/시계열 시각화? | Grafana | React 대시보드 |
| 투자 분석 UI? | React + Recharts | - |

---

## 10. 툴 도입 관련 위험 요소 및 완화

| 위험 요소 | 영향도 | 완화 전략 |
|---|---|---|
| n8n 성능 병목 | 중 | n8n은 데이터 라우팅만 담당, 복잡한 계산은 FastAPI 위임. n8n 컨테이너 리소스 충분히 할당. |
| n8n 워크플로우 장애 | 상 | WF-07(건강체크) + Grafana Alert로 장애 조기 감지. 핵심 기능(주문 실행)은 Python 직접 구현. |
| n8n 버전 업그레이드 | 중 | Docker 이미지 버전 고정, 업그레이드 전 백업 및 테스트 환경 검증 |
| 툴간 데이터 불일치 | 중 | TimescaleDB를 Single Source of Truth로 설정, 툴간 데이터는 DB 기준으로 동기화 |
| Grafana 학습 곡선 | 하 | 기본 대시보드 템플릿 활용, 점진적 커스터마이징 |
| TradingView 유료 플랜 의존 | 하 | TradingView는 보조 신호원으로만 사용, 핵심 로직은 자체 엔진에 의존 |

---

## 11. 배포 환경: MacBook M1 Pro

본 프로젝트의 개발/모의투자/초기 실전 서버로 MacBook Pro (M1 Pro, 16GB RAM, 2TB SSD)를 사용한다. Apple Silicon 환경의 특성과 제약을 고려한 배포 전략을 수립한다.

### 11.1 하드웨어 사양 및 적합성 평가

| 항목 | 사양 | 평가 |
|---|---|---|
| CPU | Apple M1 Pro (8P+2E cores) | 충분 — 분석 엔진 + Docker 컨테이너 동시 운영 가능 |
| RAM | 16GB Unified Memory | 빠듯 — 전체 스택 동시 구동 시 10~14GB 점유, 여유 적음 |
| SSD | 2TB NVMe | 충분 — 10년치 일봉 + 1년치 분봉 데이터 저장에 문제없음 |
| 네트워크 | Wi-Fi 6 / Thunderbolt 이더넷 | 유선 권장 — USB-C 이더넷 어댑터 사용 |
| 전원 | 배터리 + 충전기 | UPS 효과 — 단, 장시간 운영 시 전원 연결 필수 |

### 11.2 RAM 할당 계획 (16GB)

16GB 통합 메모리에서 각 컨테이너의 메모리 할당을 명시적으로 제한하여 스왑 발생을 방지한다. Docker Compose의 `mem_limit` 설정을 활용한다.

| 컨테이너 | 할당 RAM | 비고 |
|---|---|---|
| macOS 시스템 | ~4.5GB | 고정 점유 (OS + WindowServer) |
| OrbStack (Docker 런타임) | ~0.5GB | Docker Desktop 대비 절반 이하 |
| TimescaleDB | 2.5GB | shared_buffers=1GB, effective_cache=1.5GB |
| Redis | 0.3GB | maxmemory 256MB 설정 |
| n8n | 1.5GB | 워크플로우 10개 기준 |
| FastAPI 코어 엔진 | 2.0GB | pandas/numpy/scipy 로딩 포함 |
| Grafana + Prometheus | 0.7GB | Prometheus retention 15일 제한 |
| React 대시보드 (Nginx) | 0.1GB | 정적 서빙 |
| **합계** | **~12.1GB** | **여유 ~3.9GB (브라우저/IDE 최소한 사용)** |

> **주의**: 브라우저와 IDE를 동시에 열면 스왑이 발생할 수 있다. 장중 실전 매매 시에는 불필요한 애플리케이션을 종료하고, 모니터링은 태블릿/휴대폰의 Grafana 웹 UI로 대체하는 것을 권장한다.

### 11.3 Docker 환경: OrbStack 권장

Apple Silicon Mac에서 Docker를 실행하는 3가지 방법을 비교한다.

| 항목 | Docker Desktop | Colima | OrbStack (권장) |
|---|---|---|---|
| 메모리 사용량 | 높음 (2~4GB) | 중간 (1~2GB) | 낮음 (0.3~0.8GB) |
| 시작 속도 | 느림 (30초+) | 중간 (15초) | 빠름 (2~3초) |
| ARM 네이티브 | 지원 | 지원 | 최적화 |
| 비용 (개인) | 무료 | 무료 (OSS) | 무료 (개인용) |
| 설정 난이도 | 쉬움 (GUI) | 수동 (CLI) | 쉬움 (GUI+CLI) |
| Docker Compose | 내장 | 별도 설치 | 내장 |

> OrbStack은 M1/M2 Mac에 최적화된 Docker 런타임으로, Docker Desktop 대비 RAM 사용량이 1/4 수준이며 컨테이너 시작 속도도 10배 이상 빠르다. 16GB RAM 환경에서는 이 차이가 결정적이다.

### 11.4 실전 매매 서버 운영 요건

맥북을 24시간 서버로 운영할 때 반드시 설정해야 하는 항목들이다.

| 항목 | 설정 방법 | 중요도 |
|---|---|---|
| 절전/슬립 방지 | `caffeinate -disu` 명령어 상시 실행, 또는 Amphetamine 앱 설치. 시스템 설정 > 디스플레이 > 절전 '안 함' 설정 | 필수 |
| 자동 업데이트 비활성화 | 시스템 설정 > 소프트웨어 업데이트 > 자동 설치 모두 해제. `sudo softwareupdate --schedule off` | 필수 |
| 유선 네트워크 | USB-C 이더넷 어댑터 사용. Wi-Fi 대비 간헐적 끊김 방지 | 권장 |
| 클램셸 모드 | 뚜껑 닫고 외부 모니터 연결. 발열 관리 우수, 책상 공간 절약 | 권장 |
| Docker 자동 시작 | OrbStack 로그인 시 자동 시작 설정. Docker Compose `restart: always` 정책 | 필수 |
| 외부 접근 (Webhook) | Cloudflare Tunnel 설정 — 포트포워딩 없이 안전한 외부 접근. TradingView Webhook, Telegram Bot 수신용 | 권장 |
| UPS (무정전 전원) | 내장 배터리가 간이 UPS 역할. 장시간 정전 대비 시 별도 UPS 구비 | 선택 |
| 방화벽/보안 | macOS 방화벽에서 Docker 포트만 허용. 외부 접근은 Cloudflare Tunnel 경유만 허용 | 필수 |

### 11.5 실전 매매 시 권장 아키텍처: 주문 실행 분리

맥북을 서버로 사용할 때 가장 큰 위험은 슬립, 네트워크 끊김, macOS 업데이트 등으로 장중 시스템이 중단되는 것이다. 이를 방지하기 위해 모의투자 이후 실전 단계에서는 주문 실행 엔진을 분리하는 것을 권장한다.

| 역할 | 위치 | 구성 요소 | 비용 |
|---|---|---|---|
| 분석/모니터링 허브 | MacBook M1 Pro (로컬) | n8n, FastAPI 분석 엔진, TimescaleDB, Grafana, React 대시보드 | ₩0 (기존 장비) |
| 주문 실행 노드 | 클라우드 VPS (서울 리전) | 주문 FSM + 브로커 API Gateway + Redis(신호 수신) + 손절/익절 감시 | 월 ₩3~5만 |

- **통신**: MacBook → VPS는 Redis Pub/Sub 또는 REST API 경유. 시그널 발생 시 MacBook이 VPS의 `/order/execute` API를 호출
- **VPS 독립 동작**: MacBook이 끊겨도 VPS는 기존 포지션의 손절/익절 감시를 독립적으로 수행
- **Phase 7(모의투자)까지는 MacBook 단독 운영, Phase 8(실전)부터 VPS 분리**
- **비상 시나리오**: MacBook 장애 시 VPS가 자동으로 전체 포지션 보호 모드(신규 진입 차단, 기존 손절만 관리) 진입

### 11.6 macOS 초기 셋업 체크리스트

| # | 작업 | 명령어 / 설정 |
|---|---|---|
| 1 | Homebrew 설치 | `/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"` |
| 2 | OrbStack 설치 | `brew install orbstack` |
| 3 | Python 3.12 설치 | `brew install python@3.12` |
| 4 | Node.js 20 LTS 설치 | `brew install node@20` |
| 5 | 프로젝트 폴더 생성 | `mkdir -p ~/alphatrade/{config,data,scripts,logs}` |
| 6 | Docker Compose 파일 작성 | `~/alphatrade/docker-compose.yml` 생성 |
| 7 | 절전 방지 설정 | `caffeinate -disu &` 를 `~/.zprofile`에 추가 |
| 8 | 자동 업데이트 비활성화 | `sudo softwareupdate --schedule off` |
| 9 | Cloudflare Tunnel 설치 | `brew install cloudflared && cloudflared tunnel login` |
| 10 | Docker Compose 실행 | `cd ~/alphatrade && docker compose up -d` |
| 11 | 서비스 접속 확인 | n8n(:5678), Grafana(:3001), Dashboard(:3000), API(:8000) |

---

## 12. 도구 비용 종합 비교

### 12.1 워크플로우 도구 비용 비교

트레이딩 시스템 기준으로 1분 주기 워크플로우 10개, 일간 실행 횟수 약 15,000회(장중 6.5시간 포함)를 기준으로 월간 비용을 비교한다.

| 도구 | 월간 비용 | 과금 방식 | 셀프호스팅 | 비고 |
|---|---|---|---|---|
| n8n Community | ₩0 (무료) | - | 가능 | 실행 횟수/워크플로우 무제한 |
| n8n Cloud Pro | 월 €60 (~₩90,000) | 워크플로우 실행 단위 | 불가 | 10,000회/월 — 부족할 수 있음 |
| Zapier Professional | 월 $19.99 (~₩28,000) | 태스크(스텝) 단위 | 불가 | 750태스크/월 — 심각하게 부족 |
| Zapier Team | 월 $69 (~₩95,000) | 태스크(스텝) 단위 | 불가 | 2,000태스크/월 — 여전히 부족 |
| Make Core | 월 $9 (~₩12,000) | 오퍼레이션 단위 | 불가 | 10,000 ops/월 — 빠듯할 수 있음 |
| Pipedream Pro | 월 $19 (~₩26,000) | 크레딧 단위 | 불가 | Workday 인수 후 정책 변동 가능성 |
| Activepieces | ₩0 (무료) | - | 가능 (MIT) | 생태계 성숙도 낮음 |
| Node-RED | ₩0 (무료) | - | 가능 (Apache 2.0) | IoT 특화, SaaS 연동 약함 |
| Apache Airflow | ₩0 (무료) | - | 가능 (Apache 2.0) | 배치 파이프라인 특화 |

> **핵심 차이**: n8n은 워크플로우 전체 실행을 1회로 카운트하지만, Zapier는 각 스텝을 별도 과금한다. 10개 스텝 워크플로우 기준 n8n이 10~20배 저렴하다.

### 12.2 본 프로젝트 월간 총비용 추정

| 항목 | 월간 비용 | 비고 |
|---|---|---|
| 서버 인프라 (MacBook) | ₩0 | 기존 장비 활용, 전기요금 별도 |
| n8n Community Edition | ₩0 | 셀프호스팅, 무제한 |
| Grafana + Prometheus | ₩0 | 셀프호스팅, 오픈소스 |
| TimescaleDB + Redis | ₩0 | 셀프호스팅, 오픈소스 |
| TradingView Pro | 월 ~₩20,000 | Webhook Alert 기능 필요 (Pro 이상) |
| 한국투자증권 OpenAPI | ₩0 | API 이용료 무료 (거래 수수료 별도) |
| DART API | ₩0 | 공시 데이터 무료 |
| LLM API (Claude / GPT) | 월 ~₩10,000~30,000 | 센티먼트 분석 + 리포트 생성 사용량 기준 |
| Telegram Bot | ₩0 | 무제한 |
| Cloudflare Tunnel | ₩0 | Free 플랜으로 충분 |
| 클라우드 VPS (실전 단계) | 월 ~₩30,000~50,000 | Phase 8부터 주문 실행 분리 시 |
| **모의투자 단계 총액** | **월 ₩30,000~50,000** | TradingView + LLM API 만 유료 |
| **실전 단계 총액** | **월 ₩60,000~100,000** | + 클라우드 VPS 추가 |

> 동일 기능을 클라우드 도구로 구성할 경우: Zapier Team(₩95,000) + 모니터링 SaaS(₩50,000+) + TradingView(₩20,000) + LLM(₩20,000) = 월 ₩185,000 이상. 셀프호스팅 대비 3~5배 비용 발생.

---

## 13. n8n 경쟁 도구 비교

본 프로젝트 관점에서 중요한 4가지 기준(셀프호스팅, AI/LLM 연동, 코드 확장성, 비용)으로 주요 경쟁 도구를 평가한다.

| 도구 | 유형 | 셀프호스팅 | AI/LLM 연동 | 코드 확장 | 트레이딩 적합성 |
|---|---|---|---|---|---|
| **n8n** | 하이브리드 | 가능 | 최고 (LangChain, RAG 내장) | JS + Python 호출 | ★★★★★ |
| Zapier | No-Code SaaS | 불가 | 기본 (OpenAI 연동) | 제한적 | ★★☆☆☆ |
| Make | Low-Code SaaS | 불가 | 중간 (HTTP 경유) | 제한적 | ★★★☆☆ |
| Pipedream | 개발자 SaaS | 불가 | 중간 (API 경유) | JS/Python/Go | ★★★☆☆ |
| Node-RED | Flow-based OSS | 가능 | 약함 | JS (Function 노드) | ★★★☆☆ |
| Activepieces | No-Code OSS | 가능 (MIT) | 중간 (AI 피스 내장) | 제한적 | ★★☆☆☆ |
| Apache Airflow | DAG 오케스트레이터 | 가능 | 없음 (직접 구현) | Python 전체 | ★★★☆☆ |
| Power Automate | MS 생태계 | 불가 | 기본 (Copilot) | 제한적 | ★☆☆☆☆ |

### 13.1 도구 선정 결론

- **1차 선택 (n8n)**: 셀프호스팅 + AI 내장 + 코드 확장성이 모두 충족되는 유일한 도구. 워크플로우 자동화 허브로 사용
- **2차 보조 (Grafana)**: 운영 모니터링 전담. n8n으로는 무리인 시계열 시각화/알러트 영역
- **3차 보조 (Node-RED)**: 선택적 도입. 실시간 시세 WebSocket 이벤트 처리에 특화된 작업이 있을 경우
- **Airflow**: 시스템 확장 시 검토. 일간 배치 파이프라인이 복잡해지면 도입 고려
- **Zapier/Make/Pipedream**: 본 프로젝트에서는 비권장 (클라우드 전용 + API 키 보안 문제 + 고빈도 과금 부담)

---

## 14. v1.3 리팩토링 성과 및 현재 상태

v1.2 계획 후 전면적 아키텍처 리팩토링(Phase R1~R6)을 완료하였다. 독립 감사 2건(Claude, Gemini)을 교차 검증하였으며, 상용 준비도 감사도 수행하였다.

### 14.1 리팩토링 완료 항목

| Phase | 작업 | 핵심 성과 |
|---|---|---|
| R1 | 코드 구조 정리 | DI 전환 (Depends 패턴), 15개 설정 외부화, 8개 거대 함수 분리, 싱글톤 제거 |
| R2 | 에러 처리 & 로깅 | 재시도 유틸 (5개 서비스), Prometheus 메트릭 6종, DB 트랜잭션, ExternalAPIError |
| R3 | 테스트 강화 | 784 테스트, 72% 커버리지 (목표 60% 초과) |
| R4 | 프론트엔드 | i18n 157키, fetch→apiGet 전환, 인라인 스타일 206→44 (78% 감소) |
| R5 | 보안 강화 | CORS, 엔드포인트별 Rate Limit, 보안 헤더 4종, nginx API Key 전달 |
| R6 | 인프라 보완 | Grafana 20+ 패널, DB 인덱스/CHECK 제약, Prometheus 정상 수집 |

### 14.2 추가 구현 기능

| 기능 | 설명 |
|---|---|
| 전 종목 적재 | KRX KOSPI 837 + KOSDAQ 1,782 = 2,619종목, `POST /collect/stocks` 매일 자동 갱신 |
| 종목 검색 | `GET /market/search?q=삼성` — 이름/코드 퍼지 검색 + StockSearch 자동완성 UI |
| 시장 변동 알림 | `POST /alert/scan` — 가격 급변/뉴스 급증/주요 공시 감지 → 카카오톡+텔레그램 |

### 14.3 외부 감사 결과 요약

| 감사 | 전체 완성도 | 최대 갭 |
|---|---|---|
| Claude 감사 (리팩 전) | 수치 미제시, 보수적 | n8n 1/10, Grafana empty |
| Gemini 감사 (리팩 후) | 65% | n8n 1/10, WebSocket 미구현 |
| **자체 평가 (리팩 후)** | **~75%** | **n8n 워크플로우, 실시간 시세** |

### 14.4 현재 시스템 수치

| 지표 | 값 |
|---|---|
| API 엔드포인트 | 37개 (+alert/scan, market/search, collect/stocks) |
| 테스트 | 784 (16개 파일) |
| 커버리지 | 72% |
| DB 종목 수 | 2,619 (KOSPI 837 + KOSDAQ 1,782) |
| Docker 서비스 | 8개 (전체 healthy) |
| Grafana 패널 | 20+ |
| i18n 번역 키 | 157개 |

---

## 15. 실시간 주가 수신 아키텍처

### 15.1 현재 상태: REST 폴링

```
KIS REST API ←── get_current_price() ←── n8n (1분) 또는 수동
      │
      ├── TimescaleDB 저장
      ├── Redis Pub/Sub 발행 (ohlcv:{code}) ← 소비자 없음
      │
Dashboard ─── 60초 polling ─── GET /market/prices
```

- KIS REST API: 요청당 1건 조회 (동작 중)
- Redis Pub/Sub: 발행만 하고 구독 없음
- WebSocket: nginx 프록시만 설정, 서버/클라이언트 미구현
- 프론트엔드: Market.tsx 60초 setInterval

### 15.2 목표 아키텍처: KIS WebSocket 실시간

```
KIS WebSocket (wss://) ──→ 백그라운드 태스크 ──→ Redis Pub/Sub
                                                       │
                                    ┌──────────────────┘
                                    ▼
                          FastAPI WebSocket /ws ──→ 프론트엔드 실시간
```

### 15.3 구현 필요 작업

| 순서 | 작업 | 설명 |
|------|------|------|
| 1 | KIS WebSocket 클라이언트 | `wss://` 연결, 종목 구독, 틱 파싱 |
| 2 | 백그라운드 스트리밍 태스크 | lifespan에서 asyncio.create_task 상시 실행 |
| 3 | Redis → WebSocket 브릿지 | Pub/Sub 구독 → 연결 클라이언트 broadcast |
| 4 | FastAPI `/ws` 엔드포인트 | WebSocket 연결 관리 + 종목 필터링 |
| 5 | 프론트엔드 `useWebSocket` 훅 | 실시간 가격 반영 |
| 6 | config 확장 | `KIS_WEBSOCKET_URL`, 구독 코드 추가 |

---

## 16. 상용 준비도 평가 및 로드맵

### 16.1 판정

| 목적 | 판정 |
|------|------|
| 프로토타입 / 연구 / 페이퍼 트레이딩 | ✅ 충분 |
| 소액 실전 파일럿 (엄격 한도 내) | ⚠️ 조건부 — Phase A 완료 필요 |
| 상용급 자동매매 | ❌ 불가 — Phase A+B+C + 법률 검토 필요 |

### 16.2 핵심 갭 10가지

| # | 갭 | 심각도 | 현재 상태 |
|---|---|--------|----------|
| 1 | 리스크 정책 미정의 | 🔴 | 한도 있으나 킬스위치/강제 정지 없음 |
| 2 | 주문 상태 조정 없음 | 🔴 | 트랜잭션 있으나 브로커↔내부 대조 없음 |
| 3 | 내구성 이벤트 아키텍처 없음 | 🟠 | Redis Pub/Sub만 (fire-and-forget) |
| 4 | 데이터 품질 거버넌스 없음 | 🟠 | 미수신/지연/이상 가격 검증 없음 |
| 5 | 재해 복구 미설계 | 🟠 | 백업 없음, RTO/RPO 미정의 |
| 6 | 감사 추적 없음 | 🟠 | orders 테이블만, 불변 로그 아님 |
| 7 | 컴플라이언스 없음 | 🟡 | 보존 정책/배포 승인/변경 관리 없음 |
| 8 | 로컬 워크스테이션 의존 | 🟡 | MacBook에서 전체 스택 실행 |
| 9 | LLM 가드레일 없음 | 🟡 | 타임아웃/폴백만, 비용 상한/버전 핀 없음 |
| 10 | 상용급 테스트 없음 | 🟡 | 784 테스트이나, 브로커 장애/카오스 테스트 없음 |

### 16.3 상용화 3단계 로드맵

#### Phase A: 최소 실전 통제 패키지 (실전 배포 전 필수)

| # | 작업 |
|---|------|
| A-1 | 리스크 정책 문서화 + 코드 강제 적용 |
| A-2 | 주문 FSM (created→submitted→acked→filled→cancelled) + 멱등키 |
| A-3 | EOD 포지션/현금 브로커 조정 자동화 |
| A-4 | 불량 데이터 감지 시 매매 차단 |
| A-5 | 킬 스위치 (자동: 일간 손실 초과 / 수동: API+대시보드) |
| A-6 | 불변 감사 로그 (append-only, 모든 매매 결정+브로커 응답) |
| A-7 | Docker 이미지, 의존성, LLM 모델 버전 핀 |
| A-8 | VPS에서 실전 매매 실행 (MacBook은 분석/모니터링만) |

#### Phase B: 운영 경화

| # | 작업 |
|---|------|
| B-1 | 백업/복원/RTO/RPO 정의 및 정기 테스트 |
| B-2 | 주문/포지션 이벤트 내구성 저장 (Redis + WAL/DB) |
| B-3 | 장애 대응 런북 (브로커/데이터 장애, 중복 주문, 재시작 복구) |
| B-4 | 시크릿 로테이션, RBAC, 이미지/의존성 스캔 |
| B-5 | 전략/코드 릴리즈 배포 승인 게이트 |

#### Phase C: 연구 거버넌스

| # | 작업 |
|---|------|
| C-1 | 전략 프로모션: 연구→페이퍼→섀도우→소액→증액 단계 정의 |
| C-2 | Walk-forward 검증, 레짐 테스트 |
| C-3 | 슬리피지/회전율/지연을 전략 메트릭으로 추적 |
| C-4 | LLM 프롬프트/결과 버전 관리, 비용 상한 |

### 16.4 필수 아키텍처 가정 변경

| 현재 (v1.2) | 변경 (v1.3) |
|---|---|
| MacBook 실전 운영 | **서버 우선 실행** (Phase 8부터 → Phase A부터) |
| Redis Pub/Sub만 | **Redis + 내구성 이벤트 저장** |
| 대시보드 모니터링 | **모니터링 + 런북 + 자동 세이프가드** |
| 리스크 엔진 "언급" | **리스크 정책 정의/인코딩/테스트 완료** |
| 페이퍼→실전 (2단계) | **페이퍼→섀도우→소액→증액** (4단계) |
| REST 폴링 시세 | **KIS WebSocket 실시간** |

---

## 17. 통합 우선순위 (Next Actions)

기능 갭과 상용화 갭을 통합하여 우선순위를 정한다.

| 순위 | 과제 | 분류 | 영향도 |
|---|---|---|---|
| 1 | 실시간 주가 수신 (KIS WebSocket) | 기능 | 핵심 기능 |
| 2 | 킬 스위치 (자동+수동) | 상용 A-5 | 🔴 안전 |
| 3 | 리스크 정책 문서화 + 강제 적용 | 상용 A-1 | 🔴 안전 |
| 4 | 주문 FSM + 브로커 조정 | 상용 A-2,3 | 🔴 안전 |
| 5 | n8n 워크플로우 확장 (9개) | 자동화 | 아키텍처 |
| 6 | 불변 감사 로그 | 상용 A-6 | 🟠 추적 |
| 7 | 불량 데이터 차단 | 상용 A-4 | 🟠 안전 |
| 8 | WebSocket 대시보드 실시간 | 기능 | UX |
| 9 | 버전 고정 + VPS 분리 | 상용 A-7,8 | 🟡 운영 |
| 10 | 백업/복원/DR | 상용 B-1 | 🟡 운영 |

---

## 18. 문서 이력

| 버전 | 일자 | 변경 내용 |
|---|---|---|
| v1.0 | 2026-03-28 | 초기 작성 (순수 코드 기반 설계) |
| v1.1 | 2026-03-29 | Hybrid Architecture 전환: n8n, Grafana, TradingView 통합. 도구 생태계, 연동 패턴, Docker Compose 구성, 비용 분석 추가 |
| v1.2 | 2026-03-29 | MacBook M1 Pro 배포 환경 추가: RAM 할당 계획, OrbStack 권장, 실전 운영 요건, 주문실행 분리 아키텍처, macOS 초기 셋업. 도구 비용 종합 비교, n8n 경쟁 도구 분석 추가 |
| v1.3 | 2026-03-30 | **리팩토링 성과 반영**: R1-R6 완료 (DI, 설정 외부화, 에러 처리, 테스트 784건/72%, 보안, Grafana). **외부 감사 3건 통합**: Claude/Gemini plan-audit + 상용 준비도 감사. **신규 섹션**: 실시간 시세 아키텍처 (KIS WebSocket), 상용화 3단계 로드맵 (Phase A/B/C), 핵심 갭 10가지, 아키텍처 가정 변경, 통합 우선순위 10개. 전 종목 2,619개 적재, 시장 변동 알림, 종목 검색 기능 추가 |

---

*— End of Document —*
