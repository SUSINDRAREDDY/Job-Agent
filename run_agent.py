import sys
import os
import json
import argparse
from dotenv import load_dotenv

# Load env variables (API Keys)
load_dotenv()

from agent.browser_agent import create_browser_agent
from agent.intent_parser import parse_user_query
from agent.reasoning_callback import get_reasoning_callback
from prompts import SEARCH_TASK_TEMPLATE, APPLY_TASK_TEMPLATE
from browser.playwright_tools import reset_extraction_session


def load_user_data():
    """Load user data for form filling."""
    user_data_path = os.path.join(os.path.dirname(__file__), "user_data.json")
    if os.path.exists(user_data_path):
        with open(user_data_path, "r") as f:
            return json.load(f)
    return {}


def main():
    parser = argparse.ArgumentParser(description="Job Search & Apply Agent")
    parser.add_argument("query", help="Your job search query")
    parser.add_argument("url", nargs="?", default="https://www.indeed.com/jobs", 
                        help="Target job site URL (default: Indeed)")
    parser.add_argument("--max-jobs", type=int, default=3,
                        help="Maximum number of jobs to apply to (default: 3)")
    
    args = parser.parse_args()
    
    user_query = args.query
    start_url = args.url
    max_jobs = args.max_jobs
    
    print(f"\nParsing Query: '{user_query}'...")
    
    reset_extraction_session()
    
    try:
        intent = parse_user_query(user_query)
        print(f"Intent Extracted: {intent.model_dump_json()}")
    except Exception as e:
        print(f"Failed to parse intent: {e}")
        return

    user_data = load_user_data()
    if user_data:
        print(f"User data loaded: {list(user_data.keys())}")
    else:
        print("No user_data.json found - agent will skip form fields it can't fill")

    print("\nBrowser will connect when agent starts working...")
    print("Agent will decide whether to search-only or search+apply based on query")

    print("\nInitializing Agent...")
    try:
        agent = create_browser_agent()
        
        # Build task message - always include user data, agent decides what to do
        user_data_str = json.dumps(user_data, indent=2) if user_data else "{}"
        task_message = APPLY_TASK_TEMPLATE.format(
            user_query=user_query,
            start_url=start_url,
            max_jobs=max_jobs,
            intent_json=intent.model_dump_json(indent=2),
            user_data_json=user_data_str
        )

        
        print("\nRunning Agent Loop...")
        
        reasoning_callback = get_reasoning_callback(verbose=True)
        
        result = agent.invoke(
            {"messages": [{"role": "user", "content": task_message}]},
            config={
                "callbacks": [reasoning_callback],
            }
        )
        print("\nAgent Finished.")
        
        final_content = result['messages'][-1].content
        
        # Handle case where content is a list (Grok returns reasoning blocks)
        if isinstance(final_content, list):
            # Extract just the text parts
            text_parts = [item.get('text', '') for item in final_content if isinstance(item, dict) and 'text' in item]
            final_text = '\n'.join(text_parts)
        else:
            final_text = str(final_content)
        
        print(f"Final Response: {final_text}")
        
        # LOGGING: Save final response
        from datetime import datetime
        os.makedirs("logs", exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        mode_suffix = "_apply"  # Always apply mode now
        log_file = f"logs/agent_response_{timestamp}{mode_suffix}.txt"
        with open(log_file, "w") as f:
            f.write(f"User Query: {user_query}\n")
            f.write(f"Mode: APPLY\n")
            f.write(f"Parsed Intent: {intent.model_dump_json()}\n")
            f.write("-" * 20 + "\n")
            f.write(final_text)
        print(f"Saved Agent Response to {log_file}")
        
    except Exception as e:
        print(f"Agent Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
