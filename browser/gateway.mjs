import fs from 'node:fs/promises';
import path from 'node:path';

export function validateRequest(input, endpoint) {
  if (!input || typeof input !== 'object') throw new Error('Invalid request');
  const url = new URL(input.url), allowed = new URL(endpoint);
  const operation = input.payload?.operationName;
  if (url.origin !== allowed.origin || url.pathname !== allowed.pathname
      || url.username || url.password || url.hash
      || !['searchModel', 'storeSearch', 'storeDetails'].includes(operation)
      || url.searchParams.get('opname') !== operation
      || [...url.searchParams.keys()].some(key => key !== 'opname')
      || typeof input.payload?.query !== 'string'
      || !input.payload.variables || typeof input.payload.variables !== 'object') {
    throw new Error('Only the configured Home Depot GraphQL operations are allowed');
  }
  // The running browser supplies its own UA, cookies, origin and compression.
  const allowedHeaders = ['accept', 'content-type', 'x-experience-name', 'x-hd-dc', 'x-debug'];
  const headers = Object.fromEntries(Object.entries(input.headers || {}).filter(([name]) =>
    allowedHeaders.includes(name.toLowerCase())));
  return {url: url.href, payload: input.payload, headers};
}

export class BrowserGateway {
  constructor({browser, endpoint, home, directory, scannerCooldown,
    cooldownSeconds = 3600, minDelayMs = 1500, maxBytes = 10 * 1024 * 1024}) {
    Object.assign(this, {browser, endpoint, home, directory, scannerCooldown,
      cooldownSeconds, minDelayMs, maxBytes});
    this.queue = Promise.resolve();
    this.lastRequest = 0;
    this.lastUsed = Date.now();
    this.sent = 0;
  }

  serialize(operation) {
    const promise = this.queue.then(operation);
    this.queue = promise.catch(() => {});
    return promise;
  }

  async cooldownUntil() {
    const files = [path.join(this.directory, 'cooldown'), this.scannerCooldown].filter(Boolean);
    const dates = await Promise.all(files.map(async file => {
      try { return Date.parse((await fs.readFile(file, 'utf8')).trim()) || 0; }
      catch { return 0; }
    }));
    return Math.max(0, ...dates);
  }

  async rememberCooldown(response) {
    const type = response.headers['content-type'] || '';
    if (![206, 403, 429].includes(response.status) && !/html/i.test(type)
        && !response.body.trimStart().startsWith('<')) return;
    const retry = response.headers['retry-after'];
    const requested = /^\d+$/.test(retry || '') ? Date.now() + Number(retry) * 1000 : Date.parse(retry);
    const until = Math.max(Date.now() + this.cooldownSeconds * 1000, requested || 0,
      await this.cooldownUntil());
    await fs.writeFile(path.join(this.directory, 'cooldown'), new Date(until).toISOString(), {mode: 0o600});
  }

  async pageReady(request) {
    if (this.page && !this.page.isClosed()) return this.page;
    const context = await this.browser.context('home-depot', process.env.HD_BROWSER_ENGINE || 'chromiumfish');
    await context.route('**/federation-gateway/graphql*', async route => {
      // Site-initiated catalog calls are blocked so the scanner owns the budget.
      let payload;
      try { payload = route.request().postDataJSON(); } catch {}
      if (this.expected && route.request().url() === this.expected.url
          && JSON.stringify(payload) === JSON.stringify(this.expected.payload)
          && !this.dispatched) {
        this.dispatched = true;
        this.sent++;
        await route.continue();
      } else await route.abort();
    });
    this.page = context.pages()[0] || await context.newPage();
    const home = await this.page.goto(this.home, {waitUntil: 'domcontentloaded'});
    if (!home || home.status() !== 200 || new URL(this.page.url()).origin !== new URL(this.home).origin) {
      throw new Error('Home Depot browser page requires attention');
    }
    return this.page;
  }

  request(input) {
    const request = validateRequest(input, this.endpoint);
    return this.serialize(async () => {
      this.lastUsed = Date.now();
      const until = await this.cooldownUntil();
      if (until > Date.now()) return {status: 206, body: '{}', headers: {
        'content-type': 'application/json', 'retry-after': String(Math.ceil((until - Date.now()) / 1000)),
      }};
      const page = await this.pageReady(request);
      const delay = Math.max(0, this.minDelayMs - (Date.now() - this.lastRequest));
      if (delay) await new Promise(resolve => setTimeout(resolve, delay));
      this.expected = request;
      this.dispatched = false;
      this.lastRequest = Date.now();
      let networkResponse;
      const observe = response => {
        if (response.url() === request.url && response.request().method() === 'POST') networkResponse = response;
      };
      page.on('response', observe);
      try {
        const response = await page.evaluate(async ({url, payload, headers, maxBytes}) => {
          const controller = new AbortController();
          const timer = setTimeout(() => controller.abort(), 30000);
          try {
            const response = await fetch(url, {method: 'POST', headers,
              credentials: 'include', redirect: 'error', body: JSON.stringify(payload), signal: controller.signal});
            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            let bytes = 0, body = '';
            while (true) {
              const chunk = await reader.read();
              if (chunk.done) break;
              bytes += chunk.value.byteLength;
              if (bytes > maxBytes) {await reader.cancel(); throw new Error('Response exceeds size limit');}
              body += decoder.decode(chunk.value, {stream: true});
            }
            body += decoder.decode();
            return {status: response.status, body, headers: Object.fromEntries(response.headers.entries())};
          } finally {clearTimeout(timer);}
        }, {...request, maxBytes: this.maxBytes});
        // Browser fetch exposes only CORS-safe headers; preserve Retry-After too.
        if (networkResponse) response.headers = await networkResponse.allHeaders();
        await this.rememberCooldown(response);
        this.lastUsed = Date.now();
        return response;
      } catch (error) {
        if (networkResponse && [206, 403, 429].includes(networkResponse.status())) {
          const response = {status: networkResponse.status(), body: '{}', headers: await networkResponse.allHeaders()};
          await this.rememberCooldown(response);
          return response;
        }
        // A dispatched request with an unreadable result must not be replayed.
        if (this.dispatched) {
          const response = {status: 403, body: JSON.stringify({error: 'browser_response_unreadable'}),
            headers: {'content-type': 'application/json'}};
          await this.rememberCooldown(response);
          return response;
        }
        throw error;
      } finally {this.expected = null; page.off('response', observe);}
    });
  }

  closeIfIdle(idleMs) {
    return this.serialize(async () => {
      if (Date.now() - this.lastUsed > idleMs) {
        await this.browser.close();
        this.page = null;
      }
    });
  }

  close() {
    return this.serialize(async () => {await this.browser.close(); this.page = null;});
  }
}
