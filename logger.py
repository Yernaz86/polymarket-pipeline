from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).parent / "trades.db"


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    conn = _conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            market_id TEXT NOT NULL,
            market_question TEXT NOT NULL,
            claude_score REAL NOT NULL,
            market_price REAL NOT NULL,
            edge REAL NOT NULL,
            side TEXT NOT NULL,
            amount_usd REAL NOT NULL,
            order_id TEXT,
            status TEXT NOT NULL DEFAULT 'dry_run',
            reasoning TEXT,
            headlines TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            -- V2 columns
            news_source TEXT,
            classification TEXT,
            materiality REAL,
            news_latency_ms INTEGER,
            classification_latency_ms INTEGER,
            total_latency_ms INTEGER
        );

        CREATE TABLE IF NOT EXISTS outcomes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trade_id INTEGER NOT NULL REFERENCES trades(id),
            resolved_at TEXT,
            result TEXT,
            pnl REAL,
            UNIQUE(trade_id)
        );

        CREATE TABLE IF NOT EXISTS pipeline_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            markets_scanned INTEGER DEFAULT 0,
            signals_found INTEGER DEFAULT 0,
            trades_placed INTEGER DEFAULT 0,
            status TEXT DEFAULT 'running'
        );

        CREATE TABLE IF NOT EXISTS news_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            headline TEXT NOT NULL,
            source TEXT NOT NULL,
            received_at TEXT NOT NULL,
            latency_ms INTEGER,
            matched_markets INTEGER DEFAULT 0,
            triggered_trades INTEGER DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS calibration (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trade_id INTEGER REFERENCES trades(id),
            classification TEXT,
            materiality REAL,
            entry_price REAL,
            exit_price REAL,
            actual_direction TEXT,
            correct INTEGER,
            resolved_at TEXT,
            UNIQUE(trade_id)
        );

        CREATE TABLE IF NOT EXISTS positions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trade_id INTEGER NOT NULL REFERENCES trades(id),
            market_id TEXT NOT NULL,
            side TEXT NOT NULL,
            entry_price REAL NOT NULL,
            shares REAL NOT NULL,
            stop_loss_price REAL NOT NULL,
            current_price REAL,
            unrealized_pnl REAL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'open',
            opened_at TEXT NOT NULL DEFAULT (datetime('now')),
            closed_at TEXT,
            exit_price REAL,
            exit_reason TEXT,
            UNIQUE(trade_id)
        );
    """)
    # Add V2 columns to existing trades table if missing
    _migrate_v2_columns(conn)
    conn.close()


def _migrate_v2_columns(conn):
    """Add V2 columns to trades table if they don't exist."""
    cursor = conn.execute("PRAGMA table_info(trades)")
    columns = {row[1] for row in cursor.fetchall()}
    new_cols = [
        ("news_source", "TEXT"),
        ("classification", "TEXT"),
        ("materiality", "REAL"),
        ("news_latency_ms", "INTEGER"),
        ("classification_latency_ms", "INTEGER"),
        ("total_latency_ms", "INTEGER"),
        ("filled_usd", "REAL"),  # actual fill amount for partial/full fills; NULL = unknown
    ]
    for col_name, col_type in new_cols:
        if col_name not in columns:
            conn.execute(f"ALTER TABLE trades ADD COLUMN {col_name} {col_type}")
    conn.commit()


def log_trade(
    market_id: str,
    market_question: str,
    claude_score: float,
    market_price: float,
    edge: float,
    side: str,
    amount_usd: float,
    order_id: str | None = None,
    status: str = "dry_run",
    reasoning: str = "",
    headlines: str = "",
    news_source: str | None = None,
    classification: str | None = None,
    materiality: float | None = None,
    news_latency_ms: int | None = None,
    classification_latency_ms: int | None = None,
    total_latency_ms: int | None = None,
    filled_usd: float | None = None,
) -> int:
    conn = _conn()
    cur = conn.execute(
        """INSERT INTO trades
           (market_id, market_question, claude_score, market_price, edge,
            side, amount_usd, order_id, status, reasoning, headlines,
            news_source, classification, materiality,
            news_latency_ms, classification_latency_ms, total_latency_ms,
            filled_usd)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (market_id, market_question, claude_score, market_price, edge,
         side, amount_usd, order_id, status, reasoning, headlines,
         news_source, classification, materiality,
         news_latency_ms, classification_latency_ms, total_latency_ms,
         filled_usd),
    )
    trade_id = cur.lastrowid
    conn.commit()
    conn.close()
    return trade_id


def log_news_event(
    headline: str,
    source: str,
    received_at: str,
    latency_ms: int = 0,
    matched_markets: int = 0,
    triggered_trades: int = 0,
) -> int:
    conn = _conn()
    cur = conn.execute(
        """INSERT INTO news_events
           (headline, source, received_at, latency_ms, matched_markets, triggered_trades)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (headline, source, received_at, latency_ms, matched_markets, triggered_trades),
    )
    event_id = cur.lastrowid
    conn.commit()
    conn.close()
    return event_id


def log_calibration(
    trade_id: int,
    classification: str,
    materiality: float,
    entry_price: float,
    exit_price: float | None = None,
    actual_direction: str | None = None,
    correct: bool | None = None,
    resolved_at: str | None = None,
):
    conn = _conn()
    conn.execute(
        """INSERT OR REPLACE INTO calibration
           (trade_id, classification, materiality, entry_price, exit_price,
            actual_direction, correct, resolved_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (trade_id, classification, materiality, entry_price, exit_price,
         actual_direction, 1 if correct else (0 if correct is not None else None),
         resolved_at),
    )
    conn.commit()
    conn.close()


def log_run_start() -> int:
    conn = _conn()
    now = datetime.now(timezone.utc).isoformat()
    cur = conn.execute(
        "INSERT INTO pipeline_runs (started_at) VALUES (?)", (now,)
    )
    run_id = cur.lastrowid
    conn.commit()
    conn.close()
    return run_id


def log_run_end(run_id: int, markets_scanned: int, signals_found: int, trades_placed: int, status: str = "completed"):
    conn = _conn()
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """UPDATE pipeline_runs
           SET finished_at=?, markets_scanned=?, signals_found=?, trades_placed=?, status=?
           WHERE id=?""",
        (now, markets_scanned, signals_found, trades_placed, status, run_id),
    )
    conn.commit()
    conn.close()


def has_trade_today(market_id: str) -> bool:
    """Return True if a non-rejected, non-error trade was placed today for this market."""
    conn = _conn()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    row = conn.execute(
        """SELECT 1 FROM trades
           WHERE market_id = ?
             AND created_at LIKE ?
             AND status NOT LIKE 'rejected_%'
             AND status NOT LIKE 'error_%'
           LIMIT 1""",
        (market_id, f"{today}%"),
    ).fetchone()
    conn.close()
    return row is not None


def get_daily_pnl() -> float:
    """
    Return total USD spent on live orders today (negative = loss exposure).

    Per-status accounting:
    - 'filled' / 'executed' / 'executed_filled': count full amount_usd
    - 'executed_partial': count filled_usd (actual fill); falls back to
      amount_usd if filled_usd was not recorded (conservative)
    - 'executed_cancelled': count 0 (order did not fill, no capital deployed)
    - 'executed_pending': count full amount_usd (pessimistic; order may still fill)
    - dry_run / rejected_* / error_*: count 0
    """
    conn = _conn()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    row = conn.execute(
        """SELECT COALESCE(SUM(
               CASE
                 WHEN status IN ('filled', 'executed', 'executed_filled')
                   THEN -amount_usd
                 WHEN status = 'executed_partial'
                   THEN -COALESCE(filled_usd, amount_usd)
                 WHEN status = 'executed_pending'
                   THEN -amount_usd
                 WHEN status = 'executed_cancelled'
                   THEN 0
                 ELSE 0
               END
           ), 0) as spent
           FROM trades WHERE created_at LIKE ?""",
        (f"{today}%",),
    ).fetchone()
    conn.close()
    return row["spent"]


def get_recent_trades(limit: int = 20) -> list[dict]:
    conn = _conn()
    rows = conn.execute(
        "SELECT * FROM trades ORDER BY created_at DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_recent_news_events(limit: int = 20) -> list[dict]:
    conn = _conn()
    rows = conn.execute(
        "SELECT * FROM news_events ORDER BY created_at DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_trade_stats() -> dict:
    conn = _conn()
    total = conn.execute("SELECT COUNT(*) as c FROM trades").fetchone()["c"]
    by_status = conn.execute(
        "SELECT status, COUNT(*) as c FROM trades GROUP BY status"
    ).fetchall()
    conn.close()
    return {
        "total_trades": total,
        "by_status": {r["status"]: r["c"] for r in by_status},
    }


def get_calibration_stats() -> dict:
    conn = _conn()
    total = conn.execute("SELECT COUNT(*) as c FROM calibration WHERE correct IS NOT NULL").fetchone()["c"]
    if total == 0:
        conn.close()
        return {"total": 0, "accuracy": 0.0, "by_source": {}, "by_classification": {}}

    correct = conn.execute("SELECT COUNT(*) as c FROM calibration WHERE correct = 1").fetchone()["c"]

    by_source = {}
    rows = conn.execute("""
        SELECT t.news_source as source, COUNT(*) as total,
               SUM(CASE WHEN c.correct = 1 THEN 1 ELSE 0 END) as wins
        FROM calibration c JOIN trades t ON c.trade_id = t.id
        WHERE c.correct IS NOT NULL AND t.news_source IS NOT NULL
        GROUP BY t.news_source
    """).fetchall()
    for r in rows:
        by_source[r["source"]] = round(r["wins"] / r["total"] * 100, 1) if r["total"] > 0 else 0

    by_cls = {}
    rows = conn.execute("""
        SELECT classification, COUNT(*) as total,
               SUM(CASE WHEN correct = 1 THEN 1 ELSE 0 END) as wins
        FROM calibration WHERE correct IS NOT NULL
        GROUP BY classification
    """).fetchall()
    for r in rows:
        by_cls[r["classification"]] = round(r["wins"] / r["total"] * 100, 1) if r["total"] > 0 else 0

    conn.close()
    return {
        "total": total,
        "accuracy": round(correct / total * 100, 1),
        "by_source": by_source,
        "by_classification": by_cls,
    }


def get_signals_timeline(days: int = 7) -> list[dict]:
    """Return daily signal count and exposure for the last N days."""
    conn = _conn()
    rows = conn.execute(
        """SELECT
             substr(created_at, 1, 10) as day,
             COUNT(*) as signals,
             COALESCE(SUM(amount_usd), 0) as exposure,
             SUM(CASE WHEN classification='bullish' THEN 1 ELSE 0 END) as bullish,
             SUM(CASE WHEN classification='bearish' THEN 1 ELSE 0 END) as bearish
           FROM trades
           WHERE created_at >= date('now', ?)
           GROUP BY day
           ORDER BY day ASC""",
        (f"-{days} days",),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_signal_distribution() -> dict:
    """Count signals by classification and side."""
    conn = _conn()
    by_cls = conn.execute(
        """SELECT classification, COUNT(*) as c FROM trades
           WHERE classification IS NOT NULL
           GROUP BY classification"""
    ).fetchall()
    by_side = conn.execute(
        """SELECT side, COUNT(*) as c FROM trades GROUP BY side"""
    ).fetchall()
    conn.close()
    return {
        "by_classification": {r["classification"]: r["c"] for r in by_cls},
        "by_side": {r["side"]: r["c"] for r in by_side},
    }


def get_news_health() -> dict:
    """Return news ingestion health: last receipt time + per-source counts today."""
    conn = _conn()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    by_source = conn.execute(
        """SELECT source, COUNT(*) as c,
                  MAX(received_at) as last_seen
           FROM news_events
           WHERE created_at LIKE ?
           GROUP BY source""",
        (f"{today}%",),
    ).fetchall()
    last_row = conn.execute(
        "SELECT MAX(received_at) as last FROM news_events"
    ).fetchone()
    total_today = conn.execute(
        "SELECT COUNT(*) as c FROM news_events WHERE created_at LIKE ?",
        (f"{today}%",),
    ).fetchone()["c"]
    conn.close()
    return {
        "last_news_at": last_row["last"] if last_row else None,
        "total_today": total_today,
        "by_source": {r["source"]: {"count": r["c"], "last_seen": r["last_seen"]} for r in by_source},
    }


def get_latency_stats() -> dict:
    conn = _conn()
    row = conn.execute("""
        SELECT
            AVG(total_latency_ms) as avg_total,
            MIN(total_latency_ms) as min_total,
            MAX(total_latency_ms) as max_total,
            AVG(news_latency_ms) as avg_news,
            AVG(classification_latency_ms) as avg_class,
            COUNT(*) as count
        FROM trades
        WHERE total_latency_ms IS NOT NULL
    """).fetchone()
    conn.close()
    if not row or row["count"] == 0:
        return {"avg_total_ms": 0, "min_total_ms": 0, "max_total_ms": 0,
                "avg_news_ms": 0, "avg_class_ms": 0, "count": 0}
    return {
        "avg_total_ms": round(row["avg_total"] or 0),
        "min_total_ms": round(row["min_total"] or 0),
        "max_total_ms": round(row["max_total"] or 0),
        "avg_news_ms": round(row["avg_news"] or 0),
        "avg_class_ms": round(row["avg_class"] or 0),
        "count": row["count"],
    }


def open_position(
    trade_id: int,
    market_id: str,
    side: str,
    entry_price: float,
    shares: float,
    stop_loss_price: float,
) -> int:
    """Record a new open position after a successful fill."""
    conn = _conn()
    cur = conn.execute(
        """INSERT OR IGNORE INTO positions
           (trade_id, market_id, side, entry_price, shares, stop_loss_price, current_price)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (trade_id, market_id, side, entry_price, shares, stop_loss_price, entry_price),
    )
    pos_id = cur.lastrowid
    conn.commit()
    conn.close()
    return pos_id


def get_open_positions() -> list[dict]:
    conn = _conn()
    rows = conn.execute(
        "SELECT * FROM positions WHERE status = 'open' ORDER BY opened_at DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_position_price(market_id: str, current_price: float) -> None:
    """Update current price and unrealized P&L for all open positions on this market."""
    conn = _conn()
    conn.execute(
        """UPDATE positions
           SET current_price = ?,
               unrealized_pnl = (? - entry_price) * shares
           WHERE market_id = ? AND status = 'open'""",
        (current_price, current_price, market_id),
    )
    conn.commit()
    conn.close()


def close_position(trade_id: int, exit_price: float, reason: str) -> None:
    """Mark a position as closed."""
    conn = _conn()
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """UPDATE positions
           SET status = ?,
               closed_at = ?,
               exit_price = ?,
               exit_reason = ?,
               unrealized_pnl = (? - entry_price) * shares
           WHERE trade_id = ?""",
        (f"closed_{reason}", now, exit_price, reason, exit_price, trade_id),
    )
    conn.commit()
    conn.close()


def get_positions_summary() -> dict:
    """Return summary stats for open and closed positions."""
    conn = _conn()
    open_row = conn.execute(
        """SELECT COUNT(*) as count,
                  COALESCE(SUM(unrealized_pnl), 0) as total_upnl,
                  COALESCE(SUM(entry_price * shares), 0) as total_exposure
           FROM positions WHERE status = 'open'"""
    ).fetchone()
    closed_row = conn.execute(
        """SELECT COUNT(*) as count,
                  COALESCE(SUM(unrealized_pnl), 0) as total_realized
           FROM positions WHERE status != 'open'"""
    ).fetchone()
    conn.close()
    return {
        "open_count": open_row["count"],
        "open_unrealized_pnl": round(open_row["total_upnl"], 2),
        "open_exposure_usd": round(open_row["total_exposure"], 2),
        "closed_count": closed_row["count"],
        "closed_realized_pnl": round(closed_row["total_realized"], 2),
    }


init_db()
