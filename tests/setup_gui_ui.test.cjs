'use strict';
// Actual frontend with a tiny DOM boundary; no browser, network or OS operations.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname, '..');
const source = fs.readFileSync(path.join(root, 'candidate/setup_gui/web/app.js'), 'utf8');
const html = fs.readFileSync(path.join(root, 'candidate/setup_gui/web/index.html'), 'utf8');
class Element {
  constructor(tag = 'div') { this.tagName = tag; this.value = ''; this.checked = false; this.disabled = false; this.children = []; this.events = {}; this.attrs = {}; this.classList = { toggle() {} }; }
  addEventListener(name, handler) { this.events[name] = handler; }
  append(...items) { this.children.push(...items); }
  replaceChildren() { this.children = []; }
  setAttribute(name, value) { this.attrs[name] = value; }
  querySelectorAll() { return this.children; }
  focus() {}
}
async function fixture(overrides = {}, options = {}) {
  let monotonic = 0;
  const storage = options.storage || new Map();
  const writes = [];
  const localStorage = {
    getItem(key) { if (options.storageBlocked) throw new Error('Storage denied'); return storage.get(key) ?? null; },
    setItem(key, value) { if (options.storageBlocked) throw new Error('Storage denied'); writes.push([key, value]); storage.set(key, value); },
    removeItem(key) { if (options.storageBlocked) throw new Error('Storage denied'); storage.delete(key); }
  };
  const unauthorized = new Set();
  const elements = Object.fromEntries([...html.matchAll(/<([\w-]+)\b[^>]*\bid="([^"]+)"/g)].map((match) => [match[2], new Element(match[1])]));
  elements.priority.value = '50';
  let status = { deviceId: 'GPS-002', preview: false, changesEnabled: false, scanAvailable: true,
    wifiConnected: true, internet: 'full', manager: 'NetworkManager', interface: 'wlan0',
    connectionMessage: 'Use Enable connections.', task: { state: 'idle', message: 'No changes.' },
    presence: { state: 'not_configured', message: 'This app has not sent an authenticated setup check-in.' },
    backend: { origin: 'http://192.168.1.5:5000', state: 'not_checked', message: 'Not checked.' }, ...overrides };
  const requests = [];
  const intervals = [];
  const document = { hidden: false, getElementById(id) { assert.ok(elements[id], `missing HTML element ${id}`); return elements[id]; },
    querySelectorAll(selector) { const tags = selector.split(',').map((s) => s.trim()); return Object.values(elements).filter((element) => tags.includes(element.tagName)); },
    createElement() { return new Element(); }, addEventListener() {} };
  const sandbox = { document, location: { protocol: options.protocol || 'http:', hash: options.hash ?? '#synthetic-session', pathname: '/' }, history: { replaceState() {} },
    window: { addEventListener() {} }, AbortController, Date, Set, URL, localStorage, performance: { now() { return monotonic; } },
    setTimeout() { return 1; }, clearTimeout() {}, clearInterval() {}, setInterval(fn) { intervals.push(fn); return intervals.length; },
    async fetch(url, requestOptions) {
      const body = JSON.parse(requestOptions.body); requests.push({ url, body, headers: requestOptions.headers });
      if (unauthorized.has(url)) return {status:401,ok:false,async json(){return {};}};
      let result = {};
      if (url === '/api/status') result = status;
      if (url === '/api/session/reopen') result = { accepted: true };
      if (url === '/api/authorize') { status = { ...status, changesEnabled: true }; result = { accepted: true }; }
      if (url === '/api/scan') result = { networks: [
        { id: 'chosen', ssid: 'Depot', security: 'wpa2-personal', signal: 80, connected: false },
        { id: 'active', ssid: 'Current', security: 'wpa2-personal', signal: 70, connected: true }] };
      if (url === '/api/connect') { status = { ...status, task: { state: 'awaiting_confirmation', deadlineEpoch: Date.now() / 1000 + 30 } }; result = { accepted: true }; }
      if (url === '/api/backend-check') result = { backend: options.backendReport || { origin: body.origin, state: 'unreachable', message: 'Laptop backend unreachable.' } };
      if (url === '/api/presence/start') { status = { ...status, presence: { state: 'online', configured: true, canStart: false, running: true, active: true, expiresInSeconds: 44, lastConfirmedAt: '2026-10-18T04:00:00.123Z', message: 'Verified check-in.' } }; result = { presence: status.presence }; }
      if (url === '/api/presence/stop') { status = { ...status, presence: { state: 'stopped', configured: true, canStart: true, running: false, active: false } }; result = { presence: status.presence }; }
      return { status: 200, ok: true, async json() { return result; } };
    } };
  vm.runInNewContext(source, sandbox, { filename: 'app.js' });
  const settle = () => new Promise((resolve) => setImmediate(resolve));
  await settle();
  return { elements, requests, intervals, storage, writes, settle, unauthorize(url) { unauthorized.add(url); }, advance(ms) { monotonic += ms; }, update(next) { status = { ...status, ...next }; },
    async fire(id, event = 'click') { assert.ok(elements[id].events[event], `missing handler ${id}`); await elements[id].events[event]({ preventDefault() {} }); await settle(); } };
}

test('assets resolve beside the HTML both as a file and through the local server', () => {
  const css = html.match(/<link[^>]+href="([^"]+)"/)[1];
  const js = html.match(/<script[^>]+src="([^"]+)"/)[1];
  for (const [base, directory] of [['file:///package/candidate/setup_gui/web/index.html', 'file:///package/candidate/setup_gui/web/'],
    ['http://127.0.0.1:8765/', 'http://127.0.0.1:8765/']]) {
    assert.equal(new URL(css, base).href, directory + 'style.css');
    assert.equal(new URL(js, base).href, directory + 'app.js');
  }
});

test('direct file opening shows launcher instructions with no requests, timers or enabled controls', async () => {
  const f = await fixture({}, { protocol: 'file:' });
  assert.equal(f.requests.length, 0);
  assert.equal(f.intervals.length, 0);
  assert.equal(f.storage.size, 0);
  assert.equal(f.elements['session-recovery'].hidden, false);
  assert.equal(f.elements['session-reopen'].hidden, true);
  assert.equal(f.elements['launch-instructions'].hidden, false);
  assert.match(f.elements.notice.textContent, /setup-pi\.py/);
  assert.match(f.elements['session-message'].textContent, /No device status has been checked/);
  assert.equal(f.elements.password.value, '');
  for (const [id, element] of Object.entries(f.elements)) {
    if (['button', 'input'].includes(element.tagName)) assert.equal(element.disabled, true, id);
  }
});

test('read-only session enables Connect after explicit approval without relaunch', async () => {
  const f = await fixture(); const e = f.elements;
  assert.equal(e.connect.disabled, true);
  assert.equal(e.enable.disabled, true);
  e['enable-confirm'].checked = true; await f.fire('enable-confirm', 'change');
  assert.equal(e.enable.disabled, false);
  await f.fire('enable');
  assert.deepEqual(f.requests.find((r) => r.url === '/api/authorize').body, { confirmed: true });
  assert.equal(e['enable-panel'].hidden, true);
  await f.fire('scan'); await e.networks.children[0].events.click();
  assert.equal(e.ssid.value, 'Depot'); assert.equal(e.password.disabled, false); assert.equal(e.connect.disabled, false);
  e.password.value = 'synthetic-wifi-only'; e.confirm.checked = true;
  await f.fire('connect-form', 'submit');
  assert.equal(f.requests.find((r) => r.url === '/api/connect').body.password, 'synthetic-wifi-only');
  assert.equal(e.password.value, ''); assert.equal(e.keep.disabled, false);
});

test('already connected selection points to API check rather than another profile', async () => {
  const f = await fixture({ changesEnabled: true });
  await f.fire('scan'); await f.elements.networks.children[1].events.click();
  assert.equal(f.elements.connect.disabled, true); assert.equal(f.elements.connect.textContent, 'Already connected');
  assert.match(f.elements['connection-help'].textContent, /Check Express API/);
  assert.equal(f.requests.filter((r) => r.url === '/api/backend-check').length, 0);
  await f.fire('backend-form', 'submit');
  assert.equal(f.elements['backend-state'].textContent, 'Unreachable');
  assert.match(f.elements['backend-message'].textContent, /unreachable/);
});

test('native authorization failures stay actionable across status refreshes', async () => {
  const message = 'No desktop authentication agent. Open the setup from the Pi desktop terminal.';
  const f = await fixture({ task: { state: 'failed', message }, connectionMessage: message });
  assert.equal(f.elements.notice.textContent, message);
  await f.fire('refresh');
  assert.equal(f.elements.notice.textContent, message);
  assert.equal(f.elements.connect.disabled, true);
});

test('preview never enables connection or backend operations', async () => {
  const f = await fixture({ preview: true, scanAvailable: false });
  f.elements['enable-confirm'].checked = true; await f.fire('enable-confirm', 'change');
  assert.equal(f.elements.enable.disabled, true); assert.equal(f.elements['backend-check'].disabled, true);
  assert.equal(f.requests.length, 1);
});

test('setup-only API readiness is separate from GPS writes and dashboard check-in', async () => {
  const f = await fixture({ backend: { state: 'ready', mode: 'local-setup', gpsPersistenceEnabled: false,
    setupPresenceEnabled: true, message: 'Express setup API is ready.' } });
  assert.equal(f.elements['backend-state'].textContent, 'API ready');
  assert.equal(f.elements['backend-mode'].textContent, 'Setup only');
  assert.equal(f.elements['gps-state'].textContent, 'Disabled');
  assert.equal(f.elements['presence-state'].textContent, 'Not configured');
  assert.match(f.elements['presence-message'].textContent, /has not sent/);
  assert.deepEqual(f.requests.map((request) => request.url), ['/api/status']);
});

test('GPS readiness never becomes confirmed dashboard presence and resets on a failed check', async () => {
  const f = await fixture({ backend: { state: 'ready', mode: 'real-lan', gpsPersistenceEnabled: true } });
  assert.equal(f.elements['gps-state'].textContent, 'Enabled');
  assert.equal(f.elements['presence-state'].textContent, 'Not configured');
  await f.fire('backend-form', 'submit');
  assert.equal(f.elements['backend-state'].textContent, 'Unreachable');
  assert.equal(f.elements['backend-mode'].textContent, 'Not checked');
  assert.equal(f.elements['gps-state'].textContent, 'Not checked');
  assert.equal(f.elements['presence-state'].textContent, 'Not configured');
});

test('authenticated check-ins require explicit approval and stay separate from GPS writes', async () => {
  const f = await fixture({ backend: { origin: 'http://192.168.1.5:5000', state: 'ready', mode: 'local-setup', gpsPersistenceEnabled: false },
    presence: { state: 'stopped', configured: true, canStart: true, running: false } });
  assert.equal(f.elements['presence-start'].disabled, true);
  f.elements['backend-origin'].value = 'http://192.168.1.6:5000';
  await f.fire('backend-origin', 'input');
  f.elements['presence-confirm'].checked = true; await f.fire('presence-confirm', 'change');
  assert.equal(f.elements['presence-start'].disabled, true);
  f.elements['backend-origin'].value = 'http://192.168.1.5:5000';
  assert.equal(f.requests.length, 1);
  f.elements['presence-confirm'].checked = true; await f.fire('presence-confirm', 'change');
  assert.equal(f.elements['presence-start'].disabled, false);
  await f.fire('presence-start');
  assert.deepEqual(f.requests.find((request) => request.url === '/api/presence/start').body, { confirmed: true });
  assert.equal(f.elements['presence-state'].textContent, 'Setup online');
  assert.equal(f.elements['gps-state'].textContent, 'Disabled');
  assert.equal(f.elements['presence-stop'].disabled, false);
  await f.fire('presence-stop');
  assert.equal(f.elements['presence-state'].textContent, 'Stopped');
  assert.equal(f.elements['presence-start'].disabled, true);
});

test('setup online expires locally without waiting for a status poll', async () => {
  const f = await fixture({ presence: { state: 'online', running: true, expiresInSeconds: 1 } });
  assert.equal(f.elements['presence-state'].textContent, 'Setup online');
  f.advance(1001); f.intervals[1]();
  assert.equal(f.elements['presence-state'].textContent, 'Expired');
});

test('reload without a token shows recovery immediately instead of Opening forever', async () => {
  const f = await fixture({}, { hash: '' });
  assert.equal(f.requests.length, 0);
  assert.equal(f.elements['session-recovery'].hidden, false);
  assert.match(f.elements.notice.textContent, /Reloading cleared/);
  assert.equal(f.elements.refresh.disabled, true);
  assert.equal(f.elements.scan.disabled, true);
  assert.equal(f.elements['session-reopen'].disabled, false);
  await f.fire('session-reopen');
  assert.equal(f.requests[0].url, '/api/session/reopen');
  assert.equal(f.requests[0].headers.Authorization, undefined);
  assert.deepEqual(f.requests[0].body, {});
  assert.match(f.elements['session-message'].textContent, /newly opened window/);
  assert.equal(f.elements.scan.disabled, true);
});

test('expired session disables protected controls and exposes recovery', async () => {
  const f = await fixture({ task: { state: 'awaiting_confirmation', deadlineEpoch: Date.now() / 1000 + 30 },
    presence: { state: 'online', running: true, expiresInSeconds: 30 } });
  assert.equal(f.elements.keep.disabled, false);
  f.unauthorize('/api/status');
  await f.fire('refresh');
  for (const id of ['refresh', 'scan', 'connect', 'keep', 'rollback', 'presence-stop', 'backend-check']) assert.equal(f.elements[id].disabled, true, id);
  assert.equal(f.elements['session-recovery'].hidden, false);
  assert.match(f.elements.notice.textContent, /session expired/);
  assert.equal(f.elements['session-reopen'].disabled, false);
  const before = f.requests.length;
  await f.intervals[0](); await f.settle();
  assert.equal(f.requests.length, before);
});

test('verified public API origin is remembered per device and restored without probes or presence', async () => {
  const storage = new Map();
  const origin = 'https://api.example.test';
  const f = await fixture({}, { storage, backendReport: { origin, state: 'ready', setupPresenceEnabled: true } });
  f.elements['backend-origin'].value = origin;
  await f.fire('backend-form', 'submit');
  assert.deepEqual([...storage], [['centrabus.setup.api-origin.v1:GPS-002', origin]]);
  const reopened = await fixture({ backend: { origin: '', state: 'not_checked' } }, { storage });
  assert.equal(reopened.elements['backend-origin'].value, origin);
  assert.equal(reopened.elements['backend-state'].textContent, 'Not checked');
  assert.equal(reopened.elements['presence-start'].disabled, true);
  assert.deepEqual(reopened.requests.map((r) => r.url), ['/api/status']);
});

test('unreachable and unverified API checks do not overwrite a validated address', async () => {
  for (const state of ['unreachable', 'unverified']) {
    const storage = new Map([['centrabus.setup.api-origin.v1:GPS-002', 'https://known.example.test']]);
    const f = await fixture({}, { storage, backendReport: { origin: 'https://other.example.test', state } });
    await f.fire('backend-form', 'submit');
    assert.equal(storage.get('centrabus.setup.api-origin.v1:GPS-002'), 'https://known.example.test');
    assert.equal(f.writes.length, 0);
  }
});

test('unsafe remembered addresses are discarded without transmission', async () => {
  for (const origin of ['https://user:synthetic-secret@api.example.test', 'https://api.example.test?key=synthetic-secret',
    'https://api.example.test/path', 'https://api.example.test#synthetic-secret', 'http://api.example.test',
    'https://localhost', 'http://127.0.0.1:8765', 'https://169.254.1.1', 'javascript:alert(1)']) {
    const storage = new Map([['centrabus.setup.api-origin.v1:GPS-002', origin]]);
    const f = await fixture({ backend: { origin: '', state: 'not_checked' } }, { storage });
    assert.equal(f.elements['backend-origin'].value, '', origin);
    assert.equal(storage.size, 0);
    assert.deepEqual(f.requests.map((r) => r.url), ['/api/status']);
  }
});

test('server-provided origin wins and another device address is not reused', async () => {
  const storage = new Map([['centrabus.setup.api-origin.v1:GPS-001', 'https://pi1.example.test'],
    ['centrabus.setup.api-origin.v1:GPS-002', 'https://saved.example.test']]);
  const f = await fixture({}, { storage });
  assert.equal(f.elements['backend-origin'].value, 'http://192.168.1.5:5000');
  storage.delete('centrabus.setup.api-origin.v1:GPS-002');
  const g = await fixture({ backend: { origin: '', state: 'not_checked' } }, { storage });
  assert.equal(g.elements['backend-origin'].value, '');
});

test('storage receives only the normalized public origin after Wi-Fi password submission', async () => {
  const origin = 'http://192.168.1.5:5000';
  const f = await fixture({ changesEnabled: true }, { backendReport: { origin, state: 'ready' } });
  await f.fire('scan'); await f.elements.networks.children[0].events.click();
  f.elements.password.value = 'synthetic-wifi-only'; f.elements.confirm.checked = true;
  await f.fire('connect-form', 'submit');
  await f.fire('backend-form', 'submit');
  assert.deepEqual(f.writes, [['centrabus.setup.api-origin.v1:GPS-002', origin]]);
  assert.equal(JSON.stringify([...f.storage]).includes('synthetic-wifi-only'), false);
  assert.equal(JSON.stringify([...f.storage]).includes('synthetic-session'), false);
  assert.equal(f.elements.password.value, '');
});

test('blocked browser storage does not break API checking or restore readiness', async () => {
  const f = await fixture({ backend: { origin: '', state: 'not_checked' } }, {
    storageBlocked: true, backendReport: { origin: 'https://api.example.test', state: 'ready' }
  });
  assert.equal(f.elements['backend-origin'].value, '');
  await f.fire('backend-form', 'submit');
  assert.equal(f.elements['backend-state'].textContent, 'API ready');
  assert.equal(f.elements['presence-start'].disabled, true);
});

test('Wi-Fi, Internet, API readiness and setup online never claim GPS freshness', async () => {
  const f = await fixture({ backend: { state: 'ready', mode: 'real-lan', gpsPersistenceEnabled: true },
    presence: { state: 'online', running: true, expiresInSeconds: 30 } });
  assert.equal(f.elements.wifi.textContent, 'Connected');
  assert.match(f.elements.internet.textContent, /Reachable/);
  assert.equal(f.elements['backend-state'].textContent, 'API ready');
  assert.equal(f.elements['presence-state'].textContent, 'Setup online');
  assert.equal(f.elements['gps-state'].textContent, 'Enabled');
  assert.equal(f.elements['gps-freshness'].textContent, 'Not checked by Wi-Fi setup');
});

test('secret-bearing API response is never persisted even if incorrectly marked ready', async () => {
  const f = await fixture({}, { backendReport: { origin: 'https://synthetic:private@api.example.test', state: 'ready' } });
  await f.fire('backend-form', 'submit');
  assert.equal(f.storage.size, 0);
});
