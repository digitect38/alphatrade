-- ===========================================
-- AlphaTrade Database Schema
-- TimescaleDB (PostgreSQL 16)
-- ===========================================

-- Enable TimescaleDB extension
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- ===========================================
-- Regular Tables
-- ===========================================

-- 종목 마스터
CREATE TABLE stocks (
    stock_code    VARCHAR(20) PRIMARY KEY,       -- 종목코드 (예: 005930)
    stock_name    VARCHAR(100) NOT NULL,          -- 종목명
    market        VARCHAR(10) NOT NULL,           -- KOSPI / KOSDAQ
    sector        VARCHAR(100),                   -- 업종
    market_cap    BIGINT,                         -- 시가총액
    listed_shares BIGINT,                         -- 상장주식수
    is_active     BOOLEAN DEFAULT TRUE,
    created_at    TIMESTAMPTZ DEFAULT NOW(),
    updated_at    TIMESTAMPTZ DEFAULT NOW()
);

-- 매매 대상 유니버스
CREATE TABLE universe (
    id            SERIAL PRIMARY KEY,
    stock_code    VARCHAR(20) NOT NULL REFERENCES stocks(stock_code),
    reason        TEXT,                            -- 편입 사유
    added_at      TIMESTAMPTZ DEFAULT NOW(),
    removed_at    TIMESTAMPTZ,
    is_active     BOOLEAN DEFAULT TRUE
);

CREATE INDEX idx_universe_active ON universe(is_active) WHERE is_active = TRUE;

-- 포트폴리오 현재 포지션
CREATE TABLE portfolio_positions (
    id            SERIAL PRIMARY KEY,
    stock_code    VARCHAR(20) NOT NULL REFERENCES stocks(stock_code),
    quantity      INTEGER NOT NULL DEFAULT 0,
    avg_price     NUMERIC(12,2) NOT NULL,          -- 평균 매입가
    current_price NUMERIC(12,2),
    unrealized_pnl NUMERIC(14,2),                  -- 미실현 손익
    weight        NUMERIC(5,4),                    -- 포트폴리오 비중
    opened_at     TIMESTAMPTZ DEFAULT NOW(),
    updated_at    TIMESTAMPTZ DEFAULT NOW()
);

CREATE UNIQUE INDEX idx_positions_stock ON portfolio_positions(stock_code);

-- ===========================================
-- Hypertables (시계열)
-- ===========================================

-- OHLCV 시세 데이터
CREATE TABLE ohlcv (
    time          TIMESTAMPTZ NOT NULL,
    stock_code    VARCHAR(20) NOT NULL,
    open          NUMERIC(12,2),
    high          NUMERIC(12,2),
    low           NUMERIC(12,2),
    close         NUMERIC(12,2),
    volume        BIGINT,
    value         BIGINT,                          -- 거래대금
    interval      VARCHAR(10) NOT NULL DEFAULT '1d' -- 1m, 5m, 15m, 1h, 1d
);

SELECT create_hypertable('ohlcv', 'time');
CREATE INDEX idx_ohlcv_stock ON ohlcv(stock_code, time DESC);
CREATE INDEX idx_ohlcv_interval ON ohlcv(interval, stock_code, time DESC);

-- 뉴스 기사
CREATE TABLE news (
    time          TIMESTAMPTZ NOT NULL,
    source        VARCHAR(50) NOT NULL,             -- 네이버, 한경, 매경 등
    title         TEXT NOT NULL,
    content       TEXT,
    url           TEXT,
    stock_codes   VARCHAR(20)[],                    -- 관련 종목 코드 배열
    category      VARCHAR(50),                      -- 시장, 기업, 산업 등
    is_processed  BOOLEAN DEFAULT FALSE
);

SELECT create_hypertable('news', 'time');
CREATE INDEX idx_news_stock ON news USING GIN(stock_codes);
CREATE INDEX idx_news_processed ON news(is_processed, time DESC) WHERE is_processed = FALSE;

-- DART 공시
CREATE TABLE disclosures (
    time          TIMESTAMPTZ NOT NULL,
    stock_code    VARCHAR(20) NOT NULL,
    report_name   TEXT NOT NULL,                    -- 공시 제목
    report_type   VARCHAR(50),                      -- 주요사항보고, 분기보고서 등
    rcept_no      VARCHAR(20),                       -- DART 접수번호
    dcm_no        VARCHAR(20),                      -- 문서번호
    url           TEXT,
    is_major      BOOLEAN DEFAULT FALSE,            -- 주요 공시 여부
    is_processed  BOOLEAN DEFAULT FALSE
);

SELECT create_hypertable('disclosures', 'time');
CREATE INDEX idx_disclosures_stock ON disclosures(stock_code, time DESC);
CREATE UNIQUE INDEX idx_disclosures_rcept ON disclosures(time, rcept_no);

-- 센티먼트 점수
CREATE TABLE sentiment_scores (
    time          TIMESTAMPTZ NOT NULL,
    stock_code    VARCHAR(20) NOT NULL,
    source_type   VARCHAR(20) NOT NULL,             -- news, disclosure, social
    score         NUMERIC(5,4) NOT NULL,            -- -1.0 ~ 1.0
    confidence    NUMERIC(5,4),                     -- 신뢰도
    model         VARCHAR(50),                      -- KoBERT, Claude, GPT 등
    raw_text_id   TEXT,                             -- 원본 텍스트 참조
    metadata      JSONB
);

SELECT create_hypertable('sentiment_scores', 'time');
CREATE INDEX idx_sentiment_stock ON sentiment_scores(stock_code, time DESC);

-- 전략 시그널
CREATE TABLE strategy_signals (
    time          TIMESTAMPTZ NOT NULL,
    stock_code    VARCHAR(20) NOT NULL,
    signal        VARCHAR(10) NOT NULL,             -- BUY, SELL, HOLD
    strength      NUMERIC(5,4),                     -- 신호 강도 0.0 ~ 1.0
    strategy_name VARCHAR(50) NOT NULL,             -- ensemble, momentum, mean_reversion 등
    reasons       JSONB,                            -- 개별 전략 근거
    metadata      JSONB
);

SELECT create_hypertable('strategy_signals', 'time');
CREATE INDEX idx_signals_stock ON strategy_signals(stock_code, time DESC);
CREATE INDEX idx_signals_signal ON strategy_signals(signal, time DESC);

-- 주문 이력
CREATE TABLE orders (
    time          TIMESTAMPTZ NOT NULL,
    order_id      VARCHAR(50) NOT NULL,
    stock_code    VARCHAR(20) NOT NULL,
    side          VARCHAR(4) NOT NULL,              -- BUY, SELL
    order_type    VARCHAR(10) NOT NULL,             -- MARKET, LIMIT
    quantity      INTEGER NOT NULL,
    price         NUMERIC(12,2),                    -- 주문 가격
    filled_qty    INTEGER DEFAULT 0,
    filled_price  NUMERIC(12,2),                    -- 체결 가격
    status        VARCHAR(20) NOT NULL DEFAULT 'PENDING',  -- PENDING, SUBMITTED, FILLED, PARTIAL, CANCELLED, FAILED
    signal_id     TEXT,                             -- 연결된 시그널 참조
    slippage      NUMERIC(8,4),                    -- 슬리피지
    commission    NUMERIC(10,2),                   -- 수수료
    metadata      JSONB
);

SELECT create_hypertable('orders', 'time');
CREATE UNIQUE INDEX idx_orders_id ON orders(time, order_id);
CREATE INDEX idx_orders_stock ON orders(stock_code, time DESC);
CREATE INDEX idx_orders_status ON orders(status, time DESC);

-- 포트폴리오 스냅샷 (일간)
CREATE TABLE portfolio_snapshots (
    time              TIMESTAMPTZ NOT NULL,
    total_value       NUMERIC(14,2) NOT NULL,       -- 총 평가금액
    cash              NUMERIC(14,2) NOT NULL,       -- 현금
    invested          NUMERIC(14,2) NOT NULL,       -- 투자금액
    daily_pnl         NUMERIC(14,2),                -- 일간 손익
    daily_return      NUMERIC(8,6),                 -- 일간 수익률
    cumulative_return NUMERIC(8,6),                 -- 누적 수익률
    mdd               NUMERIC(8,6),                 -- Maximum Drawdown
    sharpe_ratio      NUMERIC(8,4),                 -- Sharpe Ratio
    positions_count   INTEGER,
    metadata          JSONB
);

SELECT create_hypertable('portfolio_snapshots', 'time');
CREATE INDEX idx_snapshots_time ON portfolio_snapshots(time DESC);

-- ===========================================
-- n8n 전용 데이터베이스 생성
-- ===========================================
-- Note: Docker entrypoint에서 POSTGRES_DB만 자동 생성되므로
-- n8n DB는 별도 생성이 필요. init.sql은 기본 DB(alphatrade)에서 실행됨.

-- n8n DB 생성은 docker-compose의 별도 command로 처리

-- ===========================================
-- CHECK Constraints (데이터 무결성)
-- ===========================================

ALTER TABLE sentiment_scores ADD CONSTRAINT chk_sentiment_score CHECK (score >= -1.0 AND score <= 1.0);
ALTER TABLE sentiment_scores ADD CONSTRAINT chk_sentiment_confidence CHECK (confidence IS NULL OR (confidence >= 0.0 AND confidence <= 1.0));
ALTER TABLE strategy_signals ADD CONSTRAINT chk_signal_strength CHECK (strength IS NULL OR (strength >= 0.0 AND strength <= 1.0));
ALTER TABLE strategy_signals ADD CONSTRAINT chk_signal_type CHECK (signal IN ('BUY', 'SELL', 'HOLD'));
ALTER TABLE orders ADD CONSTRAINT chk_order_side CHECK (side IN ('BUY', 'SELL'));
ALTER TABLE orders ADD CONSTRAINT chk_order_status CHECK (status IN ('PENDING', 'SUBMITTED', 'FILLED', 'PARTIAL', 'CANCELLED', 'FAILED'));
ALTER TABLE orders ADD CONSTRAINT chk_order_type CHECK (order_type IN ('MARKET', 'LIMIT'));
ALTER TABLE stocks ADD CONSTRAINT chk_stock_market CHECK (market IN ('KOSPI', 'KOSDAQ'));
ALTER TABLE ohlcv ADD CONSTRAINT chk_ohlcv_interval CHECK (interval IN ('1m', '5m', '15m', '1h', '1d'));
ALTER TABLE ohlcv ADD CONSTRAINT chk_ohlcv_prices CHECK (open >= 0 AND high >= 0 AND low >= 0 AND close >= 0);

-- ===========================================
-- Audit Log (v1.31 16.5.3 — append-only)
-- ===========================================

CREATE TABLE audit_log (
    event_id        TEXT NOT NULL,                    -- UUID
    event_time      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    source          VARCHAR(50) NOT NULL,             -- strategy, risk, order, broker, operator, system
    event_type      VARCHAR(50) NOT NULL,             -- order_created, risk_blocked, kill_switch, etc.
    strategy_id     VARCHAR(50),
    symbol          VARCHAR(20),
    operator_id     VARCHAR(50) DEFAULT 'system',
    correlation_id  TEXT,                             -- links related events
    payload         JSONB NOT NULL,
    payload_hash    TEXT NOT NULL                     -- SHA-256 of payload for integrity
);

SELECT create_hypertable('audit_log', 'event_time');
CREATE INDEX idx_audit_source ON audit_log(source, event_time DESC);
CREATE INDEX idx_audit_symbol ON audit_log(symbol, event_time DESC);
CREATE INDEX idx_audit_correlation ON audit_log(correlation_id, event_time DESC);

-- Prevent UPDATE/DELETE on audit_log (append-only)
CREATE OR REPLACE RULE audit_no_update AS ON UPDATE TO audit_log DO INSTEAD NOTHING;
CREATE OR REPLACE RULE audit_no_delete AS ON DELETE TO audit_log DO INSTEAD NOTHING;

-- Update orders status constraint to include BLOCKED
-- v1.31 FSM states: all order lifecycle states must be allowed
ALTER TABLE orders DROP CONSTRAINT IF EXISTS chk_order_status;
ALTER TABLE orders ADD CONSTRAINT chk_order_status CHECK (status IN (
    'CREATED', 'VALIDATED', 'SUBMITTED', 'ACKED',
    'PARTIALLY_FILLED', 'FILLED', 'CANCELLED', 'REJECTED',
    'EXPIRED', 'UNKNOWN', 'BLOCKED', 'FAILED',
    'PARTIAL', 'PENDING'  -- legacy compat
));

-- ============================================================
-- v1.4: Execution Quality Tracking
-- ============================================================
CREATE TABLE IF NOT EXISTS execution_quality (
    time           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    order_id       TEXT NOT NULL,
    stock_code     TEXT NOT NULL,
    side           TEXT NOT NULL CHECK (side IN ('BUY', 'SELL')),
    signal_price   NUMERIC NOT NULL,
    fill_price     NUMERIC NOT NULL,
    slippage_bps   NUMERIC NOT NULL,       -- basis points (positive = adverse for the side)
    fill_delay_seconds NUMERIC DEFAULT 0   -- time from order creation to fill
);
SELECT create_hypertable('execution_quality', 'time', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS idx_eq_stock ON execution_quality(stock_code, time DESC);
CREATE INDEX IF NOT EXISTS idx_eq_order ON execution_quality(order_id);
