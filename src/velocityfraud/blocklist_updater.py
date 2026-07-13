"""Layer 8 — Blocklist updater (Postgres -> Redis).

Reads recent scored_events from Postgres, computes repeat-offender patterns,
and pushes matching entities into Redis blocklist / hot-list.

Runs periodically (cron in production, on-demand for POC). Idempotent —
safe to run any time; Redis TTL handles freshness.

Detection criteria (STRICT — designed to minimize false positives):

    CARDS
      block_count >= 3 in last 24h    -> BLOCK-LIST (24h TTL)
      block_count == 2 in last 24h    -> HOT-LIST   (24h TTL)

    MERCHANTS
      block_rate >= 90% over 100+ txns in 7d  -> BLOCK-LIST (7d TTL)
      block_rate >= 50% over  30+ txns in 7d  -> HOT-LIST   (7d TTL)

    IPs
      block_count >= 5 in last 1h     -> BLOCK-LIST (1h TTL)

    DEVICES
      block_count >= 3 in last 24h    -> BLOCK-LIST (24h TTL)

All add_* calls go through blocklist.py's guardrails (whitelist check,
block_count floor, TTL enforcement) as defence-in-depth.

Usage (from velocityfraud/ root):
    uv run python -m velocityfraud.blocklist_updater
    uv run python -m velocityfraud.blocklist_updater --dry-run     # preview only

Env vars:
    (inherits POSTGRES_* from db.py and REDIS_* from blocklist.py)
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field

from loguru import logger

from velocityfraud import blocklist
from velocityfraud.db import get_connection


# ---------------------------------------------------------------------------
# SQL — repeat-offender detection queries
# ---------------------------------------------------------------------------
SQL_CARD_REPEATS = """
SELECT card_token,
       COUNT(*) AS block_count
FROM scored_events
WHERE decision = 'BLOCK'
  AND card_token IS NOT NULL
  AND card_token <> ''
  AND scored_at_ms > (EXTRACT(EPOCH FROM NOW()) - %s) * 1000
GROUP BY card_token
HAVING COUNT(*) >= 2
ORDER BY COUNT(*) DESC
"""

SQL_MERCHANT_FRAUD_RATE = """
SELECT merchant_id_hash,
       COUNT(*) AS total,
       COUNT(*) FILTER (WHERE decision = 'BLOCK') AS blocks,
       (COUNT(*) FILTER (WHERE decision = 'BLOCK')::float / COUNT(*)) AS block_rate
FROM scored_events
WHERE merchant_id_hash IS NOT NULL
  AND merchant_id_hash <> ''
  AND scored_at_ms > (EXTRACT(EPOCH FROM NOW()) - %s) * 1000
GROUP BY merchant_id_hash
HAVING COUNT(*) >= 30
   AND (COUNT(*) FILTER (WHERE decision = 'BLOCK')::float / COUNT(*)) >= 0.5
ORDER BY block_rate DESC, blocks DESC
"""

SQL_IP_BURSTS = """
SELECT ip_address_hash,
       COUNT(*) AS block_count
FROM scored_events
WHERE decision = 'BLOCK'
  AND ip_address_hash IS NOT NULL
  AND ip_address_hash <> ''
  AND scored_at_ms > (EXTRACT(EPOCH FROM NOW()) - %s) * 1000
GROUP BY ip_address_hash
HAVING COUNT(*) >= 5
ORDER BY COUNT(*) DESC
"""

SQL_DEVICE_REPEATS = """
SELECT device_fingerprint_hash,
       COUNT(*) AS block_count
FROM scored_events
WHERE decision = 'BLOCK'
  AND device_fingerprint_hash IS NOT NULL
  AND device_fingerprint_hash <> ''
  AND scored_at_ms > (EXTRACT(EPOCH FROM NOW()) - %s) * 1000
GROUP BY device_fingerprint_hash
HAVING COUNT(*) >= 3
ORDER BY COUNT(*) DESC
"""


# ---------------------------------------------------------------------------
# Runtime configuration (thresholds — tunable but sensible defaults)
# ---------------------------------------------------------------------------
CARD_WINDOW_S = 86400              # 24h
CARD_BLOCK_THRESHOLD = 3           # BLOCK-list at 3+ blocks
CARD_HOT_THRESHOLD = 2             # HOT-list at exactly 2 blocks

MERCHANT_WINDOW_S = 7 * 86400      # 7d
MERCHANT_BLOCK_MIN_TXNS = 100
MERCHANT_BLOCK_MIN_RATE = 0.90
MERCHANT_HOT_MIN_TXNS = 30
MERCHANT_HOT_MIN_RATE = 0.50

IP_WINDOW_S = 3600                 # 1h
IP_BLOCK_THRESHOLD = 5

DEVICE_WINDOW_S = 86400
DEVICE_BLOCK_THRESHOLD = 3


@dataclass
class UpdaterStats:
    cards_scanned:     int = 0
    cards_blocked:     int = 0
    cards_hotlisted:   int = 0
    merchants_scanned: int = 0
    merchants_blocked: int = 0
    merchants_hotlisted: int = 0
    ips_scanned:       int = 0
    ips_blocked:       int = 0
    devices_scanned:   int = 0
    devices_blocked:   int = 0
    refused:           int = 0
    errors:            list = field(default_factory=list)


# ---------------------------------------------------------------------------
# Per-entity processors
# ---------------------------------------------------------------------------
def _process_cards(cur, stats: UpdaterStats, dry_run: bool) -> None:
    cur.execute(SQL_CARD_REPEATS, (CARD_WINDOW_S,))
    rows = cur.fetchall()
    stats.cards_scanned = len(rows)
    for token, count in rows:
        if count >= CARD_BLOCK_THRESHOLD:
            reason = f"{count} BLOCK decisions in last 24h"
            if dry_run:
                logger.info("[DRY-RUN] would BLOCK card={} count={}", token[:12], count)
                stats.cards_blocked += 1
            else:
                ok = blocklist.add_blocklist(
                    "card", token, reason, block_count=count,
                    ttl_s=blocklist.TTL_CARD_S,
                )
                if ok:
                    stats.cards_blocked += 1
                else:
                    stats.refused += 1
        elif count == CARD_HOT_THRESHOLD:
            reason = f"{count} BLOCK decisions in last 24h (hot-list)"
            if dry_run:
                logger.info("[DRY-RUN] would HOT card={} count={}", token[:12], count)
                stats.cards_hotlisted += 1
            else:
                ok = blocklist.add_hotlist(
                    "card", token, reason, block_count=count,
                    ttl_s=blocklist.TTL_CARD_S,
                )
                if ok:
                    stats.cards_hotlisted += 1
                else:
                    stats.refused += 1


def _process_merchants(cur, stats: UpdaterStats, dry_run: bool) -> None:
    cur.execute(SQL_MERCHANT_FRAUD_RATE, (MERCHANT_WINDOW_S,))
    rows = cur.fetchall()
    stats.merchants_scanned = len(rows)
    for merchant, total, blocks, block_rate in rows:
        if total >= MERCHANT_BLOCK_MIN_TXNS and block_rate >= MERCHANT_BLOCK_MIN_RATE:
            reason = f"merchant fraud rate {block_rate:.0%} over {total} txns (7d)"
            if dry_run:
                logger.info("[DRY-RUN] would BLOCK merchant={} rate={:.1%} n={}",
                            merchant[:12], block_rate, total)
                stats.merchants_blocked += 1
            else:
                ok = blocklist.add_blocklist(
                    "merchant", merchant, reason, block_count=blocks,
                    ttl_s=blocklist.TTL_MERCHANT_S,
                )
                if ok:
                    stats.merchants_blocked += 1
                else:
                    stats.refused += 1
        elif total >= MERCHANT_HOT_MIN_TXNS and block_rate >= MERCHANT_HOT_MIN_RATE:
            reason = f"merchant fraud rate {block_rate:.0%} over {total} txns (7d, hot-list)"
            if dry_run:
                logger.info("[DRY-RUN] would HOT merchant={} rate={:.1%} n={}",
                            merchant[:12], block_rate, total)
                stats.merchants_hotlisted += 1
            else:
                ok = blocklist.add_hotlist(
                    "merchant", merchant, reason, block_count=blocks,
                    ttl_s=blocklist.TTL_MERCHANT_S,
                )
                if ok:
                    stats.merchants_hotlisted += 1
                else:
                    stats.refused += 1


def _process_ips(cur, stats: UpdaterStats, dry_run: bool) -> None:
    cur.execute(SQL_IP_BURSTS, (IP_WINDOW_S,))
    rows = cur.fetchall()
    stats.ips_scanned = len(rows)
    for ip_hash, count in rows:
        if count >= IP_BLOCK_THRESHOLD:
            reason = f"{count} BLOCK decisions in last 1h (IP burst)"
            if dry_run:
                logger.info("[DRY-RUN] would BLOCK ip={} count={}", ip_hash[:12], count)
                stats.ips_blocked += 1
            else:
                ok = blocklist.add_blocklist(
                    "ip", ip_hash, reason, block_count=count,
                    ttl_s=blocklist.TTL_IP_S,
                )
                if ok:
                    stats.ips_blocked += 1
                else:
                    stats.refused += 1


def _process_devices(cur, stats: UpdaterStats, dry_run: bool) -> None:
    cur.execute(SQL_DEVICE_REPEATS, (DEVICE_WINDOW_S,))
    rows = cur.fetchall()
    stats.devices_scanned = len(rows)
    for device_hash, count in rows:
        if count >= DEVICE_BLOCK_THRESHOLD:
            reason = f"{count} BLOCK decisions in last 24h (device)"
            if dry_run:
                logger.info("[DRY-RUN] would BLOCK device={} count={}",
                            device_hash[:12], count)
                stats.devices_blocked += 1
            else:
                ok = blocklist.add_blocklist(
                    "device", device_hash, reason, block_count=count,
                    ttl_s=blocklist.TTL_DEVICE_S,
                )
                if ok:
                    stats.devices_blocked += 1
                else:
                    stats.refused += 1


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def run_update(dry_run: bool = False) -> UpdaterStats:
    stats = UpdaterStats()

    if not blocklist.is_redis_alive():
        logger.error("Redis unreachable — aborting update.")
        stats.errors.append("redis-unreachable")
        return stats

    with get_connection() as conn:
        with conn.cursor() as cur:
            logger.info("Scanning cards for repeat offenders (window={}s)...",
                        CARD_WINDOW_S)
            _process_cards(cur, stats, dry_run)

            logger.info("Scanning merchants for high fraud rate (window={}s)...",
                        MERCHANT_WINDOW_S)
            _process_merchants(cur, stats, dry_run)

            logger.info("Scanning IPs for BLOCK bursts (window={}s)...", IP_WINDOW_S)
            _process_ips(cur, stats, dry_run)

            logger.info("Scanning devices for repeats (window={}s)...", DEVICE_WINDOW_S)
            _process_devices(cur, stats, dry_run)

    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description="Blocklist updater (Postgres -> Redis)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print what would be added without touching Redis.")
    args = parser.parse_args()

    logger.info("=" * 74)
    logger.info("BLOCKLIST UPDATER — dry_run={}", args.dry_run)
    logger.info("=" * 74)

    stats = run_update(dry_run=args.dry_run)

    logger.info("-" * 74)
    logger.info("UPDATE SUMMARY")
    logger.info("-" * 74)
    logger.info("  Cards scanned          : {}", stats.cards_scanned)
    logger.info("  Cards blocklisted      : {}", stats.cards_blocked)
    logger.info("  Cards hot-listed       : {}", stats.cards_hotlisted)
    logger.info("  Merchants scanned      : {}", stats.merchants_scanned)
    logger.info("  Merchants blocklisted  : {}", stats.merchants_blocked)
    logger.info("  Merchants hot-listed   : {}", stats.merchants_hotlisted)
    logger.info("  IPs scanned            : {}", stats.ips_scanned)
    logger.info("  IPs blocklisted        : {}", stats.ips_blocked)
    logger.info("  Devices scanned        : {}", stats.devices_scanned)
    logger.info("  Devices blocklisted    : {}", stats.devices_blocked)
    logger.info("  Refused by guardrails  : {}", stats.refused)
    if stats.errors:
        logger.error("  Errors                 : {}", stats.errors)

    # Show final Redis inventory
    logger.info("-" * 74)
    logger.info("REDIS INVENTORY AFTER UPDATE")
    for k, v in blocklist.stats()["counts"].items():
        logger.info("  {:25s} {}", k, v)

    logger.info("=" * 74)
    return 0 if not stats.errors else 1


if __name__ == "__main__":
    sys.exit(main())
