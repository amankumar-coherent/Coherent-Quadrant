/**
 * Drains the bridge's pending queue using a small pool of tabs.
 *
 * Serial draining was safe but slow: ~6s per question meant a 122-question
 * ownership sweep took a quarter of an hour. A worker pool of N tabs cuts that
 * by roughly N while keeping each individual tab paced — the thing that degrades
 * AI Overview rendering is hammering Google from one tab in a tight loop, not
 * having a few tabs open, which is ordinary browsing behaviour.
 *
 * Each worker owns exactly one tab for its whole life and pulls from a shared
 * in-memory work list, so a slow question blocks only its own worker.
 *
 * A heartbeat goes to the bridge every 10s. Without it, "the extension is
 * running but every scrape is failing" and "the extension is not running at all"
 * are indistinguishable from the server side — which cost real debugging time.
 */

const DEFAULTS = {
  bridge: "http://127.0.0.1:15552",
  market: "",
  batch: 40,
  tabs: 4, // parallel workers; each owns one tab
  minDelayMs: 2500, // per worker, between its own questions
  maxDelayMs: 6000,
  idlePollMs: 15000,
  heartbeatMs: 10000,
};

let running = false;
let workerTabs = [];
const stats = { answered: 0, missing: 0, failed: 0, startedAt: 0, last: "", tabs: 0 };

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const jitter = (lo, hi) => lo + Math.random() * (hi - lo);

async function config() {
  const saved = await chrome.storage.local.get(Object.keys(DEFAULTS));
  const cfg = { ...DEFAULTS, ...saved };
  cfg.tabs = Math.max(1, Math.min(8, Number(cfg.tabs) || DEFAULTS.tabs));
  return cfg;
}

async function setBadge(text, color = "#0057a8") {
  try {
    await chrome.action.setBadgeText({ text });
    await chrome.action.setBadgeBackgroundColor({ color });
  } catch {
    /* cosmetic */
  }
}

async function fetchPending(cfg) {
  const url = new URL("/pending", cfg.bridge);
  url.searchParams.set("limit", String(cfg.batch));
  if (cfg.market) url.searchParams.set("market", cfg.market);
  const res = await fetch(url, { cache: "no-store" });
  if (!res.ok) throw new Error(`bridge /pending ${res.status}`);
  return (await res.json()).questions || [];
}

async function postAnswer(cfg, body) {
  const res = await fetch(new URL("/answers", cfg.bridge), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`bridge /answers ${res.status}`);
  return res.json();
}

async function beat(cfg) {
  try {
    await fetch(new URL("/heartbeat", cfg.bridge), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ running, ...stats }),
    });
  } catch {
    /* the bridge being down is already visible elsewhere */
  }
}

async function newTab() {
  const tab = await chrome.tabs.create({ url: "about:blank", active: false });
  return tab.id;
}

async function ensureTab(id) {
  if (id !== null && id !== undefined) {
    try {
      await chrome.tabs.get(id);
      return id;
    } catch {
      /* user closed it */
    }
  }
  return newTab();
}

function waitForLoad(tabId, timeoutMs = 30000) {
  return new Promise((resolve) => {
    const timer = setTimeout(finish, timeoutMs);
    function onUpdated(id, info) {
      if (id === tabId && info.status === "complete") finish();
    }
    function finish() {
      clearTimeout(timer);
      chrome.tabs.onUpdated.removeListener(onUpdated);
      resolve();
    }
    chrome.tabs.onUpdated.addListener(onUpdated);
  });
}

async function askOne(cfg, tabId, question) {
  const url = `https://www.google.com/search?q=${encodeURIComponent(question.text)}&hl=en`;
  await chrome.tabs.update(tabId, { url });
  await waitForLoad(tabId);
  await sleep(1200); // let the overview start streaming

  let result;
  try {
    result = await chrome.tabs.sendMessage(tabId, { type: "SCRAPE_AI_OVERVIEW" });
  } catch {
    // Consent interstitial or a redirect killed the content script — inject and retry.
    try {
      await chrome.scripting.executeScript({ target: { tabId }, files: ["content.js"] });
      result = await chrome.tabs.sendMessage(tabId, { type: "SCRAPE_AI_OVERVIEW" });
    } catch (err2) {
      throw new Error(`content script unreachable: ${err2.message || err2}`);
    }
  }

  await postAnswer(cfg, {
    question: question.text,
    key: question.key || "",
    market: question.market || cfg.market || "",
    markdown: result?.markdown || "",
    citations: result?.citations || [],
    ai_overview_missing: Boolean(result?.ai_overview_missing),
    error: result?.error || "",
    source: "chrome",
  });
  return result;
}

/** One worker: owns a tab, pulls from the shared list until it is empty. */
async function worker(cfg, work, index) {
  let tabId = await newTab();
  workerTabs[index] = tabId;
  while (running) {
    const question = work.shift();
    if (!question) return;
    try {
      tabId = await ensureTab(tabId);
      workerTabs[index] = tabId;
      const res = await askOne(cfg, tabId, question);
      if (res?.ai_overview_missing) {
        stats.missing++;
        stats.last = `no overview: ${question.text.slice(0, 56)}`;
      } else {
        stats.answered++;
        stats.last = `ok: ${question.text.slice(0, 56)}`;
      }
    } catch (err) {
      stats.failed++;
      stats.last = `failed: ${String(err.message || err).slice(0, 90)}`;
    }
    await setBadge(String(work.length));
    if (running) await sleep(jitter(cfg.minDelayMs, cfg.maxDelayMs));
  }
}

async function closeTabs() {
  for (const id of workerTabs) {
    if (id === null || id === undefined) continue;
    try {
      await chrome.tabs.remove(id);
    } catch {
      /* already gone */
    }
  }
  workerTabs = [];
}

async function loop() {
  const cfg = await config();
  stats.startedAt = Date.now();
  stats.tabs = cfg.tabs;
  const hb = setInterval(() => beat(cfg), cfg.heartbeatMs);
  await beat(cfg);

  try {
    while (running) {
      let queue = [];
      try {
        queue = await fetchPending(cfg);
      } catch (err) {
        stats.last = `bridge unreachable: ${err.message}`;
        await setBadge("!", "#9b2c2c");
        await sleep(cfg.idlePollMs);
        continue;
      }

      if (!queue.length) {
        stats.last = "queue empty — waiting for the pipeline to enqueue more";
        await setBadge("0", "#3f9b50");
        await closeTabs();
        await sleep(cfg.idlePollMs);
        continue;
      }

      const work = queue.slice();
      workerTabs = new Array(cfg.tabs).fill(null);
      await Promise.all(
        Array.from({ length: Math.min(cfg.tabs, work.length) }, (_, i) => worker(cfg, work, i))
      );
      await closeTabs();
    }
  } finally {
    clearInterval(hb);
    await beat(cfg);
    await setBadge("");
    await closeTabs();
  }
}

function startLoop() {
  if (running) return false;
  running = true;
  Object.assign(stats, { answered: 0, missing: 0, failed: 0, last: "starting…" });
  loop().catch((err) => {
    running = false;
    stats.last = `loop crashed: ${err.message || err}`;
  });
  return true;
}

/**
 * Auto-start when launched via `chrome --load-extension=...`, where there is no
 * one to click Start. A stored autostart:false (set by Stop) keeps it stopped.
 */
function maybeAutostart() {
  chrome.storage.local.get(["autostart"], ({ autostart }) => {
    if (autostart !== false) startLoop();
  });
}
chrome.runtime.onInstalled.addListener(maybeAutostart);
chrome.runtime.onStartup.addListener(maybeAutostart);
maybeAutostart(); // also cover a service-worker restart mid-session

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg?.type === "START") {
    chrome.storage.local.set({ autostart: true });
    startLoop();
    sendResponse({ running });
    return false;
  }
  if (msg?.type === "STOP") {
    running = false;
    chrome.storage.local.set({ autostart: false });
    stats.last = "stopped";
    sendResponse({ running });
    return false;
  }
  if (msg?.type === "STATUS") {
    sendResponse({ running, ...stats });
    return false;
  }
  return false;
});
