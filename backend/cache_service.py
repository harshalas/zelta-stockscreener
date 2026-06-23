import os
import json
from datetime import datetime, time
from typing import Optional, Any
import redis
from dotenv import load_dotenv

load_dotenv()


class RedisCacheService:
    def __init__(self):
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        self.pool = redis.ConnectionPool.from_url(redis_url, decode_responses=True)

    @property
    def client(self):
        return redis.Redis(connection_pool=self.pool)

    def get_cached_feed(self, key: str) -> Optional[Any]:
        try:
            data = self.client.get(key)
            if data:
                return json.loads(data)
        except Exception as e:
            print(f"Redis Read Error: {e}")
        return None

    # Base low-level setter
    def set_market_feed(self, key: str, data: Any, ttl_seconds: int):
        try:
            serialized_data = json.dumps(data)
            self.client.setex(key, ttl_seconds, serialized_data)
        except Exception as e:
            print(f"Redis Write Error: {e}")

    # =====================================================================
    # STRATEGIC MARKET TTL WRAPPERS
    # =====================================================================

    def cache_intraday_ticker(self, symbol: str, data: Any):
        """Intraday shifts rapidly. Cache for only 15 seconds during market hours."""
        key = f"ticker:live:{symbol.upper()}"
        self.set_market_feed(key, data, ttl_seconds=15)

    def cache_intraday_ticker_smart(self, symbol: str, data: Any):
        """Caches live data briefly during active hours, but locks it overnight."""
        key = f"ticker:live:{symbol.upper()}"
        current_time = datetime.now().time()

        # Check if current time is outside normal premarket/market hours (4:00 AM - 4:00 PM EST)
        if current_time > time(16, 0) or current_time < time(4, 0):
            ttl = 43200  # Keep it cached for 12 hours overnight
        else:
            ttl = 15  # Keep it fluid for 15 seconds during active momentum swings

        self.set_market_feed(key, data, ttl_seconds=ttl)

    def cache_historical_timeline(self, symbol: str, data: Any):
        """Historical data (EOD) changes daily. Cache for 1 hour (3600s)."""
        key = f"ticker:history:{symbol.upper()}"
        self.set_market_feed(key, data, ttl_seconds=3600)

    def cache_morning_alerts(self, data: Any):
        """Heavy calculations. Keep the generated batch alerts clean for 15 minutes (900s)."""
        key = "screener:morning:matched"
        self.set_market_feed(key, data, ttl_seconds=900)

    def cache_news_feed(self, symbol: str, data: Any):
        """News updates steadily. Hold context for 30 minutes (1800s)."""
        key = f"news:feed:{symbol.upper()}"
        self.set_market_feed(key, data, ttl_seconds=1800)

# Global instance to import across endpoints
market_cache = RedisCacheService()