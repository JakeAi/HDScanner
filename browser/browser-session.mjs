import { binaryPath, buildArgs } from 'chromiumfish';
import { chromium } from 'playwright-core';
import path from 'node:path';
import fs from 'node:fs/promises';
import crypto from 'node:crypto';
import * as cloakBrowser from 'cloakbrowser';
import { retailers, browserEngines } from './state.mjs';

export const redactBrowserSecrets = value => String(value ?? '').replace(/cb_[a-zA-Z0-9_-]+/g, '[license key hidden]');

export class BrowserSession {
  constructor(directory, {
    headless = false,
    sandbox = true,
    profile = process.env.CRAWLER_BROWSER_PROFILE || 'profile',
    walmartProfile = process.env.CRAWLER_WALMART_BROWSER_PROFILE || 'profile-walmart',
    cloak = cloakBrowser,
    licenseKey = process.env.CLOAKBROWSER_LICENSE_KEY || '',
  } = {}) {
    if (![profile, walmartProfile].every(value => /^[a-zA-Z0-9_-]+$/.test(value))) {
      throw new Error('Crawler browser profile must be a directory name.');
    }

    this.directory = directory;
    this.headless = headless;
    this.sandbox = sandbox;
    this.profile = profile;
    this.walmartProfile = walmartProfile;
    this.cloak = cloak;
    this.licenseKey = licenseKey.trim();
    this.pending = Promise.resolve();
  }

  profileForRetailer(id, engine = 'chromiumfish') {
    if (!Object.hasOwn(browserEngines, engine)) throw new Error('Choose a supported browser.');
    if (id !== undefined && !Object.hasOwn(retailers, id)) {
      throw new Error('Unknown retailer.');
    }

    if (engine === 'cloakbrowser') return id === 'walmart' ? 'profile-cloakbrowser-walmart' : 'profile-cloakbrowser';
    return id === 'walmart' ? this.walmartProfile : this.profile;
  }

  serialize(operation) {
    const result = this.pending.then(operation);
    this.pending = result.catch(() => {});
    return result;
  }

  context(id, engine = 'chromiumfish') {
    const profile = this.profileForRetailer(id, engine);
    return this.serialize(() => this.openProfile(profile, engine));
  }

  async openProfile(profile, engine) {
    if (this.launching && (this.activeProfile !== profile || this.activeEngine !== engine)) {
      await (await this.launching).close();
    }

    if (!this.launching) {
      this.activeProfile = profile;
      this.activeEngine = engine;

      this.launching = (engine === 'cloakbrowser' ? this.launchCloak(profile) : this.launchFish(profile)).then(context => {
        context.setDefaultTimeout(30000);
        context.setDefaultNavigationTimeout(60000);
        this.activeContext = context;

        context.on('close', () => {
          if (this.activeContext !== context) return;

          this.launching = null;
          this.loginPage = null;
          this.activeContext = null;
          this.activeProfile = null;
          this.activeEngine = null;
        });

        return context;
      }).catch(error => {
        this.launching = null;
        this.activeProfile = null;
        this.activeEngine = null;
        error.message = redactBrowserSecrets(error.message);
        throw error;
      });
    }

    return this.launching;
  }

  launchFish(profile) {
    return binaryPath().then(executablePath => chromium.launchPersistentContext(path.join(this.directory, profile), {
        executablePath,
        headless: this.headless,
        viewport: null,
        chromiumSandbox: this.sandbox,
        acceptDownloads: false, serviceWorkers: 'block',
        // The SDK's default no-sandbox/no-zygote flags conflict with our sandbox.
        args: buildArgs({ personaSeed: profile, windowSize: null, args: ['--start-maximized'] })
          .filter(arg => !this.sandbox || !['--no-sandbox', '--no-zygote'].includes(arg.split('=')[0])),
        ignoreDefaultArgs: ['--enable-automation'],
      }));
  }

  cloakStatus() {
    const info = this.cloak.binaryInfo(undefined, 'stable');
    return { configured: this.hasLicense(), version: info.installed ? info.version : null };
  }

  hasLicense() {
    return /^cb_[a-zA-Z0-9_-]+$/.test(this.licenseKey) && !/redacted|^cb_xxx$/i.test(this.licenseKey);
  }

  async launchCloak(profile) {
    if (!this.hasLicense()) throw new Error('Add your complete CLOAKBROWSER_LICENSE_KEY to .env and recreate the crawler before using CloakBrowser.');
    const userDataDir = path.join(this.directory, profile);
    await fs.mkdir(userDataDir, { recursive: true, mode: 0o700 });
    const identityFile = path.join(userDataDir, 'hdscanner-browser-identity.json');
    let seed;
    try { ({ seed } = JSON.parse(await fs.readFile(identityFile, 'utf8'))); }
    catch (error) {
      if (error.code !== 'ENOENT') throw error;
      seed = crypto.randomInt(1, 2147483647);
      await fs.writeFile(identityFile, JSON.stringify({ seed }), { mode: 0o600, flag: 'wx' });
    }
    if (!Number.isInteger(seed) || seed < 1 || seed > 2147483647) throw new Error('The saved CloakBrowser identity is invalid. Restore its profile from your backup.');
    const options = {
      userDataDir, licenseKey: this.licenseKey, releaseChannel: 'stable',
      headless: this.headless, viewport: null, humanize: true, humanPreset: 'careful',
      timezone: process.env.TZ || 'America/New_York', locale: 'en-US',
      args: [`--fingerprint=${seed}`, '--start-maximized'],
      contextOptions: { acceptDownloads: false, serviceWorkers: 'block' },
    };
    // Use the SDK's public builder, preserving its flags except those that disable our sandbox.
    const prepared = await this.cloak.buildLaunchOptions(options);
    return this.cloak.launchPersistentContext({ ...options, launchOptions: {
      chromiumSandbox: this.sandbox,
      args: prepared.args.filter(arg => !this.sandbox || !['--no-sandbox', '--no-zygote'].includes(arg.split('=')[0])),
    } });
  }

  async login(id, engine = 'chromiumfish') {
    const context = await this.context(id, engine);

    if (!this.loginPage || this.loginPage.isClosed()) {
      this.loginPage = context.pages()[0] || await context.newPage();
    }

    await this.loginPage.goto(retailers[id].url, {
      waitUntil: 'domcontentloaded',
    });
    await this.loginPage.bringToFront();
  }

  close() {
    return this.serialize(async () => {
      if (this.launching) {
        await (await this.launching).close();
      }
    });
  }
}
