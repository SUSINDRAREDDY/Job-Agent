#!/usr/bin/env python3
"""
Fetch LangSmith trace data and save to JSON for debugging.

Usage:
    python fetch_langsmith_trace.py <run_id_or_url>
    
Example:
    python fetch_langsmith_trace.py e220e2c9-938b-462a-bf26-47dd24ecc870
    python fetch_langsmith_trace.py "https://smith.langchain.com/public/e220e2c9-938b-462a-bf26-47dd24ecc870/r"
"""

import os
import sys
import json
import re
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()


def extract_run_id(url_or_id: str) -> str:
    """Extract run ID from URL or return as-is if already an ID."""
    # Pattern for LangSmith URLs
    # https://smith.langchain.com/public/e220e2c9-938b-462a-bf26-47dd24ecc870/r
    # https://smith.langchain.com/o/org-id/projects/p/project-id/r/run-id
    uuid_pattern = r'[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}'
    
    if url_or_id.startswith('http'):
        # Extract UUID from URL - get the last UUID in the path
        matches = re.findall(uuid_pattern, url_or_id)
        if matches:
            return matches[-1] if '/r' in url_or_id else matches[0]
    
    # Check if it's already a UUID
    if re.match(f'^{uuid_pattern}$', url_or_id):
        return url_or_id
    
    raise ValueError(f"Could not extract run ID from: {url_or_id}")


def run_to_dict(run) -> dict:
    """Convert a LangSmith Run object to a serializable dict."""
    return {
        "id": str(run.id),
        "name": run.name,
        "run_type": run.run_type,
        "status": run.status,
        "start_time": run.start_time.isoformat() if run.start_time else None,
        "end_time": run.end_time.isoformat() if run.end_time else None,
        "inputs": run.inputs,
        "outputs": run.outputs,
        "error": run.error,
        "parent_run_id": str(run.parent_run_id) if run.parent_run_id else None,
        "trace_id": str(run.trace_id) if run.trace_id else None,
        "extra": run.extra,
        "events": run.events,
        "tags": run.tags,
    }


def fetch_trace(run_id: str, include_children: bool = True, is_public: bool = True) -> dict:
    """
    Fetch a trace from LangSmith by run ID.
    
    Args:
        run_id: The run ID to fetch
        include_children: If True, fetch all child runs (full trace tree)
        is_public: If True, fetch using public share API
    
    Returns:
        Dict with trace data
    """
    import requests
    from langsmith import Client
    
    client = Client()
    
    print(f"Fetching run: {run_id}")
    
    # For public traces, use the public API
    if is_public:
        print("   Trying public share API...")
        # Public traces are accessible via share token
        public_url = f"https://api.smith.langchain.com/public/{run_id}/run"
        try:
            resp = requests.get(public_url)
            if resp.status_code == 200:
                run_data = resp.json()
                result = {
                    "trace_id": run_id,
                    "root_run": run_data,
                    "child_runs": [],
                    "fetched_at": datetime.now().isoformat(),
                    "source": "public_api"
                }
                
                # Fetch child runs from public API
                if include_children:
                    children_url = f"https://api.smith.langchain.com/public/{run_id}/runs"
                    children_resp = requests.get(children_url)
                    if children_resp.status_code == 200:
                        children_data = children_resp.json()
                        if isinstance(children_data, list):
                            result["child_runs"] = children_data
                        elif isinstance(children_data, dict) and "runs" in children_data:
                            result["child_runs"] = children_data["runs"]
                    print(f"   Found {len(result['child_runs'])} child runs")
                
                return result
            else:
                print(f"   Public API returned {resp.status_code}: {resp.text}")
        except Exception as e:
            print(f"   Public API error: {e}")
    
    # Fall back to authenticated API
    print("   Trying authenticated API...")
    try:
        main_run = client.read_run(run_id)
    except Exception as e:
        print(f"Error fetching run: {e}")
        print("Make sure your LANGCHAIN_API_KEY is set and the run ID is correct.")
        raise
    
    result = {
        "trace_id": str(main_run.trace_id) if main_run.trace_id else run_id,
        "root_run": run_to_dict(main_run),
        "child_runs": [],
        "fetched_at": datetime.now().isoformat(),
        "source": "authenticated_api"
    }
    
    if include_children:
        print(f"Fetching child runs for trace: {main_run.trace_id or run_id}")
        
        # Fetch ALL runs in this trace (no filters to get everything)
        child_runs = list(client.list_runs(
            trace_id=main_run.trace_id or run_id,
        ))
        
        print(f"   Found {len(child_runs)} runs in trace")
        
        for run in child_runs:
            if str(run.id) != run_id:  # Don't duplicate root
                result["child_runs"].append(run_to_dict(run))
    
    return result


def format_trace_summary(trace_data: dict) -> str:
    """Create a readable summary of the trace."""
    lines = ["=" * 60, "TRACE SUMMARY", "=" * 60, ""]
    
    root = trace_data["root_run"]
    lines.append(f"Root Run: {root['name']} ({root['run_type']})")
    lines.append(f"Status: {root['status']}")
    lines.append(f"Start: {root['start_time']}")
    lines.append(f"End: {root['end_time']}")
    
    if root.get("error"):
        lines.append(f"\nERROR: {root['error']}")
    
    # Calculate Token Usage & Throughput
    total_tokens = 0
    total_duration = 0.0
    
    # Scan child runs for usage
    usage_list = []
    for child in trace_data.get("child_runs", []):
        if child.get("outputs") and isinstance(child["outputs"], dict):
            llm_output = child["outputs"].get("llm_output", {})
            if llm_output and "token_usage" in llm_output:
                usage = llm_output["token_usage"]
                total_tokens += usage.get("total_tokens", 0)
                usage_list.append(usage)
        
        # Calculate duration if available
        if child.get("start_time") and child.get("end_time"):
            try:
                start = datetime.fromisoformat(child["start_time"])
                end = datetime.fromisoformat(child["end_time"])
                duration = (end - start).total_seconds()
                total_duration += duration
            except:
                pass

    lines.append("\n" + "-" * 40)
    lines.append("METRICS")
    lines.append("-" * 40)
    lines.append(f"Total Tokens: {total_tokens}")
    if total_duration > 0:
        tps = total_tokens / total_duration
        lines.append(f"Est. Throughput: {tps:.2f} tokens/sec")
    
    lines.append("\n" + "-" * 40)
    lines.append("CHILD RUNS (Tool Calls & Sub-agents)")
    lines.append("-" * 40)
    
    for i, child in enumerate(trace_data.get("child_runs", []), 1):
        status_icon = "[OK]" if child["status"] == "success" else "[ERR]" if child["status"] == "error" else "[...]"
        lines.append(f"\n{i}. {status_icon} {child['name']} ({child['run_type']})")
        
        # Show inputs summary
        if child.get("inputs"):
            inputs = child["inputs"]
            if isinstance(inputs, dict):
                for k, v in inputs.items():
                    v_str = str(v)
                    lines.append(f"   Input[{k}]: {v_str}")
        
        # Show outputs summary
        if child.get("outputs"):
            outputs = child["outputs"]
            if isinstance(outputs, dict):
                for k, v in outputs.items():
                    v_str = str(v)
                    lines.append(f"   Output[{k}]: {v_str}")
        
        # Show errors
        if child.get("error"):
            lines.append(f"   Error: {child['error']}")
    
    lines.append("\n" + "=" * 60)
    return "\n".join(lines)


def main():
    try:
        run_id = "019b8515-173f-7c43-ae01-8e32fd821043"
        print(f"Extracted run ID: {run_id}")
    except ValueError as e:
        print(f"{e}")
        return
    
    # Fetch the trace
    try:
        trace_data = fetch_trace(run_id, include_children=True)
    except Exception as e:
        print(f"Failed to fetch trace: {e}")
        return
    
    # Save to JSON
    os.makedirs("logs/traces", exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = f"logs/traces/trace_{run_id}_{timestamp}.json"  # Save to JSON
    
    with open(json_path, "w") as f:
        json.dump(trace_data, f, indent=2, default=str)
    
    print(f"\nTrace saved to: {json_path}")
    
    # Print summary
    summary = format_trace_summary(trace_data)
    print(summary)
    
    # Also save summary
    summary_path = json_path.replace(".json", "_summary.txt")
    with open(summary_path, "w") as f:
        f.write(summary)
    print(f"Summary saved to: {summary_path}")


if __name__ == "__main__":
    main()
