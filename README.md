# macOS Computer Agent

A local-only macOS automation agent that can observe the screen and control input.

## Goals
- Local-only control (no remote access yet)
- macOS-first implementation
- Pluggable architecture for future Windows/Linux support

## Planned Capabilities
- Screen capture ✅
- OCR / UI text detection ✅ (requires Tesseract)
- Mouse & keyboard control ✅
- App launch / focus ✅
- AppleScript triggers ✅
- Accessibility tree inspection (next)

## Quickstart
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# run
uvicorn macos_agent.server:app --host 127.0.0.1 --port 8765
```

## API (local-only)
- `GET /health`
- `GET /screen`
- `GET /cursor`
- `GET /screenshot` (base64 PNG)
- `POST /click` `{x,y,button}`
- `POST /type` `{text, interval}`
- `POST /press` `{keys:["cmd","space"]}`
- `POST /open_app` `{name:"Terminal"}` (requires confirmation)
- `POST /run_applescript` `{script:"..."}` (requires confirmation)
- `POST /shortcuts/run` `{name:"Shortcut Name"}` (requires confirmation)
- `GET /ui_tree` (best-effort frontmost app info)
- `GET /ui_tree/full` (full AX UI tree, use `?max_depth=5`)
- `POST /ui_search` `{query:"...", max_depth:5}`
- `POST /ui_click` `?element_id=...&action_id=...`
- `POST /ocr` `{x,y,width,height}` (optional crop)
- `POST /confirm` `{action_id:"..."}`

## Dependencies
- `pyautogui` (requires Accessibility permission)
- `mss` + `Pillow` (screen capture)
- `pytesseract` (OCR; requires system tesseract)
- `shortcuts` CLI (built-in on macOS)

Install Tesseract (macOS):
```bash
brew install tesseract
```

## Security & Safety
- Local-only API
- Add allowlist + confirmations for sensitive operations (planned)
- Audit logs (planned)

## Roadmap
- Phase 2: Accessibility UI tree + safer high-level actions
- Phase 3: Remote control (opt-in)
