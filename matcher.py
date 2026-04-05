"""
News-to-market matching — routes breaking news to relevant active markets.
Two strategies: fast weighted TF-IDF matching + category fallback.
"""
from __future__ import annotations

import logging
import math
from collections import Counter
from markets import Market

log = logging.getLogger(__name__)

STOPWORDS = {
    "will", "the", "a", "an", "be", "by", "in", "on", "at", "to", "of",
    "for", "is", "it", "this", "that", "and", "or", "not", "before",
    "after", "end", "yes", "no", "any", "has", "have", "does", "do",
    "than", "more", "less", "over", "under", "above", "below", "through",
    "during", "between", "reach", "exceed", "with", "from", "are", "was",
    "been", "would", "could", "should", "may", "might", "its", "their",
    "there", "then", "when", "which", "what", "who", "how", "new", "said",
}


def _tokenize(text: str) -> list[str]:
    """Lowercase, strip punctuation, remove stopwords, min length 3."""
    words = text.lower().split()
    return [
        w.strip("?.,!\"'()[]:-")
        for w in words
        if w.strip("?.,!\"'()[]:-") not in STOPWORDS
        and len(w.strip("?.,!\"'()[]:-")) >= 3
    ]


def _bigrams(tokens: list[str]) -> list[str]:
    """Generate adjacent word pairs: ['fed rate', 'rate cut', ...]"""
    return [f"{tokens[i]} {tokens[i+1]}" for i in range(len(tokens) - 1)]


def _idf_weight(token: str) -> float:
    """
    Approximate IDF by token length — longer/rarer words score higher.
    Short common words (3-4 chars) get low weight even if not in stopwords.
    Bigrams always get a boost.
    """
    if " " in token:  # bigram
        return 2.5
    length = len(token)
    if length <= 4:
        return 0.5
    if length <= 6:
        return 1.0
    if length <= 9:
        return 1.5
    return 2.0


def _score_similarity(headline_tokens: set[str], market_tokens: list[str]) -> float:
    """
    Compute weighted overlap score between headline tokens and market tokens.
    Returns a score in [0, 1] range (normalized by market token weights).
    """
    if not market_tokens:
        return 0.0

    total_weight = sum(_idf_weight(t) for t in market_tokens)
    if total_weight == 0:
        return 0.0

    matched_weight = sum(
        _idf_weight(t) for t in market_tokens if t in headline_tokens
    )
    return matched_weight / total_weight


def extract_keywords(question: str) -> list[str]:
    """Extract meaningful keywords from a market question (public API, kept for compatibility)."""
    return _tokenize(question)


def match_news_to_markets(
    headline: str,
    markets: list[Market],
    max_matches: int = 5,
) -> list[Market]:
    """
    Find markets that a news headline is relevant to.
    Uses weighted TF-IDF scoring with bigram support — fast, no API call.
    Requires at least one meaningful keyword hit to qualify.
    """
    h_tokens = _tokenize(headline)
    h_bigrams = _bigrams(h_tokens)
    headline_set = set(h_tokens) | set(h_bigrams)

    scored = []
    for market in markets:
        q_tokens = _tokenize(market.question)
        q_bigrams = _bigrams(q_tokens)
        all_market_tokens = q_tokens + q_bigrams

        # Require at least one direct token hit (avoids noisy category-only matches)
        if not any(t in headline_set for t in all_market_tokens):
            continue

        score = _score_similarity(headline_set, all_market_tokens)
        if score > 0:
            scored.append((score, market))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [m for _, m in scored[:max_matches]]


def match_news_to_markets_broad(
    headline: str,
    summary: str,
    markets: list[Market],
    max_matches: int = 5,
) -> list[Market]:
    """
    Broader matching using headline + summary text.
    Falls back to category matching if keyword matching returns nothing.
    """
    # Try keyword matching first
    matches = match_news_to_markets(headline, markets, max_matches)
    if matches:
        return matches

    # Fallback: match on category keywords in the headline
    combined = f"{headline} {summary}".lower()
    category_keywords = {
        "ai": ["ai", "openai", "gpt", "anthropic", "claude", "llm", "chatgpt", "gemini", "artificial intelligence"],
        "crypto": ["bitcoin", "ethereum", "solana", "crypto", "blockchain", "defi", "token", "btc", "eth"],
        "politics": ["trump", "biden", "congress", "senate", "election", "tariff", "fed", "white house"],
        "technology": ["apple", "google", "microsoft", "nvidia", "tech", "software", "startup"],
        "science": ["spacex", "nasa", "climate", "research", "discovery"],
    }

    matched_categories = set()
    for cat, kws in category_keywords.items():
        if any(kw in combined for kw in kws):
            matched_categories.add(cat)

    if not matched_categories:
        return []

    # Return markets in matching categories
    category_matches = [m for m in markets if m.category in matched_categories]
    return category_matches[:max_matches]


if __name__ == "__main__":
    from markets import fetch_active_markets, filter_by_categories
    import config

    print("Fetching markets...")
    all_m = fetch_active_markets(limit=100)
    filtered = filter_by_categories(all_m)
    niche = [m for m in filtered if config.MIN_VOLUME_USD <= m.volume <= config.MAX_VOLUME_USD]
    print(f"Niche markets: {len(niche)}")

    test_headlines = [
        "OpenAI reportedly testing GPT-5 internally with select partners",
        "Bitcoin ETF inflows hit $2.1B in single week",
        "Fed minutes signal growing consensus for summer rate cut",
    ]

    for h in test_headlines:
        matches = match_news_to_markets(h, niche)
        print(f"\n\"{h[:60]}...\"")
        print(f"  Matched {len(matches)} markets:")
        for m in matches:
            print(f"    [{m.category}] {m.question[:50]}")
