"""
Pleasance RunPod Worker

Local LLM worker for bulk content generation.
Runs on RunPod with GPU for fast inference.

Usage:
  1. Create RunPod pod with vLLM template
  2. Set environment variables
  3. Run: python worker.py
"""

import os
import time
import requests
from typing import List, Dict, Optional

# Configuration
API_URL = os.environ.get("PLEASANCE_API", "https://api.pleasance.app")
AGENT_SECRET = os.environ["AGENT_SECRET"]
AGENT_ID = os.environ.get("AGENT_ID", f"runpod-worker-{os.getpid()}")
MODEL = os.environ.get("MODEL", "meta-llama/Llama-3.1-70B-Instruct")
BATCH_SIZE = int(os.environ.get("BATCH_SIZE", "10"))

# Headers for API requests
HEADERS = {
    "X-Agent-Key": AGENT_SECRET,
    "X-Agent-Id": AGENT_ID,
    "Content-Type": "application/json"
}

# Section prompts (customize as needed)
SECTION_PROMPTS = {
    "appeal": "Write a compelling 2-3 paragraph description of why people find '{name}' appealing. Focus on psychological and sensory aspects.",
    "howTo": "Write a practical guide for safely exploring '{name}' as beginners. Include safety considerations and communication tips.",
    "variations": "Describe 3-5 common variations or related practices to '{name}'. Be specific but tasteful.",
}


def get_queue(limit: int = BATCH_SIZE) -> List[Dict]:
    """Fetch unprocessed kinks from API."""
    try:
        resp = requests.get(
            f"{API_URL}/api/bulk/queue",
            params={"type": "kink", "processed": "false", "limit": limit},
            headers=HEADERS,
            timeout=30
        )
        resp.raise_for_status()
        return resp.json().get("items", [])
    except requests.RequestException as e:
        print(f"[ERROR] Failed to fetch queue: {e}")
        return []


def generate_section(llm, kink: Dict, section_key: str) -> Optional[str]:
    """Generate a section using vLLM."""
    prompt_template = SECTION_PROMPTS.get(section_key)
    if not prompt_template:
        return None
    
    prompt = prompt_template.format(name=kink["name"], category=kink.get("category", ""))
    
    # vLLM inference
    from vllm import SamplingParams
    sampling_params = SamplingParams(
        temperature=0.7,
        max_tokens=1024,
        top_p=0.9
    )
    
    outputs = llm.generate([prompt], sampling_params)
    return outputs[0].outputs[0].text.strip()


def push_sections(sections: List[Dict]) -> bool:
    """Push generated sections to API."""
    try:
        resp = requests.post(
            f"{API_URL}/api/bulk/sections",
            json={"sections": sections},
            headers=HEADERS,
            timeout=60
        )
        resp.raise_for_status()
        result = resp.json()
        print(f"[OK] Pushed {result.get('upserted', 0)} sections")
        return True
    except requests.RequestException as e:
        print(f"[ERROR] Failed to push sections: {e}")
        return False


def mark_processed(ids: List[str]) -> bool:
    """Mark kinks as processed."""
    try:
        resp = requests.post(
            f"{API_URL}/api/bulk/mark-processed",
            json={"type": "kink", "ids": ids},
            headers=HEADERS,
            timeout=30
        )
        resp.raise_for_status()
        return True
    except requests.RequestException as e:
        print(f"[ERROR] Failed to mark processed: {e}")
        return False


def process_batch(llm) -> int:
    """Process one batch of kinks."""
    queue = get_queue()
    if not queue:
        print("[INFO] Queue empty")
        return 0
    
    print(f"[INFO] Processing {len(queue)} kinks...")
    sections = []
    processed_ids = []
    
    for kink in queue:
        kink_id = kink["id"]
        kink_name = kink["name"]
        print(f"  → {kink_name}")
        
        for section_key in SECTION_PROMPTS.keys():
            try:
                content = generate_section(llm, kink, section_key)
                if content:
                    sections.append({
                        "kinkId": kink_id,
                        "sectionKey": section_key,
                        "content": content,
                        "model": MODEL
                    })
            except Exception as e:
                print(f"    [ERROR] {section_key}: {e}")
        
        processed_ids.append(kink_id)
    
    # Push sections
    if sections:
        push_sections(sections)
    
    # Mark as processed
    if processed_ids:
        mark_processed(processed_ids)
    
    return len(processed_ids)


def main():
    """Main worker loop."""
    print(f"=== Pleasance RunPod Worker ===")
    print(f"API: {API_URL}")
    print(f"Agent: {AGENT_ID}")
    print(f"Model: {MODEL}")
    print(f"Batch size: {BATCH_SIZE}")
    print()
    
    # Initialize vLLM
    from vllm import LLM
    print("[INFO] Loading model...")
    llm = LLM(model=MODEL, tensor_parallel_size=1)
    print("[OK] Model loaded")
    
    # Process until queue empty
    total_processed = 0
    while True:
        processed = process_batch(llm)
        if processed == 0:
            break
        total_processed += processed
        time.sleep(1)  # Brief pause between batches
    
    print(f"\n[DONE] Processed {total_processed} kinks")


if __name__ == "__main__":
    main()
