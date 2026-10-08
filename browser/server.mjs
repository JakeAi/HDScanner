import http from 'node:http';
import fs from 'node:fs/promises';
import crypto from 'node:crypto';
import { BrowserSession, redactBrowserSecrets } from './browser-session.mjs';
import { BrowserGateway } from './gateway.mjs';

const directory = process.env.HD_BROWSER_DATA || '/browser-data';
await fs.mkdir(directory, {recursive: true});
const token = (await fs.readFile(process.env.HD_BROWSER_TOKEN_FILE || '/run/hd-browser-token', 'utf8')).trim();
if (token.length < 32) throw new Error('A private browser service token is required');
const browser = new BrowserSession(directory, {headless: false, sandbox: true, profile: 'hdscanner-chromiumfish'});
const gateway = new BrowserGateway({browser, directory,
  endpoint: process.env.HD_API_ENDPOINT || 'https://apionline.homedepot.com/federation-gateway/graphql',
  home: process.env.HD_BROWSER_HOME || 'https://www.homedepot.com/',
  scannerCooldown: process.env.HD_SCANNER_COOLDOWN || '/scanner-data/.hd_throttle_cooldown'});

function authorized(request) {
  const supplied = Buffer.from(request.headers.authorization || ''), expected = Buffer.from(`Bearer ${token}`);
  return supplied.length === expected.length && crypto.timingSafeEqual(supplied, expected);
}
function json(response, status, body) {
  response.writeHead(status, {'Content-Type': 'application/json'});
  response.end(JSON.stringify(body));
}
const server = http.createServer(async (request, response) => {
  if (request.url === '/health' && request.method === 'GET') return json(response, 200, {ready: true});
  if (!authorized(request)) return json(response, 401, {error: 'Unauthorized'});
  if (request.url === '/status' && request.method === 'GET') return json(response, 200, {
    engine: process.env.HD_BROWSER_ENGINE || 'chromiumfish', sent: gateway.sent,
    browserOpen: Boolean(gateway.page && !gateway.page.isClosed()), cooldownUntil: await gateway.cooldownUntil(),
  });
  if (request.url !== '/request' || request.method !== 'POST') return json(response, 404, {error: 'Not found'});
  let raw = '';
  try {
    for await (const chunk of request) {
      raw += chunk;
      if (Buffer.byteLength(raw) > 2 * 1024 * 1024) return json(response, 413, {error: 'Request too large'});
    }
    let input;
    try {input = JSON.parse(raw);} catch {return json(response, 400, {error: 'Invalid JSON'});}
    const result = await gateway.request(input);
    json(response, 200, result);
  } catch (error) {
    console.error(redactBrowserSecrets(error.message));
    json(response, 502, {error: 'Browser request failed; check the browser service log'});
  }
});
server.listen(4010, '0.0.0.0', () => console.log('HDScanner headed browser ready on internal port 4010'));
const idle = setInterval(() => gateway.closeIfIdle(120000).catch(error => console.error(redactBrowserSecrets(error.message))), 30000);
let stopping = false;
async function stop() {
  if (stopping) return;
  stopping = true;
  clearInterval(idle);
  server.close();
  await gateway.close();
  process.exit(0);
}
process.on('SIGTERM', stop);
process.on('SIGINT', stop);
