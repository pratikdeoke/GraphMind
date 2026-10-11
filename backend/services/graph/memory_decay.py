"""
Background hard-decay service for persisted memory confidence.

This service periodically applies time-based decay directly in Neo4j so
confidence values reflect forgetting even outside retrieval-time scoring.
"""

import asyncio
import math
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from neo4j import GraphDatabase

from config.settings import Settings


class MemoryDecayService:
    """Periodic hard-decay worker for graph node confidence."""

    def __init__(self):
        self.enabled = Settings.MEMORY_HARD_DECAY_ENABLED
        self.interval_seconds = max(60, Settings.MEMORY_HARD_DECAY_INTERVAL_SECONDS)
        self.batch_size = max(10, Settings.MEMORY_HARD_DECAY_BATCH_SIZE)
        self.half_life_days = max(1.0, Settings.MEMORY_DECAY_HALF_LIFE_DAYS)
        self.floor = min(1.0, max(0.0, Settings.MEMORY_DECAY_FLOOR))

        self.driver = None
        self._task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()

    def _to_datetime(self, value: Any) -> Optional[datetime]:
        """Normalize Neo4j/Python date-time values into timezone-aware datetime."""
        if value is None:
            return None

        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=timezone.utc)

        if hasattr(value, "to_native"):
            try:
                native = value.to_native()
                if isinstance(native, datetime):
                    return native if native.tzinfo else native.replace(tzinfo=timezone.utc)
            except Exception:
                pass

        if isinstance(value, str):
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
            except Exception:
                return None

        return None

    async def start(self):
        """Start background decay loop if enabled."""
        if not self.enabled:
            print("[MemoryDecay] Hard decay disabled")
            return

        try:
            self.driver = GraphDatabase.driver(
                Settings.NEO4J_URI,
                auth=(Settings.NEO4J_USER, Settings.NEO4J_PASSWORD)
            )
            self.driver.verify_connectivity()
        except Exception as e:
            print(f"[MemoryDecay] Could not start worker (Neo4j unavailable): {e}")
            self.driver = None
            return

        self._stop_event.clear()
        self._task = asyncio.create_task(self._run_loop())
        print(
            "[MemoryDecay] Worker started "
            f"(interval={self.interval_seconds}s, batch={self.batch_size}, "
            f"half_life={self.half_life_days}d, floor={self.floor})"
        )

    async def stop(self):
        """Stop background decay loop and close resources."""
        self._stop_event.set()

        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            except Exception as e:
                print(f"[MemoryDecay] Error while stopping worker: {e}")

        if self.driver:
            self.driver.close()
            self.driver = None

        print("[MemoryDecay] Worker stopped")

    async def _run_loop(self):
        """Run periodic hard-decay updates."""
        while not self._stop_event.is_set():
            try:
                updated, scanned = await asyncio.to_thread(self.apply_decay_once)
                if scanned > 0:
                    print(f"[MemoryDecay] Scanned {scanned} nodes, updated {updated}")
            except Exception as e:
                print(f"[MemoryDecay] Decay cycle failed: {e}")

            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self.interval_seconds)
            except asyncio.TimeoutError:
                pass

    def apply_decay_once(self) -> tuple[int, int]:
        """Apply one hard-decay batch and persist updated confidence values."""
        if not self.driver:
            return 0, 0

        now = datetime.now(timezone.utc)

        fetch_query = """
        MATCH (n)
                WHERE n.confidence IS NOT NULL
                    AND n.user_id IS NOT NULL
        WITH n
        ORDER BY coalesce(n.last_decay_at, n.last_reinforced, n.created_at) ASC
        LIMIT $batch_size
        RETURN n.id AS id,
               n.user_id AS user_id,
               n.confidence AS confidence,
               n.last_reinforced AS last_reinforced,
               n.last_decay_at AS last_decay_at,
               n.created_at AS created_at
        """

        updates: List[Dict[str, Any]] = []

        with self.driver.session() as session:
            records = list(session.run(fetch_query, batch_size=self.batch_size))

            for record in records:
                node_id = record.get("id")
                user_id = record.get("user_id")

                if not node_id or not user_id:
                    continue

                try:
                    confidence = float(record.get("confidence", 0.0))
                except Exception:
                    continue

                confidence = min(1.0, max(0.0, confidence))

                base_dt = (
                    self._to_datetime(record.get("last_decay_at"))
                    or self._to_datetime(record.get("last_reinforced"))
                    or self._to_datetime(record.get("created_at"))
                )

                if not base_dt:
                    continue

                days_ago = max(0.0, (now - base_dt).total_seconds() / 86400.0)
                if days_ago <= 0:
                    continue

                decay_multiplier = max(
                    self.floor,
                    math.pow(0.5, days_ago / self.half_life_days)
                )
                new_confidence = max(self.floor, min(1.0, confidence * decay_multiplier))

                if abs(new_confidence - confidence) < 1e-6:
                    continue

                updates.append(
                    {
                        "id": node_id,
                        "user_id": user_id,
                        "confidence": round(new_confidence, 6)
                    }
                )

            if not updates:
                return 0, len(records)

            update_query = """
            UNWIND $updates AS row
            MATCH (n {id: row.id, user_id: row.user_id})
            SET n.confidence = row.confidence,
                n.last_decay_at = datetime($now_iso)
            RETURN count(n) AS updated_count
            """

            result = session.run(
                update_query,
                updates=updates,
                now_iso=now.isoformat()
            )
            rec = result.single()
            updated_count = rec["updated_count"] if rec else 0
            return int(updated_count), len(records)
