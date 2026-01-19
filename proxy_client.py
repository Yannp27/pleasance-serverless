"""
Antigravity Proxy Client

Centralized client for all agents to access Claude/Gemini via the Antigravity proxy.
Implements "Never Fully Fail" with full model fallback chain.

For remote agents (RunPod), expose the proxy via Cloudflare Tunnel:
  cloudflared tunnel --url http://localhost:8080

Then set:
  ANTHROPIC_BASE_URL=https://your-tunnel.trycloudflare.com
"""

import os
import time
import json
import requests
from typing import Optional, Dict, List, Any

# =============================================================================
# CONFIGURATION
# =============================================================================

# Proxy URL - permanent Cloudflare tunnel
PROXY_URL = os.environ.get("ANTHROPIC_BASE_URL", "https://agproxy12461249316123.pleasance.app")

# Full model list supported by Antigravity Claude Proxy
# Source: GEMINI.md governance rules
CLAUDE_MODELS = [
    "claude-opus-4-5-thinking",
    "claude-sonnet-4-5",
    "claude-sonnet-4-5-thinking",
]

GEMINI_MODELS = [
    "gemini-3-flash",
    "gemini-3-pro-image",
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-2.5-flash-thinking",
    "gemini-2.5-pro",
    "gemini-3-pro-high",
    "gemini-3-pro",
]

# Default fallback chains for different use cases
FALLBACK_CHAINS = {
    "standard": [
        "claude-sonnet-4-5",
        "gemini-2.5-flash",
        "gemini-2.5-pro",
        "gemini-3-flash",
    ],
    "fast": [
        "gemini-2.5-flash-lite",
        "gemini-2.5-flash",
        "gemini-3-flash",
        "claude-sonnet-4-5",
    ],
    "deep": [
        "claude-sonnet-4-5-thinking",
        "claude-opus-4-5-thinking",
        "gemini-2.5-pro",
        "gemini-3-pro-high",
    ],
    "image": [
        "gemini-3-pro-image",
        "gemini-3-pro",
        "gemini-2.5-pro",
    ],
}

# =============================================================================
# PROXY CLIENT
# =============================================================================

class AntigravityClient:
    """
    Unified client for Antigravity Claude Proxy.
    
    Usage:
        client = AntigravityClient()
        response = client.complete("What is 2+2?", chain="standard")
    """
    
    def __init__(self, base_url: str = None):
        self.base_url = base_url or PROXY_URL
        self._health_checked = False
    
    def health_check(self) -> bool:
        """Check if proxy is available."""
        try:
            resp = requests.get(f"{self.base_url}/health", timeout=5)
            self._health_checked = resp.status_code == 200
            return self._health_checked
        except:
            return False
    
    def _call_model(self, prompt: str, model: str, max_tokens: int = 2048, 
                    system: str = None, temperature: float = 0.7) -> Optional[str]:
        """
        Call a specific model through the proxy.
        Returns response text or None on failure.
        """
        try:
            messages = [{"role": "user", "content": prompt}]
            
            payload = {
                "model": model,
                "max_tokens": max_tokens,
                "messages": messages,
                "temperature": temperature,
            }
            
            if system:
                payload["system"] = system
            
            resp = requests.post(
                f"{self.base_url}/v1/messages",
                headers={"Content-Type": "application/json"},
                json=payload,
                timeout=120  # 2 min timeout for long generations
            )
            
            if resp.status_code == 200:
                data = resp.json()
                
                # Claude format
                if "content" in data and len(data["content"]) > 0:
                    return data["content"][0].get("text", "")
                
                # Gemini format (proxied)
                if "text" in data:
                    return data["text"]
                
                # Fallback: try to extract any text
                if "choices" in data:
                    return data["choices"][0].get("message", {}).get("content", "")
            
            return None
            
        except requests.Timeout:
            return None
        except Exception as e:
            print(f"[PROXY] Error with {model}: {e}")
            return None
    
    def complete(self, prompt: str, chain: str = "standard", 
                 max_tokens: int = 2048, system: str = None,
                 temperature: float = 0.7) -> Dict[str, Any]:
        """
        Complete a prompt using the specified fallback chain.
        
        Args:
            prompt: The user prompt
            chain: Fallback chain name ("standard", "fast", "deep", "image")
            max_tokens: Maximum tokens to generate
            system: Optional system prompt
            temperature: Sampling temperature
        
        Returns:
            {
                "text": str,           # Generated text
                "model": str,          # Model that succeeded
                "fallbacks_used": int, # How many fallbacks were tried
                "success": bool
            }
        """
        models = FALLBACK_CHAINS.get(chain, FALLBACK_CHAINS["standard"])
        
        for i, model in enumerate(models):
            response = self._call_model(
                prompt=prompt,
                model=model,
                max_tokens=max_tokens,
                system=system,
                temperature=temperature
            )
            
            if response:
                return {
                    "text": response,
                    "model": model,
                    "fallbacks_used": i,
                    "success": True
                }
            
            if i < len(models) - 1:
                print(f"[PROXY] {model} failed, trying {models[i+1]}...")
        
        # All models failed
        return {
            "text": None,
            "model": None,
            "fallbacks_used": len(models),
            "success": False
        }
    
    def complete_json(self, prompt: str, chain: str = "standard", **kwargs) -> Optional[Dict]:
        """
        Complete and parse JSON response.
        """
        result = self.complete(prompt, chain, **kwargs)
        
        if not result["success"]:
            return None
        
        try:
            text = result["text"]
            # Find JSON in response
            start = text.find("{")
            end = text.rfind("}") + 1
            if start != -1 and end > start:
                return json.loads(text[start:end])
        except json.JSONDecodeError:
            pass
        
        return None


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

# Global client instance
_client: Optional[AntigravityClient] = None

def get_client() -> AntigravityClient:
    """Get or create the global client instance."""
    global _client
    if _client is None:
        _client = AntigravityClient()
    return _client


def complete(prompt: str, chain: str = "standard", **kwargs) -> Dict[str, Any]:
    """Quick complete using global client."""
    return get_client().complete(prompt, chain, **kwargs)


def complete_json(prompt: str, chain: str = "standard", **kwargs) -> Optional[Dict]:
    """Quick JSON complete using global client."""
    return get_client().complete_json(prompt, chain, **kwargs)


# =============================================================================
# REMOTE PROXY SETUP (for RunPod workers)
# =============================================================================

def setup_cloudflare_tunnel():
    """
    Instructions for exposing proxy to remote workers.
    
    On your local machine (where proxy runs):
    
    1. Install cloudflared:
       winget install cloudflare.cloudflared
    
    2. Start tunnel:
       cloudflared tunnel --url http://localhost:8080
    
    3. Copy the tunnel URL (e.g., https://xyz-abc.trycloudflare.com)
    
    4. On RunPod worker, set:
       export ANTHROPIC_BASE_URL=https://xyz-abc.trycloudflare.com
    
    The temporary tunnel URL changes each time. For persistent tunnel:
       cloudflared tunnel create pleasance-proxy
       cloudflared tunnel route dns pleasance-proxy proxy.pleasance.app
       cloudflared tunnel run pleasance-proxy
    """
    pass


if __name__ == "__main__":
    # Test the client
    print(f"Proxy URL: {PROXY_URL}")
    
    client = AntigravityClient()
    
    if client.health_check():
        print("[OK] Proxy is healthy")
        
        result = client.complete("Say 'hello' in exactly one word.", chain="fast")
        if result["success"]:
            print(f"[OK] Response from {result['model']}: {result['text']}")
        else:
            print("[ERROR] All models failed")
    else:
        print("[ERROR] Proxy not available")
        print("Start with: antigravity-claude-proxy start")
