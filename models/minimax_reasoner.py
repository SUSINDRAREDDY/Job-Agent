"""
Custom MiniMax M2.1 Reasoner wrapper for LangChain.

MiniMax via OpenRouter sometimes produces duplicated JSON in tool call arguments,
e.g., `{"arg": "val"}{"arg": "val"}` which is invalid JSON.

This wrapper fixes such issues by:
1. Detecting duplicated JSON objects
2. Recovering the first valid JSON object
3. Handling the response properly
"""

from typing import Any, Dict, List, Optional
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import (
    AIMessage, 
    BaseMessage, 
    HumanMessage, 
    SystemMessage, 
    ToolMessage,
)
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.callbacks import CallbackManagerForLLMRun
from openai import OpenAI
import os
import json
import re
import uuid


def _fix_duplicated_json(args_str: str) -> Dict:
    """
    Fix duplicated JSON in tool call arguments.
    
    MiniMax sometimes outputs: {"a": "b"}{"a": "b"}
    This function extracts the first valid JSON object.
    
    Returns:
        Parsed dict from the first valid JSON object
    """
    args_str = args_str.strip()
    
    # First, try to parse as-is (maybe it's valid JSON)
    try:
        return json.loads(args_str)
    except json.JSONDecodeError:
        pass
    
    # Try to find the first complete JSON object
    # Strategy: find the first "{" and match braces until the first "}"
    brace_count = 0
    start_idx = None
    
    for i, char in enumerate(args_str):
        if char == '{':
            if start_idx is None:
                start_idx = i
            brace_count += 1
        elif char == '}':
            brace_count -= 1
            if brace_count == 0 and start_idx is not None:
                # Found a complete JSON object
                candidate = args_str[start_idx:i+1]
                try:
                    result = json.loads(candidate)
                    print(f"[MinimaxReasoner] Fixed duplicated JSON: extracted first object from malformed input")
                    return result
                except json.JSONDecodeError:
                    # Keep looking
                    start_idx = None
                    continue
    
    # If we couldn't parse anything, raise an error
    raise json.JSONDecodeError(f"Could not extract valid JSON from: {args_str[:100]}...", args_str, 0)


class MinimaxReasoner(BaseChatModel):
    """
    Custom LangChain wrapper for MiniMax M2.1 with malformed tool call recovery.
    
    Why this is needed:
    1. MiniMax sometimes duplicates JSON in tool call arguments
    2. Standard ChatOpenAI doesn't handle this gracefully
    3. We need to extract the first valid JSON object
    """
    
    client: Any = None
    model: str = "minimax/minimax-m2.1"
    temperature: float = 0.7
    api_key: Optional[str] = None
    base_url: str = "https://openrouter.ai/api/v1"
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.client = OpenAI(
            api_key=self.api_key or os.getenv("OPENROUTER_API_KEY"),
            base_url=self.base_url,
            default_headers={
                "HTTP-Referer": "https://github.com/job-agent",
                "X-Title": "Job Agent"
            }
        )
    
    @property
    def _llm_type(self) -> str:
        return "minimax-reasoner"
        
    @property
    def model_name(self) -> str:
        return self.model
    
    @property
    def _identifying_params(self) -> Dict[str, Any]:
        return {"model": self.model, "temperature": self.temperature}
    
    def _convert_messages_to_openai_format(self, messages: List[BaseMessage]) -> List[Dict]:
        """Convert LangChain messages to OpenAI format."""
        openai_messages = []
        
        for msg in messages:
            if isinstance(msg, SystemMessage):
                openai_messages.append({"role": "system", "content": msg.content})
            
            elif isinstance(msg, HumanMessage):
                openai_messages.append({"role": "user", "content": msg.content})
            
            elif isinstance(msg, AIMessage):
                content = msg.content or ""
                ai_msg = {"role": "assistant", "content": content}
                
                # Handle tool calls
                if msg.tool_calls:
                    ai_msg["tool_calls"] = [
                        {
                            "id": tc["id"],
                            "type": "function",
                            "function": {
                                "name": tc["name"],
                                "arguments": json.dumps(tc["args"]) if isinstance(tc["args"], dict) else str(tc["args"])
                            }
                        }
                        for tc in msg.tool_calls
                    ]
                
                openai_messages.append(ai_msg)
            
            elif isinstance(msg, ToolMessage):
                openai_messages.append({
                    "role": "tool",
                    "tool_call_id": msg.tool_call_id,
                    "content": msg.content,
                })
        
        return openai_messages
    
    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs,
    ) -> ChatResult:
        """Generate a response from MiniMax M2.1."""
        
        openai_messages = self._convert_messages_to_openai_format(messages)
        
        # Build request params
        params = {
            "model": self.model,
            "messages": openai_messages,
        }

        # Handle temperature if not default
        if self.temperature is not None:
            params["temperature"] = self.temperature
        
        # Add tools if provided
        if "tools" in kwargs:
            params["tools"] = kwargs["tools"]
        
        if stop:
            params["stop"] = stop
            
        # Add OpenRouter specific parameters
        params["extra_body"] = {
            "provider": {
                "sort": "throughput",  # Prioritize highest throughput providers
            },
        }
        
        # Make the API call
        response = self.client.chat.completions.create(**params)
        
        choice = response.choices[0]
        message = choice.message
        
        # Extract content
        content = message.content or ""
        
        # Build additional_kwargs
        additional_kwargs = {}
            
        # Handle tool calls with malformed JSON recovery
        tool_calls = []
        invalid_tool_calls = []
        
        if message.tool_calls:
            for tc in message.tool_calls:
                try:
                    # Use our custom JSON fixer
                    args = _fix_duplicated_json(tc.function.arguments)
                    tool_calls.append({
                        "id": tc.id,
                        "name": tc.function.name,
                        "args": args,
                    })
                except Exception as e:
                    print(f"[MinimaxReasoner] Failed to parse tool call args: {e}")
                    print(f"[MinimaxReasoner] Raw args: {tc.function.arguments[:200]}...")
                    # Store as invalid tool call so LangGraph can handle it
                    invalid_tool_calls.append({
                        "id": tc.id,
                        "name": tc.function.name,
                        "args": tc.function.arguments,
                        "error": str(e),
                    })
        
        # Create usage dict
        token_usage = {}
        if response.usage:
            token_usage = {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            }
            # Try to find reasoning tokens
            completion_details = getattr(response.usage, "completion_tokens_details", None)
            if completion_details:
                reasoning_tokens = getattr(completion_details, "reasoning_tokens", 0)
                if reasoning_tokens:
                    token_usage["reasoning_tokens"] = reasoning_tokens

        # Create the AIMessage
        ai_message = AIMessage(
            content=content,
            additional_kwargs=additional_kwargs,
            tool_calls=tool_calls if tool_calls else [],
            invalid_tool_calls=invalid_tool_calls if invalid_tool_calls else [],
            response_metadata={
                "model_name": self.model,
                "finish_reason": choice.finish_reason,
                "token_usage": token_usage
            }
        )
        
        return ChatResult(
            generations=[ChatGeneration(message=ai_message)],
            llm_output={
                "token_usage": token_usage,
                "model_name": self.model,
            }
        )
    
    def bind_tools(self, tools: List, **kwargs) -> "MinimaxReasoner":
        """Bind tools to this model."""
        from langchain_core.utils.function_calling import convert_to_openai_tool
        
        openai_tools = [convert_to_openai_tool(t) for t in tools]
        
        # Return a new instance with tools bound
        return self.__class__(
            model=self.model,
            temperature=self.temperature,
            api_key=self.api_key,
            base_url=self.base_url,
        ).configurable_fields().bind(tools=openai_tools, **kwargs)
