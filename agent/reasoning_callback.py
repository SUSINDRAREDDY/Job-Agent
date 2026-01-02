"""
Reasoning Content Callback Handler
===================================
Simple callback to display reasoning tokens in console.
Does NOT modify LangSmith runs to avoid interference.
"""

from typing import Any, Dict, List, Optional
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult


class ReasoningCallbackHandler(BaseCallbackHandler):
    """
    Callback handler that extracts reasoning tokens from LLM responses
    and logs them to console. Read-only - does not modify runs.
    """
    
    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self.reasoning_log = []
    
    def on_llm_end(
        self,
        response: LLMResult,
        *,
        run_id,
        parent_run_id = None,
        **kwargs: Any,
    ) -> None:
        """
        Called when LLM finishes. Extract and display reasoning tokens.
        """
        try:
            for gen_list in response.generations:
                for gen in gen_list:
                    reasoning_tokens = 0
                    
                    msg = getattr(gen, 'message', None)
                    if msg:
                        # Check response_metadata for reasoning tokens
                        response_meta = getattr(msg, 'response_metadata', {}) or {}
                        token_usage = response_meta.get('token_usage', {})
                        
                        # OpenRouter format: completion_tokens_details.reasoning_tokens
                        completion_details = token_usage.get('completion_tokens_details', {})
                        reasoning_tokens = completion_details.get('reasoning_tokens', 0)
                        
                        # Also check usage_metadata (LangChain format)
                        if not reasoning_tokens:
                            usage_meta = getattr(msg, 'usage_metadata', {}) or {}
                            output_details = usage_meta.get('output_token_details', {})
                            reasoning_tokens = output_details.get('reasoning', 0)
                    
                    # Display in console
                    if reasoning_tokens and self.verbose:
                        print(f"💭 Reasoning tokens: {reasoning_tokens}")
                        
                        self.reasoning_log.append({
                            'run_id': str(run_id),
                            'reasoning_tokens': reasoning_tokens,
                        })
                            
        except Exception as e:
            if self.verbose:
                print(f"Error extracting reasoning: {e}")
    
    def get_reasoning_log(self) -> List[Dict]:
        """Return all captured reasoning info."""
        return self.reasoning_log


def get_reasoning_callback(verbose: bool = True) -> ReasoningCallbackHandler:
    """Create a reasoning callback handler."""
    return ReasoningCallbackHandler(verbose=verbose)
