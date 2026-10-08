"""An operational home for the local HDScanner installation."""
from __future__ import annotations

from nicegui import ui

from hd.dashboard import _state
from hd.dashboard.components.header import render_header
from hd.dashboard.components.formatters import fmt_ts_relative
from hd.dashboard.monitor import observation_history, recent_runs, scanner_status
from hd.dashboard.queries import get_alerts, get_overview_stats
from hd.logging import get_logger

log = get_logger("dashboard.home")


def _metric(label: str, value: int, note: str, icon: str) -> None:
    with ui.element("section").classes("monitor-metric"):
        with ui.row().classes("items-center justify-between w-full"):
            ui.label(label).classes("monitor-muted")
            ui.icon(icon).classes("monitor-muted text-xl")
        ui.label(f"{value:,}").classes("monitor-number")
        ui.label(note).classes("monitor-caption")


@ui.page("/")
async def home_page() -> None:
    settings = _state.settings
    render_header(settings.dashboard_title, current_path="/")

    with ui.column().classes("monitor-wrap gap-6"):
        with ui.row().classes("w-full items-center justify-between gap-4"):
            with ui.column().classes("gap-1"):
                ui.label("YOUR LOCAL PRICE WATCH").classes("monitor-eyebrow")
                ui.label("Scanner overview").classes("monitor-title")
            ui.button("Refresh status", icon="refresh", on_click=lambda: content.refresh()).props("outline no-caps").classes("monitor-refresh")

        @ui.refreshable
        async def content() -> None:
            try:
                stats = await get_overview_stats(settings)
                runs = await recent_runs(settings)
                status = scanner_status(settings, stats, runs[0] if runs else None)
                history = await observation_history(settings)
                alerts = await get_alerts(settings, limit=5)
            except Exception as exc:
                log.warning("Could not load dashboard overview", error=str(exc))
                with ui.element("section").classes("monitor-panel w-full"):
                    ui.icon("error_outline").classes("text-amber text-3xl")
                    ui.label("Unable to read scanner data").classes("text-xl font-bold")
                    ui.label("Check the container logs and database connection, then refresh status.")
                return

            with ui.element("section").classes(f"monitor-health {status['tone']}").props('role="status"'):
                with ui.column().classes("gap-2"):
                    with ui.row().classes("items-center gap-3"):
                        ui.icon("pause_circle" if status["tone"] == "warning" else "sensors").classes("text-3xl")
                        ui.label(status["title"]).classes("text-xl font-bold")
                    ui.label(status["detail"]).classes("monitor-health-detail")
                with ui.column().classes("gap-1 monitor-health-time"):
                    if status["until"]:
                        ui.label("COOLDOWN ENDS").classes("monitor-eyebrow")
                        ui.label(status["until"].strftime("%H:%M UTC · %b %d")).classes("text-lg font-bold")
                        ui.label("Eligibility to retry; no scan is scheduled here.").classes("monitor-caption")
                    else:
                        ui.label("LATEST PRICE RECORD").classes("monitor-eyebrow")
                        ui.label(fmt_ts_relative(stats["latest_snapshot_ts"]) if stats["latest_snapshot_ts"] else "Not recorded yet").classes("text-lg font-bold")

            with ui.element("div").classes("monitor-metrics"):
                _metric("Products observed", stats["watched_products"], f"In the last {stats['watched_days']} days", "inventory_2")
                _metric("Clearance finds", stats["clearance_count"], "Fresh, actionable clearance records", "sell")
                _metric("Recent alerts", stats["alert_count_24h"], "Recorded in the last 24 hours", "notifications_none")
                _metric("Price records", stats["total_snapshots"], "Retained snapshots across this installation", "timeline")

            with ui.element("div").classes("monitor-columns"):
                with ui.element("section").classes("monitor-panel"):
                    with ui.row().classes("items-start justify-between w-full"):
                        with ui.column().classes("gap-1"):
                            ui.label("Collection activity").classes("monitor-section-title")
                            ui.label("Price observations per day · past 14 days · UTC").classes("monitor-caption")
                        ui.icon("bar_chart").classes("monitor-muted text-2xl")
                    if not any(h["count"] for h in history):
                        with ui.column().classes("monitor-empty items-center justify-center"):
                            ui.icon("query_stats").classes("text-5xl monitor-muted")
                            ui.label("Your price history starts here" if not stats["total_snapshots"] else "No observations in this window").classes("text-lg font-semibold")
                            ui.label("The chart fills as scans record prices. Older records remain available in product history.").classes("monitor-muted text-center")
                    else:
                        ui.echart({
                            "backgroundColor": "transparent",
                            "tooltip": {"trigger": "axis"},
                            "grid": {"left": 48, "right": 12, "top": 28, "bottom": 35},
                            "xAxis": {"type": "category", "data": [h["date"][5:] for h in history], "axisLabel": {"color": "#a7b4c8"}},
                            "yAxis": {"type": "value", "minInterval": 1, "axisLabel": {"color": "#a7b4c8"}, "splitLine": {"lineStyle": {"color": "#29364a"}}},
                            "series": [{"type": "bar", "name": "Price observations", "data": [h["count"] for h in history], "itemStyle": {"color": "#f15361", "borderRadius": [4, 4, 0, 0]}, "barMaxWidth": 24}],
                        }).classes("w-full h-64")
                    ui.link("Explore products and price history →", "/products").classes("monitor-link")

                with ui.element("section").classes("monitor-panel"):
                    ui.label("Your watch area").classes("monitor-section-title")
                    ui.label("STORES").classes("monitor-eyebrow mt-5")
                    with ui.row().classes("gap-2 flex-wrap"):
                        for store in settings.store_list:
                            ui.badge(f"Store #{store}").classes("monitor-tag").props("outline")
                        if not settings.store_list:
                            ui.label("No stores configured").classes("monitor-muted")
                    ui.label("BRANDS").classes("monitor-eyebrow mt-5")
                    with ui.row().classes("gap-2 flex-wrap"):
                        for brand in settings.brand_list:
                            ui.badge(brand).classes("monitor-tag").props("outline")
                        if not settings.brand_list:
                            ui.label("No brands configured").classes("monitor-muted")
                    ui.separator().classes("my-5")
                    ui.label("Scans run on your Unraid schedule.").classes("font-medium")
                    ui.label("Refreshing this page reads saved data. It does not contact Home Depot or start a scan.").classes("monitor-caption mt-2")
                    ui.link("View store records →", "/stores").classes("monitor-link mt-4")

            with ui.element("section").classes("monitor-panel w-full"):
                ui.label("Recent scans").classes("monitor-section-title")
                ui.label("Recorded browse runs. Finished runs may still have partial catalog coverage.").classes("monitor-caption mt-1 mb-4")
                if not runs:
                    ui.label("No browse runs recorded yet.").classes("monitor-muted py-4")
                else:
                    columns = [
                        {"name": "started", "label": "Started (UTC)", "field": "started", "align": "left"},
                        {"name": "status", "label": "Outcome", "field": "status", "align": "left"},
                        {"name": "tiers", "label": "Coverage", "field": "tiers", "align": "left"},
                        {"name": "requests", "label": "Requests", "field": "requests"},
                        {"name": "snapshots", "label": "Price records", "field": "snapshots"},
                        {"name": "deferred", "label": "Walks deferred", "field": "deferred"},
                    ]
                    rows = [{**r, "started": r["started"].strftime("%b %d, %H:%M"),
                             "status": {"complete": "Finished", "aborted": "Stopped early", "running": "Not finalized"}.get(r["status"], r["status"]),
                             "deferred": r["deferred_walks"] if r["deferred_walks"] is not None else "Not recorded"} for r in runs]
                    ui.table(columns=columns, rows=rows, row_key="id").props("flat hide-bottom wrap-cells").classes("w-full monitor-runs")

            with ui.element("section").classes("monitor-panel w-full"):
                with ui.row().classes("items-center justify-between w-full mb-4"):
                    ui.label("Latest alerts").classes("monitor-section-title")
                    ui.link("View all alerts →", "/alerts").classes("monitor-link")
                if not alerts:
                    with ui.row().classes("items-center gap-4 py-5"):
                        ui.icon("notifications_none").classes("text-3xl monitor-muted")
                        with ui.column().classes("gap-1"):
                            ui.label("No alerts recorded yet").classes("font-semibold")
                            ui.label("Price changes can be detected once the scanner has observations to compare.").classes("monitor-caption")
                for alert in alerts:
                    with ui.row().classes("monitor-alert-row"):
                        ui.badge(alert["alert_type"].replace("_", " ")).props("outline").classes("monitor-tag")
                        with ui.column().classes("gap-1 flex-1"):
                            ui.label(alert["product_title"] or alert["payload"].get("message") or "Scanner event").classes("font-medium")
                            ui.label(f"Store {alert['store_id']} · {fmt_ts_relative(alert['ts'])}").classes("monitor-caption")
                        if alert["product_title"]:
                            ui.link("Details →", f"/products/{alert['item_id']}").classes("monitor-link")
            with ui.row().classes("w-full justify-between monitor-caption flex-wrap gap-2"):
                ui.label("Saved observations, not live inventory. Confirm price and stock with the store.")
                ui.link("Open deal board →", "/deals").classes("monitor-link")

        await content()
        ui.timer(60, content.refresh)
