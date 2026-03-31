# AlphaTrade Incident Runbook

**최종 업데이트**: 2026-04-01
**대상 시스템**: Docker Compose 기반 AlphaTrade (MacBook M1 Pro)

---

## 시나리오 1: 브로커 API 장애 (KIS API 무응답)

### 증상
- 주문이 SUBMITTED에서 진행되지 않음
- `/trading/check-fills` 응답의 `errors` 배열에 KIS 에러
- 텔레그램 `[CRITICAL] broker_failure` 알림
- 3회 연속 실패 시 킬 스위치 자동 발동

### 대응 절차
1. **즉시**: 킬 스위치 상태 확인
   ```bash
   curl http://localhost:8000/trading/kill-switch/status
   ```
2. **확인**: KIS API 상태 확인 (한국투자증권 공지사항)
   - https://securities.koreainvestment.com
   - 시스템 점검/장애 공지 확인
3. **대기**: API 장애인 경우 복구 대기
   - 인플라이트 주문은 fill_monitor가 30분 후 자동 만료
   - 장 중이면 브로커 HTS에서 수동 확인/취소
4. **복구 후**:
   ```bash
   # 킬 스위치 해제
   curl -X POST http://localhost:8000/trading/kill-switch/deactivate
   # 체결 확인 실행
   curl -X POST http://localhost:8000/trading/check-fills
   # EOD 정합성 검증
   curl -X POST http://localhost:8000/trading/reconcile
   ```

### 예방
- `risk_broker_max_failures` 값 조정 (기본 3회)
- KIS API 상태 모니터링을 n8n WF-07에 추가

---

## 시나리오 2: 데이터베이스 연결 장애

### 증상
- `/health` 응답에서 `"db": "error"`
- 모든 API 엔드포인트 500 에러
- 로그: `asyncpg.exceptions.ConnectionDoesNotExistError`

### 대응 절차
1. **확인**: TimescaleDB 컨테이너 상태
   ```bash
   docker compose ps timescaledb
   docker compose logs timescaledb --tail 50
   ```
2. **재시작** (데이터 손실 없음):
   ```bash
   docker compose restart timescaledb
   # 30초 대기 후 헬스체크
   sleep 30
   curl http://localhost:8000/health
   ```
3. **디스크 공간 확인** (DB가 디스크 풀로 중단된 경우):
   ```bash
   docker exec alphatrade-timescaledb df -h /var/lib/postgresql/data
   # 오래된 데이터 정리
   docker exec alphatrade-timescaledb psql -U alphatrade -d alphatrade -c \
     "SELECT hypertable_name, hypertable_size(format('%I.%I', hypertable_schema, hypertable_name)::regclass) FROM timescaledb_information.hypertables;"
   ```
4. **데이터 손실 시 복원**:
   ```bash
   # 최신 백업 확인
   ./scripts/backup.sh status
   # 복원 (주의: 현재 데이터 덮어씀)
   ./scripts/backup.sh restore data/backups/full_YYYYMMDD_HHMMSS.sql.gz
   ```

### 예방
- 일간 full 백업: `0 3 * * * ./scripts/backup.sh full`
- 5분 incremental: `*/5 * * * * ./scripts/backup.sh incremental`
- 디스크 용량 80% 이상 시 Grafana 알림

---

## 시나리오 3: Redis 장애

### 증상
- `/health` 응답에서 `"redis": "error"`
- WebSocket 실시간 데이터 중단
- 킬 스위치/시장 상태 캐시 접근 불가
- 전략 활성 설정 조회 실패

### 대응 절차
1. **즉시**: 모든 신규 주문 수동 중단 (킬 스위치가 Redis 의존)
2. **확인**:
   ```bash
   docker compose ps redis
   docker compose logs redis --tail 30
   ```
3. **재시작**:
   ```bash
   docker compose restart redis
   sleep 10
   curl http://localhost:8000/health
   ```
4. **복구 후**: 킬 스위치 상태 재설정 (Redis 재시작 시 초기화됨)
   ```bash
   # 장 중이라면 킬 스위치 활성화 후 상태 확인
   curl -X POST http://localhost:8000/trading/kill-switch/activate
   # 수동 확인 후 해제
   ```

### 주의
- Redis 재시작 시 `strategy:active_config` 초기화됨 → 기본 ensemble로 복귀
- KIS WebSocket 재연결은 자동 처리

---

## 시나리오 4: 킬 스위치 발동 후 복구

### 발동 원인 확인
```bash
# 감사 로그에서 발동 원인 조회
docker exec alphatrade-timescaledb psql -U alphatrade -d alphatrade -c \
  "SELECT event_time, event_type, payload FROM audit_log WHERE source = 'kill_switch' ORDER BY event_time DESC LIMIT 5;"
```

### 일간 손실 자동 발동인 경우
1. 현재 손실 확인:
   ```bash
   curl http://localhost:8000/trading/status
   ```
2. 포지션 확인 (추가 손실 위험 평가):
   ```bash
   curl http://localhost:8000/risk/pnl
   ```
3. **당일 재개 금지** — 일간 손실 한도 초과 후 당일 거래 재개는 원칙적으로 금지
4. 다음 거래일 시작 전 해제:
   ```bash
   curl -X POST http://localhost:8000/trading/kill-switch/deactivate
   ```

### 브로커 서킷브레이커 발동인 경우
1. KIS API 상태 확인 (시나리오 1 참조)
2. API 정상 확인 후:
   ```bash
   curl -X POST http://localhost:8000/trading/kill-switch/deactivate
   ```

---

## 시나리오 5: 장 중 시스템 재시작

### 계획된 재시작 (업데이트)
1. **킬 스위치 활성화** (새 주문 차단):
   ```bash
   curl -X POST http://localhost:8000/trading/kill-switch/activate
   ```
2. **인플라이트 주문 확인**:
   ```bash
   curl -X POST http://localhost:8000/trading/check-fills
   ```
3. **재시작**:
   ```bash
   docker compose build core-engine
   docker compose up -d core-engine
   ```
4. **헬스체크**:
   ```bash
   sleep 10 && curl http://localhost:8000/health
   ```
5. **인플라이트 복구 확인**: 재시작 시 `recover_inflight_orders()` 자동 실행
6. **킬 스위치 해제**:
   ```bash
   curl -X POST http://localhost:8000/trading/kill-switch/deactivate
   ```

### 비계획 재시작 (크래시)
1. 자동 복구: Docker `restart: unless-stopped` 정책
2. 재시작 후 자동으로:
   - DB/Redis 연결 복구
   - KIS WebSocket 재연결
   - 인플라이트 주문 복구 시도
3. **수동 확인 필수**:
   ```bash
   curl http://localhost:8000/health
   curl http://localhost:8000/trading/kill-switch/status
   curl -X POST http://localhost:8000/trading/check-fills
   ```

---

## 시나리오 6: 중복 주문 의심

### 증상
- 동일 종목에 대해 같은 방향 주문이 여러 건 체결
- `audit_log`에 같은 idempotency_key로 다른 order_id

### 확인
```bash
# 오늘 주문 확인
docker exec alphatrade-timescaledb psql -U alphatrade -d alphatrade -c \
  "SELECT order_id, stock_code, side, quantity, status, metadata->>'idempotency_key' as idem_key
   FROM orders WHERE time > CURRENT_DATE ORDER BY time;"
```

### 대응
1. **킬 스위치 활성화** (추가 주문 차단)
2. 브로커 HTS에서 실제 체결 확인
3. 중복이 확인되면 반대 매매로 정리 (수동)
4. 원인 분석: idempotency_key 생성 로직 점검

---

## 시나리오 7: EOD 정합성 불일치

### 증상
- `/trading/reconcile` 응답에 `mismatches > 0`
- 텔레그램 `[CRITICAL] reconciliation_mismatch` 알림

### 대응
1. **상세 확인**:
   ```bash
   curl -X POST http://localhost:8000/trading/reconcile | python3 -m json.tool
   ```
2. 불일치 유형별 대응:
   - `position_qty_mismatch`: 브로커 HTS에서 실제 잔고 확인 → DB 수동 보정
   - `broker_cash_mismatch`: 미체결 수수료/세금 반영 차이 → 다음 스냅샷에서 보정
   - `orphaned_order`: 체결 확인 재실행 → 여전히 미해결이면 만료 처리
   - `broker_api_unavailable`: KIS API 장애 → 시나리오 1 참조
3. DB 수동 보정 (최후 수단):
   ```sql
   -- 포지션 수량 보정 (주의!)
   UPDATE portfolio_positions SET quantity = <actual_qty> WHERE stock_code = '<code>';
   ```

### 예방
- 매일 15:40 이후 자동 reconciliation (n8n 스케줄)
- 불일치 0건이 14일 연속 → 실전 전환 Gate 통과

---

## 연락처

| 역할 | 연락처 |
|------|--------|
| 시스템 운영 | digitect38@gmail.com |
| 텔레그램 알림 | @AlphaTrade38_bot |
| KIS 고객센터 | 1544-5000 (한국투자증권) |
| DART 시스템 | dart.fss.or.kr |

---

## 백업/복원 빠른 참조

```bash
# 백업 상태 확인
./scripts/backup.sh status

# 즉시 전체 백업
./scripts/backup.sh full

# 복원 (주의: 데이터 덮어씀!)
./scripts/backup.sh restore data/backups/full_YYYYMMDD_HHMMSS.sql.gz

# 서비스 전체 재시작
docker compose down && docker compose up -d
```
