"""Audit log service — append-only, tamper-evident event recording.

Per v1.31 Section 16.5.3: all trade decisions, broker responses,
risk blocks, and manual operator actions are logged immutably.
"""

import hashlib
import json
import logging
import uuid

import asyncpg

logger = logging.getLogger(__name__)


async def log_event(
    pool: asyncpg.Pool,
    *,
    source: str,
    event_type: str,
    payload: dict,
    strategy_id: str | None = None,
    symbol: str | None = None,
    operator_id: str = "system",
    correlation_id: str | None = None,
):
    """Write an immutable audit log entry."""
    event_id = str(uuid.uuid4())
    payload_json = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    payload_hash = hashlib.sha256(payload_json.encode()).hexdigest()

    try:
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO audit_log (event_id, source, event_type, strategy_id, symbol,
                    operator_id, correlation_id, payload, payload_hash)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb, $9)
                """,
                event_id, source, event_type, strategy_id, symbol,
                operator_id, correlation_id, payload_json, payload_hash,
            )
    except Exception as e:
        # Audit log failure should never block trading, but MUST be logged
        logger.error("AUDIT LOG WRITE FAILED: %s — event_type=%s payload=%s", e, event_type, payload_json[:200])
