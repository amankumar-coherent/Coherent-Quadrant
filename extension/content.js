/**
 * Reads the AI Overview block out of a Google results page.
 *
 * Google ships obfuscated, frequently-rotated class names, so nothing here may
 * depend on a single selector. The extractor tries increasingly generic
 * strategies and reports which one worked, so when Google changes the markup the
 * logs say *how* it changed rather than just going quiet.
 */

const OVERVIEW_LABEL = /^\s*ai overview\s*$/i;
const MISSING_TEXT =
  /(ai overview is not available|can'?t generate an ai overview|unable to generate an ai overview|no ai overview)/i;

/** SERP furniture that must never end up in evidence. */
const CHROME_LINE =
  /^(skip to|accessibility|sign in|google apps|search results|ai mode|all|images|videos|news|shopping|forums|more|web results|people also ask|short videos|show all|show more|tools|about \d|filter|settings|privacy|terms|feedback|dive deeper in ai mode)\b/i;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/** Strategy 1 — attributes Google has used for the overview subtree. */
function byKnownSelectors() {
  const selectors = [
    'div[data-subtree="aio"]',
    'div[data-attrid="SGE"]',
    "#m-x-content",
    'div[data-mcpr="aio"]',
    'div[aria-label="AI Overview"]',
    '[data-async-context*="ai_overview"]',
  ];
  for (const sel of selectors) {
    const el = document.querySelector(sel);
    if (el && el.innerText.trim().length > 80) return { el, how: `selector:${sel}` };
  }
  return null;
}

/**
 * Strategy 2 — find the literal "AI Overview" heading and climb to the ancestor
 * that actually holds the prose. Climbing is bounded: past ~6 levels you start
 * swallowing the whole results column.
 */
function byHeadingLabel() {
  const nodes = document.querySelectorAll("h1, h2, h3, div[role='heading'], span");
  for (const node of nodes) {
    if (!OVERVIEW_LABEL.test(node.textContent || "")) continue;
    let cur = node;
    for (let hops = 0; hops < 6 && cur.parentElement; hops++) {
      cur = cur.parentElement;
      const text = (cur.innerText || "").trim();
      if (text.length > 200) return { el: cur, how: `heading+${hops}` };
    }
  }
  return null;
}

/** Strategy 3 — the largest text block above the first organic result. */
function byFirstBlock() {
  const main = document.querySelector("#rcnt, #center_col, #search");
  if (!main) return null;
  const firstResult = main.querySelector("div.g, div[data-hveid] a h3");
  let best = null;
  for (const div of main.querySelectorAll("div")) {
    if (firstResult && !(div.compareDocumentPosition(firstResult) & Node.DOCUMENT_POSITION_FOLLOWING)) {
      continue; // sits below the first organic hit — not the overview
    }
    const text = (div.innerText || "").trim();
    if (text.length < 200 || text.length > 12000) continue;
    if (!best || text.length < best.text.length) best = { el: div, text }; // tightest wrapper wins
  }
  return best ? { el: best.el, how: "first-block" } : null;
}

function findOverview() {
  return byKnownSelectors() || byHeadingLabel() || byFirstBlock();
}

/** Expand the overview so the collapsed tail is in the DOM before reading it. */
async function expand() {
  const labels = /^(show more|more|expand|show all)$/i;
  for (const btn of document.querySelectorAll("div[role='button'], button, a[role='button']")) {
    const text = (btn.innerText || "").trim();
    if (!labels.test(text)) continue;
    try {
      btn.click();
      await sleep(700);
      return true;
    } catch {
      /* a non-interactive match — keep looking */
    }
  }
  return false;
}

function cleanText(raw) {
  const lines = [];
  for (const line of (raw || "").split("\n")) {
    const s = line.trim();
    if (!s) {
      if (lines.length && lines[lines.length - 1]) lines.push("");
      continue;
    }
    if (CHROME_LINE.test(s)) continue;
    if (/^(ai overview|ai mode|pro|read more|show more)$/i.test(s)) continue;
    lines.push(s);
  }
  return lines.join("\n").replace(/\n{3,}/g, "\n\n").trim();
}

/** Citations are the links inside the overview, minus Google's own chrome. */
function collectCitations(el) {
  const out = [];
  const seen = new Set();
  for (const a of el.querySelectorAll("a[href]")) {
    const url = a.href || "";
    if (!/^https?:\/\//i.test(url)) continue;
    if (/^https?:\/\/(www\.)?google\.com/i.test(url)) continue;
    if (url.includes("/search?") || url.startsWith("https://www.google.com/url?")) continue;
    if (seen.has(url)) continue;
    seen.add(url);
    out.push({ title: (a.innerText || "").trim().slice(0, 200), url });
    if (out.length >= 40) break;
  }
  return out;
}

/**
 * Google streams the overview in. Poll until the text stops growing rather than
 * sleeping a fixed amount — a slow answer would otherwise be captured half-written.
 */
async function waitForOverview(timeoutMs = 12000) {
  const deadline = Date.now() + timeoutMs;
  let last = "";
  let stableFor = 0;
  while (Date.now() < deadline) {
    const found = findOverview();
    const text = found ? (found.el.innerText || "").trim() : "";
    if (text && text === last) {
      stableFor += 400;
      if (stableFor >= 1200) return found; // unchanged across three polls
    } else {
      stableFor = 0;
      last = text;
    }
    await sleep(400);
  }
  return findOverview();
}

async function scrape() {
  if (MISSING_TEXT.test(document.body.innerText || "")) {
    return { markdown: "", citations: [], ai_overview_missing: true, how: "explicit-missing" };
  }
  await waitForOverview();
  await expand();
  const found = await waitForOverview(4000);
  if (!found) {
    return { markdown: "", citations: [], ai_overview_missing: true, how: "not-found" };
  }
  const markdown = cleanText(found.el.innerText || "");
  return {
    markdown,
    citations: collectCitations(found.el),
    ai_overview_missing: markdown.length < 40,
    how: found.how,
  };
}

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg?.type !== "SCRAPE_AI_OVERVIEW") return false;
  scrape()
    .then(sendResponse)
    .catch((err) =>
      sendResponse({ markdown: "", citations: [], ai_overview_missing: true, error: String(err) })
    );
  return true; // async sendResponse
});
