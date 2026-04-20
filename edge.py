from __future__ import annotations

from dataclasses import dataclass

import config
from markets import Market
from classifier import Classification
from news_stream import NewsEvent


@dataclass
class Signal:
    market: Market
    claude_score: float
    market_price: float
    edge: float
    side: str  # "YES" or "NO"
    bet_amount: float
    reasoning: str
    headlines: str
    # V2 fields
    news_source: str = ""
    classification: str = ""
    materiality: float = 0.0
    news_latency_ms: int = 0
    classification_latency_ms: int = 0
    total_latency_ms: int = 0


def detect_edge(
    market: Market,
    claude_score: float,
    reasoning: str = "",
    headlines: str = "",
) -> Signal | None:
    """V1: Compare Claude's confidence against market price."""
    market_price = market.yes_price
    edge = claude_score - market_price

    if abs(edge) < config.EDGE_THRESHOLD:
        return None

    if edge > 0:
        side = "YES"
        raw_edge = edge
        our_prob = claude_score          # prob YES = 1
        token_price = market_price       # cost of YES token
    else:
        side = "NO"
        raw_edge = abs(edge)
        our_prob = 1.0 - claude_score    # prob NO = 1
        token_price = 1.0 - market_price # cost of NO token

    bet_amount = size_position(our_prob, token_price)

    return Signal(
        market=market,
        claude_score=claude_score,
        market_price=market_price,
        edge=raw_edge,
        side=side,
        bet_amount=bet_amount,
        reasoning=reasoning,
        headlines=headlines,
    )


def detect_edge_v2(
    market: Market,
    classification: Classification,
    news_event: NewsEvent,
) -> Signal | None:
    """
    V2: Use classification direction + materiality instead of probability estimation.
    Only generates a signal when:
    - Direction is bullish or bearish (not neutral)
    - Materiality exceeds threshold
    - Market price has room to move in the predicted direction
    """
    if classification.direction == "neutral":
        return None

    if classification.materiality < config.MATERIALITY_THRESHOLD:
        return None

    market_price = market.yes_price

    # Derive implied probability from materiality: mat=0.6 → 77%, mat=1.0 → 95%
    our_prob = 0.5 + classification.materiality * 0.45

    if classification.direction == "bullish":
        side = "YES"
        # Don't buy YES on markets already priced high
        if market_price > 0.85:
            return None
        edge = classification.materiality * (1.0 - market_price)
        token_price = market_price
    else:  # bearish
        side = "NO"
        # Don't buy NO on markets already priced low
        if market_price < 0.15:
            return None
        edge = classification.materiality * market_price
        token_price = 1.0 - market_price  # cost of NO token

    if edge < config.EDGE_THRESHOLD:
        return None

    bet_amount = size_position(our_prob, token_price)
    total_latency = news_event.latency_ms + classification.latency_ms

    return Signal(
        market=market,
        claude_score=classification.materiality,
        market_price=market_price,
        edge=edge,
        side=side,
        bet_amount=bet_amount,
        reasoning=classification.reasoning,
        headlines=news_event.headline,
        news_source=news_event.source,
        classification=classification.direction,
        materiality=classification.materiality,
        news_latency_ms=news_event.latency_ms,
        classification_latency_ms=classification.latency_ms,
        total_latency_ms=total_latency,
    )


def size_position(our_prob: float, token_price: float) -> float:
    """
    Quarter-Kelly position sizing for binary prediction markets.

    Full Kelly fraction for a binary bet:
      f* = (b*p - q) / b  where b = (1-mp)/mp, p = our_prob, q = 1-p
         = p - (1-p) * mp / (1-mp)
    We apply a 0.25 safety factor (quarter-Kelly) to account for model error.
    Bankroll = DAILY_LOSS_LIMIT_USD (max capital at risk per day).

    Args:
        our_prob:    our estimated probability the token resolves to $1
        token_price: current market price of the token (cost per share)
    """
    mp = max(min(token_price, 0.99), 0.01)
    p = max(min(our_prob, 0.99), 0.01)
    q = 1.0 - p
    b = (1.0 - mp) / mp           # net odds: risk mp to win (1-mp)
    kelly = (b * p - q) / b       # full Kelly fraction
    kelly = max(kelly, 0.0)       # never bet negative
    fraction = kelly * 0.25       # quarter-Kelly
    raw_size = config.DAILY_LOSS_LIMIT_USD * fraction
    return min(max(round(raw_size, 2), 1.0), config.MAX_BET_USD)
