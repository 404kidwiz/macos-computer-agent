"""Local-only macOS automation agent server."""

from __future__ import annotations

import base64
import io
import json
import subprocess
from typing import Optional, Dict
from uuid import uuid4

from fastapi import FastAPI, HTTPException
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


def _require_confirmation(action: str) -> Optional[str]:
    if action not in SENSITIVE_ACTIONS:
        return None
    action_id = str(uuid4())
    PENDING_CONFIRMATIONS[action_id] = action
    return action_id


def _consume_confirmation(action_id: str, action: str) -> bool:
    return PENDING_CONFIRMATIONS.pop(action_id, None) == action


def _run_applescript(script: str) -> str:
    result = subprocess.check_output(["osascript", "-e", script])
    return result.decode("utf-8").strip()


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/confirm")
def confirm(req: ConfirmRequest):
    if req.action_id in PENDING_CONFIRMATIONS:
        action = PENDING_CONFIRMATIONS.pop(req.action_id)
        return {"ok": True, "action": action}
    raise HTTPException(status_code=404, detail="Invalid action_id")


@app.post("/click")
def click(req: ClickRequest):
    pyautogui.click(x=req.x, y=req.y, button=req.button)
    return {"ok": True}


@app.post("/type")
def type_text(req: TypeRequest):
    pyautogui.typewrite(req.text, interval=req.interval)
    return {"ok": True}


@app.post("/press")
def press_keys(req: PressRequest, action_id: Optional[str] = None):
    if "press" in SENSITIVE_ACTIONS and not (action_id and _consume_confirmation(action_id, "press")):
        pending = _require_confirmation("press")
        return {"ok": False, "requires_confirmation": True, "action_id": pending}
    pyautogui.hotkey(*req.keys)
    return {"ok": True}


@app.post("/open_app")
def open_app(req: OpenAppRequest, action_id: Optional[str] = None):
    if "open_app" in SENSITIVE_ACTIONS and not (action_id and _consume_confirmation(action_id, "open_app")):
        pending = _require_confirmation("open_app")
        return {"ok": False, "requires_confirmation": True, "action_id": pending}
    try:
        subprocess.check_call(["open", "-a", req.name])
        return {"ok": True}
    except subprocess.CalledProcessError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/run_applescript")
def run_applescript(req: AppleScriptRequest, action_id: Optional[str] = None):
    if "run_applescript" in SENSITIVE_ACTIONS and not (action_id and _consume_confirmation(action_id, "run_applescript")):
        pending = _require_confirmation("run_applescript")
        return {"ok": False, "requires_confirmation": True, "action_id": pending}
    try:
        result = _run_applescript(req.script)
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
def run_shortcut(req: ShortcutsRequest, action_id: Optional[str] = None):
    if "shortcuts_run" in SENSITIVE_ACTIONS and not (action_id and _consume_confirmation(action_id, "shortcuts_run")):
        pending = _require_confirmation("shortcuts_run")
        return {"ok": False, "requires_confirmation": True, "action_id": pending}
    try:
        result = subprocess.check_output(["shortcuts", "run", req.name])
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
    node = {
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
def ui_tree_full(max_depth: int = 5):
    """Full accessibility tree for frontmost app (AXUIElement)."""
    if AXUIElementCreateSystemWide is None:
        raise HTTPException(status_code=400, detail="pyobjc/Quartz not available")

    system = AXUIElementCreateSystemWide()
    app = _ax_get_attr(system, kAXFocusedApplicationAttribute)
    if app is None:
        raise HTTPException(status_code=404, detail="No focused application")

    tree = _ax_to_node(app, 0, max_depth)
    return {"ok": True, "tree": tree}


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
