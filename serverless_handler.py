"""
Pleasance RunPod Serverless Handler (Async Parallel)

Serverless endpoint for content generation and review.
Uses asyncio for massive parallelism - all LLM calls run simultaneously.

Deploy to RunPod Serverless for auto-scaling.
"""

import os
import asyncio
import runpod
import aiohttp
from typing import Optional, Dict, Any, List

# =============================================================================
# CONFIGURATION
# =============================================================================

PLEASANCE_API = os.environ.get("PLEASANCE_API", "https://api.pleasance.app")
AGENT_SECRET = os.environ.get("AGENT_SECRET")
PROXY_URL = os.environ.get("ANTHROPIC_BASE_URL", "https://agproxy12461249316123.pleasance.app")

# Fallback chain for bulk generation
FAST_CHAIN = [
    "gemini-2.5-flash-lite",
    "gemini-2.5-flash",
    "gemini-3-flash",
    "claude-sonnet-4-5",
]

# =============================================================================
# PROMPTS
# =============================================================================

SECTION_PROMPTS = {
    "appeal": """Write a compelling 2-3 paragraph description of why people find '{name}' appealing. 
Focus on psychological and sensory aspects. Be educational and non-judgmental.""",

    "howTo": """Write a practical guide for safely exploring '{name}' as beginners. 
Include safety considerations, communication tips, and gradual progression suggestions.""",

    "variations": """Describe 3-5 common variations or related practices to '{name}'. 
Be specific but tasteful. Include intensity levels.""",
}

REVIEW_PROMPT = """Review this content for an educational kink encyclopedia:

KINK: {name}
SECTION: {section_key}
CONTENT:
{content}

Check for:
1. Factual accuracy
2. Educational tone (non-judgmental)
3. Safety warnings where needed
4. Completeness

Respond in JSON:
{{"approved": true/false, "issues": [], "severity": "none|low|medium|high"}}
"""

# =============================================================================
# ASYNC PROXY CLIENT
# =============================================================================

class AsyncProxyClient:
    """Async client for parallel LLM calls."""
    
    def __init__(self, base_url: str = None):
        self.base_url = base_url or PROXY_URL
        self._session: Optional[aiohttp.ClientSession] = None
    
    async def get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=120)
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session
    
    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()
    
    async def call_model(self, prompt: str, model: str, max_tokens: int = 2048) -> Optional[str]:
        """Call a specific model through the proxy."""
        try:
            session = await self.get_session()
            
            payload = {
                "model": model,
                "max_tokens": max_tokens,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.7,
            }
            
            async with session.post(
                f"{self.base_url}/v1/messages",
                json=payload,
                headers={"Content-Type": "application/json"}
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    
                    # Claude format
                    if "content" in data and len(data["content"]) > 0:
                        return data["content"][0].get("text", "")
                    
                    # Gemini format
                    if "text" in data:
                        return data["text"]
                    
            return None
        except Exception as e:
            print(f"[ERROR] {model}: {e}")
            return None
    
    async def complete(self, prompt: str, models: List[str] = None) -> Dict[str, Any]:
        """Complete with fallback chain."""
        models = models or FAST_CHAIN
        
        for i, model in enumerate(models):
            result = await self.call_model(prompt, model)
            if result:
                return {"text": result, "model": model, "success": True}
            if i < len(models) - 1:
                print(f"[FALLBACK] {model} failed, trying {models[i+1]}")
        
        return {"text": None, "model": None, "success": False, "error": "All models failed"}
    
    async def health_check(self) -> bool:
        """Check if proxy is available."""
        try:
            session = await self.get_session()
            async with session.get(f"{self.base_url}/health") as resp:
                return resp.status == 200
        except:
            return False


# Global client
client = AsyncProxyClient()

# =============================================================================
# ASYNC GENERATION
# =============================================================================

async def generate_section_async(kink: dict, section_key: str) -> dict:
    """Generate a single section for a kink (async)."""
    prompt_template = SECTION_PROMPTS.get(section_key)
    if not prompt_template:
        return {
            "kinkId": kink.get("id"),
            "sectionKey": section_key,
            "content": None,
            "error": f"Unknown section: {section_key}"
        }
    
    prompt = prompt_template.format(
        name=kink.get("name", "Unknown"),
        category=kink.get("category", "")
    )
    
    print(f"[GEN] {kink.get('name')} → {section_key}")
    
    result = await client.complete(prompt)
    
    return {
        "kinkId": kink["id"],
        "sectionKey": section_key,
        "content": result.get("text"),
        "model": result.get("model"),
        "error": result.get("error") if not result["success"] else None
    }


async def generate_batch_async(kinks: List[dict]) -> List[dict]:
    """Generate all sections for all kinks in parallel."""
    tasks = []
    
    for kink in kinks:
        for section_key in SECTION_PROMPTS.keys():
            tasks.append(generate_section_async(kink, section_key))
    
    print(f"[BATCH] Starting {len(tasks)} parallel LLM calls...")
    
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # Handle any exceptions
    sections = []
    for r in results:
        if isinstance(r, Exception):
            sections.append({"error": str(r)})
        else:
            sections.append(r)
    
    print(f"[BATCH] Completed {len(sections)} sections")
    return sections


async def review_section_async(item: dict) -> dict:
    """Review a section (async)."""
    prompt = REVIEW_PROMPT.format(
        name=item.get("name", "Unknown"),
        section_key=item.get("sectionKey"),
        content=item.get("content", "")
    )
    
    result = await client.complete(prompt)
    
    if result["success"]:
        try:
            import json
            text = result["text"]
            start = text.find("{")
            end = text.rfind("}") + 1
            if start != -1 and end > start:
                review = json.loads(text[start:end])
                review["kinkId"] = item.get("kinkId")
                review["sectionKey"] = item.get("sectionKey")
                return review
        except:
            pass
    
    return {
        "kinkId": item.get("kinkId"),
        "sectionKey": item.get("sectionKey"),
        "approved": True,
        "error": "Review parse failed"
    }


async def review_batch_async(items: List[dict]) -> List[dict]:
    """Review all items in parallel."""
    print(f"[REVIEW] Starting {len(items)} parallel reviews...")
    
    tasks = [review_section_async(item) for item in items]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    reviews = []
    for r in results:
        if isinstance(r, Exception):
            reviews.append({"approved": True, "error": str(r)})
        else:
            reviews.append(r)
    
    return reviews

# =============================================================================
# RUNPOD HANDLER
# =============================================================================

def handler(job: dict) -> dict:
    """
    RunPod Serverless Handler (Async Parallel)
    
    All LLM calls run simultaneously for maximum throughput.
    """
    try:
        input_data = job.get("input", {})
        action = input_data.get("action", "generate")
        
        # Health check
        if action == "health":
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                proxy_ok = loop.run_until_complete(client.health_check())
                return {"status": "ok", "proxy": proxy_ok, "mode": "async_parallel"}
            finally:
                loop.run_until_complete(client.close())
                loop.close()
        
        # Batch generation (parallel)
        if action == "batch_generate":
            kinks = input_data.get("kinks", [])
            
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                sections = loop.run_until_complete(generate_batch_async(kinks))
                return {"sections": sections, "count": len(sections)}
            finally:
                loop.run_until_complete(client.close())
                loop.close()
        
        # Batch review (parallel)
        if action == "batch_review":
            items = input_data.get("items", [])
            
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                reviews = loop.run_until_complete(review_batch_async(items))
                return {"reviews": reviews, "count": len(reviews)}
            finally:
                loop.run_until_complete(client.close())
                loop.close()
        
        # Single generation (for testing)
        if action == "generate":
            kink = input_data.get("kink", {})
            section_key = input_data.get("sectionKey", "appeal")
            
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                result = loop.run_until_complete(generate_section_async(kink, section_key))
                return {"section": result}
            finally:
                loop.run_until_complete(client.close())
                loop.close()
        
        return {"error": f"Unknown action: {action}"}
        
    except Exception as e:
        import traceback
        return {"error": str(e), "traceback": traceback.format_exc()}


# RunPod Serverless entry point
runpod.serverless.start({"handler": handler})
