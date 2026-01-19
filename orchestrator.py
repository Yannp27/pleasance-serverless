"""
Pleasance Orchestrator

Calls RunPod Serverless endpoint to process content.
Run locally after setting up the proxy tunnel.

Usage:
    python orchestrator.py health          # Check endpoint health
    python orchestrator.py generate 10     # Generate sections for 10 kinks
    python orchestrator.py review 5        # Review 5 processed kinks
"""

import os
import sys
import json
import requests
from pathlib import Path

# =============================================================================
# CONFIGURATION
# =============================================================================

# RunPod
RUNPOD_API_KEY = os.environ.get("RUNPOD_API_KEY", "")
RUNPOD_ENDPOINT_ID = os.environ.get("RUNPOD_ENDPOINT_ID", "")  # Set after creating endpoint

# Pleasance API
PLEASANCE_API = os.environ.get("PLEASANCE_API", "http://localhost:3001")
AGENT_SECRET = os.environ.get("AGENT_SECRET", "")

# =============================================================================
# RUNPOD CLIENT
# =============================================================================

def call_runpod(action: str, input_data: dict, timeout: int = 300):
    """
    Call RunPod Serverless endpoint.
    Uses runsync for immediate response (up to 5 min).
    """
    if not RUNPOD_ENDPOINT_ID:
        print("[ERROR] RUNPOD_ENDPOINT_ID not set")
        print("Set it after creating your endpoint at runpod.io/serverless")
        return None
    
    url = f"https://api.runpod.ai/v2/{RUNPOD_ENDPOINT_ID}/runsync"
    
    headers = {
        "Authorization": f"Bearer {RUNPOD_API_KEY}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "input": {
            "action": action,
            **input_data
        }
    }
    
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
        
        if resp.status_code == 200:
            data = resp.json()
            if "output" in data:
                return data["output"]
            return data
        else:
            print(f"[ERROR] RunPod returned {resp.status_code}")
            print(resp.text[:500])
            return None
            
    except requests.Timeout:
        print("[ERROR] RunPod request timed out")
        return None
    except Exception as e:
        print(f"[ERROR] {e}")
        return None

# =============================================================================
# PLEASANCE API CLIENT
# =============================================================================

def get_kinks_queue(limit: int = 10, processed: bool = False):
    """Get kinks from Pleasance API for processing."""
    headers = {"X-Agent-Key": AGENT_SECRET} if AGENT_SECRET else {}
    
    try:
        resp = requests.get(
            f"{PLEASANCE_API}/api/bulk/queue",
            params={"type": "kink", "processed": str(processed).lower(), "limit": limit},
            headers=headers,
            timeout=30
        )
        
        if resp.status_code == 200:
            return resp.json().get("items", [])
        elif resp.status_code == 403:
            print("[ERROR] Agent authentication required. Set AGENT_SECRET.")
            return []
        else:
            print(f"[ERROR] API returned {resp.status_code}")
            return []
            
    except Exception as e:
        print(f"[ERROR] Failed to fetch queue: {e}")
        return []


def push_sections(sections: list):
    """Push generated sections to Pleasance API."""
    headers = {
        "X-Agent-Key": AGENT_SECRET,
        "Content-Type": "application/json"
    }
    
    try:
        resp = requests.post(
            f"{PLEASANCE_API}/api/bulk/sections",
            headers=headers,
            json={"sections": sections},
            timeout=60
        )
        
        if resp.status_code == 200:
            return resp.json()
        else:
            print(f"[ERROR] Failed to push sections: {resp.status_code}")
            return None
            
    except Exception as e:
        print(f"[ERROR] {e}")
        return None

# =============================================================================
# COMMANDS
# =============================================================================

def cmd_health():
    """Check endpoint health."""
    print("Checking RunPod endpoint...")
    result = call_runpod("health", {})
    
    if result:
        print(f"[OK] Endpoint healthy: {json.dumps(result, indent=2)}")
    else:
        print("[ERROR] Endpoint not responding")
        print("\nTroubleshooting:")
        print("1. Is RUNPOD_ENDPOINT_ID set?")
        print("2. Is the endpoint active at runpod.io/serverless?")
        print("3. Is the tunnel running? (start-proxy-tunnel.ps1)")


def cmd_generate(count: int = 10):
    """Generate sections for unprocessed kinks."""
    print(f"Fetching {count} unprocessed kinks...")
    kinks = get_kinks_queue(limit=count, processed=False)
    
    if not kinks:
        print("No unprocessed kinks found")
        return
    
    print(f"Found {len(kinks)} kinks to process:")
    for k in kinks:
        print(f"  - {k['name']} ({k['id'][:8]}...)")
    
    print("\nSending to RunPod Serverless...")
    
    result = call_runpod("batch_generate", {"kinks": kinks}, timeout=600)
    
    if result and "sections" in result:
        sections = result["sections"]
        print(f"\n{'='*60}")
        print(f"GENERATED {len(sections)} SECTIONS")
        print(f"{'='*60}\n")
        
        # Log each section
        for s in sections:
            kink_id = s.get('kinkId', '?')[:8]
            section_key = s.get('sectionKey', '?')
            content = s.get('content', '')
            preview = content[:200].replace('\n', ' ') if content else '(empty)'
            print(f"[{kink_id}] {section_key}:")
            print(f"  Preview: {preview}...")
            print()
        
        # Push to API
        if AGENT_SECRET:
            print("Pushing to Pleasance API...")
            push_result = push_sections(sections)
            if push_result:
                print(f"[OK] Pushed {push_result.get('upserted', 0)} sections")
                print(f"     Failed: {push_result.get('failed', 0)}")
        else:
            print("[WARN] AGENT_SECRET not set, skipping API push")
            print("Full sections JSON:")
            print(json.dumps(sections, indent=2))
    else:
        print("[ERROR] Generation failed")
        if result:
            print(f"Result: {json.dumps(result, indent=2)}")


def cmd_review(count: int = 5):
    """Review processed kinks for quality."""
    print(f"Fetching {count} processed kinks for review...")
    kinks = get_kinks_queue(limit=count, processed=True)
    
    if not kinks:
        print("No processed kinks found")
        return
    
    print(f"Found {len(kinks)} kinks to review")
    
    # Build review items
    items = []
    for kink in kinks:
        for section in kink.get("pageSections", []):
            if section.get("content"):
                items.append({
                    "kinkId": kink["id"],
                    "name": kink["name"],
                    "sectionKey": section["sectionKey"],
                    "content": section["content"]
                })
    
    if not items:
        print("No sections to review")
        return
    
    print(f"Reviewing {len(items)} sections...")
    result = call_runpod("batch_review", {"items": items}, timeout=600)
    
    if result and "reviews" in result:
        reviews = result["reviews"]
        issues = [r for r in reviews if not r.get("approved", True)]
        print(f"[OK] Reviewed {len(reviews)} sections, {len(issues)} issues found")
        
        if issues:
            print("\nIssues:")
            for issue in issues[:5]:
                print(f"  - {issue.get('kinkId', '?')}/{issue.get('sectionKey', '?')}: {issue.get('issues', [])}")
    else:
        print("[ERROR] Review failed")


# =============================================================================
# MAIN
# =============================================================================

def print_usage():
    print("Usage: python orchestrator.py <command> [args]")
    print("")
    print("Commands:")
    print("  health           Check endpoint health")
    print("  generate [N]     Generate sections for N kinks (default: 10)")
    print("  review [N]       Review N processed kinks (default: 5)")
    print("")
    print("Environment:")
    print(f"  RUNPOD_ENDPOINT_ID = {RUNPOD_ENDPOINT_ID or '(not set)'}")
    print(f"  PLEASANCE_API      = {PLEASANCE_API}")
    print(f"  AGENT_SECRET       = {'(set)' if AGENT_SECRET else '(not set)'}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print_usage()
        sys.exit(1)
    
    command = sys.argv[1].lower()
    
    if command == "health":
        cmd_health()
    elif command == "generate":
        count = int(sys.argv[2]) if len(sys.argv) > 2 else 10
        cmd_generate(count)
    elif command == "review":
        count = int(sys.argv[2]) if len(sys.argv) > 2 else 5
        cmd_review(count)
    else:
        print(f"Unknown command: {command}")
        print_usage()
        sys.exit(1)
