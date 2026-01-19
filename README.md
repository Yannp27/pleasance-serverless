# Pleasance Agent Workers

Python-based AI agents for content generation and quality control.

## Architecture

```
Orchestrator → RunPod Serverless → Proxy Client → Antigravity Proxy
                                                        ↓
                                              Claude / Gemini
                                                        ↓
                                               Pleasance API
```

## Files

| File | Purpose |
|------|---------|
| `proxy_client.py` | Centralized proxy access with fallback chains |
| `serverless_handler.py` | RunPod Serverless endpoint |
| `cloud_reviewer.py` | Local review script (uses proxy_client) |
| `Dockerfile` | Serverless deployment image |

## RunPod Serverless Deployment

### 1. Build and Push Image
```bash
cd agents
docker build -t your-dockerhub/pleasance-agent .
docker push your-dockerhub/pleasance-agent
```

### 2. Create Endpoint
1. Go to runpod.io/serverless
2. Create new endpoint
3. Set Docker image: `your-dockerhub/pleasance-agent`
4. Environment variables:
   - `ANTHROPIC_BASE_URL=https://proxy.pleasance.app`
   - `PLEASANCE_API=https://api.pleasance.app`
   - `AGENT_SECRET=xxx`

### 3. Call the Endpoint
```python
import requests

ENDPOINT_ID = "your-endpoint-id"
RUNPOD_API_KEY = "your-runpod-key"

# Generate sections
resp = requests.post(
    f"https://api.runpod.ai/v2/{ENDPOINT_ID}/runsync",
    headers={"Authorization": f"Bearer {RUNPOD_API_KEY}"},
    json={
        "input": {
            "action": "batch_generate",
            "kinks": [{"id": "xxx", "name": "Bondage"}]
        }
    }
)
print(resp.json())
```

## Proxy Setup (for remote access)

Expose local proxy via Cloudflare Tunnel:
```bash
cloudflared tunnel --url http://localhost:8080
# Use the generated URL as ANTHROPIC_BASE_URL
```

For persistent tunnel:
```bash
cloudflared tunnel create pleasance-proxy
cloudflared tunnel route dns pleasance-proxy proxy.pleasance.app
```

## Model Fallback Chains

| Chain | Models | Use Case |
|-------|--------|----------|
| `standard` | claude-sonnet → gemini-flash → gemini-pro | Reviews |
| `fast` | gemini-flash-lite → gemini-flash → claude | Bulk gen |
| `deep` | claude-thinking → opus → gemini-pro | Analysis |

## Costs

| Task | Method | Cost |
|------|--------|------|
| Bulk (500 kinks) | Serverless + Gemini | ~$5 |
| Review | Serverless + Claude | ~$10 |
| **Per batch** | | **~$15** |
