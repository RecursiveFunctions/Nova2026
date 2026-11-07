# NOVA deploy

Production: https://novabox.recursivefunctions.dev/  
Branch demos: https://novabox.recursivefunctions.dev/p/&lt;slug&gt;/

## Host layout (1mhzmb4-1)

| Piece | Role |
| --- | --- |
| `nova-display.service` | main on `:8081` |
| `nova-preview-router.service` | path router on `:8090` (`/` → prod, `/p/&lt;slug&gt;/` → preview) |
| `/home/ray/apps/nova2026/previews/&lt;slug&gt;/` | per-branch checkout + DB + log |
| self-hosted runner label `nova-box` | runs the GitHub Actions workflows |

Caddy on `pop-os` (garden tunnel `:8080`) proxies:

- `novabox.recursivefunctions.dev` → `100.84.7.123:8090` (router)

## One-time host install

```bash
./deploy/install-host.sh
# then register a self-hosted runner with label nova-box (see below)
```

## Manual deploys

```bash
./deploy/deploy-main.sh
./deploy/deploy-preview.sh upsert origin/my-branch my-branch
# → https://novabox.recursivefunctions.dev/p/my-branch/
./deploy/deploy-preview.sh destroy my-branch
```

## Self-hosted runner

```bash
mkdir -p ~/actions-runner && cd ~/actions-runner
curl -fsSL -o actions-runner-linux-x64.tar.gz \
  https://github.com/actions/runner/releases/download/v2.329.0/actions-runner-linux-x64-2.329.0.tar.gz
tar xzf actions-runner-linux-x64.tar.gz
./config.sh --url https://github.com/RecursiveFunctions/Nova2026 \
  --token "$RUNNER_TOKEN" --labels nova-box --unattended --name nova-box
sudo ./svc.sh install
sudo ./svc.sh start
```

Create `$RUNNER_TOKEN` with:
`gh api -X POST repos/RecursiveFunctions/Nova2026/actions/runners/registration-token --jq .token`
