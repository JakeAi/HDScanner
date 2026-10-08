"""The dashboard must not mistake a failed or absent scan for success."""
from datetime import datetime, timedelta, timezone

import pytest

from hd.config import Settings
from hd.dashboard.monitor import observation_history, recent_runs, scanner_status
from hd.db.base import get_session, init_db
from hd.db.models import Product, ScanRun, Store, StoreSnapshot
from hd.http.cooldown import ThrottleCooldown
from hd.pipeline.health import HealthStatus, ScanHealth, save_scan_health


@pytest.fixture
def config(tmp_path):
    return Settings(_env_file=None, stores="1234", brands="Test", brand_tokens="Test:token",
                    database_url=f"sqlite+aiosqlite:///{tmp_path / 'test.db'}",
                    health_state_path=str(tmp_path / "health"),
                    throttle_cooldown_path=str(tmp_path / "cooldown"))


def test_empty_install_is_not_healthy(config):
    assert scanner_status(config, {})["title"] == "Awaiting first prices"


def test_cooldown_overrides_recent_prices(config):
    ThrottleCooldown(config.throttle_cooldown_path).start()
    status = scanner_status(config, {"latest_snapshot_ts": datetime.now(timezone.utc)})
    assert status["title"] == "Requests paused"
    assert status["until"] is not None
    assert "exact cause" in status["detail"]


def test_expired_cooldown_does_not_erase_failure(config):
    from pathlib import Path
    Path(config.throttle_cooldown_path).write_text((datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat())
    status = scanner_status(config, {"latest_snapshot_ts": datetime.now(timezone.utc)}, {"status": "aborted"})
    assert status["title"] == "Last scan stopped early"
    assert status["until"] is None


def test_unfinished_run_does_not_claim_process_is_alive(config):
    assert scanner_status(config, {}, {"status": "running"})["title"] == "Scan not finalized"


def test_persisted_degradation_overrides_recent_prices(config):
    save_scan_health(config.health_state_path, ScanHealth(status=HealthStatus.DEGRADED))
    assert scanner_status(config, {"latest_snapshot_ts": datetime.now(timezone.utc)})["tone"] == "warning"


def test_old_and_naive_timestamps(config):
    assert scanner_status(config, {"latest_snapshot_ts": datetime.now(timezone.utc) - timedelta(days=1)})["title"] == "Prices need refreshing"
    assert scanner_status(config, {"latest_snapshot_ts": datetime.now(timezone.utc).replace(tzinfo=None)})["title"] == "Prices recently recorded"


def test_missing_brand_configuration(config):
    assert scanner_status(config.model_copy(update={"brand_tokens": ""}), {})["title"] == "Setup needed"


@pytest.mark.asyncio
async def test_daily_counts_and_failed_run_are_real_database_values(config):
    await init_db(config)
    now = datetime.now(timezone.utc)
    async with get_session(config) as session:
        session.add(Store(store_id="1234"))
        session.add(Product(item_id="item", brand="Test", title="Fixture product"))
        await session.flush()
        for when in (now, now, now - timedelta(days=15)):
            session.add(StoreSnapshot(store_id="1234", item_id="item", ts=when, price_value=10))
        session.add(ScanRun(started=now, ended=now, status="aborted", tiers="shelf", snapshots=0, requests_used=1))
    history = await observation_history(config)
    assert len(history) == 14
    assert history[-1]["count"] == 2
    assert sum(r["count"] for r in history) == 2
    runs = await recent_runs(config)
    assert len(runs) == 1
    assert runs[0]["status"] == "aborted"
    assert runs[0]["requests"] == 1
    assert runs[0]["snapshots"] == 0
