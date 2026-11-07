# NOVA Box Display

Frontend for the pickup box monitor (a phone mounted on the box). Served by
`display/app.py` on the same origin as the backend API.

## Run locally

```bash
uv run --with fastapi --with uvicorn python display/app.py
```

Open `http://localhost:8081/` (`?box=BOX-02` for the second box).

## Public URLs

| What | URL |
| --- | --- |
| Production (main) | https://novabox.recursivefunctions.dev/ |
| Branch preview | https://novabox.recursivefunctions.dev/p/&lt;slug&gt;/ |

CI/CD (see `deploy/`):

- Push to `main` → restarts production on this host
- Push/PR on other branches → upserts a preview at `/p/&lt;slug&gt;/`

## Files

- `app.py` — single-port server: static display at `/`, backend API under the same origin
- `serve.sh` — local server + optional quick cloudflared tunnel
- `index.html` / `style.css` / `script.js` — screen UI; polls `GET {BASE}/boxes/{box_id}`
  (`BASE` is empty on prod, `/p/&lt;slug&gt;` on previews)
