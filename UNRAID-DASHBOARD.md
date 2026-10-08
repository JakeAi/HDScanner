# HDScanner dashboard for Unraid

This local dashboard extends KenStager/HDScanner revision
`89494ecf6fbae15d301e960a6be1aa2e80fe33b9`. It is a custom build, not an upstream release.

The overview at `/` shows scan health, persistent cooldown timing, observed product
counts, clearance records, retained observations, a 14-day collection chart, recent
browse outcomes, recent alerts, and configured stores and brands. The original deal
board lives at `/deals`; products, price history, alerts, and stores remain available.
The overview refreshes every 60 seconds and has a manual refresh button. Refreshing
reads local records and does not start scans or contact Home Depot.

## Install over your existing Unraid setup

1. Download `hdscanner-dashboard.tar.gz` and copy it into
   `/mnt/user/appdata/hdscanner/` on your Unraid server using your normal file transfer.
2. Open the Unraid terminal and run:

```bash
cd /mnt/user/appdata/hdscanner
tar -xzf hdscanner-dashboard.tar.gz
docker build -t hdscanner:dashboard ./hdscanner-dashboard
```

3. Stop `hdscanner` in Unraid's Docker tab. If you enabled scheduled scans, pause
   them and let any active scan finish. Back up the existing data directory:

```bash
cd /mnt/user/appdata/hdscanner
tar -czf "data-before-dashboard-$(date +%Y%m%d-%H%M%S).tar.gz" data
```

4. Edit the existing `hdscanner` container. Change **Repository** from
   `hdscanner:local` to **`hdscanner:dashboard`**. Keep the container name and mappings:

| Setting | Value |
| --- | --- |
| Container name | `hdscanner` |
| Network | `bridge` |
| Container path | `/data` |
| Host path | `/mnt/user/appdata/hdscanner/data` |
| Access | Read/Write |
| Container port | `8080` TCP |
| Host port | `8085` (or your existing choice) |
| WebUI | `http://[IP]:[PORT:8080]` |

5. Click Apply, enable Autostart, and open `http://YOUR-UNRAID-IP:8085`.
   Hard-refresh the browser if the old header remains cached.

The container loads your existing `.env` from `/data`, including store 3888 and
Milwaukee if you saved them earlier. The archive contains no personal configuration or credentials. The dashboard
displays only your database records; source tests include isolated sample fixtures. Existing scheduled `docker exec
hdscanner hd run-once` commands continue to use the same name. Keep scans disabled
while investigating the current API rejection.

## Verify

```bash
docker logs --tail 100 hdscanner
```

The overview should show your saved watch area. A blocked scan can display
"Requests paused" during its cooldown and "Last scan stopped early" afterward.
Neither state implies that Home Depot access has recovered. Recent scans should
show the recorded failed run with one request and zero price records, if that
run exists in your database.

## Roll back

Edit the container's Repository back to `hdscanner:local` and Apply. Keep that
original local image until you are satisfied with the dashboard. This change
adds no new database tables or migrations; startup still runs upstream's existing
schema initialization. All retailer request logic and rate limits are unchanged.

## Validation and limitations

- 250 targeted tests passed for dashboard queries, formatting, cards, health,
  and the new monitoring states and daily aggregation.
- Python source compiled and a wheel was built successfully with Python 3.12
  and NiceGUI 3.16.0. The Dockerfile pins this tested NiceGUI version.
- Local HTTP route checks cover overview, deals, products, alerts, and stores.
- The Docker image itself could not be built here because Docker is unavailable;
  the image build and Unraid deployment must run on your server.
- No live retailer scan was used to validate the dashboard. It does not fix the
  HTTP 206 rejection. No browser interaction or visual testing was performed.
- Like the upstream dashboard, this is intended for your local network and has
  no added login system.
- The collection chart counts retained snapshots by UTC date across the entire
  installation. It is not a count of successful or complete scans. Historical
  records may include stores you no longer watch.

For development, install `pip install -e ".[dashboard,dev]"`, then run `hd serve`.
The new source is in `src/hd/dashboard/monitor.py` and
`src/hd/dashboard/pages/home.py`; navigation and styles are in
`src/hd/dashboard/components/header.py`.


## Browser transport (installed October 8, 2026)

HDScanner can now send GraphQL operations through a private headed-browser service. The scanner stays at port 8085 and keeps its original /data volume, store selection and host scan schedule. The running images are hdscanner:browser and hdscanner-browser:local. The browser runtime derives from the existing receipt crawler image and uses its pinned ChromiumFish/CloakBrowser SDKs. HTTP_TRANSPORT=browser selects this transport; curl remains the default for other installations.

The browser has a separate persistent profile under /mnt/user/appdata/hdscanner/browser-data. Its API has no published host port and requires a private token. The existing CloakBrowser license is stored in browser-private.env outside the build context; never commit that file or the scanner token. Both containers use restart-unless-stopped.

The browser service serializes API calls, enforces pacing, blocks incidental website GraphQL requests, and preserves status, body and response headers. HTTP 206, 403, 429 or an HTML challenge stops requests and persists a cooldown. It also reads the scanner's existing cooldown. A dispatched request whose response cannot be read is stopped rather than replayed. No automatic CAPTCHA completion is added. The browser closes after two minutes of inactivity to release its license session; receipt collection and scanning still share the license's concurrency allowance.

Validation: 76 Python transport/client/store tests, 137 browse/pipeline/dashboard tests and four Node gateway tests passed. A real headed CloakBrowser session with sandbox enabled passed against a local mock API on Unraid. On October 8 at 16:49 Eastern, a user-authorized live CloakBrowser shelf scan saved 97 Milwaukee products and 97 priced snapshots for store 3888, using 10 requests with no throttling. The 12-request budget deferred eight walks, so this is partial catalog coverage; no clearance records were observed in this sample. The earlier queued cooldown scan was cancelled. The live log is /mnt/user/appdata/hdscanner/browser-source/forced-cloakbrowser-scan.log. Standalone browse now updates collection health when it saves snapshots or is aborted; a successful manual scan clears older empty-run failures without sending notifications. Unraid scheduling checks read the actual host cron file and the two scanner User Scripts through read-only mounts, so missing or disabled jobs still raise an error.

The old container is retained stopped as hdscanner-before-browser-20261008. Its full configuration and .env are backed up privately under /mnt/user/appdata/hdscanner/backups/pre-browser-20261008. To roll back, stop and rename the new scanner, restore scanner.env to data/.env, rename the old container to hdscanner, and start it. Stop the browser service after rolling back. Original data is shared, so do not start both scanner containers together.

Deploy source is staged in /mnt/user/appdata/hdscanner/browser-source. deploy/unraid.browser.compose.yml records a reproducible two-service setup; do not start that stack while the command-line-created containers already exist. browser/Dockerfile and Dockerfile.browser-scanner build the two images from the existing local base images.

Working source is located at /Users/jakeihasz/GitHub/hdscanner. Retailer requests and scheduled collection run on Unraid; the Mac is not required for collection.
