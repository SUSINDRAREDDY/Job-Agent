"""
Job Filtering Agent - General-purpose browser automation agent.

Architecture:
- Orchestrator: Receives user intent, delegates to browser_agent
- Browser Agent: 12 general-purpose tools for any web automation task

NOTE: Uses create_lean_deep_agent (forked from deepagents) to remove 
TodoListMiddleware and save ~6000 tokens per task.
"""
import os
import asyncio
import atexit
from dotenv import load_dotenv

# LangChain imports for lean agent
from langchain.agents import create_agent
from langchain.agents.middleware.summarization import SummarizationMiddleware
from deepagents.backends import FilesystemBackend
from deepagents.middleware.filesystem import FilesystemMiddleware
from deepagents.middleware.subagents import SubAgentMiddleware
from deepagents.middleware.patch_tool_calls import PatchToolCallsMiddleware

from config import get_default_llm
from prompts import (
    BROWSER_AGENT_PROMPT,
    ORCHESTRATOR_AND_APPLY_PROMPT,
    STANDALONE_APPLY_AGENT_PROMPT
)



from browser.playwright_tools import (
    # Navigation (3)
    navigate_to_url,
    scroll_page,
    wait_seconds,
    
    # Coordinate-based interaction
    click_at,
    type_at,
    press_key,
    
    # Scanning (2)
    get_page_elements,    # Lean scan - links, buttons, inputs
    
    # JavaScript (1)
    execute_javascript,
    
    # Vision (1)
    analyze_page_visually,
    
    # Tab management (3)
    list_browser_tabs,
    switch_to_tab,
    close_current_tab,
    
    # Batching tools (2) - Reduce LLM round-trips
    execute_action_sequence,  # Batch multiple clicks/types/presses
    fill_form,                # Fill multiple form fields at once
    
    # Element ref tools (2) - WeakRef-based stable element references
    form_input,               # Smart form filling by ref (dropdowns, checkboxes, etc.)
    get_element_by_ref,       # Get fresh coordinates for a ref after scrolling
    extract_jobs,             # Dedicated job extraction tool
)

load_dotenv()


def create_lean_deep_agent(
    model,
    tools=None,
    system_prompt=None,
    subagents=None,
    backend=None,
    debug=False,
):
    """
    Lean version of create_deep_agent WITHOUT TodoListMiddleware.
    
    Keeps:
    - SubAgentMiddleware (for subagents like browser_agent, apply_agent, future resume_agent, etc.)
    - FilesystemMiddleware (for file operations)
    - SummarizationMiddleware (for context management)
    
    Removes:
    - TodoListMiddleware (saves ~6000 tokens per task!)
    
    This is a fork of deepagents.create_deep_agent with TodoListMiddleware removed.
    """
    # Summarization config - Use HIGHER threshold to avoid eating initial task messages
    # The subagent needs to keep the task description intact for the first few turns
    trigger = ("tokens", 10000)   # Summarize when context exceeds 10K tokens
    keep = ("messages", 6)        # Keep last 6 messages to retain task context
    
    # Subagent middleware - NO FilesystemMiddleware!
    # Browser/apply agents should ONLY have browser tools, not filesystem tools
    subagent_middleware = [
        PatchToolCallsMiddleware(),
        # NO FilesystemMiddleware here - was causing browser agents to use ls/glob!
        # Summarization LAST - only runs after several tool calls
        SummarizationMiddleware(
            model=model,
            trigger=trigger,
            keep=keep, trim_tokens_to_summarize=2000
        ),
    ]
    
    # Lean middleware stack - NO TodoListMiddleware!
    lean_middleware = [
        # Keep: File operations
        FilesystemMiddleware(backend=backend),
        
        # Keep: Subagent support (for browser_agent, apply_agent, future agents)
        SubAgentMiddleware(
            default_model=model,
            default_tools=tools,
            subagents=subagents or [],
            default_middleware=subagent_middleware,
            general_purpose_agent=True,
        ),
        
        # Keep: Context summarization for orchestrator (reduces bloat)
        SummarizationMiddleware(
            model=model,
            trigger=trigger,
            keep=keep,trim_tokens_to_summarize=1000
        ),
        PatchToolCallsMiddleware(),
    ]

    
    return create_agent(
        model,
        system_prompt=system_prompt,
        tools=tools,
        middleware=lean_middleware,
        debug=debug,
    ).with_config({"recursion_limit": 100})



def create_browser_agent():
    """
    Creates a general-purpose browser automation agent.
    
    Uses 12 tools for any web task - no domain-specific hardcoding.
    Uses create_lean_deep_agent to avoid TodoListMiddleware token bloat.
    """
    llm = get_default_llm()  # Use default temperature (1.0 for Kimi K2)
    
    project_root = os.path.abspath(".")
    os.makedirs(os.path.join(project_root, "logs"), exist_ok=True)

    local_backend = FilesystemBackend(root_dir=project_root)
    print(f"FilesystemBackend: {project_root}")


    # All 19 general-purpose browser tools (including element ref tools)
    browser_tools = [
        # Navigation (3)
        navigate_to_url,
        scroll_page,
        wait_seconds,
        
        # Coordinate-based interaction (3) - PREFERRED
        click_at,
        type_at,
        press_key,
        
        # Scanning (1)
        get_page_elements,    # Lean scan - use this first

        # JavaScript (1)
        execute_javascript,
        extract_jobs,  # Dedicated job extraction tool
        
        # Vision (1)
        analyze_page_visually,
        
        # Tab management (3)
        list_browser_tabs,
        switch_to_tab,
        close_current_tab,
        
        # Batching tools (2) - HIGHLY EFFICIENT, use these!
        execute_action_sequence,  # Batch multiple clicks/types/presses
        fill_form,                # Fill multiple form fields at once
        
        # Element ref tools (2) - Smart form handling by ref
        form_input,               # Fill dropdowns, checkboxes, radios by ref
        get_element_by_ref,       # Get fresh coords after scroll/DOM change
    ]
    
    # Create a model configured for sequential tool calls (required for Playwright threading)
    # Don't pre-bind tools - let deepagents handle that internally
    browser_model_config = llm.bind(parallel_tool_calls=False)
    
    browser_subagent = {
        "name": "browser_agent",
        "description": "General-purpose browser automation. Navigates, scans, clicks, types. Uses accessibility-based refs. INPUT: what to do. OUTPUT: result.",
        "system_prompt": BROWSER_AGENT_PROMPT,
        "model": browser_model_config,  # Pass configured model, not pre-bound with tools
        "tools": browser_tools,
    }
    
    # Apply agent uses same tools (no domain-specific tools)
    apply_model_config = llm.bind(parallel_tool_calls=False)
    
    apply_subagent = {
        "name": "apply_agent",
        "description": "Fills out forms and submits applications. Uses same tools as browser_agent.",
        "system_prompt": STANDALONE_APPLY_AGENT_PROMPT,
        "model": apply_model_config,  # Pass configured model, not pre-bound with tools
        "tools": browser_tools,
    }

    # Use LEAN agent - no TodoListMiddleware = saves ~6000 tokens!
    # FORCE sequential tools on the orchestrator too
    orchestrator_model = llm.bind(parallel_tool_calls=False)
    
    agent = create_lean_deep_agent(
        model=orchestrator_model,
        tools=[],
        subagents=[browser_subagent, apply_subagent],
        backend=local_backend,
        system_prompt=ORCHESTRATOR_AND_APPLY_PROMPT,
        debug=True
    )
    
    return agent



async def connect_to_browser_async():
    """Connect to browser asynchronously."""
    from browser.playwright_manager import get_playwright_manager
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, lambda: get_playwright_manager().connect())


async def close_browser_async():
    """Close browser asynchronously."""
    from browser.playwright_manager import _cleanup_all_managers
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _cleanup_all_managers)


def connect_to_browser():
    """Sync wrapper."""
    return asyncio.get_event_loop().run_until_complete(connect_to_browser_async())


def close_browser():
    """Sync wrapper."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.ensure_future(close_browser_async())
        else:
            loop.run_until_complete(close_browser_async())
    except Exception:
        pass


def _cleanup():
    try:
        from browser.playwright_manager import _cleanup_all_managers
        _cleanup_all_managers()
    except Exception:
        pass

atexit.register(_cleanup)
