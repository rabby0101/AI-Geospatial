"""
Schema Watcher - Background polling for database schema changes.

Polls the vector schema every 30 seconds. When tables are added or removed:
- Added tables: generates rich metadata via AutoTableDiscovery
- Removed tables: evicts from SchemaDiscovery cache
- Always: refreshes schema cache and invalidates the LLM query cache
"""

import asyncio
from typing import Optional, Set


class SchemaWatcher:
    """Background task that polls for vector schema changes every 30 seconds."""

    POLL_INTERVAL_SECONDS = 30

    def __init__(self):
        self._known_tables: Set[str] = set()
        self._running: bool = False
        self._task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        """
        Start the background polling loop.
        Captures the current table set as baseline before starting.
        """
        from app.utils.schema_discovery import schema_discovery

        self._known_tables = schema_discovery.get_current_table_set()
        self._running = True
        self._task = asyncio.create_task(self._watch_loop())
        print(f"✅ SchemaWatcher started. Monitoring {len(self._known_tables)} tables "
              f"(polling every {self.POLL_INTERVAL_SECONDS}s)")

    async def stop(self) -> None:
        """Stop the background polling loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        print("✅ SchemaWatcher stopped")

    async def _watch_loop(self) -> None:
        """Main polling loop. Errors are caught and logged; loop always continues."""
        while self._running:
            try:
                await self._poll_once()
            except Exception as e:
                print(f"⚠️ SchemaWatcher error: {e}")
            await asyncio.sleep(self.POLL_INTERVAL_SECONDS)

    async def _poll_once(self) -> None:
        """
        Check for schema changes and react:
        - New tables → generate metadata, write to JSON + DB
        - Removed tables → evict from cache
        - Any change → refresh schema cache, invalidate query cache
        """
        from app.utils.schema_discovery import schema_discovery
        from app.utils.auto_discovery import AutoTableDiscovery
        from app.utils.lmstudio_client import invalidate_query_cache

        loop = asyncio.get_event_loop()

        # Run the blocking DB call in a thread pool
        current = await loop.run_in_executor(None, schema_discovery.get_current_table_set)

        added = current - self._known_tables
        removed = self._known_tables - current

        if not added and not removed:
            return  # No changes

        print(f"\n🔄 SchemaWatcher: schema change detected!")
        if added:
            print(f"  ➕ New tables: {', '.join(sorted(added))}")
        if removed:
            print(f"  ➖ Removed tables: {', '.join(sorted(removed))}")

        # Handle new tables (generate metadata in thread pool)
        for table in sorted(added):
            try:
                await loop.run_in_executor(None, AutoTableDiscovery.discover_single_table, table)
            except Exception as e:
                print(f"  ⚠️ Failed to discover {table}: {e}")

        # Handle removed tables
        for table in sorted(removed):
            try:
                schema_discovery.remove_table(table)
            except Exception as e:
                print(f"  ⚠️ Failed to remove {table} from cache: {e}")
            try:
                from app.utils.semantic_layer import get_semantic_layer
                get_semantic_layer().remove_table_triples(table)
            except Exception as e:
                print(f"  ⚠️ Failed to remove {table} from knowledge graph: {e}")

        # Refresh schema cache and invalidate LLM query cache
        await loop.run_in_executor(None, schema_discovery.refresh_cache)
        invalidate_query_cache()

        self._known_tables = current
        print(f"✅ SchemaWatcher: cache updated. Total tables: {len(current)}")
