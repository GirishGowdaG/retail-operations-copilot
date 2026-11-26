"""Fix RetailOps Copilot chat scroll/composer layout without touching other projects.

Run this from the root of an existing retail-operations-copilot checkout:
    python fix_retail_chat_scroll.py

Changes only frontend/src/main.jsx and frontend/src/style.css, retaining
user changes (including localhost:8001 backend configuration).
"""

from pathlib import Path
import shutil
import sys


def patch_once(text, original, updated, label):
    hits = text.count(original)
    if hits != 1:
        raise ValueError(f"Expected one {label} marker, found {hits}. No files changed.")
    return text.replace(original, updated, 1)


def main():
    root = Path(__file__).resolve().parent
    jsx_path = root / "frontend" / "src" / "main.jsx"
    css_path = root / "frontend" / "src" / "style.css"
    if not jsx_path.is_file() or not css_path.is_file():
        print("ERROR: Place this script next to docker-compose.yml in the RetailOps project directory.")
        print(f"Looked for: {jsx_path}")
        return 1

    jsx = jsx_path.read_text(encoding="utf-8")
    css = css_path.read_text(encoding="utf-8")
    marker = "/* RETAILOPS_CHAT_SCROLL_FIX_V1 */"
    if marker in css and 'className={"main"+(page==="copilot"?" chat-viewport":"")}' in jsx:
        print("Chat scroll fix is already installed. Nothing changed.")
        return 0
    if marker in css or "chat-viewport" in jsx:
        print("ERROR: Found a partially modified chat fix. No files changed; inspect frontend files.")
        return 1

    try:
        result = patch_once(
            jsx,
            "import React,{useEffect,useState,useMemo} from 'react';",
            "import React,{useEffect,useState,useMemo,useRef} from 'react';",
            "React import",
        )
        result = patch_once(
            result,
            'function ChatPage(){const [messages,setMessages]',
            'function ChatPage(){const messagesRef=useRef(null);const [messages,setMessages]',
            "chat ref declaration",
        )
        result = patch_once(
            result,
            "\n async function send(text=q)",
            "\n useEffect(()=>{const el=messagesRef.current;if(el)el.scrollTop=el.scrollHeight;},[messages,busy,sid]);\n async function send(text=q)",
            "chat auto-scroll effect",
        )
        result = patch_once(
            result,
            '<section className="chat-main"><div className="messages">',
            '<section className="chat-main"><div className="messages" ref={messagesRef}>',
            "scrollable messages element",
        )
        result = patch_once(
            result,
            '<main className="main"><header className="topbar">',
            '<main className={"main"+(page==="copilot"?" chat-viewport":"")}><header className="topbar">',
            "chat-only main layout class",
        )
    except ValueError as error:
        print("ERROR:", error)
        return 1

    css_addition = """

/* RETAILOPS_CHAT_SCROLL_FIX_V1 */
/* Chat alone uses the viewport; message history scrolls, composer remains visible. */
.main.chat-viewport {
  height: 100vh;
  height: 100dvh;
  min-height: 0;
  overflow: hidden;
}
.main.chat-viewport .topbar { flex: 0 0 73px; }
.main.chat-viewport .content {
  display: flex;
  flex-direction: column;
  flex: 1 1 auto;
  width: 100%;
  min-height: 0;
  min-width: 0;
  margin: 0 auto;
  padding-top: 20px;
  padding-bottom: 8px;
  overflow: hidden;
}
.main.chat-viewport .section-title { flex: 0 0 auto; margin-bottom: 14px; }
.main.chat-viewport .chat-shell {
  flex: 1 1 auto;
  height: auto;
  min-height: 0;
  min-width: 0;
  overflow: hidden;
}
.main.chat-viewport .chat-sidebar { min-height: 0; overflow-y: auto; }
.main.chat-viewport .chat-main { min-height: 0; overflow: hidden; }
.main.chat-viewport .messages {
  flex: 1 1 auto;
  min-height: 0;
  overflow-y: auto;
  overscroll-behavior: contain;
}
.main.chat-viewport .composer {
  flex: 0 0 auto;
  position: relative;
  z-index: 1;
  background: #fff;
  padding: 12px 16px;
}
.main.chat-viewport footer { flex: 0 0 auto; padding: 8px 12px; }
@media (max-width: 800px) {
  .main.chat-viewport .content { padding: 12px 12px 8px; }
  .main.chat-viewport .section-title { margin-bottom: 10px; }
  .main.chat-viewport .composer { padding: 10px; }
}
"""
    if not jsx.endswith("\n") and result.endswith("\n"):
        print("WARNING: Existing line ending was adjusted")
    backups = [jsx_path.with_name("main.jsx.before_chat_scroll_fix.bak"), css_path.with_name("style.css.before_chat_scroll_fix.bak")]
    for source, backup in zip((jsx_path, css_path), backups):
        if not backup.exists():
            shutil.copy2(source, backup)
    jsx_path.write_text(result, encoding="utf-8")
    css_path.write_text(css + css_addition, encoding="utf-8")
    print("SUCCESS: RetailOps chat layout fixed.")
    print("- Messages scroll inside chat, rather than pushing the typing bar away.")
    print("- Typing bar remains visible at the bottom of the chat area.")
    print("- New messages auto-scroll to the latest reply.")
    print("- Changes only RetailOps frontend files. AutoCare is untouched.")
    print("- Original files backed up beside the modified files (*.before_chat_scroll_fix.bak).")
    print("NEXT: docker compose up -d --build --no-deps frontend")
    return 0


if __name__ == "__main__":
    sys.exit(main())
