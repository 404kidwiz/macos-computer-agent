"""Local-only macOS automation agent server."""

from __future__ import annotations

import base64
import io
import json
import subprocess
from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

import pyautogui
import mss
from PIL import Image

try:
    import pytesseract
except Exception:  # pragma: no cover
    pytesseract = None  # type: ignore

app = FastAPI(title="macOS Computer Agent", version="0.1.0")


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


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/click")
def click(req: ClickRequest):
    pyautogui.click(x=req.x, y=req.y, button=req.button)
    return {"ok": True}


@app.post("/type")
def type_text(req: TypeRequest):
    pyautogui.typewrite(req.text, interval=req.interval)
    return {"ok": True}


@app.post("/press")
def press_keys(req: PressRequest):
    pyautogui.hotkey(*req.keys)
    return {"ok": True}


@app.post("/open_app")
def open_app(req: OpenAppRequest):
    try:
        subprocess.check_call(["open", "-a", req.name])
        return {"ok": True}
    except subprocess.CalledProcessError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/run_applescript")
def run_applescript(req: AppleScriptRequest):
    try:
        result = subprocess.check_output(["osascript", "-e", req.script])
        return {"ok": True, "output": result.decode("utf-8").strip()}
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
