# NOVA deploy

Production: https://novabox.recursivefunctions.dev/  
Branch demos: https://novabox.recursivefunctions.dev/<slug>/  
Pickup QR/NFC: https://novabox.recursivefunctions.dev/<slug>/pickup/BOX-01

## Host layout (1mhzmb4-1)

| Piece | Role |
| --- | --- |
| `nova-display.service` | main on `:8081` |
| `nova-preview-router.service` | path router on `:8090` (`/` → prod, `/<slug>/` → preview) |
| `/home/ray/apps/nova2026/previews/<slug>/` | per-branch checkout + DB + log |
| self-hosted runner label `nova-box` | runs the GitHub Actions workflows |

Caddy on `pop-os` (garden tunnel `:8080`) proxies:

- `novabox.recursivefunctions.dev` → `100.84.7.123:8090` (router)

## Manual deploys

```bash
./deploy/deploy-main.sh
./deploy/deploy-preview.sh upsert my-branch my-branch
# → https://novabox.recursivefunctions.dev/my-branch/
# → https://novabox.recursivefunctions.dev/my-branch/pickup/BOX-01
./deploy/deploy-preview.sh destroy my-branch
```
