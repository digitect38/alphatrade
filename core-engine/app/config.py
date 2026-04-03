from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Database
    postgres_user: str = "alphatrade"
    postgres_password: str = ""
    postgres_db: str = "alphatrade"
    postgres_host: str = "timescaledb"
    postgres_port: int = 5432

    # Redis
    redis_host: str = "redis"
    redis_port: int = 6379
    redis_password: str = ""

    # Server
    core_engine_host: str = "0.0.0.0"
    core_engine_port: int = 8000

    # Security
    api_auth_key: str = ""  # Set to enable API key auth (empty = dev mode, no auth)
    api_auth_key_admin: str = ""  # Admin role key (full access)
    api_auth_key_operator: str = ""  # Operator role key (trade + kill switch)
    api_auth_key_viewer: str = ""  # Viewer role key (read-only)
    rate_limit_max: int = 300  # Max requests per window
    rate_limit_window: int = 60  # Window in seconds

    # 한국투자증권 OpenAPI
    kis_app_key: str = ""
    kis_app_secret: str = ""
    kis_account_no: str = ""
    kis_cano: str = ""
    kis_acnt_prdt_cd: str = "01"
    kis_mode: str = "paper"  # "paper" = 모의투자, "live" = 실전
    kis_base_url: str = "https://openapivts.koreainvestment.com:29443"  # 모의투자
    kis_ws_url: str = "ws://ops.koreainvestment.com:31000"  # 모의투자 WebSocket (실전: 21000)

    # DART 공시 API
    dart_api_key: str = ""

    # LLM
    anthropic_api_key: str = ""
    openai_api_key: str = ""

    # Telegram
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    # KakaoTalk
    kakao_access_token: str = ""

    # TradingView
    tradingview_webhook_secret: str = ""

    # --- Risk Management (v1.31 16.5.1 기준) ---
    risk_max_total_capital: float = 500_000  # 총 투자 한도 (원)
    risk_max_per_stock: float = 250_000  # 종목당 최대 (원)
    risk_max_position_ratio: float = 0.10  # 종목당 최대 비중 (v1.31: 10%)
    risk_max_sector_ratio: float = 0.25  # 섹터 집중 한도 (v1.31: 25%)
    risk_max_total_invested: float = 0.90  # 최대 투자 비율
    risk_stop_loss_pct: float = -0.015  # 손절 기준 (v1.31: -1.5%)
    risk_take_profit_pct: float = 0.10  # 익절 기준
    risk_max_daily_loss_pct: float = -0.02  # 일간 최대 손실 → 킬 스위치 발동
    risk_max_strategy_daily_loss_pct: float = -0.01  # 전략별 일간 손실 (v1.31: -1%)
    risk_max_daily_trades: int = 50  # 일간 최대 거래 (10→50, 사이클 기반 운영)
    risk_max_participation_rate: float = 0.01  # 20일 평균 거래대금 대비 참여율 (v1.31: 1%)
    risk_stale_price_seconds: int = 90  # 시세 유효 기간 (폴링 60초 + 여유 30초)
    risk_broker_max_failures: int = 3  # 브로커 연속 실패 차단 횟수
    risk_session_open_delay_min: int = 5  # 장 개시 후 진입 대기 (분)
    risk_session_close_buffer_min: int = 20  # 장 마감 전 진입 차단 (분)

    # --- Market Hours ---
    market_timezone: str = "Asia/Seoul"
    market_open_time: str = "09:00"  # 정규장 시작
    market_close_time: str = "15:30"  # 종가 동시호가 종료
    market_regular_close: str = "15:20"  # 정규장 종료 (종가 동시호가 시작)
    market_state_poll_interval_sec: int = 60  # WS 무수신 시 시장 상태 fallback polling 주기 (KIS 차단 방지)

    # --- Strategy ---
    strategy_weight_momentum: float = 0.30
    strategy_weight_mean_reversion: float = 0.25
    strategy_weight_volume: float = 0.20
    strategy_weight_sentiment: float = 0.25
    strategy_buy_threshold: float = 0.15
    strategy_sell_threshold: float = -0.15

    # --- Portfolio ---
    initial_capital: float = 10_000_000  # 초기 자본금 (원)

    # --- Position Sizing ---
    sizing_max_position_pct: float = 0.15  # 포트폴리오 대비 종목 비중
    sizing_max_cash_per_order_pct: float = 0.30  # 1회 주문 현금 비율
    sizing_min_order_value: float = 100_000  # 최소 주문금액
    sizing_min_signal_strength: float = 0.3  # 최소 시그널 강도
    sizing_full_exit_strength: float = 0.7  # 전량 매도 시그널 강도
    sizing_half_exit_strength: float = 0.4  # 반량 매도 시그널 강도
    sizing_half_exit_ratio: float = 0.5  # 반량 매도 비율
    sizing_trim_ratio: float = 0.3  # 트림 매도 비율

    # --- Scanner ---
    scanner_gap_threshold: float = 0.02  # 갭 감지 기준
    scanner_volume_surge_ratio: float = 3.0  # 거래량 급증 배수
    scanner_top_n: int = 5  # 상위 종목 수
    scanner_max_buy_per_scan: int = 3  # 스캔당 최대 매수

    # --- Scanner (alert) ---
    scanner_price_surge_alert_pct: float = 3.0  # 가격 급등 알림 기준 (%)

    # --- Analysis ---
    analysis_volume_surge_ratio: float = 2.0  # 분석용 거래량 급증 판단 비율
    analysis_default_period: int = 200  # 기술적 분석 기본 기간
    analysis_volume_lookback: int = 60  # 거래량 분석 조회 기간

    # --- HTTP ---
    http_timeout_default: float = 15.0  # 기본 HTTP 타임아웃 (초)
    http_timeout_notification: float = 10.0  # 알림 서비스 타임아웃 (초)
    http_timeout_llm: float = 30.0  # LLM API 타임아웃 (초)

    # --- Cache ---
    cache_technical_ttl: int = 60  # 기술적 분석 캐시 (초)
    cache_kis_token_ttl: int = 80000  # KIS 토큰 캐시 (초)

    @property
    def database_url(self) -> str:
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
