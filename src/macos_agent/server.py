"""Local-only macOS automation agent server."""

from __future__ import annotations

import base64
import io
import json
import subprocess
from typing import Optional, Dict, Any
from uuid import uuid4
import os
import time

from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel

import pyautogui
import mss
from PIL import Image

try:
    import pytesseract
except Exception:  # pragma: no cover
    pytesseract = None  # type: ignore

try:
    from Quartz import (
        AXUIElementCreateSystemWide,
        AXUIElementCopyAttributeValue,
        kAXFocusedApplicationAttribute,
        kAXChildrenAttribute,
        kAXRoleAttribute,
        kAXTitleAttribute,
        kAXValueAttribute,
    )
except Exception:  # pragma: no cover
    AXUIElementCreateSystemWide = None  # type: ignore

app = FastAPI(title="macOS Computer Agent", version="0.1.0")

# In-memory confirmation store (local-only)
PENDING_CONFIRMATIONS: Dict[str, str] = {}

# Actions that require explicit confirmation
SENSITIVE_ACTIONS = {
    "run_applescript",
    "open_app",
    "press",
    "shortcuts_run",
}

CONFIG_PATH = os.getenv("AGENT_CONFIG", "config.json")

# Default allowlist (overridden by config)
ALLOWED_APPS = {"Terminal", "Visual Studio Code", "Safari", "Google Chrome"}

# UI element store for click-by-id
UI_ELEMENT_INDEX: Dict[str, Any] = {}

# Audit log
AUDIT_LOG = "agent_audit.log"

# Auth token + safety controls
AGENT_TOKEN: Optional[str] = None
SESSION_TOKEN_TTL_SEC = 3600
SESSION_TOKENS: Dict[str, float] = {}
RATE_LIMIT_PER_MINUTE = 60
COOLDOWNS: Dict[str, float] = {}
LAST_ACTION: Dict[str, float] = {}
REQUEST_TIMESTAMPS: list[float] = []
ENDPOINT_ALLOWLIST: set[str] = set()


def _load_config():
    global ALLOWED_APPS, AUDIT_LOG, AGENT_TOKEN, RATE_LIMIT_PER_MINUTE, COOLDOWNS, SESSION_TOKEN_TTL_SEC, ENDPOINT_ALLOWLIST
    try:
        with open(CONFIG_PATH, "r") as f:
            cfg = json.load(f)
            ALLOWED_APPS = set(cfg.get("allowed_apps", list(ALLOWED_APPS)))
            AUDIT_LOG = cfg.get("audit_log", AUDIT_LOG)
            AGENT_TOKEN = cfg.get("token")
            SESSION_TOKEN_TTL_SEC = cfg.get("session_token_ttl_sec", SESSION_TOKEN_TTL_SEC)
            RATE_LIMIT_PER_MINUTE = cfg.get("rate_limit_per_minute", RATE_LIMIT_PER_MINUTE)
            COOLDOWNS = cfg.get("cooldowns", {})
            ENDPOINT_ALLOWLIST = set(cfg.get("endpoint_allowlist", []))
    except Exception:
        pass


_load_config()


class ClickRequest(BaseModel):
    x: int
    y: int
    button: str = "left"


class TypeRequest(BaseModel):
    text: str
    interval: float = 0.0


class PressRequest(BaseModel):
    keys: list[str]


class OpenAppRequest(BaseModel):
    name: str


class AppleScriptRequest(BaseModel):
    script: str


class OcrRequest(BaseModel):
    x: Optional[int] = None
    y: Optional[int] = None
    width: Optional[int] = None
    height: Optional[int] = None


class ConfirmRequest(BaseModel):
    action_id: str


class ShortcutsRequest(BaseModel):
    name: str


class UiSearchRequest(BaseModel):
    query: str
    max_depth: int = 5


class UiActionRequest(BaseModel):
    element_id: str
    value: Optional[str] = None


def _require_confirmation(action: str) -> Optional[str]:
    if action not in SENSITIVE_ACTIONS:
        return None
    action_id = str(uuid4())
    PENDING_CONFIRMATIONS[action_id] = action
    return action_id


def _consume_confirmation(action_id: str, action: str) -> bool:
    return PENDING_CONFIRMATIONS.pop(action_id, None) == action


def _audit(action: str, payload: Dict[str, Any]):
    try:
        with open(AUDIT_LOG, "a") as f:
            f.write(json.dumps({"ts": time.time(), "action": action, "payload": payload}) + "\n")
    except Exception:
        pass


def _redact(payload: Dict[str, Any]) -> Dict[str, Any]:
    redacted = dict(payload)
    for key in ["text", "script", "value", "token"]:
        if key in redacted:
            redacted[key] = "***"
    return redacted


def _auth(token: Optional[str]):
    if AGENT_TOKEN and token != AGENT_TOKEN:
        raise HTTPException(status_code=401, detail="invalid token")


def _session_auth(session_token: Optional[str]):
    if session_token is None:
        raise HTTPException(status_code=401, detail="missing session token")
    expiry = SESSION_TOKENS.get(session_token)
    if expiry is None or time.time() > expiry:
        SESSION_TOKENS.pop(session_token, None)
        raise HTTPException(status_code=401, detail="invalid/expired session token")


def _endpoint_allow(path: str):
    if ENDPOINT_ALLOWLIST and path not in ENDPOINT_ALLOWLIST:
        raise HTTPException(status_code=403, detail="endpoint not allowed")


def _rate_limit():
    now = time.time()
    REQUEST_TIMESTAMPS[:] = [t for t in REQUEST_TIMESTAMPS if now - t < 60]
    if len(REQUEST_TIMESTAMPS) >= RATE_LIMIT_PER_MINUTE:
        raise HTTPException(status_code=429, detail="rate limit exceeded")
    REQUEST_TIMESTAMPS.append(now)


def _cooldown(action: str):
    now = time.time()
    cooldown = float(COOLDOWNS.get(action, 0))
    last = LAST_ACTION.get(action, 0)
    if cooldown > 0 and (now - last) < cooldown:
        raise HTTPException(status_code=429, detail=f"cooldown active for {action}")
    LAST_ACTION[action] = now


def _run_applescript(script: str) -> str:
    result = subprocess.check_output(["osascript", "-e", script])
    return result.decode("utf-8").strip()


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/session")
def create_session(x_agent_token: Optional[str] = Header(None)):
    _auth(x_agent_token)
    token = str(uuid4())
    SESSION_TOKENS[token] = time.time() + SESSION_TOKEN_TTL_SEC
    return {"ok": True, "session_token": token, "expires_in": SESSION_TOKEN_TTL_SEC}


@app.post("/confirm")
def confirm(req: ConfirmRequest, x_agent_token: Optional[str] = Header(None), x_session_token: Optional[str] = Header(None)):
    _auth(x_agent_token)
    _session_auth(x_session_token)
    if req.action_id in PENDING_CONFIRMATIONS:
        action = PENDING_CONFIRMATIONS.pop(req.action_id)
        return {"ok": True, "action": action}
    raise HTTPException(status_code=404, detail="Invalid action_id")


@app.post("/click")
def click(req: ClickRequest, x_agent_token: Optional[str] = Header(None), x_session_token: Optional[str] = Header(None)):
    _endpoint_allow("/click")
    _auth(x_agent_token)
    _session_auth(x_session_token)
    _rate_limit()
    _cooldown("click")
    pyautogui.click(x=req.x, y=req.y, button=req.button)
    _audit("click", _redact(req.dict()))
    return {"ok": True}


@app.post("/type")
def type_text(req: TypeRequest, x_agent_token: Optional[str] = Header(None), x_session_token: Optional[str] = Header(None)):
    _endpoint_allow("/type")
    _auth(x_agent_token)
    _session_auth(x_session_token)
    _rate_limit()
    _cooldown("type")
    pyautogui.typewrite(req.text, interval=req.interval)
    _audit("type", _redact(req.dict()))
    return {"ok": True}


@app.post("/press")
def press_keys(req: PressRequest, action_id: Optional[str] = None, x_agent_token: Optional[str] = Header(None), x_session_token: Optional[str] = Header(None)):
    _endpoint_allow("/press")
    _auth(x_agent_token)
    _session_auth(x_session_token)
    _rate_limit()
    _cooldown("press")
    if "press" in SENSITIVE_ACTIONS and not (action_id and _consume_confirmation(action_id, "press")):
        pending = _require_confirmation("press")
        return {"ok": False, "requires_confirmation": True, "action_id": pending}
    pyautogui.hotkey(*req.keys)
    _audit("press", _redact(req.dict()))
    return {"ok": True}


@app.post("/open_app")
def open_app(req: OpenAppRequest, action_id: Optional[str] = None, x_agent_token: Optional[str] = Header(None), x_session_token: Optional[str] = Header(None)):
    _endpoint_allow("/open_app")
    _auth(x_agent_token)
    _session_auth(x_session_token)
    _rate_limit()
    _cooldown("open_app")
    if req.name not in ALLOWED_APPS:
        raise HTTPException(status_code=403, detail="App not in allowlist")
    if "open_app" in SENSITIVE_ACTIONS and not (action_id and _consume_confirmation(action_id, "open_app")):
        pending = _require_confirmation("open_app")
        return {"ok": False, "requires_confirmation": True, "action_id": pending}
    try:
        subprocess.check_call(["open", "-a", req.name])
        _audit("open_app", _redact(req.dict()))
        return {"ok": True}
    except subprocess.CalledProcessError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/run_applescript")
def run_applescript(req: AppleScriptRequest, action_id: Optional[str] = None, x_agent_token: Optional[str] = Header(None), x_session_token: Optional[str] = Header(None)):
    _endpoint_allow("/run_applescript")
    _auth(x_agent_token)
    _session_auth(x_session_token)
    _rate_limit()
    _cooldown("run_applescript")
    if "run_applescript" in SENSITIVE_ACTIONS and not (action_id and _consume_confirmation(action_id, "run_applescript")):
        pending = _require_confirmation("run_applescript")
        return {"ok": False, "requires_confirmation": True, "action_id": pending}
    try:
        result = _run_applescript(req.script)
        _audit("run_applescript", _redact(req.dict()))
        return {"ok": True, "output": result}
    except subprocess.CalledProcessError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/screenshot")
def screenshot():
    with mss.mss() as sct:
        monitor = sct.monitors[1]
        sct_img = sct.grab(monitor)
        img = Image.frombytes("RGB", sct_img.size, sct_img.rgb)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
        return {"ok": True, "png_base64": b64}


@app.post("/shortcuts/run")
def run_shortcut(req: ShortcutsRequest, action_id: Optional[str] = None, x_agent_token: Optional[str] = Header(None), x_session_token: Optional[str] = Header(None)):
    _endpoint_allow("/shortcuts/run")
    _auth(x_agent_token)
    _session_auth(x_session_token)
    _rate_limit()
    _cooldown("shortcuts_run")
    if "shortcuts_run" in SENSITIVE_ACTIONS and not (action_id and _consume_confirmation(action_id, "shortcuts_run")):
        pending = _require_confirmation("shortcuts_run")
        return {"ok": False, "requires_confirmation": True, "action_id": pending}
    try:
        result = subprocess.check_output(["shortcuts", "run", req.name])
        _audit("shortcuts_run", _redact(req.dict()))
        return {"ok": True, "output": result.decode("utf-8").strip()}
    except subprocess.CalledProcessError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/ui_tree")
def ui_tree():
    """Best-effort UI tree via AppleScript (frontmost app, windows, menu items)."""
    script = r'''
    tell application "System Events"
      set frontApp to first application process whose frontmost is true
      set appName to name of frontApp
      set winNames to {}
      try
        set winNames to name of windows of frontApp
      end try
      set menuItems to {}
      try
        set menuItems to name of menu items of menu 1 of menu bar 1 of frontApp
      end try
      return "APP:" & appName & "\nWINS:" & (winNames as string) & "\nMENUS:" & (menuItems as string)
    end tell
    '''
    try:
        output = _run_applescript(script)
        return {"ok": True, "raw": output}
    except subprocess.CalledProcessError as e:
        raise HTTPException(status_code=400, detail=str(e))


def _ax_get_attr(element, attr):
    try:
        return AXUIElementCopyAttributeValue(element, attr, None)
    except Exception:
        return None


def _ax_to_node(element, depth: int, max_depth: int):
    role = _ax_get_attr(element, kAXRoleAttribute)
    title = _ax_get_attr(element, kAXTitleAttribute)
    value = _ax_get_attr(element, kAXValueAttribute)
    element_id = str(uuid4())
    UI_ELEMENT_INDEX[element_id] = element

    node = {
        "id": element_id,
        "role": str(role) if role is not None else None,
        "title": str(title) if title is not None else None,
        "value": str(value) if value is not None else None,
        "children": [],
    }
    if depth >= max_depth:
        return node
    children = _ax_get_attr(element, kAXChildrenAttribute)
    if children:
        for child in children:
            node["children"].append(_ax_to_node(child, depth + 1, max_depth))
    return node


@app.get("/ui_tree/full")
def ui_tree_full(max_depth: int = 5, x_agent_token: Optional[str] = Header(None), x_session_token: Optional[str] = Header(None)):
    _endpoint_allow("/ui_tree/full")
    _auth(x_agent_token)
    _session_auth(x_session_token)
    _rate_limit()
    """Full accessibility tree for frontmost app (AXUIElement)."""
    if AXUIElementCreateSystemWide is None:
        raise HTTPException(status_code=400, detail="pyobjc/Quartz not available")

    UI_ELEMENT_INDEX.clear()
    system = AXUIElementCreateSystemWide()
    app = _ax_get_attr(system, kAXFocusedApplicationAttribute)
    if app is None:
        raise HTTPException(status_code=404, detail="No focused application")

    tree = _ax_to_node(app, 0, max_depth)
    _audit("ui_tree_full", {"max_depth": max_depth})
    return {"ok": True, "tree": tree}


def _search_tree(node: Dict[str, Any], query: str, results: list):
    hay = " ".join(
        filter(None, [node.get("role"), node.get("title"), node.get("value")])
    ).lower()
    if query in hay:
        results.append({
            "id": node.get("id"),
            "role": node.get("role"),
            "title": node.get("title"),
            "value": node.get("value"),
        })
    for child in node.get("children", []):
        _search_tree(child, query, results)


@app.post("/ui_search")
def ui_search(req: UiSearchRequest, x_agent_token: Optional[str] = Header(None), x_session_token: Optional[str] = Header(None)):
    _endpoint_allow("/ui_search")
    _auth(x_agent_token)
    _session_auth(x_session_token)
    _rate_limit()
    if AXUIElementCreateSystemWide is None:
        raise HTTPException(status_code=400, detail="pyobjc/Quartz not available")

    UI_ELEMENT_INDEX.clear()
    system = AXUIElementCreateSystemWide()
    app = _ax_get_attr(system, kAXFocusedApplicationAttribute)
    if app is None:
        raise HTTPException(status_code=404, detail="No focused application")

    tree = _ax_to_node(app, 0, req.max_depth)
    results: list = []
    _search_tree(tree, req.query.lower(), results)
    _audit("ui_search", req.dict())
    return {"ok": True, "results": results}


@app.post("/ui_click_text")
def ui_click_text(req: UiSearchRequest, action_id: Optional[str] = None, x_agent_token: Optional[str] = Header(None), x_session_token: Optional[str] = Header(None)):
    _endpoint_allow("/ui_click_text")
    _auth(x_agent_token)
    _session_auth(x_session_token)
    _rate_limit()
    _cooldown("ui_click")
    if "press" in SENSITIVE_ACTIONS and not (action_id and _consume_confirmation(action_id, "press")):
        pending = _require_confirmation("press")
        return {"ok": False, "requires_confirmation": True, "action_id": pending}

    search = ui_search(req, x_agent_token=x_agent_token)
    results = search.get("results", [])
    if not results:
        raise HTTPException(status_code=404, detail="no matching elements")

    first = results[0]
    element_id = first.get("id")
    if not element_id:
        raise HTTPException(status_code=400, detail="result missing element id")

    return ui_click(UiActionRequest(element_id=element_id), action_id=action_id, x_agent_token=x_agent_token)


@app.post("/ui_click")
def ui_click(req: UiActionRequest, action_id: Optional[str] = None, x_agent_token: Optional[str] = Header(None), x_session_token: Optional[str] = Header(None)):
    _endpoint_allow("/ui_click")
    _auth(x_agent_token)
    _session_auth(x_session_token)
    _rate_limit()
    _cooldown("ui_click")
    if "press" in SENSITIVE_ACTIONS and not (action_id and _consume_confirmation(action_id, "press")):
        pending = _require_confirmation("press")
        return {"ok": False, "requires_confirmation": True, "action_id": pending}

    element = UI_ELEMENT_INDEX.get(req.element_id)
    if element is None:
        raise HTTPException(status_code=404, detail="element_id not found; run ui_search or ui_tree/full first")

    try:
        from Quartz import AXUIElementPerformAction  # type: ignore
        AXUIElementPerformAction(element, "AXPress")
        _audit("ui_click", {"element_id": req.element_id})
        return {"ok": True}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/ui_set")
def ui_set(req: UiActionRequest, x_agent_token: Optional[str] = Header(None), x_session_token: Optional[str] = Header(None)):
    _endpoint_allow("/ui_set")
    _auth(x_agent_token)
    _session_auth(x_session_token)
    _rate_limit()
    element = UI_ELEMENT_INDEX.get(req.element_id)
    if element is None:
        raise HTTPException(status_code=404, detail="element_id not found; run ui_search or ui_tree/full first")

    if req.value is None:
        raise HTTPException(status_code=400, detail="value required")

    try:
        from Quartz import AXUIElementSetAttributeValue  # type: ignore
        AXUIElementSetAttributeValue(element, "AXValue", req.value)
        _audit("ui_set", {"element_id": req.element_id, "value": req.value})
        return {"ok": True}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/ui_focus")
def ui_focus(req: UiActionRequest, x_agent_token: Optional[str] = Header(None), x_session_token: Optional[str] = Header(None)):
    _endpoint_allow("/ui_focus")
    _auth(x_agent_token)
    _session_auth(x_session_token)
    _rate_limit()
    element = UI_ELEMENT_INDEX.get(req.element_id)
    if element is None:
        raise HTTPException(status_code=404, detail="element_id not found; run ui_search or ui_tree/full first")

    try:
        from Quartz import AXUIElementSetAttributeValue  # type: ignore
        AXUIElementSetAttributeValue(element, "AXFocused", True)
        _audit("ui_focus", {"element_id": req.element_id})
        return {"ok": True}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/ui_scroll")
def ui_scroll(req: UiActionRequest, x_agent_token: Optional[str] = Header(None), x_session_token: Optional[str] = Header(None)):
    _endpoint_allow("/ui_scroll")
    _auth(x_agent_token)
    _session_auth(x_session_token)
    _rate_limit()
    element = UI_ELEMENT_INDEX.get(req.element_id)
    if element is None:
        raise HTTPException(status_code=404, detail="element_id not found; run ui_search or ui_tree/full first")

    try:
        from Quartz import AXUIElementPerformAction  # type: ignore
        AXUIElementPerformAction(element, "AXScrollDown")
        _audit("ui_scroll", {"element_id": req.element_id})
        return {"ok": True}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/ocr")
def ocr(req: OcrRequest):
    if pytesseract is None:
        raise HTTPException(status_code=400, detail="pytesseract not installed")

    with mss.mss() as sct:
        monitor = sct.monitors[1]
        if req.width and req.height and req.x is not None and req.y is not None:
            monitor = {
                "left": req.x,
                "top": req.y,
                "width": req.width,
                "height": req.height,
            }
        sct_img = sct.grab(monitor)
        img = Image.frombytes("RGB", sct_img.size, sct_img.rgb)
        text = pytesseract.image_to_string(img)
        return {"ok": True, "text": text}


@app.get("/cursor")
def cursor_position():
    x, y = pyautogui.position()
    return {"ok": True, "x": x, "y": y}


@app.get("/screen")
def screen_size():
    width, height = pyautogui.size()
    return {"ok": True, "width": width, "height": height}
