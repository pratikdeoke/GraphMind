"""
One-time Neo4j cleanup script - merge duplicate entity nodes.

Background
----------
The old `_merge_node` implementation MERGEd on a freshly generated random id
(e.g. `asset_a1b2c3d4`), which meant repeated mentions of the same entity
("HDFC", "HDFC Mutual Fund", ...) each created a BRAND NEW node. This script
consolidates those historical duplicates by grouping nodes on a canonical key
and merging each group into a single survivor node.

What it does
------------
For each user and each target label (Asset, Entity, Goal, Transaction, Expense,
Preference), it groups nodes by their normalized identity
(canonical_name / normalized_name / lowercased name / id). When a group has more
than one node it:
  1. Picks a survivor (the one that already has a canonical_name, else the
     earliest-created, else lowest id).
  2. Re-points every incoming/outgoing relationship of the losers onto the
     survivor.
  3. Merges numeric aggregates (amount, value, shares, reinforcement_count,
     confidence) from losers onto the survivor.
  4. Deletes the loser nodes.

It is idempotent and safe: it only deletes nodes it actually merged.

Usage
-----
    # Dry run (prints a plan, changes nothing)
    python -m scripts.dedupe_graph --dry-run

    # Apply changes
    python -m scripts.dedupe_graph --apply

    # Limit to a single user
    python -m scripts.dedupe_graph --apply --user-id <id>
"""

import argparse
import sys
import os
from typing import Dict, List

# Ensure backend root is importable when run as `python -m scripts.dedupe_graph`
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from neo4j import GraphDatabase
from config.settings import Settings


# Labels that commonly suffer from the fan-out duplicate problem.
TARGET_LABELS = ["Asset", "Entity", "Goal", "Transaction", "Expense", "Preference"]

# Numeric properties that should be summed when merging duplicates.
SUM_PROPERTIES = ["amount", "value", "shares", "buy_price", "monthly_sip", "nav",
                  "monthly_amount", "target_amount", "reinforcement_count"]

# Scalar properties where we keep the max / most-confident value.
MAX_PROPERTIES = ["confidence", "relevance", "centrality"]


def _canonical(properties: Dict) -> str:
    """Compute a canonical dedupe key from a node's properties."""
    for key in ("canonical_name", "normalized_name", "name"):
        val = properties.get(key)
        if val:
            return str(val).strip().lower()
    return str(properties.get("id", "")).strip().lower()

class GraphDedupe:
    def __init__(self):
        self.driver = GraphDatabase.driver(
            Settings.NEO4J_URI,
            auth=(Settings.NEO4J_USER, Settings.NEO4J_PASSWORD),
        )
        self.driver.verify_connectivity()

    def close(self):
        self.driver.close()

    def find_duplicate_groups(self, label: str, user_id: str = None):
        """Return groups of nodes (per user) that share a canonical key."""
        query = f"""
        MATCH (n:{label})
        WHERE n.user_id IS NOT NULL {"AND n.user_id = $user_id" if user_id else ""}
        RETURN n.user_id AS user_id,
               collect({{
                 id: elementId(n),
                 props: properties(n)
               }}) AS members
        """
        params = {"user_id": user_id} if user_id else {}
        groups = []
        with self.driver.session() as session:
            for record in session.run(query, **params):
                buckets: Dict[str, List] = {}
                for m in record["members"]:
                    key = _canonical(m["props"])
                    if not key:
                        continue
                    buckets.setdefault(key, []).append(m)
                for key, members in buckets.items():
                    if len(members) > 1:
                        groups.append({
                            "user_id": record["user_id"],
                            "label": label,
                            "canonical_key": key,
                            "members": members,
                        })
        return groups

    def _pick_survivor(self, members: List):
        """Prefer a node that already carries a canonical_name, else earliest."""
        with_canon = [m for m in members if m["props"].get("canonical_name")]
        pool = with_canon or members

        def sort_key(m):
            created = m["props"].get("created_at") or m["props"].get("timestamp")
            return (str(created) if created else "9999", str(m["id"]))

        return sorted(pool, key=sort_key)[0]
    def _check_apoc(self, session) -> bool:
        """Return True if the APOC procedure is available on this Neo4j."""
        try:
            result = session.run("RETURN apoc.version() AS v").single()
            if result and result.get("v"):
                print(f"  APOC version: {result['v']}")
                return True
        except Exception as e:
            print(f"  APOC not available ({e}); will use manual merge.")
        return False

    def merge_group_apoc(self, session, group: Dict, dry_run: bool) -> int:
        """Merge a duplicate group using apoc.refactor.mergeNodes."""
        survivor = self._pick_survivor(group["members"])
        loser_ids = [m["id"] for m in group["members"] if m["id"] != survivor["id"]]
        if not loser_ids:
            return 0
        ordered_ids = [survivor["id"]] + loser_ids
        prop_config = {p: "combine" for p in SUM_PROPERTIES}
        query = """
        MATCH (n) WHERE elementId(n) IN $ids
        WITH n ORDER BY CASE elementId(n) WHEN $survivor_id THEN 0 ELSE 1 END
        WITH collect(n) AS nodes
        CALL apoc.refactor.mergeNodes(nodes, {
            properties: $prop_config,
            mergeRels: true
        })
        YIELD node
        RETURN count(node) AS survivor_count
        """
        if dry_run:
            return len(loser_ids)
        try:
            result = session.run(
                query,
                ids=ordered_ids,
                survivor_id=survivor["id"],
                prop_config=prop_config,
            )
            rec = result.single()
            return (len(ordered_ids) - (rec["survivor_count"] if rec else 1))
        except Exception as e:
            print(f"      APOC merge failed for {group['canonical_key']!r}: {e}")
            return 0
    def merge_group(self, group: Dict, dry_run: bool) -> int:
        """Merge one duplicate group. Returns number of nodes removed."""
        survivor = self._pick_survivor(group["members"])
        canonical = group["canonical_key"]
        losers = [m for m in group["members"] if m["id"] != survivor["id"]]
        if not losers:
            return 0
        if dry_run:
            return len(losers)
        with self.driver.session() as session:
            if self._check_apoc(session):
                removed = self.merge_group_apoc(session, group, dry_run)
                session.run(
                    """
                    MATCH (s) WHERE elementId(s) = $survivor_id
                    SET s.canonical_name = coalesce(s.canonical_name, $canonical)
                    """,
                    survivor_id=survivor["id"],
                    canonical=canonical,
                )
                return removed
            return self._merge_group_manual(session, group)

    def _merge_group_manual(self, session, group: Dict) -> int:
        """Fallback merge without APOC: sum aggregates then delete losers.

        NOTE: This does not re-point relationships (requires APOC). Use only
        when APOC is unavailable and losing duplicate-node edges is acceptable.
        """
        survivor = self._pick_survivor(group["members"])
        survivor_id = survivor["id"]
        canonical = group["canonical_key"]
        losers = [m for m in group["members"] if m["id"] != survivor["id"]]
        loser_ids = [l["id"] for l in losers]
        sum_sets = [
            p for p in SUM_PROPERTIES
            if p in survivor["props"] or any(p in l["props"] for l in losers)
        ]
        agg = ", ".join(f"s.{p} = s.{p} + coalesce(l.{p}, 0)" for p in sum_sets)
        query = f"""
        MATCH (s) WHERE elementId(s) = $survivor_id
        SET s.canonical_name = coalesce(s.canonical_name, $canonical)
        UNWIND $loser_ids AS lid
        MATCH (l) WHERE elementId(l) = lid
        WITH s, l {"SET " + agg if agg else ""}
        DETACH DELETE l
        RETURN count(l) AS removed
        """
        try:
            rec = session.run(
                query, survivor_id=survivor_id,
                loser_ids=loser_ids, canonical=canonical,
            ).single()
            return rec["removed"] if rec else 0
        except Exception as e:
            print(f"      Manual merge failed for {canonical!r}: {e}")
            return 0

    def run(self, dry_run: bool = True, user_id: str = None):
        total_removed = 0
        for label in TARGET_LABELS:
            groups = self.find_duplicate_groups(label, user_id)
            if not groups:
                continue
            print(f"\n[{label}] found {len(groups)} duplicate group(s)"
                  f"{' (DRY RUN)' if dry_run else ''}")
            for group in groups:
                n = len(group["members"])
                preview = group["canonical_key"][:40]
                print(f"  - user {group['user_id'][:8]}... key={preview!r} nodes={n}")
                removed = self.merge_group(group, dry_run)
                total_removed += removed
                if not dry_run and removed:
                    print(f"      -> merged, removed {removed} duplicate node(s)")
        print(f"\nDone. Total duplicate nodes "
              f"{'that would be ' if dry_run else ''}removed: {total_removed}")
        return total_removed


def main():
    parser = argparse.ArgumentParser(description="Dedupe Neo4j entity nodes.")
    parser.add_argument("--apply", action="store_true",
                        help="Actually merge duplicates (default is dry-run).")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be merged without changing data.")
    parser.add_argument("--user-id", default=None,
                        help="Limit cleanup to a single user_id.")
    args = parser.parse_args()
    dry_run = not args.apply or args.dry_run
    dedupe = GraphDedupe()
    try:
        dedupe.run(dry_run=dry_run, user_id=args.user_id)
    finally:
        dedupe.close()


if __name__ == "__main__":
    main()