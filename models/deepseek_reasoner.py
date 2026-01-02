"""
Custom DeepSeek Reasoner wrapper for LangChain.

Handles DeepSeek V3/R1 models via OpenRouter which return `reasoning` or `reasoning_content`.
Configured specifically for the user's preferred provider (Baseten/fp4).
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
    Parse malformed XML-style tool calls (generic fallback).
    """
    tool_calls = []
    tool_call_pattern = r'<tool_call>(.*?)</tool_call>'
    cleaned_text = re.sub(r'<tool_call>.*?<tool_call>', '<tool_call>', text, flags=re.DOTALL)
    matches = re.findall(tool_call_pattern, cleaned_text, re.DOTALL)
    
    for match in matches:
        try:
            name_match = re.match(r'^(\w+)', match.strip())
            if not name_match:
                continue
            tool_name = name_match.group(1)
            
            args = {}
            arg_pattern = r'<arg_key>(\w+)</arg_key><arg_value>([^<]+)</arg_value>'
            arg_matches = re.findall(arg_pattern, match)
            
            for key, value in arg_matches:
                try:
                    args[key] = int(value)
                except ValueError:
                    try:
                        args[key] = float(value)
                    except ValueError:
                        args[key] = value
            
            if tool_name:
                tool_calls.append({
                    "id": f"call_{uuid.uuid4().hex[:24]}",
                    "name": tool_name,
                    "args": args,
                })
        except Exception as e:
            print(f"[DeepSeekReasoner] Failed to parse XML tool call: {e}")
            continue
    
    return tool_calls


class DeepSeekReasoner(BaseChatModel):
    """
    Custom LangChain wrapper for DeepSeek via OpenRouter.
    """
    
    client: Any = None
    model: str = "deepseek/deepseek-v3.2"
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
        return "deepseek-reasoner"
        
    @property
    def model_name(self) -> str:
        return self.model
    
    @property
    def _identifying_params(self) -> Dict[str, Any]:
        return {"model": self.model, "temperature": self.temperature}
    
    def _convert_messages_to_openai_format(self, messages: List[BaseMessage]) -> List[Dict]:
        openai_messages = []
        for msg in messages:
            if isinstance(msg, SystemMessage):
                openai_messages.append({"role": "system", "content": msg.content})
            elif isinstance(msg, HumanMessage):
                openai_messages.append({"role": "user", "content": msg.content})
            elif isinstance(msg, AIMessage):
                content = msg.content or ""
                # Strip reasoning fences to avoid feeding them back in a confusing way
                if "---REASONING---" in content:
                    content = re.sub(r'---REASONING---.*?---END REASONING---\s*', '', content, flags=re.DOTALL)
                
                ai_msg = {"role": "assistant", "content": content}
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
        openai_messages = self._convert_messages_to_openai_format(messages)
        
        params = {
            "model": self.model,
            "messages": openai_messages,
        }

        if self.temperature is not None:
            params["temperature"] = self.temperature
        
        if "tools" in kwargs:
            params["tools"] = kwargs["tools"]
        
        if stop:
            params["stop"] = stop
            
        # Provider configuration
        # NOTE: Allowing fallbacks to avoid 404 if specific provider is down
        params["extra_body"] = {
            "provider": {
                "only": ["DeepSeek"],
                # "quantizations": ["fp4"],
                # "sort":"throughput",
                # "allow_fallbacks": False  # Changed to True to prevent 404s
            },
        }
        
        response = self.client.chat.completions.create(**params)
        choice = response.choices[0]
        message = choice.message
        
        raw_content = message.content or ""
        reasoning_content = getattr(message, "reasoning", None) or getattr(message, "reasoning_content", None)
        
        content = raw_content
        if reasoning_content:
            content = f"---REASONING---\n{reasoning_content}\n---END REASONING---\n\n{raw_content}"
        
        additional_kwargs = {}
        if reasoning_content:
            additional_kwargs["reasoning_content"] = reasoning_content
            
        tool_calls = []
        if message.tool_calls:
            for tc in message.tool_calls:
                try:
                    args = json.loads(tc.function.arguments)
                    if not isinstance(args, dict):
                        args = {"raw": args}
                except (json.JSONDecodeError, TypeError):
                    # If args is a string that's not valid JSON, wrap it
                    args = {"raw": tc.function.arguments} if tc.function.arguments else {}
                tool_calls.append({
                    "id": tc.id,
                    "name": tc.function.name,
                    "args": args,
                })
        
        # XML Fallback
        if not tool_calls:
            text_to_check = (reasoning_content or "") + (raw_content or "")
            if "<tool_call>" in text_to_check:
                xml_tool_calls = _parse_xml_tool_calls(text_to_check)
                if xml_tool_calls:
                    tool_calls = xml_tool_calls
                    content = re.sub(r'<tool_call>.*?</tool_call>', '', content, flags=re.DOTALL).strip()
        
        token_usage = {}
        if response.usage:
            token_usage = {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            }
            completion_details = getattr(response.usage, "completion_tokens_details", None)
            if completion_details:
                reasoning_tokens = getattr(completion_details, "reasoning_tokens", 0)
                if reasoning_tokens:
                    token_usage["reasoning_tokens"] = reasoning_tokens

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
    
    def bind_tools(self, tools: List, **kwargs) -> "DeepSeekReasoner":
        from langchain_core.utils.function_calling import convert_to_openai_tool
        openai_tools = [convert_to_openai_tool(t) for t in tools]
        return self.__class__(
            model=self.model,
            temperature=self.temperature,
            api_key=self.api_key,
            base_url=self.base_url,
        ).configurable_fields().bind(tools=openai_tools, **kwargs)
