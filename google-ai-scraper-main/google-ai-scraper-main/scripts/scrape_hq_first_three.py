import json
import time
import urllib.parse
import urllib.request

companies = [
    "Adiglobaldistribution",
    "Econnet s.r.l",
    "Router Switch",
]

base = "http://127.0.0.1:15551"
results = []

with urllib.request.urlopen(base + "/health", timeout=5) as r:
    health = json.loads(r.read().decode())
print(
    f"backend=ok extension={health.get('extension_connected')} "
    f"pending={health.get('pending')}"
)

for c in companies:
    # Company name first so it cannot be dropped from the prompt
    q = f"{c} company headquarters full address"
    params = urllib.parse.urlencode({"q": q, "close_thread": "1"})
    url = f"{base}/ask?{params}"
    print(f"=== searching: {c} ===")
    print(f"query: {q}")
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode())
        md = data.get("markdown") or ""
        err = data.get("error")
        cites = data.get("citations") or []
        print(f"error={err} citations={len(cites)} markdown_len={len(md)}")
        if md:
            print(md[:1500] + ("\n...[truncated]" if len(md) > 1500 else ""))
        results.append(
            {
                "company": c,
                "query": q,
                "error": err,
                "citations": len(cites),
                "markdown": md,
                "query_id": data.get("query_id"),
            }
        )
    except Exception as e:
        print(f"FAIL: {e}")
        results.append(
            {
                "company": c,
                "query": q,
                "error": str(e),
                "citations": 0,
                "markdown": "",
            }
        )
    print()
    time.sleep(2)

print("=== SUMMARY ===")
for row in results:
    print(
        f"{row['company']}: error={row.get('error')} "
        f"md_len={len(row.get('markdown') or '')}"
    )

out = (
    r"c:\Users\aman.kumar\Downloads\google-ai-scraper-main"
    r"\google-ai-scraper-main\hq-first-three-results.json"
)
with open(out, "w", encoding="utf-8") as f:
    json.dump(results, f, indent=2, ensure_ascii=False)
print(f"saved: {out}")
print("=== DONE ===")
