"""Centralized LLM configuration for the Job Agent.

Supports multiple LLM backends:
- MiniMax M2 via OpenRouter (default) - efficient reasoning model with 196K context
- DeepSeek Reasoner (available) - requires special reasoning_content handling
"""

import os
from typing import Any
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

load_dotenv()

# OPENROUTER CONFIGURATION (PRIMARY)

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

MAIN_MODEL = "minimax/minimax-m2.1"

# Vision model for screenshot analysis
VISION_MODEL = "x-ai/grok-4.1-fast"

# DEEPSEEK CONFIGURATION (AVAILABLE BUT NOT DEFAULT)

DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = "deepseek-reasoner"


def get_openrouter_api_key() -> str:
    """Get the OpenRouter API key."""
    return os.getenv("OPENROUTER_API_KEY")


def get_deepseek_api_key() -> str:
    """Get the DeepSeek API key."""
    return os.getenv("DEEPSEEK_API_KEY")



def get_default_llm(temperature: float = 0.7) -> Any:
    """Get the default LLM based on MAIN_MODEL.
    
    - For DeepSeek models: Use DeepSeekReasoner (handles reasoning_content)
    - For GLM models: Use GLMReasoner (handles reasoning field)
    - For other models (Minimax, etc.): Use standard ChatOpenAI
    
    Returns:
        Configured LLM instance
    """

    if "deepseek" in MAIN_MODEL.lower():
        from models.deepseek_reasoner import DeepSeekReasoner
        return DeepSeekReasoner(
            model=MAIN_MODEL,
            temperature=temperature,
            api_key=get_openrouter_api_key(),
            base_url=OPENROUTER_BASE_URL,
        )
    
    if "glm" in MAIN_MODEL.lower():
        from models.glm_reasoner import GLMReasoner
        return GLMReasoner(
            model=MAIN_MODEL,
            temperature=temperature,
            api_key=get_openrouter_api_key(),
            base_url=OPENROUTER_BASE_URL,
        )
    
    # MiniMax models: Use MinimaxReasoner which handles duplicated JSON in tool calls
    if "minimax" in MAIN_MODEL.lower():
        from models.minimax_reasoner import MinimaxReasoner
        return MinimaxReasoner(
            model=MAIN_MODEL,
            temperature=temperature,
            api_key=get_openrouter_api_key(),
            base_url=OPENROUTER_BASE_URL,
        )
    
    # Default: Use standard ChatOpenAI for other OpenRouter-compatible models
    return ChatOpenAI(
        model=MAIN_MODEL,
        temperature=temperature,
        api_key=get_openrouter_api_key(),
        base_url=OPENROUTER_BASE_URL,
        default_headers={
            "HTTP-Referer": "https://github.com/SUSINDRAREDDY/Job-Agent",
            "X-Title": "Job Agent"
        },
        extra_body={
            "provider": {
                "sort": "throughput",
            }
        }
    )


def get_deepseek_llm(temperature: float = 0) -> "DeepSeekReasoner":
    """DeepSeek Reasoner via direct DeepSeek API.
    
    Uses custom wrapper that handles reasoning_content for tool calling.
    NOTE: Not currently used - MiniMax M2 is the default.
    
    Args:
        temperature: Sampling temperature (0 = deterministic)
    
    Returns:
        Configured DeepSeekReasoner instance
    """
    from models.deepseek_reasoner import DeepSeekReasoner
    
    return DeepSeekReasoner(
        model=DEEPSEEK_MODEL,
        api_key=get_deepseek_api_key(),
        base_url=DEEPSEEK_BASE_URL,
        temperature=temperature,
    )


def get_vision_llm(max_tokens: int = 1024) -> ChatOpenAI:
    """LLM for vision/screenshot analysis via OpenRouter.
    
    DeepSeek doesn't support vision, so we use Grok via OpenRouter.
    
    Args:
        max_tokens: Maximum tokens in response
    
    Returns:
        Configured ChatOpenAI instance for vision tasks
    """
    return ChatOpenAI(
        model=VISION_MODEL,
        max_tokens=max_tokens,
        api_key=get_openrouter_api_key(),
        base_url=OPENROUTER_BASE_URL,
        default_headers={
            "HTTP-Referer": "https://github.com/job-agent",
            "X-Title": "Job Agent"
        }
    )
