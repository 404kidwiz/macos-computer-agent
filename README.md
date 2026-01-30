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
All endpoints (except `/health` and `/session`) require headers:
- `X-Agent-Token: <config token>`
- `X-Session-Token: <from /session>`

- `GET /health`
- `POST /session`
- `POST /session/allow` `{endpoint:"/click"}`
- `POST /session/deny` `{endpoint:"/run_applescript"}`
- `POST /session/confirm` `{request_id:"..."}`
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
- `GET /ax_status` (AX trust status; add `?prompt=true` to request permission)
- `POST /focus_app` `{name:"Terminal"}`
- `POST /menu_click` `{menu_item:"About This Mac"}`
- `POST /menu_click_index` `{index:1}`
- `POST /menu_click_contains` `{text:"About"}`
- `POST /menu_click_path` `{path:"File > New Folder"}`
- `POST /window_find` `{title:"Finder"}`
- `POST /window_focus` `{title:"Finder"}` (5s timeout with 1 retry)
- `POST /window_close` `{title:"Finder"}` (5s timeout with 1 retry)
- `GET /windows`
- `GET /ui_tree/full` (AX tree; includes `fallback` AppleScript UI data)
- `POST /ui_search` `{query:"...", max_depth:5}`
- `POST /ui_click_text` `{query:"...", max_depth:5}` (confirmation required)
- `POST /ui_click` `{element_id:"..."}` (confirmation required)
- `POST /ui_set` `{element_id:"...", value:"..."}`
- `POST /ui_focus` `{element_id:"..."}`
- `POST /ui_scroll` `{element_id:"..."}`

**Per-action confirmation:** add `?require_confirm=true` to any endpoint to force a session confirmation flow.
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
- Allowlist (config.json)
- Confirmations for sensitive operations
- Token auth via `X-Agent-Token`
- Rate limiting + cooldowns (config.json)
- Audit logs (`agent_audit.log`)

## Roadmap
- Phase 3: Remote control (opt-in)
