const $ = (id) => document.getElementById(id);

async function loadSettings() {
  const { bridge = "http://127.0.0.1:15552", market = "" } = await chrome.storage.local.get([
    "bridge",
    "market",
  ]);
  $("bridge").value = bridge;
  $("market").value = market;
}

function persist() {
  chrome.storage.local.set({
    bridge: $("bridge").value.trim() || "http://127.0.0.1:15552",
    market: $("market").value.trim(),
  });
}

function render(s) {
  $("answered").textContent = s.answered ?? 0;
  $("missing").textContent = s.missing ?? 0;
  $("failed").textContent = s.failed ?? 0;
  $("last").innerHTML =
    `<span class="dot ${s.running ? "on" : "off"}"></span>` +
    (s.last || (s.running ? "running…" : "idle"));
  $("start").disabled = Boolean(s.running);
  $("stop").disabled = !s.running;
}

function poll() {
  chrome.runtime.sendMessage({ type: "STATUS" }, (s) => {
    if (!chrome.runtime.lastError && s) render(s);
  });
}

$("start").addEventListener("click", () => {
  persist();
  chrome.runtime.sendMessage({ type: "START" }, poll);
});

$("stop").addEventListener("click", () => {
  chrome.runtime.sendMessage({ type: "STOP" }, poll);
});

$("bridge").addEventListener("change", persist);
$("market").addEventListener("change", persist);

loadSettings().then(poll);
setInterval(poll, 1000);
