"""
Custom GLM-4.7 Reasoner wrapper for LangChain.

GLM-4.7 via OpenRouter returns a `reasoning` field (or `reasoning_content`) that needs 
special handling to be visible in LangSmith and usable in agent loops.
"""

from typing import Any, Dict, List, Optional, Iterator
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import (
    AIMessage, 
    BaseMessage, 
    HumanMessage, 
    SystemMessage, 
    ToolMessage,
    AIMessageChunk,
)
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.callbacks import CallbackManagerForLLMRun
from openai import OpenAI
import os
import json
import re
import uuid


def _parse_xml_tool_calls(text: str) -> List[Dict]:
    """
    Parse malformed XML-style tool calls that GLM-4.7 sometimes outputs.
    
    Example malformed output:
    <tool_call>click_at<arg_key>x</arg_key><arg_value>1111</arg_value></tool_call>
    """
    tool_calls = []
    
    # Pattern to match <tool_call>...</tool_call>
    tool_call_pattern = r'<tool_call>(.*?)</tool_call>'
    
    # Pre-clean the text to handle "stuttered" tags like <tool_call>get<tool_call>...
    # This happens when the model outputs a partial tag then restarts
    cleaned_text = re.sub(r'<tool_call>.*?<tool_call>', '<tool_call>', text, flags=re.DOTALL)
    
    matches = re.findall(tool_call_pattern, cleaned_text, re.DOTALL)
    
    for match in matches:
        try:
            # Extract tool name (first word before any <arg_key>)
            name_match = re.match(r'^(\w+)', match.strip())
            if not name_match:
                continue
            tool_name = name_match.group(1)
            
            # Extract arg key-value pairs
            args = {}
            arg_pattern = r'<arg_key>(\w+)</arg_key><arg_value>([^<]+)</arg_value>'
            arg_matches = re.findall(arg_pattern, match)
            
            for key, value in arg_matches:
                # Try to convert to appropriate type
                try:
                    args[key] = int(value)
                except ValueError:
                    try:
                        args[key] = float(value)
                    except ValueError:
                        args[key] = value
            
            # Fix: Allow tools with no args (like get_page_elements)
            if tool_name:
                tool_calls.append({
                    "id": f"call_{uuid.uuid4().hex[:24]}",
                    "name": tool_name,
                    "args": args,
                })
                print(f"[GLMReasoner] Recovered XML tool call: {tool_name}({args})")
        except Exception as e:
            print(f"[GLMReasoner] Failed to parse XML tool call: {e}")
            continue
    
    return tool_calls


class GLMReasoner(BaseChatModel):
    """
    Custom LangChain wrapper for GLM-4.7 with proper reasoning handling/visibility.
    
    Why this is needed:
    1. Standard ChatOpenAI drops non-standard fields like 'reasoning'.
    2. We want to prepend the reasoning to the content for visibility (in <thinking> tags).
    3. We want to correctly capture 'reasoning_tokens' in usage metadata.
    """
    
    client: Any = None
    model: str = "z-ai/glm-4.7"
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
        return "glm-reasoner"
        
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
                # Clean content: remove reasoning fences if we added them previously
                content = msg.content or ""
                # Strip old XML-style thinking tags (for backwards compatibility)
                if "<thinking>" in content and "</thinking>" in content:
                    content = re.sub(r'<thinking>.*?</thinking>\s*', '', content, flags=re.DOTALL)
                # Strip new markdown-style reasoning fences
                if "---REASONING---" in content:
                    content = re.sub(r'---REASONING---.*?---END REASONING---\s*', '', content, flags=re.DOTALL)
                
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
        """Generate a response from GLM-4.7."""
        
        openai_messages = self._convert_messages_to_openai_format(messages)
        
        # Build request params
        params = {
            "model": self.model,
            "messages": openai_messages,
            # "temperature": self.temperature, # OpenRouter sometimes implies params via extra_body
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
            "reasoning": {"effort": "high"},
            "provider": {
            #     # "order": ["Baseten"],
            #     # "quantizations": ["fp4"],
                "sort": "throughput",  # Prioritize highest throughput providers
                # "allow_fallbacks": False
            },
        }
        
        # Make the API call (Non-streaming for safety first)
        response = self.client.chat.completions.create(**params)
        
        choice = response.choices[0]
        message = choice.message
        
        # Extract content
        raw_content = message.content or ""
        
        # Extract reasoning - OpenRouter GLM sends it in 'reasoning' field of message
        # OR sometimes in 'reasoning_content'
        reasoning_content = getattr(message, "reasoning", None) or getattr(message, "reasoning_content", None)
        
        # Build display content
        content = raw_content
        if reasoning_content:
            # Prepend reasoning for visibility - using markdown-style fences NOT XML
            # (XML tags like <thinking> confuse GLM into outputting XML tool calls)
            content = f"---REASONING---\n{reasoning_content}\n---END REASONING---\n\n{raw_content}"
        
        # Build additional_kwargs
        additional_kwargs = {}
        if reasoning_content:
            additional_kwargs["reasoning_content"] = reasoning_content
            
        # Handle tool calls
        tool_calls = []
        if message.tool_calls:
            for tc in message.tool_calls:
                try:
                    args = json.loads(tc.function.arguments)
                except:
                    args = tc.function.arguments
                tool_calls.append({
                    "id": tc.id,
                    "name": tc.function.name,
                    "args": args,
                })
        
        # FALLBACK: Check for XML-style tool calls in content/reasoning if none found
        # GLM sometimes outputs <tool_call>...</tool_call> instead of proper JSON
        if not tool_calls:
            # Check reasoning first, then content
            text_to_check = (reasoning_content or "") + (raw_content or "")
            if "<tool_call>" in text_to_check:
                xml_tool_calls = _parse_xml_tool_calls(text_to_check)
                if xml_tool_calls:
                    tool_calls = xml_tool_calls
                    # Clean XML tool calls from content for cleaner output
                    content = re.sub(r'<tool_call>.*?</tool_call>', '', content, flags=re.DOTALL).strip()
        
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
    
    def bind_tools(self, tools: List, **kwargs) -> "GLMReasoner":
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
