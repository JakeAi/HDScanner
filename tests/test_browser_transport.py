"""Local service tests; no retailer requests or real browser sessions."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from hd.config import Settings
from hd.http.browser import BrowserTransport
from hd.http.client import HDClient, FAILURE_KEY
from hd.http.transport import TransportError, make_transport, CurlTransport


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        self.server.seen.append((self.headers['Authorization'], json.loads(
            self.rfile.read(int(self.headers['Content-Length'])))))
        raw = json.dumps(self.server.result).encode()
        self.send_response(self.server.status)
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *args):
        pass


@pytest.fixture
def bridge(tmp_path):
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    server.seen = []
    server.status = 200
    server.result = {'status': 200, 'body': '{"data": {}}', 'headers': {'content-type': 'application/json'}}
    token = tmp_path / 'token'
    token.write_text('a' * 64)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server, BrowserTransport(f'http://127.0.0.1:{server.server_port}', str(token)), token
    server.shutdown()
    server.server_close()


async def test_preserves_payload_and_response_headers(bridge):
    server, transport, _ = bridge
    server.result = {'status': 429, 'body': 'throttled', 'headers': {'retry-after': '3600'}}
    result = await transport.post_json('https://apionline.homedepot.com/graphql', {'query': 'x'}, {'Accept': '*/*'})
    assert result.status == 429 and result.header('Retry-After') == '3600'
    assert server.seen == [('Bearer ' + 'a' * 64, {
        'url': 'https://apionline.homedepot.com/graphql', 'payload': {'query': 'x'}, 'headers': {'Accept': '*/*'},
    })]


async def test_206_stops_client_and_persists_cooldown(bridge, tmp_path):
    server, transport, _ = bridge
    server.result = {'status': 206, 'body': '{}', 'headers': {'retry-after': '3600'}}
    settings = Settings(_env_file=None, throttle_cooldown_path=str(tmp_path / 'cooldown'),
                        jitter_min_ms=0, jitter_max_ms=0)
    client = HDClient(settings, transport=transport)
    assert (await client.post_graphql({}))[FAILURE_KEY] == 'http_206_quota'
    assert (await client.post_graphql({}))[FAILURE_KEY] == 'throttled'
    assert len(server.seen) == 1
    assert client.cooldown.is_active()
    await client.close()


@pytest.mark.parametrize('result', [None, {'status': '200', 'body': '', 'headers': {}},
                                   {'status': 200, 'body': {}, 'headers': {}},
                                   {'status': 200, 'body': '', 'headers': {'x': 5}}])
async def test_invalid_bridge_response_is_not_success(bridge, result):
    server, transport, _ = bridge
    server.result = result
    with pytest.raises(TransportError):
        await transport.post_json('https://example.com', {}, {})


async def test_auth_failure_is_not_replayed(bridge):
    server, transport, _ = bridge
    server.status = 401
    with pytest.raises(TransportError, match='401'):
        await transport.post_json('https://example.com', {}, {})
    assert len(server.seen) == 1


async def test_missing_token_makes_no_request(bridge):
    server, transport, token = bridge
    token.unlink()
    with pytest.raises(TransportError, match='token file'):
        await transport.post_json('https://example.com', {}, {})
    assert server.seen == []


async def test_store_lookup_obeys_saved_cooldown(tmp_path, monkeypatch):
    from hd.hd_api.stores import search_stores, StoreLookupThrottled
    from hd.http.cooldown import ThrottleCooldown
    cooldown = tmp_path / 'cooldown'
    ThrottleCooldown(cooldown).start()
    monkeypatch.setenv('HTTP_TRANSPORT', 'browser')
    monkeypatch.setenv('THROTTLE_COOLDOWN_PATH', str(cooldown))
    with pytest.raises(StoreLookupThrottled, match='saved cooldown'):
        await search_stores('44805')


def test_transport_selection_defaults_to_curl():
    assert isinstance(make_transport(Settings(_env_file=None)), CurlTransport)
    assert isinstance(make_transport(Settings(_env_file=None, http_transport='browser')), BrowserTransport)
