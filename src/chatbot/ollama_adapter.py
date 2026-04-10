import json
import httpx
from typing import List
from google.genai import types

def _convert_schema(s):
    res = {}
    type_val = getattr(s, "type", None)
    if type_val:
        res["type"] = str(type_val).lower().replace("type.", "")
    desc_val = getattr(s, "description", None)
    if desc_val:
        res["description"] = desc_val
    props = getattr(s, "properties", None)
    if props:
        res["properties"] = {k: _convert_schema(v) for k, v in props.items()}
    req = getattr(s, "required", None)
    if req:
        res["required"] = req
    items_val = getattr(s, "items", None)
    if items_val:
        res["items"] = _convert_schema(items_val)
    return res

def get_openai_tools(gemini_tools):
    openai_tools = []
    for tool in gemini_tools:
        for fd in getattr(tool, "function_declarations", []):
            params = _convert_schema(fd.parameters) if getattr(fd, "parameters", None) else {"type": "object", "properties": {}}
            otool = {
                "type": "function",
                "function": {
                    "name": fd.name,
                    "description": fd.description,
                    "parameters": params
                }
            }
            openai_tools.append(otool)
    return openai_tools

def convert_messages(contents: List[types.Content], system_prompt: str = ""):
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    
    for content in contents:
        role = content.role
        if role == "model":
            role = "assistant"
        
        parts = getattr(content, "parts", [])
        text_content = ""
        tool_calls = []
        function_responses = []

        for p in parts:
            if getattr(p, "text", None):
                text_content += p.text + "\n"
            elif getattr(p, "function_call", None):
                fc = p.function_call
                tool_calls.append({
                    "id": f"call_{fc.name}",
                    "type": "function",
                    "function": {
                        "name": fc.name,
                        "arguments": json.dumps(dict(fc.args)) if getattr(fc, "args", None) else "{}"
                    }
                })
            elif getattr(p, "function_response", None):
                fr = p.function_response
                function_responses.append({
                    "role": "tool",
                    "tool_call_id": f"call_{fr.name}",
                    "name": fr.name,
                    "content": json.dumps(dict(fr.response), ensure_ascii=False) if getattr(fr, "response", None) else "{}"
                })
        
        msg = {"role": role}
        if text_content:
            msg["content"] = text_content.strip()
        else:
            msg["content"] = ""
            
        if tool_calls:
            msg["tool_calls"] = tool_calls
            
        if function_responses:
            for fr_msg in function_responses:
                messages.append(fr_msg)
            # function_responses are user role in gemini but tool role in openai
            continue
            
        messages.append(msg)
    
    return messages

class MockPart:
    def __init__(self, text=None, function_call=None):
        self.text = text
        self.function_call = function_call

class MockFunctionCall:
    def __init__(self, name, args):
        self.name = name
        self.args = args

class MockContent:
    def __init__(self, parts):
        self.parts = parts

class MockCandidate:
    def __init__(self, content):
        self.content = content

class MockResponse:
    def __init__(self, candidates):
        self.candidates = candidates

def call_ollama(url: str, model: str, contents: List[types.Content], system_prompt: str, gemini_tools: list):
    openai_tools = get_openai_tools(gemini_tools)
    messages = convert_messages(contents, system_prompt)
    
    payload = {
        "model": model,
        "messages": messages,
        "tools": openai_tools,
        "temperature": 0.7,
    }
    
    # httpx post
    with httpx.Client(timeout=30.0) as client:
        resp = client.post(f"{url.rstrip('/')}/v1/chat/completions", json=payload)
        resp.raise_for_status()
        data = resp.json()
    
    choice = data["choices"][0]["message"]
    parts = []
    if choice.get("content"):
        parts.append(MockPart(text=choice["content"]))
    
    if choice.get("tool_calls"):
        for tc in choice.get("tool_calls"):
            args = json.loads(tc["function"]["arguments"]) if tc["function"].get("arguments") else {}
            parts.append(MockPart(function_call=MockFunctionCall(name=tc["function"]["name"], args=args)))
            
    content = MockContent(parts=parts)
    candidate = MockCandidate(content=content)
    return MockResponse(candidates=[candidate])
