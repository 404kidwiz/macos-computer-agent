# macOS Computer Agent

A local-only macOS automation agent that can observe the screen and control input.

## Goals
- Local-only control (no remote access yet)
- macOS-first implementation
- Pluggable architecture for future Windows/Linux support

## Planned Capabilities
- Screen capture
- OCR / UI text detection
- Mouse & keyboard control
- App launch / focus
- AppleScript & Shortcuts triggers
- Accessibility tree inspection

## Security & Safety
- Local-only API
- Action allowlist + confirmations for sensitive operations
- Audit logs

## Roadmap
- Phase 1: Minimal daemon + basic tools
- Phase 2: Accessibility UI tree + safer high-level actions
- Phase 3: Remote control (opt-in)
