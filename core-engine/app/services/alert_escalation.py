"""Alert escalation — tiered notifications with rate limiting.

Level 1 (INFO):  Telegram only — signals, fills, cycle complete
Level 2 (WARN):  Telegram + 반복 — loss warnings, system delays, slippage alerts
Level 3 (CRIT):  Telegram + 반복 강화 — kill switch, reconciliation mismatch, broker failure

Rate limiting: Same event type is suppressed for a cooldown period.
"""

import logging
from datetime import datetime, timezone
from enum import IntEnum

import redis.asyncio as aioredis

from app.config import settings
from app.services.notification import NotificationService
from app.utils.market_calendar import KST

logger = logging.getLogger(__name__)

# Cooldown periods (seconds) per alert level
COOLDOWN_L1 = 300    # 5 min for info alerts
COOLDOWN_L2 = 120    # 2 min for warnings
COOLDOWN_L3 = 60     # 1 min for critical (shorter = more urgent)

# Redis key prefix for cooldown tracking
COOLDOWN_PREFIX = "alert:cooldown:"


class AlertLevel(IntEnum):
    INFO = 1
    WARN = 2
    CRITICAL = 3


# Classification: event_type → level
EVENT_LEVELS = {
    # Level 1 — Info
    "signal_generated": AlertLevel.INFO,
    "order_filled": AlertLevel.INFO,
    "cycle_complete": AlertLevel.INFO,
    "take_profit": AlertLevel.INFO,
    # Level 2 — Warning
    "stop_loss": AlertLevel.WARN,
    "daily_loss_warning": AlertLevel.WARN,
    "high_slippage": AlertLevel.WARN,
    "stale_order": AlertLevel.WARN,
    "system_delay": AlertLevel.WARN,
    "partial_fill": AlertLevel.WARN,
    # Level 3 — Critical
    "kill_switch": AlertLevel.CRITICAL,
    "reconciliation_mismatch": AlertLevel.CRITICAL,
    "broker_failure": AlertLevel.CRITICAL,
    "broker_circuit_break": AlertLevel.CRITICAL,
    "system_error": AlertLevel.CRITICAL,
    "daily_loss_limit": AlertLevel.CRITICAL,
}


class AlertEscalation:
    """Tiered alert service with rate limiting."""

    def __init__(self, notifier: NotificationService, redis: aioredis.Redis):
        self.notifier = notifier
        self.redis = redis

    async def send(
        self,
        event_type: str,
        message: str,
        *,
        level: AlertLevel | None = None,
        force: bool = False,
    ) -> dict:
        """Send alert with escalation and rate limiting.

        Args:
            event_type: Alert event type (used for cooldown key)
            message: Alert message text
            level: Override level (auto-detected from event_type if None)
            force: Skip cooldown check (for critical manual alerts)

        Returns:
            {"sent": bool, "level": int, "reason": str}
        """
        if level is None:
            level = EVENT_LEVELS.get(event_type, AlertLevel.INFO)

        # Rate limiting check
        if not force:
            is_cooled = await self._check_cooldown(event_type, level)
            if is_cooled:
                return {"sent": False, "level": level, "reason": "cooldown_active"}

        # Format message with level prefix
        prefix = self._level_prefix(level)
        formatted = f"{prefix}\n{message}"

        # Send based on level
        sent = False
        if level == AlertLevel.INFO:
            sent = await self.notifier.send_telegram(formatted)
        elif level == AlertLevel.WARN:
            sent = await self.notifier.send_telegram(formatted)
            # Repeat warning after 5 min if not acknowledged
            await self._schedule_repeat(event_type, formatted, repeat_after=300)
        elif level == AlertLevel.CRITICAL:
            sent = await self.notifier.send_telegram(formatted)
            # Send again immediately (double-tap for critical)
            await self.notifier.send_telegram(f"🔴🔴🔴 REPEAT: {formatted}")
            # Schedule 3 more repeats at 1, 3, 5 min
            await self._schedule_repeat(event_type, formatted, repeat_after=60)

        # Set cooldown
        await self._set_cooldown(event_type, level)

        logger.info("Alert sent: level=%d type=%s sent=%s", level, event_type, sent)
        return {"sent": sent, "level": level, "reason": "sent"}

    async def _check_cooldown(self, event_type: str, level: AlertLevel) -> bool:
        """Check if event is still in cooldown period."""
        key = f"{COOLDOWN_PREFIX}{event_type}"
        exists = await self.redis.exists(key)
        return bool(exists)

    async def _set_cooldown(self, event_type: str, level: AlertLevel):
        """Set cooldown for event type."""
        key = f"{COOLDOWN_PREFIX}{event_type}"
        cooldown = {
            AlertLevel.INFO: COOLDOWN_L1,
            AlertLevel.WARN: COOLDOWN_L2,
            AlertLevel.CRITICAL: COOLDOWN_L3,
        }.get(level, COOLDOWN_L1)
        await self.redis.setex(key, cooldown, "1")

    async def _schedule_repeat(self, event_type: str, message: str, repeat_after: int):
        """Schedule a repeat alert via Redis key with TTL.

        A background task should poll for expired repeat keys.
        For now, this stores the repeat request for the monitoring loop.
        """
        key = f"alert:repeat:{event_type}:{int(datetime.now(timezone.utc).timestamp())}"
        import json
        await self.redis.setex(
            key,
            repeat_after,
            json.dumps({"message": message, "event_type": event_type}),
        )

    @staticmethod
    def _level_prefix(level: AlertLevel) -> str:
        if level == AlertLevel.INFO:
            return "📊 <b>[INFO]</b>"
        elif level == AlertLevel.WARN:
            return "⚠️ <b>[WARNING]</b>"
        elif level == AlertLevel.CRITICAL:
            return "🚨🚨🚨 <b>[CRITICAL]</b>"
        return ""

    async def get_alert_stats(self, hours: int = 24) -> dict:
        """Get alert statistics from Redis cooldown keys."""
        pattern = f"{COOLDOWN_PREFIX}*"
        keys = []
        async for key in self.redis.scan_iter(match=pattern):
            keys.append(key.decode() if isinstance(key, bytes) else key)

        active_cooldowns = {}
        for key in keys:
            event_type = key.replace(COOLDOWN_PREFIX, "")
            ttl = await self.redis.ttl(key)
            active_cooldowns[event_type] = ttl

        return {
            "active_cooldowns": active_cooldowns,
            "total_active": len(keys),
        }
