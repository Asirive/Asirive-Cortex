"""The tool registry (contracts/tools/tools.json): one list for LFM and Gemini.

    reg = load()
    reg.lfm_tools()            # the engine's config "tools": one JSON object per line (the model's schema form)
    reg.gemini_declarations()  # Gemini function declarations (cloud tier)
    for call in parse_calls(tool_call_event["text"]):
        call = reg.validate(call)            # ToolError: unknown tool, bad or missing argument
        reg.get(call.name).allowed_in(mode)

The model writes calls in its own XML form:
    <tool_call>\\n<function=NAME>\\n<parameter=ARG>\\nVALUE\\n</parameter>\\n</function>\\n</tool_call>
Values are text; validate() turns them into the declared types.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import os

_HERE = Path(__file__).resolve()
# the repo (core/cortex_core/brain -> contracts/) or the box (/opt/cortex/cortex_core/brain -> /opt/cortex/contracts/)
_CANDIDATES = [_HERE.parents[3] / "contracts/tools/tools.json", _HERE.parents[2] / "contracts/tools/tools.json"]


def registry_path() -> Path:
    env = os.environ.get("CORTEX_TOOLS")
    if env:
        return Path(env)
    for c in _CANDIDATES:
        if c.is_file():
            return c
    raise FileNotFoundError(f"tools.json not found (looked in {', '.join(map(str, _CANDIDATES))}; set CORTEX_TOOLS)")


class ToolError(ValueError):
    pass


@dataclass(frozen=True)
class Param:
    name: str
    type: str  # "string" | "boolean" | "integer" | "number"
    description: str = ""
    required: bool = False
    enum: tuple[str, ...] = ()


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    params: tuple[Param, ...]
    modes: tuple[str, ...] | None  # None = every mode
    spoken_by: str  # "lm" (the LM reads the result and answers) | "template" (code says a fixed sentence)

    def allowed_in(self, mode: str) -> bool:
        return self.modes is None or mode in self.modes

    def schema(self) -> dict:
        props = {}
        for p in self.params:
            d: dict = {"type": p.type}
            if p.enum:
                d["enum"] = list(p.enum)
            if p.description:
                d["description"] = p.description
            props[p.name] = d
        return {"name": self.name, "description": self.description,
                "parameters": {"type": "object", "properties": props,
                               "required": [p.name for p in self.params if p.required]}}


@dataclass(frozen=True)
class Call:
    name: str
    args: dict = field(default_factory=dict)


class Registry:
    def __init__(self, data: dict):
        self.version = data["version"]
        self.modes = tuple(data["modes"])
        tools = []
        for t in data["tools"]:
            params = tuple(Param(n, p["type"], p.get("description", ""), bool(p.get("required")),
                                 tuple(p.get("enum", ()))) for n, p in t.get("parameters", {}).items())
            modes = None if t["modes"] == "all" else tuple(t["modes"])
            if modes and not set(modes) <= set(self.modes):
                raise ValueError(f"{t['name']}: unknown modes {set(modes) - set(self.modes)}")
            if t["spoken_by"] not in ("lm", "template"):
                raise ValueError(f"{t['name']}: spoken_by must be lm or template")
            tools.append(Tool(t["name"], t["description"], params, modes, t["spoken_by"]))
        self.tools = tuple(tools)
        self._by_name = {t.name: t for t in tools}
        if len(self._by_name) != len(tools):
            raise ValueError("duplicate tool names")

    def get(self, name: str) -> Tool:
        try:
            return self._by_name[name]
        except KeyError:
            raise ToolError(f"unknown tool {name!r}") from None

    def lfm_tools(self, names: list[str] | None = None) -> str:
        """The tools for the engine's system prompt: one compact JSON object per line."""
        tools = self.tools if names is None else [self.get(n) for n in names]
        return "\n".join(json.dumps(t.schema(), separators=(", ", ": ")) for t in tools)

    def gemini_declarations(self) -> list[dict]:
        out = []
        for t in self.tools:
            d: dict = {"name": t.name, "description": t.description}
            if t.params:
                props = {}
                for p in t.params:
                    q: dict = {"type": p.type.upper(), "description": p.description}
                    if p.enum:
                        q["enum"] = list(p.enum)
                    props[p.name] = q
                d["parameters"] = {"type": "OBJECT", "properties": props,
                                   "required": [p.name for p in t.params if p.required]}
            out.append(d)
        return out

    def validate(self, call: Call) -> Call:
        tool = self.get(call.name)
        params = {p.name: p for p in tool.params}
        args = {}
        for k, v in call.args.items():
            p = params.get(k)
            if p is None:
                raise ToolError(f"{tool.name} has no argument {k!r}")
            args[k] = _coerce(tool.name, p, v)
        for p in tool.params:
            if p.required and (p.name not in args or args[p.name] == ""):
                raise ToolError(f"{tool.name} needs {p.name}")
        return Call(tool.name, args)


def _coerce(tool: str, p: Param, v):
    s = v.strip() if isinstance(v, str) else v
    if p.type == "boolean":
        if isinstance(s, bool):
            return s
        low = str(s).lower()
        if low in ("true", "1", "yes", "on"):
            return True
        if low in ("false", "0", "no", "off"):
            return False
        raise ToolError(f"{tool}: {p.name} must be true or false")
    if p.type in ("integer", "number"):
        try:
            return int(s) if p.type == "integer" else float(s)
        except (TypeError, ValueError):
            raise ToolError(f"{tool}: {p.name} must be a {p.type}") from None
    s = str(s)
    if p.enum:
        for e in p.enum:
            if s.upper() == e.upper():
                return e
        raise ToolError(f"{tool}: {p.name} must be one of {', '.join(p.enum)}")
    return s


_CALL = re.compile(r"<tool_call>(.*?)(?:</tool_call>|$)", re.S)
_FUNC = re.compile(r"<function=([A-Za-z0-9_\-]+)>(.*?)(?:</function>|$)", re.S)
_PARAM = re.compile(r"<parameter=([A-Za-z0-9_\-]+)>\n?(.*?)\n?(?:</parameter>|(?=<parameter=)|$)", re.S)


def parse_calls(text: str) -> list[Call]:
    """The calls in a tool_call event's text. A call cut before its closing tags still parses."""
    calls = []
    for block in _CALL.findall(text):
        for name, body in _FUNC.findall(block):
            args = {k: v.strip("\n") for k, v in _PARAM.findall(body)}
            calls.append(Call(name, args))
    return calls


def load(path: str | Path | None = None) -> Registry:
    return Registry(json.loads(Path(path or registry_path()).read_text()))
