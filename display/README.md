# NOVA Box Display

Frontend for the pickup box monitor (a phone mounted on the box). It is served by
`display/app.py` on the same origin as the backend API, so the phone needs only one URL.

## Run

```bash
# from the repo root (port 8081 default; deps resolved by uv)
uv run --with fastapi --with uvicorn python display/app.py
```

Open on the phone (same machine): `http://localhost:8081/` — add `?box=BOX-02` for the second box.

## Public URL: novabox.recursivefunctions.dev

`display/serve.sh` starts the server above plus a `cloudflared` tunnel:

```bash
./display/serve.sh                                  # quick tunnel -> random trycloudflare.com URL
NOVABOX_HOSTNAME=novabox.recursivefunctions.dev ./display/serve.sh
```

The fixed hostname requires a **named** Cloudflare tunnel, i.e. the `recursivefunctions.dev`
zone must be on Cloudflare and `cloudflared login` must have been run once by the zone owner
(creates `~/.cloudflared/cert.pem` and the `novabox` tunnel + DNS record):

```bash
cloudflared login            # browser auth as the recursivefunctions.dev zone owner
cloudflared tunnel create novabox
cloudflared tunnel route dns novabox novabox.recursivefunctions.dev
mkdir -p ~/.cloudflared
printf 'tunnel: novabox\ncredentials-file: /home/ray/.cloudflared/<TUNNEL-ID>.json\n' > ~/.cloudflared/config.yml
printf 'ingress:\n  - hostname: novabox.recursivefunctions.dev\n    service: http://localhost:8081\n  - service: http_status:404\n' >> ~/.cloudflared/config.yml
NOVABOX_HOSTNAME=novabox.recursivefunctions.dev ./display/serve.sh
```

Until then, the quick tunnel in `serve.sh` prints a `https://<random>.trycloudflare.com` URL
that the phone can open immediately; point the `novabox` DNS record at the named tunnel once created.

## Files

- `app.py` — single-port server: static display at `/`, backend API under the same origin
- `serve.sh` — server + cloudflared tunnel launcher
- `index.html` / `style.css` / `script.js` — the screen itself; polls `GET /boxes/{box_id}`
  every second (display-safe view: status, order id, customer, summary — never a pickup code)
- `generate_qr.py`, `order_qr.png` — the QR on the screen encodes the courier verification
  page (`/pickup/{box_id}`), i.e. what a courier opens on their phone