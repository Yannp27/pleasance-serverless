# RunPod Serverless Deployment Guide

## What I've Created (Ready to Use)

| File | Purpose |
|------|---------|
| `proxy_client.py` | Unified proxy access with all models |
| `serverless_handler.py` | RunPod Serverless endpoint |
| `orchestrator.py` | Local script to trigger jobs |
| `start-proxy-tunnel.ps1` | Start proxy + expose via tunnel |

---

## Your Steps (5 minutes)

### Step 1: Install cloudflared
```powershell
winget install cloudflare.cloudflared
```

### Step 2: Start Proxy + Tunnel
```powershell
cd "c:\Users\yannp\9425-0172 Quebec Inc Dropbox\Content Archive\Projects\Kink App\kink-database\agents"
.\start-proxy-tunnel.ps1
```
**Save the tunnel URL** (e.g., `https://abc-xyz.trycloudflare.com`)

### Step 3: Create RunPod Serverless Endpoint
1. Go to: https://www.runpod.io/console/serverless
2. Click "New Endpoint"
3. **Template**: `runpod/serverless-base`
4. **GPU**: None (we use external LLM via proxy)
5. **Environment Variables**:
   ```
   ANTHROPIC_BASE_URL = <tunnel URL from step 2>
   AGENT_SECRET = <generate with: openssl rand -hex 32>
   PLEASANCE_API = https://api.pleasance.app (or localhost:3001 for testing)
   ```
6. **Handler**: Upload `proxy_client.py` and `serverless_handler.py`
7. Copy the **Endpoint ID**

### Step 4: Test
```powershell
$env:RUNPOD_ENDPOINT_ID = "your-endpoint-id"
python orchestrator.py health
```

### Step 5: Generate Content
```powershell
python orchestrator.py generate 10  # Process 10 kinks
python orchestrator.py review 5     # Review 5 kinks
```

---

## Architecture Flow

```
You run: orchestrator.py
         ↓
    RunPod Serverless
         ↓
    (via ANTHROPIC_BASE_URL)
         ↓
    Cloudflare Tunnel
         ↓
    Your Local Proxy (localhost:8080)
         ↓
    Claude / Gemini APIs
         ↓
    Pleasance API (push results)
```

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| "Endpoint not responding" | Check RUNPOD_ENDPOINT_ID is set |
| "Proxy not healthy" | Run `start-proxy-tunnel.ps1` |
| "Agent auth failed" | Set AGENT_SECRET in both places |
| "Tunnel URL changed" | Re-run tunnel, update RunPod env vars |

---

## Persistent Tunnel (Optional)

For a stable URL that doesn't change:
```powershell
cloudflared tunnel create pleasance-proxy
cloudflared tunnel route dns pleasance-proxy proxy.pleasance.app
cloudflared tunnel run pleasance-proxy
```
Then use `https://proxy.pleasance.app` as ANTHROPIC_BASE_URL.
