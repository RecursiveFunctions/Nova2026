"""Minimal courier verification page served at GET /pickup/{box_id}.

This is a no-build fallback so the NFC tap -> enter code -> authorized flow works on a phone
straight from the API server. Person B's React page can replace it. The page never contains
a pickup code; it only POSTs what the courier types to /boxes/{box_id}/verify-pickup.
"""
import html
import json

_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Pickup verification - __BOX_HTML__</title>
<style>
  :root { color-scheme: light dark; --bg:#ffffff; --fg:#111111; --muted:#6b6b6b; --card:#f3f3f4;
          --line:#c9c9cc; --ok:#0a7a2f; --bad:#b42318; --btn:#111111; --btn-fg:#ffffff; }
  @media (prefers-color-scheme: dark) {
    :root { --bg:#111111; --fg:#f5f5f5; --muted:#a3a3a3; --card:#1c1c1e; --line:#3a3a3c;
            --ok:#4ade80; --bad:#f87171; --btn:#f5f5f5; --btn-fg:#111111; }
  }
  * { box-sizing: border-box; }
  body { margin:0; padding: max(24px, env(safe-area-inset-top)) 20px max(24px, env(safe-area-inset-bottom));
         font: 18px/1.4 -apple-system, system-ui, "Segoe UI", Roboto, sans-serif;
         background: var(--bg); color: var(--fg); }
  main { max-width: 420px; margin: 0 auto; }
  h1 { font-size: 26px; margin: 0 0 4px; }
  .box { color: var(--muted); margin: 0 0 24px; }
  label { display:block; font-weight:600; margin-bottom:8px; }
  input { width:100%; font: 600 34px/1.2 ui-monospace, Menlo, Consolas, monospace; letter-spacing: .25em;
          text-align:center; padding:14px 10px; border:2px solid var(--line); border-radius:12px;
          background: var(--card); color: var(--fg); }
  button { width:100%; margin-top:16px; padding:16px; font: 600 20px/1 inherit; border:0; border-radius:12px;
           background: var(--btn); color: var(--btn-fg); }
  button:disabled { opacity:.5; }
  #result { margin-top:24px; padding:16px; border-radius:12px; display:none; font-weight:600; }
  #result.ok  { display:block; border:2px solid var(--ok);  color: var(--ok); }
  #result.bad { display:block; border:2px solid var(--bad); color: var(--bad); }
  #result.wait{ display:block; border:2px solid var(--line); color: var(--muted); }
</style>
</head>
<body>
<main>
  <h1>Pickup verification</h1>
  <p class="box">Box __BOX_HTML__</p>
  <form id="f" autocomplete="off">
    <label for="code">Enter your 6-digit pickup code</label>
    <input id="code" name="code" inputmode="numeric" pattern="[0-9]*" maxlength="6" placeholder="------" required>
    <button id="go" type="submit">Verify</button>
  </form>
  <div id="result" role="status" aria-live="polite"></div>
</main>
<script>
  var boxId = __BOX_JSON__;
  var form = document.getElementById("f"), input = document.getElementById("code");
  var btn = document.getElementById("go"), result = document.getElementById("result");
  function show(text, kind) { result.textContent = text; result.className = kind; }
  form.addEventListener("submit", function (e) {
    e.preventDefault();
    var code = input.value.trim();
    if (!code) { return; }
    btn.disabled = true;
    show("Checking...", "wait");
    fetch("/boxes/" + encodeURIComponent(boxId) + "/verify-pickup", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pickup_code: code })
    }).then(function (res) {
      return res.json().catch(function () { return {}; }).then(function (data) { return { res: res, data: data }; });
    }).then(function (r) {
      if (r.res.ok && r.data.authorized) {
        input.value = "";
        show("Pickup authorized for order " + r.data.order_id + ". The box is unlocked.", "ok");
      } else if (r.res.status === 429) {
        show("Too many attempts. Wait a second and try again.", "bad");
      } else {
        show("Not authorized. " + (r.data.error || "Check the code and try again."), "bad");
      }
    }).catch(function () {
      show("Cannot reach the server. Check the connection and try again.", "bad");
    }).then(function () { btn.disabled = false; });
  });
</script>
</body>
</html>
"""


def render_pickup_page(box_id: str) -> str:
    safe_json = json.dumps(box_id).replace("<", "\\u003c")
    return _PAGE.replace("__BOX_HTML__", html.escape(box_id)).replace("__BOX_JSON__", safe_json)


def render_unknown_box_page(box_id: str) -> str:
    return ("<!doctype html><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'>"
            "<title>Unknown box</title><body style='font:18px system-ui;padding:24px'>"
            "<h1>Unknown box</h1><p>No box called " + html.escape(box_id) + " exists.</p></body>")
