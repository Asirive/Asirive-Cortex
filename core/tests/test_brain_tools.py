import json

import pytest

from cortex_core.brain import tools as T

REG = T.load()


def test_registry_loads_milestone_tools():
    names = {t.name for t in REG.tools}
    assert {"search_places", "plan_trip", "start_navigation", "stop_navigation", "nav_status", "nearby_bus_stops",
            "services_at_stop", "bus_arrivals", "gps_accuracy", "set_mode", "camera"} <= names
    assert REG.get("bus_arrivals").spoken_by == "template"
    assert REG.get("plan_trip").allowed_in("IDLE") and not REG.get("plan_trip").allowed_in("TRANSIT")
    assert REG.get("search_places").allowed_in("TRANSIT")


def test_lfm_lines_are_one_json_object_per_line():
    lines = REG.lfm_tools().split("\n")
    assert len(lines) == len(REG.tools)
    d = json.loads(lines[[t.name for t in REG.tools].index("bus_arrivals")])
    assert d["name"] == "bus_arrivals"
    assert d["parameters"]["type"] == "object"
    assert set(d["parameters"]["properties"]) == {"service", "stop"}
    assert d["parameters"].get("required", []) == []
    assert json.loads(lines[0])["parameters"]["required"] == ["query"]


def test_gemini_declarations():
    decl = {d["name"]: d for d in REG.gemini_declarations()}
    assert decl["camera"]["parameters"]["properties"]["on"]["type"] == "BOOLEAN"
    assert decl["set_mode"]["parameters"]["properties"]["mode"]["enum"][0] == "IDLE"
    assert "parameters" not in decl["start_navigation"]


def test_parse_one_call():
    text = "<tool_call>\n<function=bus_arrivals>\n<parameter=service>\n858\n</parameter>\n</function>\n</tool_call>"
    calls = T.parse_calls(text)
    assert calls == [T.Call("bus_arrivals", {"service": "858"})]


def test_parse_two_calls_and_no_args():
    text = ("<tool_call>\n<function=stop_navigation>\n</function>\n</tool_call>\n\n"
            "<tool_call>\n<function=camera>\n<parameter=on>\nfalse\n</parameter>\n</function>\n</tool_call>")
    calls = T.parse_calls(text)
    assert [c.name for c in calls] == ["stop_navigation", "camera"]
    assert calls[1].args == {"on": "false"}


def test_parse_tolerates_missing_closers():
    # a call cut at max tokens or ended at <|im_end|> without </tool_call>
    calls = T.parse_calls("<tool_call>\n<function=search_places>\n<parameter=query>\nNorthpoint City")
    assert calls == [T.Call("search_places", {"query": "Northpoint City"})]


def test_parse_garbage_is_empty():
    assert T.parse_calls("I think bus 858 comes soon.") == []


def test_validate_coerces_and_checks():
    ok = REG.validate(T.Call("camera", {"on": "false"}))
    assert ok.args == {"on": False}
    assert REG.validate(T.Call("bus_arrivals", {"service": " 858 "})).args == {"service": "858"}
    with pytest.raises(T.ToolError, match="unknown tool"):
        REG.validate(T.Call("fly", {}))
    with pytest.raises(T.ToolError, match="needs query"):
        REG.validate(T.Call("search_places", {}))
    with pytest.raises(T.ToolError, match="no argument"):
        REG.validate(T.Call("gps_accuracy", {"x": "1"}))
    with pytest.raises(T.ToolError, match="one of"):
        REG.validate(T.Call("set_mode", {"mode": "PARTY"}))
    assert REG.validate(T.Call("set_mode", {"mode": "explore"})).args == {"mode": "EXPLORE"}
    with pytest.raises(T.ToolError, match="true or false"):
        REG.validate(T.Call("camera", {"on": "maybe"}))
