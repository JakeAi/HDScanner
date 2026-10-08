"""Read-only monitoring data; rendering never sends retailer requests."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select

from hd.config import Settings
from hd.db.base import get_session
from hd.db.models import ScanRun, StoreSnapshot
from hd.http.cooldown import ThrottleCooldown
from hd.pipeline.health import load_scan_health


def scanner_status(settings: Settings, stats: dict[str, Any], last_run: dict[str, Any] | None = None) -> dict[str, Any]:
    """Separate cooldown, missing evidence, and stale evidence from success."""
    until = ThrottleCooldown(settings.throttle_cooldown_path).active_until()
    health = load_scan_health(settings.health_state_path)
    latest = stats.get("latest_snapshot_ts")
    if until:
        title, tone, detail = (
            "Requests paused", "warning",
            "Home Depot returned HTTP 206. The scanner is honoring its cooldown. "
            "This response does not identify the exact cause of the rejection.",
        )
    elif not settings.store_list or not settings.brand_list or not settings.brand_tokens:
        title, tone, detail = "Setup needed", "warning", "Configure your stores and brand catalog tokens before scanning."
    elif last_run and last_run["status"] == "aborted":
        title, tone, detail = "Last scan stopped early", "warning", "The most recent browse run was aborted. A finished cooldown does not mean API access has recovered."
    elif last_run and last_run["status"] == "running":
        title, tone, detail = "Scan not finalized", "neutral", "A browse run is marked as running. It may still be active or may have been interrupted; check the container logs."
    elif health.status.value == "DEGRADED":
        title, tone, detail = "Scan needs attention", "warning", "The last recorded scan health is degraded. Previously collected prices remain available."
    elif latest is None:
        title, tone, detail = "Awaiting first prices", "neutral", "No price snapshots have been recorded. An empty deal board does not mean there are no deals."
    else:
        if latest.tzinfo is None:
            latest = latest.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) - latest > timedelta(hours=12):
            title, tone, detail = "Prices need refreshing", "warning", "No prices have been recorded in the last 12 hours. Check your scheduled scan and its logs."
        else:
            title, tone, detail = "Prices recently recorded", "good", "The database contains prices from the last 12 hours. This does not guarantee a complete scan or current API access."
    return {"title": title, "tone": tone, "detail": detail, "until": until, "last_ok": health.last_ok}


async def recent_runs(settings: Settings) -> list[dict[str, Any]]:
    """Return persisted browse outcomes, including aborted and unfinished runs."""
    async with get_session(settings) as session:
        runs = (await session.execute(select(ScanRun).order_by(ScanRun.started.desc(), ScanRun.id.desc()).limit(5))).scalars().all()
        return [{"id": r.id, "started": r.started, "status": r.status,
                 "snapshots": r.snapshots, "requests": r.requests_used,
                 "tiers": r.tiers, "deferred_walks": r.deferred_walks} for r in runs]


async def observation_history(settings: Settings, days: int = 14) -> list[dict[str, Any]]:
    """Count retained observations by UTC day, without loading individual rows."""
    today = datetime.now(timezone.utc).date()
    first = today - timedelta(days=days - 1)
    cutoff = datetime.combine(first, datetime.min.time(), tzinfo=timezone.utc)
    async with get_session(settings) as session:
        rows = (await session.execute(
            select(func.date(StoreSnapshot.ts), func.count())
            .where(StoreSnapshot.ts >= cutoff)
            .group_by(func.date(StoreSnapshot.ts))
        )).all()
    counts = {str(day): count for day, count in rows}
    return [{"date": str(first + timedelta(days=i)),
             "count": counts.get(str(first + timedelta(days=i)), 0)} for i in range(days)]
