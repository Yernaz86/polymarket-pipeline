import os
from dotenv import load_dotenv

load_dotenv()

# --- Anthropic ---
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# --- Polymarket CLOB ---
POLYMARKET_API_KEY = os.getenv("POLYMARKET_API_KEY", "")
POLYMARKET_API_SECRET = os.getenv("POLYMARKET_API_SECRET", "")
POLYMARKET_API_PASSPHRASE = os.getenv("POLYMARKET_API_PASSPHRASE", "")
POLYMARKET_PRIVATE_KEY = os.getenv("POLYMARKET_PRIVATE_KEY", "")
POLYMARKET_HOST = "https://clob.polymarket.com"
POLYMARKET_WS_HOST = "wss://ws-subscriptions-clob.polymarket.com/ws/market"

# --- Twitter API v2 ---
TWITTER_BEARER_TOKEN = os.getenv("TWITTER_BEARER_TOKEN", "")

# --- Telegram ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHANNEL_IDS = [
    c.strip() for c in os.getenv("TELEGRAM_CHANNEL_IDS", "").split(",") if c.strip()
]

# --- NewsAPI (optional, RSS fallback) ---
NEWSAPI_KEY = os.getenv("NEWSAPI_KEY", "")

# --- RSS Feeds (fallback) ---
RSS_FEEDS = [
    "https://news.google.com/rss/search?q=AI+artificial+intelligence&hl=en-US&gl=US&ceid=US:en",
    "https://feeds.feedburner.com/TechCrunch",
    "https://feeds.arstechnica.com/arstechnica/technology-lab",
    "https://www.theverge.com/rss/index.xml",
    "https://rss.nytimes.com/services/xml/rss/nyt/Technology.xml",
]

# --- Pipeline Settings ---
DRY_RUN = os.getenv("DRY_RUN", "true").lower() == "true"
MAX_BET_USD = float(os.getenv("MAX_BET_USD", "25"))
DAILY_LOSS_LIMIT_USD = float(os.getenv("DAILY_LOSS_LIMIT_USD", "100"))
EDGE_THRESHOLD = float(os.getenv("EDGE_THRESHOLD", "0.10"))
NEWS_LOOKBACK_HOURS = 6

# --- V2 Settings ---
MAX_VOLUME_USD = float(os.getenv("MAX_VOLUME_USD", "500000"))
MIN_VOLUME_USD = float(os.getenv("MIN_VOLUME_USD", "1000"))
MATERIALITY_THRESHOLD = float(os.getenv("MATERIALITY_THRESHOLD", "0.6"))
SPEED_TARGET_SECONDS = float(os.getenv("SPEED_TARGET_SECONDS", "5"))
STOP_LOSS_PCT = float(os.getenv("STOP_LOSS_PCT", "0.50"))  # exit position if it loses this fraction of entry value
CLASSIFICATION_MODEL = "claude-haiku-4-5-20251001"
SCORING_MODEL = "claude-sonnet-4-6-20250514"
CLAUDE_MODEL = SCORING_MODEL  # alias for backward compatibility

# --- Categories to track ---
MARKET_CATEGORIES = [
    "ai",
    "technology",
    "crypto",
    "politics",
    "science",
]

# --- Twitter filter keywords (for filtered stream rules) ---
TWITTER_KEYWORDS = [
    "OpenAI", "GPT-5", "Anthropic", "Claude", "Google AI", "Gemini",
    "Bitcoin", "Ethereum", "Solana", "crypto",
    "Fed rate", "tariff", "Congress", "White House",
    "SpaceX", "Starship", "NASA",
    "Apple", "NVIDIA", "Microsoft", "Google",
]
