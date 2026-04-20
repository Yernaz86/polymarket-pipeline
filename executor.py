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

    if logger.has_trade_today(signal.market.condition_id):
        return _log_and_return(signal, status="rejected_duplicate", order_id=None)

    if config.DRY_RUN:
        return _log_and_return(signal, status="dry_run", order_id=None)

    _validate_live_credentials()
    return _execute_live(signal)


def _validate_live_credentials() -> None:
    """Raise RuntimeError if required live-trading credentials are missing."""
    missing = [
        name for name, val in [
            ("POLYMARKET_API_KEY", config.POLYMARKET_API_KEY),
            ("POLYMARKET_PRIVATE_KEY", config.POLYMARKET_PRIVATE_KEY),
        ] if not val
    ]
    if missing:
        raise RuntimeError(
            f"Live trading requires credentials that are not set: {', '.join(missing)}. "
            "Set them in your .env file or environment before running with DRY_RUN=False."
        )


async def execute_trade_async(signal: Signal) -> dict:
    """Async wrapper around execute_trade."""
    return await asyncio.get_event_loop().run_in_executor(None, execute_trade, signal)


def close_position_live(position: dict, current_price: float) -> dict:
    """
    Place a SELL order to close an open position at the given price.

    Args:
        position: dict from logger.get_open_positions() — must have token_id, shares, trade_id
        current_price: price at which to place the sell limit order
    """
    trade_id = position.get("trade_id")
    try:
        from py_clob_client.client import ClobClient
        from py_clob_client.clob_types import OrderArgs, OrderType

        _validate_live_credentials()

        token_id = position.get("token_id", "")
        if not token_id:
            log.error(f"[executor] close_position_live: no token_id for trade_id={trade_id}")
            return {"status": "error_no_token", "trade_id": trade_id}

        client = ClobClient(
            host=config.POLYMARKET_HOST,
            key=config.POLYMARKET_API_KEY,
            chain_id=137,
            funder=config.POLYMARKET_PRIVATE_KEY,
        )
        client.set_api_creds(client.create_or_derive_api_creds())

        shares = float(position.get("shares", 0))
        if shares <= 0:
            log.error(f"[executor] close_position_live: zero shares for trade_id={trade_id}")
            return {"status": "error_zero_shares", "trade_id": trade_id}

        order_args = OrderArgs(
            price=current_price,
            size=shares,
            side="SELL",
            token_id=token_id,
        )

        signed_order = client.create_order(order_args)
        resp = client.post_order(signed_order, OrderType.GTC)
        order_id = resp.get("orderID", resp.get("id", "unknown"))

        fill_status, _ = _poll_order_status(order_id, client, max_wait_s=30)
        reason = f"sell_{fill_status}"
        logger.close_position(trade_id, current_price, reason=reason)

        log.info(
            f"[executor] Position closed: trade_id={trade_id} "
            f"status={fill_status} price={current_price:.4f}"
        )
        return {"status": f"closed_{fill_status}", "trade_id": trade_id, "order_id": order_id}

    except ImportError:
        logger.close_position(trade_id, current_price, reason="error_no_clob_client")
        return {"status": "error_no_clob_client", "trade_id": trade_id}
    except Exception as e:
        err = f"error_{type(e).__name__}"
        log.error(f"[executor] close_position_live failed for trade_id={trade_id}: {e}")
        logger.close_position(trade_id, current_price, reason=err)
        return {"status": err, "trade_id": trade_id}


async def close_position_live_async(position: dict, current_price: float) -> dict:
    """Async wrapper around close_position_live."""
    return await asyncio.get_event_loop().run_in_executor(
        None, close_position_live, position, current_price
    )


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

        result = _log_and_return(signal, status=status, order_id=order_id, filled_usd=filled_usd)

        # Track position for stop-loss / expiry monitoring
        if fill_status in ("filled", "partial") and filled_usd and filled_usd > 0:
            entry_price = price
            shares = filled_usd / max(entry_price, 0.01)
            stop_price = entry_price * (1.0 - config.STOP_LOSS_PCT)
            logger.open_position(
                trade_id=result["trade_id"],
                market_id=signal.market.condition_id,
                side=signal.side,
                entry_price=entry_price,
                shares=shares,
                stop_loss_price=stop_price,
                token_id=token_id or "",
                market_end_date=signal.market.end_date or "",
            )
            log.info(
                f"[executor] Position opened: {signal.side} {shares:.2f} shares "
                f"@ {entry_price:.3f}, stop @ {stop_price:.3f}, "
                f"expires {signal.market.end_date}"
            )

        return result

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
