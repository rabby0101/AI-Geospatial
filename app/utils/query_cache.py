"""
Query Result Caching Module

Provides intelligent caching for geospatial queries with support for:
- Redis (preferred, distributed)
- Disk cache (fallback)
- In-memory cache (development)
- Cache invalidation strategies
- Query fingerprinting for deduplication
"""

import hashlib
import json
import logging
import os
from typing import Any, Dict, Optional, List
from datetime import datetime, timedelta
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)

# Cache configuration from environment
CACHE_TYPE = os.getenv("CACHE_TYPE", "disk")  # 'redis', 'disk', or 'memory'
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
CACHE_TTL = int(os.getenv("CACHE_TTL_SECONDS", 3600))  # 1 hour default
MAX_CACHE_SIZE_MB = int(os.getenv("MAX_CACHE_SIZE_MB", 100))


class CacheBackend(ABC):
    """Abstract base class for cache backends"""

    @abstractmethod
    def get(self, key: str) -> Optional[Dict[str, Any]]:
        """Retrieve cached value"""
        pass

    @abstractmethod
    def set(self, key: str, value: Dict[str, Any], ttl: int = None) -> bool:
        """Store value in cache"""
        pass

    @abstractmethod
    def delete(self, key: str) -> bool:
        """Delete cached value"""
        pass

    @abstractmethod
    def clear(self) -> bool:
        """Clear entire cache"""
        pass

    @abstractmethod
    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        pass


class RedisCache(CacheBackend):
    """Redis-based cache backend (distributed, production-ready)"""

    def __init__(self, redis_url: str = REDIS_URL):
        """Initialize Redis connection"""
        try:
            import redis
            self.redis_url = redis_url
            self.client = redis.from_url(redis_url)
            # Test connection
            self.client.ping()
            logger.info(f"✅ Connected to Redis at {redis_url}")
            self.stats = {
                "hits": 0,
                "misses": 0,
                "total_keys": 0
            }
        except Exception as e:
            logger.warning(f"Failed to connect to Redis: {e}. Falling back to disk cache.")
            self.client = None

    def get(self, key: str) -> Optional[Dict[str, Any]]:
        """Retrieve cached value"""
        if not self.client:
            return None

        try:
            value = self.client.get(key)
            if value:
                self.stats["hits"] += 1
                return json.loads(value)
            else:
                self.stats["misses"] += 1
                return None
        except Exception as e:
            logger.error(f"Redis get error: {e}")
            return None

    def set(self, key: str, value: Dict[str, Any], ttl: int = None) -> bool:
        """Store value in cache"""
        if not self.client:
            return False

        try:
            ttl = ttl or CACHE_TTL
            serialized = json.dumps(value)
            self.client.setex(key, ttl, serialized)
            self.stats["total_keys"] = self.client.dbsize()
            return True
        except Exception as e:
            logger.error(f"Redis set error: {e}")
            return False

    def delete(self, key: str) -> bool:
        """Delete cached value"""
        if not self.client:
            return False

        try:
            self.client.delete(key)
            return True
        except Exception as e:
            logger.error(f"Redis delete error: {e}")
            return False

    def clear(self) -> bool:
        """Clear entire cache"""
        if not self.client:
            return False

        try:
            self.client.flushdb()
            self.stats["total_keys"] = 0
            return True
        except Exception as e:
            logger.error(f"Redis clear error: {e}")
            return False

    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        if not self.client:
            return {"status": "disconnected"}

        try:
            info = self.client.info()
            return {
                "type": "redis",
                "connected": True,
                "used_memory_mb": info.get("used_memory", 0) / (1024 * 1024),
                "keys": self.client.dbsize(),
                "hits": self.stats["hits"],
                "misses": self.stats["misses"],
                "hit_rate": self.stats["hits"] / (self.stats["hits"] + self.stats["misses"] + 0.001) if (self.stats["hits"] + self.stats["misses"]) > 0 else 0
            }
        except Exception as e:
            logger.error(f"Redis stats error: {e}")
            return {"status": "error", "error": str(e)}


class DiskCache(CacheBackend):
    """Disk-based cache backend (local, file-system)"""

    def __init__(self, cache_dir: str = ".cache/query_cache"):
        """Initialize disk cache"""
        try:
            import diskcache
            self.cache_dir = cache_dir
            self.cache = diskcache.Cache(cache_dir)
            logger.info(f"✅ Initialized disk cache at {cache_dir}")
            self.stats = {"hits": 0, "misses": 0}
        except Exception as e:
            logger.error(f"Failed to initialize disk cache: {e}")
            self.cache = None

    def get(self, key: str) -> Optional[Dict[str, Any]]:
        """Retrieve cached value"""
        if not self.cache:
            return None

        try:
            value = self.cache.get(key)
            if value:
                self.stats["hits"] += 1
                return value
            else:
                self.stats["misses"] += 1
                return None
        except Exception as e:
            logger.error(f"Disk cache get error: {e}")
            return None

    def set(self, key: str, value: Dict[str, Any], ttl: int = None) -> bool:
        """Store value in cache"""
        if not self.cache:
            return False

        try:
            ttl = ttl or CACHE_TTL
            self.cache.set(key, value, expire=ttl)
            return True
        except Exception as e:
            logger.error(f"Disk cache set error: {e}")
            return False

    def delete(self, key: str) -> bool:
        """Delete cached value"""
        if not self.cache:
            return False

        try:
            del self.cache[key]
            return True
        except Exception as e:
            logger.error(f"Disk cache delete error: {e}")
            return False

    def clear(self) -> bool:
        """Clear entire cache"""
        if not self.cache:
            return False

        try:
            self.cache.clear()
            return True
        except Exception as e:
            logger.error(f"Disk cache clear error: {e}")
            return False

    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        if not self.cache:
            return {"status": "disconnected"}

        try:
            return {
                "type": "disk",
                "connected": True,
                "size_mb": len(self.cache) if self.cache else 0,
                "keys": len(self.cache) if self.cache else 0,
                "hits": self.stats["hits"],
                "misses": self.stats["misses"],
                "hit_rate": self.stats["hits"] / (self.stats["hits"] + self.stats["misses"] + 0.001) if (self.stats["hits"] + self.stats["misses"]) > 0 else 0
            }
        except Exception as e:
            logger.error(f"Disk cache stats error: {e}")
            return {"status": "error", "error": str(e)}


class MemoryCache(CacheBackend):
    """In-memory cache backend (development, ephemeral)"""

    def __init__(self):
        """Initialize in-memory cache"""
        self.cache: Dict[str, tuple] = {}  # (value, expiry_time)
        self.stats = {"hits": 0, "misses": 0}
        logger.info("✅ Initialized in-memory cache")

    def get(self, key: str) -> Optional[Dict[str, Any]]:
        """Retrieve cached value"""
        if key not in self.cache:
            self.stats["misses"] += 1
            return None

        value, expiry = self.cache[key]
        if datetime.now() > expiry:
            del self.cache[key]
            self.stats["misses"] += 1
            return None

        self.stats["hits"] += 1
        return value

    def set(self, key: str, value: Dict[str, Any], ttl: int = None) -> bool:
        """Store value in cache"""
        ttl = ttl or CACHE_TTL
        expiry = datetime.now() + timedelta(seconds=ttl)
        self.cache[key] = (value, expiry)
        return True

    def delete(self, key: str) -> bool:
        """Delete cached value"""
        if key in self.cache:
            del self.cache[key]
            return True
        return False

    def clear(self) -> bool:
        """Clear entire cache"""
        self.cache.clear()
        return True

    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        return {
            "type": "memory",
            "connected": True,
            "keys": len(self.cache),
            "hits": self.stats["hits"],
            "misses": self.stats["misses"],
            "hit_rate": self.stats["hits"] / (self.stats["hits"] + self.stats["misses"] + 0.001) if (self.stats["hits"] + self.stats["misses"]) > 0 else 0
        }


class QueryCache:
    """
    High-level cache manager for geospatial queries.

    Features:
    - Query fingerprinting for deduplication
    - Configurable TTL per query type
    - Cache statistics and monitoring
    - Fallback chain: Redis → Disk → Memory
    """

    def __init__(self):
        """Initialize cache with appropriate backend"""
        self.cache_type = CACHE_TYPE.lower()

        # Initialize backend based on configuration
        if self.cache_type == "redis":
            try:
                self.backend = RedisCache()
            except Exception as e:
                logger.warning(f"Redis initialization failed: {e}. Falling back to disk cache.")
                self.backend = DiskCache()
        elif self.cache_type == "disk":
            self.backend = DiskCache()
        else:
            self.backend = MemoryCache()

        # Query type specific TTLs
        self.ttl_overrides = {
            "spatial_query": 3600,      # 1 hour
            "stats": 1800,              # 30 minutes
            "raster": 7200,             # 2 hours
            "export": 600,              # 10 minutes
        }

    def _generate_key(self, question: str, context: Dict[str, Any] = None) -> str:
        """
        Generate a cache key from query components.

        Creates a unique fingerprint for a query to enable deduplication.
        """
        # Build canonical query representation
        query_dict = {
            "question": question.lower().strip(),
            "context": context or {}
        }
        query_str = json.dumps(query_dict, sort_keys=True)

        # Create hash
        hash_obj = hashlib.sha256(query_str.encode())
        return f"query:{hash_obj.hexdigest()}"

    def get(self, question: str, context: Dict[str, Any] = None) -> Optional[Dict[str, Any]]:
        """
        Retrieve cached query result.

        Returns:
            Cached result or None if not found/expired
        """
        key = self._generate_key(question, context)
        result = self.backend.get(key)

        if result:
            logger.info(f"💨 Cache hit for query: {question[:50]}...")
            result["_from_cache"] = True
            return result

        return None

    def set(
        self,
        question: str,
        result: Dict[str, Any],
        context: Dict[str, Any] = None,
        query_type: str = None
    ) -> bool:
        """
        Cache a query result.

        Args:
            question: User's natural language question
            result: Query result to cache
            context: Optional context information
            query_type: Type of query (for TTL override)

        Returns:
            True if successfully cached
        """
        key = self._generate_key(question, context)
        ttl = self.ttl_overrides.get(query_type, CACHE_TTL)

        # Add cache metadata
        cached_result = {
            **result,
            "_cached_at": datetime.now().isoformat(),
            "_cache_ttl": ttl
        }

        success = self.backend.set(key, cached_result, ttl)

        if success:
            logger.info(f"✅ Cached query result (TTL: {ttl}s): {question[:50]}...")

        return success

    def delete(self, question: str, context: Dict[str, Any] = None) -> bool:
        """Delete a specific cached query"""
        key = self._generate_key(question, context)
        return self.backend.delete(key)

    def invalidate_by_table(self, table_name: str) -> int:
        """
        Invalidate all cached queries that use a specific table.

        This is called when data in a table changes to maintain cache consistency.

        Note: This is a simple implementation that clears the entire cache.
        For production, implement query dependency tracking.
        """
        # For now, clear everything
        # TODO: Implement smart invalidation based on query dependencies
        self.backend.clear()
        logger.info(f"🧹 Invalidated cache for table: {table_name}")
        return 1

    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        return self.backend.get_stats()

    def clear_all(self) -> bool:
        """Clear entire cache"""
        return self.backend.clear()


# Global cache instance
query_cache = QueryCache()
