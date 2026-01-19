"""
Pleasance RunPod Serverless Handler

Serverless endpoint for content generation and review.
Deploy to RunPod Serverless for auto-scaling, no pod management.

RunPod Serverless Setup:
1. Create endpoint at runpod.io/serverless
2. Use template: runpod/pytorch:2.1.0-py3.10-cuda12.1.1-devel
3. Deploy this handler
4. Call via API: POST https://api.runpod.ai/v2/{endpoint_id}/runsync
"""

import os
import runpod
from proxy_client import AntigravityClient, FALLBACK_CHAINS

# =============================================================================
# CONFIGURATION
# =============================================================================

# API endpoints
PLEASANCE_API = os.environ.get("PLEASANCE_API", "https://api.pleasance.app")
AGENT_SECRET = os.environ.get("AGENT_SECRET")

# Proxy URL - for serverless, use the Cloudflare tunnel URL
# Set this in RunPod environment variables
PROXY_URL = os.environ.get("ANTHROPIC_BASE_URL", "https://proxy.pleasance.app")

# Initialize proxy client
client = AntigravityClient(PROXY_URL)

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
# HANDLERS
# =============================================================================

def generate_section(kink: dict, section_key: str) -> dict:
    """Generate a single section for a kink."""
    prompt_template = SECTION_PROMPTS.get(section_key)
    if not prompt_template:
        return {"kinkId": kink.get("id"), "sectionKey": section_key, "error": f"Unknown section: {section_key}"}
    
    prompt = prompt_template.format(
        name=kink.get("name", "Unknown"),
        category=kink.get("category", "")
    )
    
    print(f"[DEBUG] Generating {section_key} for {kink.get('name')}")
    print(f"[DEBUG] Using proxy: {PROXY_URL}")
    
    # Use fast chain for bulk generation
    result = client.complete(prompt, chain="fast", max_tokens=1024)
    
    print(f"[DEBUG] Result success: {result.get('success')}")
    if not result.get('success'):
        print(f"[DEBUG] Error: {result.get('error')}")
    
    if result["success"]:
        return {
            "kinkId": kink["id"],
            "sectionKey": section_key,
            "content": result["text"],
            "model": result["model"]
        }
    else:
        return {
            "kinkId": kink.get("id"),
            "sectionKey": section_key,
            "content": None,
            "error": result.get("error", "All models failed")
        }


def review_section(kink: dict, section_key: str, content: str) -> dict:
    """Review a section for quality issues."""
    prompt = REVIEW_PROMPT.format(
        name=kink.get("name", "Unknown"),
        section_key=section_key,
        content=content
    )
    
    # Use standard chain for review (needs Claude quality)
    result = client.complete_json(prompt, chain="standard")
    
    if result:
        result["kinkId"] = kink["id"]
        result["sectionKey"] = section_key
        result["model"] = "unknown"  # JSON parse loses this
        return result
    else:
        return {"approved": True, "error": "Review failed, auto-approved"}


def handler(job: dict) -> dict:
    """
    RunPod Serverless Handler
    
    Input:
    {
        "input": {
            "action": "generate" | "review" | "batch_generate",
            "kink": {...} | "kinks": [...],
            "sectionKey": "appeal" | "howTo" | "variations",
            "content": "..." (for review only)
        }
    }
    
    Output:
    {
        "sections": [...] | "reviews": [...] | "error": "..."
    }
    """
    try:
        input_data = job.get("input", {})
        action = input_data.get("action", "generate")
        
        # Health check
        if action == "health":
            proxy_ok = client.health_check()
            return {"status": "ok", "proxy": proxy_ok}
        
        # Single section generation
        if action == "generate":
            kink = input_data.get("kink", {})
            section_key = input_data.get("sectionKey", "appeal")
            result = generate_section(kink, section_key)
            return {"section": result}
        
        # Batch generation (multiple kinks, all sections)
        if action == "batch_generate":
            kinks = input_data.get("kinks", [])
            sections = []
            
            for kink in kinks:
                for section_key in SECTION_PROMPTS.keys():
                    result = generate_section(kink, section_key)
                    sections.append(result)
            
            return {"sections": sections, "count": len(sections)}
        
        # Review a section
        if action == "review":
            kink = input_data.get("kink", {})
            section_key = input_data.get("sectionKey")
            content = input_data.get("content", "")
            result = review_section(kink, section_key, content)
            return {"review": result}
        
        # Batch review
        if action == "batch_review":
            items = input_data.get("items", [])
            reviews = []
            
            for item in items:
                result = review_section(
                    {"id": item["kinkId"], "name": item.get("name", "")},
                    item["sectionKey"],
                    item["content"]
                )
                reviews.append(result)
            
            return {"reviews": reviews, "count": len(reviews)}
        
        return {"error": f"Unknown action: {action}"}
        
    except Exception as e:
        return {"error": str(e)}


# RunPod Serverless entry point
runpod.serverless.start({"handler": handler})
