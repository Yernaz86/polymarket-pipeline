from __future__ import annotations

import asyncio
import time
import logging

import config
import logger
from edge import Signal
from markets import get_token_id

log = logging.getLogger(__name__)


def execute_trade(signal: Signal) -> dict:
    """Execute a trade on Polymarket or log a dry-run. Synchronous."""
    daily_spent = abs(logger.get_daily_pnl())
    if daily_spent + signal.bet_amount > config.DAILY_LOSS_LIMIT_USD:
        return _log_and_return(signal, status="rejected_daily_limit", order_id=None)

    if config.DRY_RUN:
        return _log_and_return(signal, status="dry_run", order_id=None)

    return _execute_live(signal)


async def execute_trade_async(signal: Signal) -> dict:
    """Async wrapper around execute_trade."""
    return await asyncio.get_event_loop().run_in_executor(None, execute_trade, signal)


def _execute_live(signal: Signal) -> dict:
    """Place a real order via Polymarket CLOB client."""
    try:
        from py_clob_client.client import ClobClient
        from py_clob_client.clob_types import OrderArgs, OrderType

        client = ClobClient(
            host=config.POLYMARKET_HOST,
            key=config.POLYMARKET_API_KEY,
            chain_id=137,
            funder=config.POLYMARKET_PRIVATE_KEY,
        )

        client.set_api_creds(client.create_or_derive_api_creds())

        token_id = get_token_id(signal.market, signal.side)
        if not token_id:
            return _log_and_return(signal, status="error_no_token", order_id=None)

        price = signal.market.yes_price if signal.side == "YES" else signal.market.no_price

        order_args = OrderArgs(
            price=price,
            size=signal.bet_amount,
            side="BUY",
            token_id=token_id,
        )

        signed_order = client.create_order(order_args)
        resp = client.post_order(signed_order, OrderType.GTC)

        order_id = resp.get("orderID", resp.get("id", "unknown"))

        # Poll for fill confirmation (up to 30s); capture actual filled amount
        fill_status, filled_usd = _poll_order_status(order_id, client, max_wait_s=30)
        status = f"executed_{fill_status}"

        return _log_and_return(signal, status=status, order_id=order_id, filled_usd=filled_usd)

    except ImportError:
        return _log_and_return(signal, status="error_no_clob_client", order_id=None)
    except Exception as e:
        return _log_and_return(signal, status=f"error_{type(e).__name__}", order_id=None)


def _poll_order_status(order_id: str, client, max_wait_s: int = 30) -> tuple[str, float]:
    """
    Poll the CLOB API to check fill status after order placement.

    Returns (status, filled_usd) where:
    - status:     'filled' | 'partial' | 'cancelled' | 'pending'
    - filled_usd: actual dollar amount matched (0.0 for cancelled/pending)
    """
    deadline = time.time() + max_wait_s
    poll_interval = 3

    while time.time() < deadline:
        try:
            resp = client.get_order(order_id)
            status = (resp.get("status") or "").upper()
            size_matched = float(resp.get("sizeMatched", 0) or 0)
            size_filled = float(resp.get("sizeFilled", size_matched) or 0)
            original_size = float(resp.get("originalSize", resp.get("size", 0)) or 1)

            if status in ("MATCHED", "FILLED"):
                log.info(f"[executor] Order {order_id} filled (${size_filled:.2f})")
                return "filled", size_filled

            if status in ("CANCELLED", "CANCELED"):
                log.warning(f"[executor] Order {order_id} cancelled by exchange")
                return "cancelled", 0.0

            # Partially filled and no longer active
            if status == "UNMATCHED" and size_filled > 0:
                fill_pct = size_filled / max(original_size, 0.01)
                log.info(f"[executor] Order {order_id} partial fill ({fill_pct:.0%}, ${size_filled:.2f})")
                return "partial", size_filled

        except Exception as e:
            log.warning(f"[executor] Status poll error for {order_id}: {e}")

        time.sleep(poll_interval)

    log.warning(f"[executor] Order {order_id} status unknown after {max_wait_s}s (still open)")
    return "pending", 0.0


def _log_and_return(
    signal: Signal,
    status: str,
    order_id: str | None,
    filled_usd: float | None = None,
) -> dict:
    """Log trade to SQLite and return result dict."""
    trade_id = logger.log_trade(
        market_id=signal.market.condition_id,
        market_question=signal.market.question,
        claude_score=signal.claude_score,
        market_price=signal.market_price,
        edge=signal.edge,
        side=signal.side,
        amount_usd=signal.bet_amount,
        order_id=order_id,
        status=status,
        reasoning=signal.reasoning,
        headlines=signal.headlines,
        news_source=signal.news_source,
        classification=signal.classification,
        materiality=signal.materiality,
        news_latency_ms=signal.news_latency_ms,
        classification_latency_ms=signal.classification_latency_ms,
        total_latency_ms=signal.total_latency_ms,
        filled_usd=filled_usd,
    )

    return {
        "trade_id": trade_id,
        "market": signal.market.question,
        "side": signal.side,
        "amount": signal.bet_amount,
        "edge": signal.edge,
        "status": status,
        "order_id": order_id,
        "classification": signal.classification,
        "materiality": signal.materiality,
        "latency_ms": signal.total_latency_ms,
    }
