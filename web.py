"""
Polymarket Pipeline — Web Dashboard
Run with: python cli.py web
Then open: http://localhost:8000
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

import config
import logger
from markets import fetch_active_markets, filter_by_categories

app = FastAPI(title="Polymarket Pipeline")

TEMPLATE = Path(__file__).parent / "templates" / "index.html"


@app.get("/", response_class=HTMLResponse)
def index():
    return TEMPLATE.read_text(encoding="utf-8")


@app.get("/api/stats")
def stats():
    s = logger.get_trade_stats()
    cal = logger.get_calibration_stats()
    lat = logger.get_latency_stats()
    daily = logger.get_daily_pnl()
    return {
        "total_signals": s["total_trades"],
        "by_status": s["by_status"],
        "daily_pnl": round(daily, 2),
        "accuracy": cal["accuracy"],
        "calibrated_trades": cal["total"],
        "avg_latency_ms": lat["avg_total_ms"],
        "dry_run": config.DRY_RUN,
        "daily_limit": config.DAILY_LOSS_LIMIT_USD,
    }


@app.get("/api/trades")
def trades(limit: int = 30):
    rows = logger.get_recent_trades(limit=limit)
    return rows


@app.get("/api/news")
def news(limit: int = 20):
    return logger.get_recent_news_events(limit=limit)


@app.get("/api/calibration")
def calibration():
    return logger.get_calibration_stats()


@app.get("/api/timeline")
def timeline(days: int = 7):
    return logger.get_signals_timeline(days=days)


@app.get("/api/distribution")
def distribution():
    return logger.get_signal_distribution()


@app.get("/api/health")
def health():
    return logger.get_news_health()


@app.get("/api/positions")
def positions():
    return {
        "summary": logger.get_positions_summary(),
        "open": logger.get_open_positions(),
    }


@app.get("/api/markets")
def markets():
    try:
        all_m = fetch_active_markets(limit=150)
        filtered = filter_by_categories(all_m)
        niche = [
            m for m in filtered
            if config.MIN_VOLUME_USD <= m.volume <= config.MAX_VOLUME_USD
        ]
        return [
            {
                "question": m.question,
                "category": m.category,
                "yes_price": m.yes_price,
                "no_price": m.no_price,
                "volume": m.volume,
            }
            for m in niche[:25]
        ]
    except Exception as e:
        return {"error": str(e)}


def run(host: str = "0.0.0.0", port: int = 8000):
    import uvicorn
    uvicorn.run(app, host=host, port=port, log_level="warning")
