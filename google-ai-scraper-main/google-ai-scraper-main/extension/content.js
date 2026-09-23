(() => {
  // Avoid double-run when background.js re-injects after navigation.
  if (window.__googleAiScraperBooted) return;

  function isAiModePage() {
    const params = new URLSearchParams(window.location.search);
    // Legacy AI Mode (udm=50) OR normal SERP with AI Overview / answer content
    if (params.get("udm") === "50") return true;
    if (/\/search/i.test(location.pathname)) return true;
    return Boolean(
      document.querySelector(
        '[data-subtree="aimc"], [data-container-id="main-col"], [data-attrid="ai_overview"], #search, #rso'
      )
    );
  }

  function scheduleBegin() {
    if (isAiModePage()) {
      begin();
      return;
    }
    // Google sometimes lands without udm=50 then enters AI Mode — wait instead of exiting.
    let tries = 0;
    const id = setInterval(() => {
      tries += 1;
      if (isAiModePage()) {
        clearInterval(id);
        begin();
      } else if (tries >= 120) {
        clearInterval(id);
      }
    }, 500);
  }

  function begin() {
    if (window.__googleAiScraperBooted) return;
    window.__googleAiScraperBooted = true;

  // --- Image generation pipeline (separate from text) ---
  if (window.location.hash === "#_img") {
    const IMAGE_MAX_WAIT = 160000; // 160s — image generation takes 1-2 min
    const IMAGE_POLL_INTERVAL = 2000;
    const IMAGE_STABILITY_DELAY = 5000;

    function findGeneratedImages() {
      const imgs = document.querySelectorAll('img[alt="AI generated image"]');
      return Array.from(imgs).filter((img) => img.naturalWidth > 0);
    }

    async function fetchImageAsBase64(img) {
      const resp = await fetch(img.src, { credentials: "include" });
      if (!resp.ok) return null;
      const blob = await resp.blob();
      return new Promise((resolve) => {
        const reader = new FileReader();
        reader.onloadend = () => resolve(reader.result);
        reader.onerror = () => resolve(null);
        reader.readAsDataURL(blob);
      });
    }

    async function extractAndSendImages() {
      let lastCount = 0;
      let stableTimer = null;
      let finished = false;

      const finish = async (imgs) => {
        if (finished) return;
        finished = true;
        clearInterval(pollTimer);
        clearTimeout(maxTimer);
        clearTimeout(stableTimer);
        if (obs) obs.disconnect();

        if (imgs.length === 0) {
          chrome.runtime.sendMessage({
            type: "AI_IMAGE_RESULT",
            data: { images: [], error: "no_generated_image" },
          });
          return;
        }

        const base64Images = [];
        for (const img of imgs) {
          const data = await fetchImageAsBase64(img);
          if (data) base64Images.push(data);
        }

        chrome.runtime.sendMessage({
          type: "AI_IMAGE_RESULT",
          data: {
            images: base64Images,
            error: base64Images.length === 0 ? "image_fetch_failed" : null,
          },
        });
      };

      const attempt = () => {
        if (finished) return;
        const imgs = findGeneratedImages();
        if (imgs.length > 0 && imgs.length !== lastCount) {
          lastCount = imgs.length;
          clearTimeout(stableTimer);
          stableTimer = setTimeout(() => finish(imgs), IMAGE_STABILITY_DELAY);
        } else if (imgs.length > 0 && imgs.length === lastCount) {
          // Same count — stability timer already running
        }
      };

      const obs = new MutationObserver(attempt);
      obs.observe(document.body, {
        childList: true,
        subtree: true,
        attributes: true,
        attributeFilter: ["src"],
      });

      const pollTimer = setInterval(attempt, IMAGE_POLL_INTERVAL);
      const maxTimer = setTimeout(() => {
        const imgs = findGeneratedImages();
        finish(imgs);
      }, IMAGE_MAX_WAIT);

      attempt();
    }

    extractAndSendImages();
    return; // Don't run text extraction
  }

  const EXTRACTION_MAX_WAIT = 60000;
  const EXTRACTION_POLL_INTERVAL = 500;
  // Was 3000, then 7000: measured cases where the AI Overview renders an
  // intro paragraph, pauses while a list section (e.g. named executives) is
  // still being generated server-side, then appends it. A short stability
  // window locks in the incomplete paragraph as "final" before the list
  // ever arrives, even though EXTRACTION_MAX_WAIT (60s) has plenty of
  // budget left. The tell-tale symptom is markdown that ends mid-sentence
  // ("...formats such as firstname.lastname@"). Longer stability delay
  // trades extra seconds per query for materially fewer truncated answers.
  const EXTRACTION_STABILITY_DELAY = 12000;
  const FOLLOW_UP_INPUT_SETTLE_DELAY = 300;
  const SHOW_MORE_MAX_CLICKS = 10;
  const SHOW_MORE_CLICK_COOLDOWN_MS = 700;

  let followUpInProgress = false;
  let showMoreClickCount = 0;
  let lastShowMoreClickAt = 0;

  function controlLabel(el) {
    return `${el.getAttribute("aria-label") || ""} ${el.textContent || ""}`
      .replace(/\s+/g, " ")
      .trim();
  }

  function isVisibleControl(el) {
    if (!el) return false;
    const style = window.getComputedStyle(el);
    if (style.display === "none" || style.visibility === "hidden") return false;
    if (Number(style.opacity || "1") === 0) return false;
    const rect = el.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0;
  }

  function isAiOverviewShowMoreControl(el) {
    if (!el || el.disabled) return false;
    const label = controlLabel(el);
    if (!label) return false;
    // Already expanded / collapse controls
    if (/show\s*less|see\s*less|view\s*less|collapse/i.test(label)) return false;
    if (el.getAttribute("aria-expanded") === "true") return false;
    // Match Google AI Overview expand button (and common variants)
    if (!/show\s*more|see\s*more|view\s*more|view\s*all|see\s*all|read\s*more/i.test(label)) {
      return false;
    }
    // Skip unrelated chrome (follow-up / feedback / share)
    if (
      /follow.?up|ask\s*(a\s*)?question|feedback|share|copy|report/i.test(label)
    ) {
      return false;
    }
    return isVisibleControl(el);
  }

  function findAiOverviewShowMoreButtons(container) {
    if (!container) return [];
    const candidates = container.querySelectorAll(
      'button, [role="button"], a[role="button"], div[role="button"], span[role="button"]'
    );
    return Array.from(candidates).filter(isAiOverviewShowMoreControl);
  }

  /**
   * Expand collapsed AI Overview lists ("Show more") before scraping.
   * Returns: "clicked" | "cooldown" | "maxed" | "done"
   */
  function expandAiOverviewShowMore(container) {
    const now = Date.now();
    if (now - lastShowMoreClickAt < SHOW_MORE_CLICK_COOLDOWN_MS) {
      return "cooldown";
    }
    if (showMoreClickCount >= SHOW_MORE_MAX_CLICKS) {
      return "maxed";
    }

    // Reveal collapsed controls at the bottom of the overview panel.
    try {
      container.scrollIntoView({ block: "center", inline: "nearest" });
      if (typeof container.scrollTop === "number") {
        container.scrollTop = container.scrollHeight;
      }
      window.scrollBy(0, 350);
    } catch {
      // ignore scroll failures
    }

    const buttons = findAiOverviewShowMoreButtons(container);
    if (!buttons.length) return "done";

    const btn = buttons[0];
    try {
      btn.scrollIntoView({ block: "center", inline: "nearest" });
      btn.dispatchEvent(new MouseEvent("mousedown", { bubbles: true }));
      btn.dispatchEvent(new MouseEvent("mouseup", { bubbles: true }));
      btn.click();
      showMoreClickCount += 1;
      lastShowMoreClickAt = now;
      return "clicked";
    } catch {
      return "done";
    }
  }

  function findAIOverviewContainer() {
    // Strategy 1: data attributes (classic AI Overview + AI Mode)
    const byAttr =
      document.querySelector('[data-subtree="aimc"]') ||
      document.querySelector('[data-attrid="ai_overview"]') ||
      document.querySelector('[data-container-id="main-col"]') ||
      document.querySelector('[data-subtree="aim"]');
    if (byAttr) {
      return (
        byAttr.closest('[data-subtree="aimc"]') ||
        byAttr.closest('[data-attrid="ai_overview"]') ||
        byAttr
      );
    }

    // Strategy 2: heading text walk-up (AI Overview OR AI Mode)
    const headings = document.querySelectorAll("h2, h3, [role='heading']");
    for (const h of headings) {
      if (/ai overview|ai mode|key facts/i.test(h.textContent || "")) {
        let node = h.parentElement;
        for (let i = 0; i < 5 && node; i++) {
          if (node.querySelectorAll("p, li, span").length >= 3) return node;
          node = node.parentElement;
        }
        return h.parentElement;
      }
    }

    // Strategy 3: TreeWalker text scan
    const walker = document.createTreeWalker(
      document.body,
      NodeFilter.SHOW_TEXT,
      {
        acceptNode: (n) =>
          /ai overview|ai mode/i.test(n.textContent || "")
            ? NodeFilter.FILTER_ACCEPT
            : NodeFilter.FILTER_REJECT,
      }
    );
    const textNode = walker.nextNode();
    if (textNode) {
      let node = textNode.parentElement;
      for (let i = 0; i < 8 && node; i++) {
        if (node.querySelectorAll("p, li, span").length >= 3) return node;
        node = node.parentElement;
      }
    }

    // Strategy 4: AI Mode answer column — text near "Ask anything" follow-up box
    const askBox = document.querySelector(
      'textarea[placeholder*="Ask" i], div[role="textbox"][contenteditable="true"]'
    );
    if (askBox) {
      let node = askBox.parentElement;
      for (let i = 0; i < 10 && node; i++) {
        const text = (node.innerText || "").trim();
        if (text.length >= 80 && /founded|established|headquarter|company/i.test(text)) {
          return node;
        }
        node = node.parentElement;
      }
    }

    return null;
  }

  function createTurndownService() {
    const td = new TurndownService({
      headingStyle: "atx",
      bulletListMarker: "-",
      codeBlockStyle: "fenced",
    });

    // Custom rule: convert [role="heading"] divs/spans to markdown headings
    td.addRule("roleHeadings", {
      filter: (node) =>
        node.getAttribute && node.getAttribute("role") === "heading",
      replacement: (content) => {
        const text = content.trim();
        if (!text) return "";
        return `\n\n### ${text}\n\n`;
      },
    });

    // Custom rule: skip base64/data images
    td.addRule("skipDataImages", {
      filter: (node) =>
        node.nodeName === "IMG" &&
        (node.getAttribute("src") || "").startsWith("data:"),
      replacement: () => "",
    });

    // Custom rule: clean Google redirect links
    td.addRule("googleLinks", {
      filter: (node) => node.nodeName === "A" && node.getAttribute("href"),
      replacement: (content, node) => {
        let href = node.getAttribute("href") || "";
        // Unwrap Google redirect
        if (href.startsWith("/url?")) {
          try {
            const u = new URL(href, "https://www.google.com");
            href = u.searchParams.get("q") || u.searchParams.get("url") || href;
          } catch {
            // keep as-is
          }
        }
        // Skip internal Google links with no useful href
        if (href.startsWith("/search") || href.startsWith("#")) {
          return content;
        }
        return `[${content}](${href})`;
      },
    });

    return td;
  }

  function extractCitations(container) {
    const links = container.querySelectorAll("a[href]");
    const seen = new Set();
    const citations = [];

    for (const a of links) {
      let href = a.getAttribute("href");
      if (!href) continue;
      // Unwrap Google redirect
      if (href.startsWith("/url?")) {
        try {
          const u = new URL(href, "https://www.google.com");
          href = u.searchParams.get("q") || u.searchParams.get("url") || href;
        } catch {
          continue;
        }
      }
      // Filter out internal/junk links
      if (
        !href ||
        href.startsWith("/") ||
        href.startsWith("#") ||
        href.includes("google.com/search") ||
        href.includes("accounts.google.com") ||
        href.includes("policies.google.com") ||
        href.includes("support.google.com") ||
        href.startsWith("data:") ||
        href.length < 10
      ) {
        continue;
      }
      // Strip Google text fragments for cleaner URLs
      const clean = href.replace(/#:~:text=.*$/, "");
      if (!seen.has(clean)) {
        seen.add(clean);
        citations.push(clean);
      }
    }

    return citations;
  }

  function stripNonContentElements(root) {
    root
      .querySelectorAll(
        'style, script, noscript, template, link[rel="stylesheet"]'
      )
      .forEach((el) => el.remove());
  }

  function extractContent(container) {
    // Use main-col for markdown (AI response only), fall back to full container
    const mainCol = container.querySelector('[data-container-id="main-col"]');
    const contentSource = mainCol || container;
    const clone = contentSource.cloneNode(true);

    stripNonContentElements(clone);

    // Strip UI elements: buttons, SVGs, badges
    clone
      .querySelectorAll('[data-dtype], button, [role="button"], svg')
      .forEach((el) => el.remove());

    // Remove inline source attribution blocks
    clone
      .querySelectorAll('[data-subtree="aimba"]')
      .forEach((el) => el.remove());

    // Remove source card clusters and feedback section from wrapper children
    // Walk the wrapper's direct children to avoid removing parent containers
    const wrapper = clone.querySelector('[data-container-id="main-col"]')
      ? clone.querySelector('[data-container-id="main-col"]').children[0]
      : clone.children[0] || clone;
    const toRemove = [];
    for (const child of wrapper?.children || []) {
      const links = child.querySelectorAll("a").length;
      const imgs = child.querySelectorAll("img").length;
      // Source card clusters: many links + images, little unique text
      if (links > 3 && imgs > 3) {
        toRemove.push(child);
        continue;
      }
      // Feedback/privacy section
      if (child.querySelector('a[href*="policies.google.com"]')) {
        toRemove.push(child);
      }
    }
    toRemove.forEach((el) => el.remove());

    // Remove base64 placeholder images (1x1 transparent GIFs used for math)
    clone.querySelectorAll('img[src^="data:"]').forEach((el) => el.remove());

    // Remove only the first heading (query title), keep section headings
    const firstHeading = clone.querySelector('h2, h3, [role="heading"]');
    if (firstHeading) firstHeading.remove();

    const td = createTurndownService();
    const markdown = td.turndown(clone.innerHTML).trim();
    const citations = extractCitations(container);

    return { markdown, citations };
  }

  function hasMeaningfulMarkdown(markdown) {
    const text = markdown
      .replace(/[`*_#[\]()>-]+/g, " ")
      .replace(/\s+/g, " ")
      .trim();

    if (!text) return false;

    const lower = text.toLowerCase();
    if (
      lower === "loading" ||
      lower === "generating" ||
      lower === "searching" ||
      lower === "thinking"
    ) {
      return false;
    }

    // Do not treat "AIO unavailable" / SERP chrome as a finished answer.
    if (isIncompleteAiOverviewMarkdown(markdown)) {
      return false;
    }

    const alnumLength = text.replace(/[^a-z0-9]/gi, "").length;
    return alnumLength >= 7;
  }

  function hasRealAiAnswerSignal(text) {
    if (!text) return false;
    if (/here are (the )?(official|several|some|well-known)/i.test(text)) {
      return true;
    }
    if (/because (there is|you did) not/i.test(text)) return true;
    if (/founded on [A-Za-z]+ \d{1,2}, \d{4}/i.test(text)) return true;
    if (
      /visit [A-Z][\w .,&-]{2,60}/i.test(text) &&
      /distributor|supplier|manufacturer|wholesale/i.test(text)
    ) {
      return true;
    }

    const cleaned = String(text)
      .replace(/Skip to main content[\s\S]*?(?=AI Overview|Search Results|$)/i, " ")
      .replace(/Accessibility help[\s\S]*?(?=AI Overview|$)/i, " ")
      .replace(/Web results[\s\S]*/i, " ")
      .replace(
        /An AI Overview is not available[\s\S]*?Try again later\.?/gi,
        " "
      )
      .replace(
        /Can[''`\u2019]?t generate an AI overview[\s\S]*?Try again later\.?/gi,
        " "
      )
      .replace(/\b(Thinking|Searching|Generating|Thinking a little longer)\b/gi, " ");
    return cleaned.replace(/[^a-z0-9]/gi, "").length >= 120;
  }

  function isIncompleteAiOverviewMarkdown(markdown) {
    if (!markdown) return true;
    const text = String(markdown);
    const lower = text.toLowerCase();

    const unavailable =
      /ai overview is not available/.test(lower) ||
      /can(?:[''`\u2019]| )?t generate an ai overview/.test(lower);

    if (unavailable && !hasRealAiAnswerSignal(text)) return true;

    if (
      /\b(thinking|searching|generating|thinking a little longer)\b/i.test(text) &&
      !hasRealAiAnswerSignal(text)
    ) {
      return true;
    }

    // Heavy SERP chrome without a real overview answer
    const chromeHits = [
      "skip to main content",
      "accessibility help",
      "choose what you",
      "report inappropriate",
      "advanced search",
    ].filter((s) => lower.includes(s)).length;
    if (chromeHits >= 2 && !hasRealAiAnswerSignal(text)) return true;

    if (endsMidSentence(text)) return true;
    if (promisesRosterButHasNone(text)) return true;

    return false;
  }

  /**
   * True when the answer announces a roster of people ("the leadership team
   * ... are listed below") but contains no role-labelled person name yet.
   *
   * This is the decisive signal for leadership queries, and far more robust
   * than inspecting how the text ends: Google renders the framing sentence
   * (and often a privacy caveat about executive emails) seconds before it
   * appends the actual "CEO: Jane Doe" bullet list. Measured on real
   * captures, every truncated answer of this kind mentioned only the
   * company's own name, never a person's.
   */
  function promisesRosterButHasNone(markdown) {
    if (!markdown) return false;

    // Google splits the answer across many short lines and repeats the
    // company name as a trailing source "chip". Flatten to a single
    // whitespace-normalised string so role/name patterns can match across
    // what are only visual line breaks ("Ryan Windham\nis the\nCEO\nof").
    const text = String(markdown)
      .replace(/\b(?:Shared|\d+\s*files?|Show (?:less|more|all))\b/gi, " ")
      // Citation chips name a source and often a person ("LinkedIn Harsh
      // Vardhan +1"), which would otherwise read as a delivered roster
      // entry and mask a truncated answer.
      .replace(
        /\b(?:LinkedIn|Facebook|Twitter|X|Instagram|YouTube|Blogger\.com|Wikipedia|Crunchbase|Tracxn|ZoomInfo|RocketReach|Bloomberg|Reuters)\b[^\n]{0,60}?(?:\+\d+)?/gi,
        " "
      )
      .replace(/\s+/g, " ")
      .trim();
    if (!text) return false;

    // Only applies to answers that are clearly *about* a leadership roster.
    if (
      !/\b(leadership|executive|management team|founder|ceo|cto|chief|managing director|board of directors)\b/i.test(
        text
      )
    ) {
      return false;
    }

    const HONORIFIC = "(?:Mr\\.?|Ms\\.?|Mrs\\.?|Dr\\.?|Shri|Smt\\.?)?\\s*";
    const PERSON = "[A-Z][a-z]+(?:\\s+[A-Z][a-z'.]+){1,3}";
    const ROLE =
      "(?:MD|CEO|CTO|CIO|CMO|COO|chief[a-z ]*officer|managing director|country head|co-?founder|founder|president|chairman|head of [a-z& ]+)";

    // A delivered roster labels roles, e.g. "CEO: Jane Doe",
    // "Founder - Jane Doe", "Chief Technology Officer (CTO): Jane Doe".
    if (
      new RegExp(`\\b${ROLE}\\b[^:–-]{0,40}[:–-]\\s*${HONORIFIC}${PERSON}`, "i").test(text)
    ) {
      return false;
    }

    // Or the reverse order: "Jane Doe is the Chief Executive Officer of X".
    if (
      new RegExp(
        `\\b${PERSON}\\b.{0,40}?\\b(?:is|serves as|was appointed|holds the (?:role|position))\\b.{0,60}?\\b${ROLE}\\b`,
        "i"
      ).test(text)
    ) {
      return false;
    }

    // Or run together with no separator at all, as in "...include Founder
    // and Chairman Anil Jagasia, MD/CEO Jayant Goradia, CTO Devang Pandya".
    if (new RegExp(`\\b${ROLE}\\b[a-z/& ]{0,24}\\s${HONORIFIC}${PERSON}`, "i").test(text)) {
      return false;
    }

    // "The Managing Director (MD) of AdaniConneX is Anil Kumar Sardana" —
    // role first, company in between, then the name.
    if (
      new RegExp(`\\b${ROLE}\\b.{0,60}?\\bis\\b\\s+${HONORIFIC}${PERSON}`, "i").test(text)
    ) {
      return false;
    }

    // "Shreyaans Jain (Co-Founder & CEO)" — name with the role bracketed.
    if (new RegExp(`\\b${PERSON}\\s*\\([^)]{0,40}?${ROLE}`, "i").test(text)) {
      return false;
    }

    // Mentions a roster, but no role-labelled name arrived — still loading.
    return true;
  }

  /**
   * True when the answer stops mid-thought, which means Google is still
   * streaming it in and a fixed stability timer would capture a partial
   * answer. Observed repeatedly on leadership queries, where the panel
   * renders "...standard corporate email formats (such as
   * firstname.lastname@example.com" and only appends the actual list of
   * named executives a few seconds later.
   */
  function endsMidSentence(markdown, subject) {
    if (!markdown) return false;
    // Ignore trailing SERP chrome the extractor commonly appends, so the
    // real end of the answer is what gets inspected.
    let body = String(markdown)
      .replace(/(?:\s*(?:Shared|\d+\s*files?|Show (?:less|more|all))\s*)+$/gi, "")
      .trim();
    // Google also echoes the subject as a trailing source "chip" (a bare
    // repeat of the company name on its own line). Strip a trailing line
    // that merely repeats a line seen earlier, so the real sentence end is
    // what gets inspected.
    const lines = body.split("\n").map((l) => l.trim()).filter(Boolean);
    while (
      lines.length > 1 &&
      lines.slice(0, -1).some(
        (l) => l.toLowerCase() === lines[lines.length - 1].toLowerCase()
      )
    ) {
      lines.pop();
    }
    if (subject) {
      const subj = String(subject).trim().toLowerCase();
      while (
        lines.length > 1 &&
        subj &&
        lines[lines.length - 1].toLowerCase() === subj
      ) {
        lines.pop();
      }
    }
    body = lines.join("\n").trim();
    if (!body) return false;

    // An unclosed "(" anywhere means the sentence that opened it never
    // finished — the strongest signal in practice, because the truncation
    // reliably lands inside a parenthetical ("...formats (such as
    // firstname.lastname@example.com" with no closing paren).
    const opens = (body.match(/\(/g) || []).length;
    const closes = (body.match(/\)/g) || []).length;
    if (opens > closes) return true;

    // A dangling email prefix or trailing conjunction likewise means more
    // text is still coming.
    if (/@$/.test(body)) return true;
    if (/\b(such as|including|are|is|and|or|the|of|for|to|by|with)$/i.test(body)) {
      return true;
    }

    // A lead-in that promises content it never delivered ("...are detailed
    // below", "...is as follows:") means the list itself is still
    // streaming. Only treat it as truncated while the answer is still
    // short — a long answer ending on such a phrase has already delivered
    // its substance.
    // Trailing source chips are short Title Case fragments Google appends
    // after the prose (e.g. "Unilever Global", "LinkedIn India"). Drop them
    // so the lead-in phrase they hide becomes the visible ending.
    let tail = body;
    for (let i = 0; i < 4; i++) {
      const stripped = tail.replace(
        /\n[A-Z][A-Za-z0-9.&'-]*(?:\s+[A-Z][A-Za-z0-9.&'-]*){0,3}\s*$/,
        ""
      );
      if (stripped === tail) break;
      tail = stripped.trim();
    }

    const LEAD_IN =
      /\b(as follows|the following(?: individuals| people| executives| leaders| members)?|detailed below|listed below|outlined below|provided below|described below|are below|shown below|summarized below|compiled below|structured below|include the following)\b[\s.,-]*$/i;

    // A lead-in that ends on a COLON is a promise of a list that has not
    // arrived, at any length: "The primary leaders ... are detailed below:"
    // is 525 chars of preamble followed by nothing. Length is irrelevant
    // here — the colon is the tell.
    if (/:$/.test(tail) && (LEAD_IN.test(tail.replace(/:\s*$/, "")) || tail.length < 250)) {
      return true;
    }

    // Without the colon, only treat a trailing lead-in as truncation while
    // the answer is short, so a long answer that merely happens to end on
    // "...are listed below" is left alone.
    if (tail.length < 250 && LEAD_IN.test(tail)) {
      return true;
    }

    return false;
  }

  function finalizeExtractionResult(markdown, citations, emptyError) {
    const cleanMarkdown = markdown.trim();
    if (!hasMeaningfulMarkdown(cleanMarkdown) && citations.length === 0) {
      return { markdown: "", citations: [], error: emptyError };
    }
    return { markdown: cleanMarkdown, citations, error: null };
  }

  function extractionSignature(markdown, citations) {
    return `${markdown.trim()}\n---\n${citations.join("\n")}`;
  }

  function sendResult(data) {
    chrome.runtime.sendMessage({
      type: "AI_OVERVIEW_RESULT",
      data,
    });
    // Belt-and-suspenders: post straight to local server (bypass background handoff).
    try {
      const m = (location.hash || "").match(/gasqid=([a-f0-9]+)/i);
      if (m) {
        fetch(`http://127.0.0.1:15551/result/${m[1]}`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            markdown: data.markdown || "",
            citations: data.citations || [],
            error: data.error || null,
          }),
        }).catch(() => {});
        fetch(`http://localhost:15551/result/${m[1]}`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            markdown: data.markdown || "",
            citations: data.citations || [],
            error: data.error || null,
          }),
        }).catch(() => {});
      }
    } catch {
      // ignore
    }
  }

  function isTerminalExtractionError(error) {
    return Boolean(
      error &&
      !error.startsWith("empty_") &&
      !error.startsWith("no_ai_overview")
    );
  }

  function buildQuotaExhaustedResult(query = "") {
    return {
      markdown: "",
      citations: [],
      error: "quota_exhausted_pro",
      _query: query,
    };
  }

  const QUOTA_EXHAUSTION_PATTERNS = [
    /\byou(?:['`\u2019]ve| have)\s+reached\s+(?:your\s+)?(?:daily\s+)?(?:usage\s+)?limit\b/i,
    /\b(?:daily\s+)?(?:usage\s+)?limit\s+(?:has\s+been\s+)?reached\b/i,
  ];

  function waitForExtraction(
    extractFn,
    onDone,
    fallbackError,
    maxWait = EXTRACTION_MAX_WAIT
  ) {
    let pollTimer = null;
    let maxTimer = null;
    let stableTimer = null;
    let obs = null;
    let finished = false;
    let lastResult = { markdown: "", citations: [], error: fallbackError };
    let lastMeaningfulSignature = null;

    function finish(result) {
      if (finished) return;
      finished = true;
      if (obs) obs.disconnect();
      clearInterval(pollTimer);
       clearTimeout(stableTimer);
      clearTimeout(maxTimer);
      onDone(result);
    }

    function attempt() {
      if (finished) return;
      try {
        const result = extractFn();
        if (!result) return;
        lastResult = result;

        if (isTerminalExtractionError(result.error)) {
          finish(result);
          return;
        }

        if (result.markdown.trim() || result.citations.length > 0) {
          const signature = extractionSignature(
            result.markdown,
            result.citations
          );
          if (signature !== lastMeaningfulSignature) {
            lastMeaningfulSignature = signature;
            clearTimeout(stableTimer);
            stableTimer = setTimeout(
              () => finish(result),
              EXTRACTION_STABILITY_DELAY
            );
          }
        } else {
          lastMeaningfulSignature = null;
          clearTimeout(stableTimer);
        }
      } catch (err) {
        finish({
          markdown: "",
          citations: [],
          error: `extraction_error: ${err.message}`,
        });
      }
    }

    obs = new MutationObserver(() => {
      attempt();
    });

    obs.observe(document.body, {
      childList: true,
      subtree: true,
      characterData: true,
    });

    pollTimer = setInterval(attempt, EXTRACTION_POLL_INTERVAL);
    maxTimer = setTimeout(() => finish(lastResult), maxWait);
    attempt();
  }

  function detectQuotaExhaustion(container) {
    if (!container) return false;
    const text = container.textContent || "";
    return QUOTA_EXHAUSTION_PATTERNS.some((pattern) => pattern.test(text));
  }

  function tryExtractInitialOverview() {
    const container = findAIOverviewContainer();
    if (!container) {
      if (detectQuotaExhaustion(document.body)) {
        const q = new URLSearchParams(window.location.search).get("q") || "";
        return buildQuotaExhaustedResult(q);
      }
      return null;
    }

    if (detectQuotaExhaustion(container)) {
      const q = new URLSearchParams(window.location.search).get("q") || "";
      return buildQuotaExhaustedResult(q);
    }

    // Keep waiting while Google shows Thinking / "AIO not available" flash.
    const pendingText = `${container.innerText || ""} ${document.body?.innerText || ""}`;
    if (isIncompleteAiOverviewMarkdown(pendingText) && !hasRealAiAnswerSignal(pendingText)) {
      return null;
    }

    // Expand collapsed company lists before capturing markdown.
    const expandState = expandAiOverviewShowMore(container);
    if (expandState === "clicked" || expandState === "cooldown") {
      return null;
    }
    if (
      expandState !== "maxed" &&
      findAiOverviewShowMoreButtons(container).length > 0
    ) {
      return null;
    }

    const { markdown, citations } = extractContent(container);
    if (isIncompleteAiOverviewMarkdown(markdown)) {
      return null;
    }
    return finalizeExtractionResult(
      markdown,
      citations,
      "empty_ai_overview_extraction"
    );
  }

  function extractFollowUpSnapshot() {
    const allMainCols = document.querySelectorAll(
      '[data-container-id="main-col"]'
    );
    if (allMainCols.length === 0) {
      return { markdown: "", citations: [] };
    }

    const lastMainCol = allMainCols[allMainCols.length - 1];
    const lastAimcContainer =
      lastMainCol.closest('[data-subtree="aimc"]') || findAIOverviewContainer();
    if (!lastAimcContainer) {
      return { markdown: "", citations: [] };
    }

    return extractContent(lastAimcContainer);
  }

  function tryExtractFollowUp(prevMainColCount, prevSignature, query) {
    const allMainCols = document.querySelectorAll(
      '[data-container-id="main-col"]'
    );

    if (allMainCols.length === 0) {
      const container = findAIOverviewContainer() || document.body;
      if (detectQuotaExhaustion(container)) {
        return buildQuotaExhaustedResult(query);
      }
      return null;
    }

    if (allMainCols.length > prevMainColCount) {
      // New main-col appeared — extract only from it
      const newMainCol = allMainCols[allMainCols.length - 1];
      const newAimc =
        newMainCol.closest('[data-subtree="aimc"]') || findAIOverviewContainer();
      if (detectQuotaExhaustion(newAimc || newMainCol)) {
        return buildQuotaExhaustedResult(query);
      }

      const expandState = expandAiOverviewShowMore(newAimc || newMainCol);
      if (expandState === "clicked" || expandState === "cooldown") {
        return null;
      }

      const tempContainer = newMainCol.cloneNode(true);

      stripNonContentElements(tempContainer);

      // Apply same cleanup as extractContent
      tempContainer
        .querySelectorAll(
          '[data-dtype], button, [role="button"], svg, [data-subtree="aimba"]'
        )
        .forEach((el) => el.remove());
      tempContainer
        .querySelectorAll('img[src^="data:"]')
        .forEach((el) => el.remove());

      // Remove source card clusters and feedback from wrapper children
      const wrapper = tempContainer.children[0] || tempContainer;
      const toRemove = [];
      for (const child of wrapper?.children || []) {
        const links = child.querySelectorAll("a").length;
        const imgs = child.querySelectorAll("img").length;
        if (links > 3 && imgs > 3) {
          toRemove.push(child);
          continue;
        }
        if (child.querySelector('a[href*="policies.google.com"]')) {
          toRemove.push(child);
        }
      }
      toRemove.forEach((el) => el.remove());

      // Remove first heading (follow-up question echo)
      const firstH = tempContainer.querySelector(
        'h2, h3, [role="heading"]'
      );
      if (firstH) firstH.remove();

      const td = createTurndownService();
      const markdown = td.turndown(tempContainer.innerHTML).trim();
      const allAimcs = document.querySelectorAll('[data-subtree="aimc"]');
      const lastAimc = allAimcs[allAimcs.length - 1];
      const citations = extractCitations(lastAimc || document.body);
      return finalizeExtractionResult(
        markdown,
        citations,
        "empty_follow_up_extraction"
      );
    }

    const currentAimc =
      allMainCols[allMainCols.length - 1]?.closest('[data-subtree="aimc"]') ||
      findAIOverviewContainer();
    if (detectQuotaExhaustion(currentAimc || document.body)) {
      return buildQuotaExhaustedResult(query);
    }

    const expandState = expandAiOverviewShowMore(currentAimc);
    if (expandState === "clicked" || expandState === "cooldown") {
      return null;
    }

    const { markdown, citations } = extractFollowUpSnapshot();
    if (extractionSignature(markdown, citations) === prevSignature) {
      return null;
    }

    return finalizeExtractionResult(
      markdown,
      citations,
      "empty_follow_up_extraction"
    );
  }

  // --- Initial scrape ---
  waitForExtraction(
    tryExtractInitialOverview,
    (result) => sendResult(result),
    "no_ai_overview"
  );

  // --- Follow-up query handler ---
  chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    if (message.type !== "FOLLOW_UP_QUERY") return;

    if (followUpInProgress) {
      sendResponse({ received: false, error: "follow_up_in_progress" });
      // Also send result so background.js can notify server immediately
      chrome.runtime.sendMessage({
        type: "AI_OVERVIEW_RESULT",
        data: { markdown: "", citations: [], error: "follow_up_in_progress" },
      });
      return;
    }

    followUpInProgress = true;
    showMoreClickCount = 0;
    lastShowMoreClickAt = 0;
    handleFollowUp(message.query, message.queryId);
    sendResponse({ received: true });
  });

  async function handleFollowUp(query, queryId) {
    try {
      // 1. Find the follow-up input (textarea or contenteditable div)
      let textbox = findFollowUpInput();

      // If not visible, try clicking an expand/show-more button
      if (!textbox) {
        const buttons = document.querySelectorAll(
          'button, [role="button"], [tabindex="0"]'
        );
        for (const btn of buttons) {
          if (
            /follow.?up|ask.+question|show\s*more|ask\s*a/i.test(
              btn.textContent
            )
          ) {
            btn.click();
            await new Promise((r) => setTimeout(r, 1000));
            textbox = findFollowUpInput();
            break;
          }
        }
      }

      if (!textbox) {
        chrome.runtime.sendMessage({
          type: "AI_OVERVIEW_RESULT",
          data: {
            markdown: "",
            citations: [],
            error: "follow_up_textbox_not_found",
          },
        });
        return;
      }

      // 2. Snapshot current main-col count and latest extracted content so we
      // can tell when Google has actually rendered a new answer.
      // Follow-ups may create a new aimc container (not just a new main-col
      // within the same container), so we search document-wide.
      const prevMainColCount = document.querySelectorAll(
        '[data-container-id="main-col"]'
      ).length;
      const prevSnapshot = extractFollowUpSnapshot();
      const prevSignature = extractionSignature(
        prevSnapshot.markdown,
        prevSnapshot.citations
      );

      // 3. Type query into input
      textbox.focus();
      if (textbox.tagName === "TEXTAREA" || textbox.tagName === "INPUT") {
        // Native input: set value and fire input event
        const nativeSetter = Object.getOwnPropertyDescriptor(
          window.HTMLTextAreaElement.prototype, "value"
        )?.set || Object.getOwnPropertyDescriptor(
          window.HTMLInputElement.prototype, "value"
        )?.set;
        if (nativeSetter) {
          nativeSetter.call(textbox, query);
        } else {
          textbox.value = query;
        }
        textbox.dispatchEvent(new Event("input", { bubbles: true }));
        textbox.dispatchEvent(new Event("change", { bubbles: true }));
      } else {
        // Contenteditable div
        textbox.innerHTML = "";
        document.execCommand("insertText", false, query);
      }

      // Small delay for UI to react (e.g. show submit button)
      await new Promise((r) => setTimeout(r, FOLLOW_UP_INPUT_SETTLE_DELAY));

      // 4. Submit: find nearby submit button or press Enter
      const submitted = await submitFollowUp(textbox);
      if (!submitted) {
        chrome.runtime.sendMessage({
          type: "AI_OVERVIEW_RESULT",
          data: {
            markdown: "",
            citations: [],
            error: "follow_up_submit_failed",
          },
        });
        return;
      }

      // 5. Wait until the newly rendered follow-up is actually extractable.
      waitForExtraction(
        () => tryExtractFollowUp(prevMainColCount, prevSignature, query),
        (result) => {
          sendResult(result);
          followUpInProgress = false;
        },
        "no_ai_overview_after_follow_up"
      );
    } catch (err) {
      chrome.runtime.sendMessage({
        type: "AI_OVERVIEW_RESULT",
        data: {
          markdown: "",
          citations: [],
          error: `follow_up_error: ${err.message}`,
        },
      });
      followUpInProgress = false;
    }
  }

  function findFollowUpInput() {
    // Strategy 1: textarea with relevant placeholder/label
    const textarea = document.querySelector(
      'textarea[placeholder*="Ask" i], textarea[aria-label*="Ask" i], textarea[placeholder*="follow" i]'
    );
    if (textarea && textarea.offsetParent !== null) return textarea;

    // Strategy 2: contenteditable div with textbox role
    const contentEditable = document.querySelector(
      'div[role="textbox"][contenteditable="true"]'
    );
    if (contentEditable && contentEditable.offsetParent !== null)
      return contentEditable;

    // Strategy 3: any visible textarea inside the AI overview area
    const container = findAIOverviewContainer();
    if (container) {
      const ta = container.querySelector("textarea");
      if (ta && ta.offsetParent !== null) return ta;
    }

    return null;
  }

  async function submitFollowUp(textbox) {
    // Strategy 1: find a Send/Submit button nearby (walk up a few levels)
    let parent = textbox.parentElement;
    for (let i = 0; i < 5 && parent; i++) {
      const sendBtn = parent.querySelector(
        'button[aria-label*="Send" i], button[aria-label*="Submit" i], button[type="submit"]'
      );
      if (sendBtn) {
        sendBtn.click();
        return true;
      }
      parent = parent.parentElement;
    }

    // Strategy 2: find a form and submit it
    const form = textbox.closest("form");
    if (form) {
      const formBtn = form.querySelector("button");
      if (formBtn) {
        formBtn.click();
        return true;
      }
    }

    // Strategy 3: look for any nearby button with SVG icon (common submit pattern)
    parent = textbox.parentElement?.parentElement?.parentElement;
    if (parent) {
      const buttons = parent.querySelectorAll("button");
      for (const btn of buttons) {
        if (/cancel|close|clear/i.test(btn.textContent)) continue;
        if (btn.querySelector("svg") || btn.textContent.trim() === "") {
          btn.click();
          return true;
        }
      }
    }

    // Strategy 4: dispatch Enter key
    textbox.dispatchEvent(
      new KeyboardEvent("keydown", {
        key: "Enter",
        code: "Enter",
        keyCode: 13,
        which: 13,
        bubbles: true,
      })
    );
    return true;
  }

  } // end begin()

  scheduleBegin();
})();
