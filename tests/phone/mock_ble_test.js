// Drives phone/index.html in headless Chromium against a mock Web Bluetooth device and
// prints what happened as JSON (tests/test_phone.py checks it). The mock allows only one
// GATT operation at a time, like Android, and cuts notifications to a 23-byte MTU.
//   node tests/phone/mock_ble_test.js /path/to/phone/index.html
const { chromium } = require('playwright');
const MOCK = `
(() => {
  const enc = new TextEncoder();
  const st = { inFlight: 0, maxInFlight: 0, writes: [], pairFail: false, mtu: 23, reads: 0 };
  window.__mock = st;
  const status = () => JSON.stringify({rec:false,t:0,seg:0,bat:80,v:3.9,chg:false,free_mb:28000,left_min:600,photos:1,
      videos:2,res:st.res||"hd",q:st.q||12,seg_s:st.seg||300,maxrec:st.maxrec||0,fps:0,temp:40,clock:true,wifi:false,ver:"1.0.0"});
  const op = async (fn) => {
    st.inFlight++; st.maxInFlight = Math.max(st.maxInFlight, st.inFlight);
    if (st.inFlight > 1) { st.inFlight--; throw new Error("GATT operation already in progress"); }
    await new Promise(r => setTimeout(r, 60));          // one connection interval
    try { return await fn(); } finally { st.inFlight--; }
  };
  function makeChar(uuid) {
    const listeners = [];
    const c = {
      uuid, value: null,
      addEventListener: (t, f) => listeners.push(f),
      startNotifications: () => op(async () => c),
      readValue: () => op(async () => { st.reads++; return new DataView(enc.encode(uuid.endsWith("3-5c3b-4d8e-9f21-0c4a6b8d2e10") ? status() : (st.lastEvent || "{}")).buffer); }),
      notify(text) {
        const bytes = enc.encode(text).slice(0, st.mtu - 3);
        c.value = new DataView(bytes.buffer);
        for (const f of listeners) f({ target: c });
      },
      writeValueWithResponse: (data) => op(async () => {
        const text = new TextDecoder().decode(data);
        if (st.pairFail) throw new Error("Authentication failed");
        st.writes.push(text);
        const m = text.match(/^set (res|quality|segment|maxrec) (\\S+)/);
        if (m) { const k = {res:"res", quality:"q", segment:"seg", maxrec:"maxrec"}[m[1]]; st[k] = m[1] === "res" ? m[2] : Number(m[2]); }
        setTimeout(() => window.__chars.status.notify(status()), 20);   // the glasses send a status after every command
        if (text === "photo") { st.lastEvent = '{"ev":"photo","detail":"/DCIM/HVR_20261011_143012_0042.jpg"}';
          setTimeout(() => window.__chars.event.notify(st.lastEvent), 30); }
      }),
    };
    return c;
  }
  const chars = { cmd: makeChar("7a1e0002-5c3b-4d8e-9f21-0c4a6b8d2e10"), status: makeChar("7a1e0003-5c3b-4d8e-9f21-0c4a6b8d2e10"),
                  event: makeChar("7a1e0004-5c3b-4d8e-9f21-0c4a6b8d2e10") };
  window.__chars = chars;
  const devListeners = [];
  const device = { name: "Hologram Cam", addEventListener: (t, f) => { if (!devListeners.includes(f)) devListeners.push(f); },
    gatt: { connected: false,
      connect: async () => { device.gatt.connected = true; return { getPrimaryService: async () => ({ getCharacteristic: async (u) =>
        Object.values(chars).find(c => c.uuid === u) }) }; },
      disconnect: () => { device.gatt.connected = false; for (const f of devListeners) f(); } } };
  window.__device = device;
  Object.defineProperty(navigator, "bluetooth", { value: { requestDevice: async () => device } });
})();`;

(async () => {
  const browser = await chromium.launch({ args: ['--disable-gpu', '--no-sandbox'] });
  const page = await browser.newPage();
  const errors = [];
  page.on('pageerror', e => errors.push(String(e)));
  await page.addInitScript(MOCK);
  await page.goto('file://' + process.argv[2]);
  const results = {};
  await page.click('#connect');
  await page.waitForTimeout(800);
  results.connectedLog = await page.textContent('#log');
  results.timeWrite = await page.evaluate(() => window.__mock.writes[0]);
  results.expectedLocal = await page.evaluate(() => Math.floor(Date.now() / 1000) - new Date().getTimezoneOffset() * 60);
  // edit settings, then save while status notifications stream in
  await page.selectOption('#res', 'vga');
  await page.fill('#quality', '20');
  await page.fill('#segment', '10');
  await page.fill('#maxrec', '60');
  await page.click('#save');
  await page.waitForTimeout(1500);
  results.settingWrites = await page.evaluate(() => window.__mock.writes.filter(w => w.startsWith('set')));
  results.saveLog = (await page.textContent('#log')).split('\n')[0];
  // photo event cut short by MTU 23 -> read fallback
  await page.click('#photo');
  await page.waitForTimeout(800);
  results.photoLog = (await page.textContent('#log')).split('\n').slice(0, 3);
  results.maxInFlight = await page.evaluate(() => window.__mock.maxInFlight);
  // disconnect / reconnect / disconnect -> one "Disconnected" each
  await page.evaluate(() => window.__device.gatt.disconnect());
  await page.click('#connect');
  await page.waitForTimeout(800);
  await page.evaluate(() => window.__device.gatt.disconnect());
  await page.waitForTimeout(100);
  const log = await page.textContent('#log');
  results.disconnectedCount = (log.match(/Disconnected/g) || []).length;
  // pairing failure
  await page.evaluate(() => { window.__mock.pairFail = true; });
  await page.click('#connect');
  await page.waitForTimeout(800);
  results.pairLog = (await page.textContent('#log')).split('\n').slice(0, 3);
  results.linkText = await page.textContent('#linkText');
  results.stillConnected = await page.evaluate(() => window.__device.gatt.connected);
  results.errors = errors;
  console.log(JSON.stringify(results, null, 1));
  await browser.close();
})();
