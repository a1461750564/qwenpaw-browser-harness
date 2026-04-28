"""Browser control via CDP. Read, edit, extend -- this file is yours."""
import base64, json, os, socket, time, urllib.request
from pathlib import Path
from urllib.parse import urlparse


def _load_env():
    p = Path(__file__).parent / ".env"
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_env()

NAME = os.environ.get("BU_NAME", "default")
SOCK = f"/tmp/bu-{NAME}.sock"
INTERNAL = ("chrome://", "chrome-untrusted://", "devtools://", "chrome-extension://", "about:")


def _send(req):
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.connect(SOCK)
    s.sendall((json.dumps(req) + "\n").encode())
    data = b""
    while not data.endswith(b"\n"):
        chunk = s.recv(1 << 20)
        if not chunk: break
        data += chunk
    s.close()
    r = json.loads(data)
    if "error" in r: raise RuntimeError(r["error"])
    return r


def cdp(method, session_id=None, **params):
    """Raw CDP. cdp('Page.navigate', url='...'), cdp('DOM.getDocument', depth=-1)."""
    return _send({"method": method, "params": params, "session_id": session_id}).get("result", {})


def drain_events():  return _send({"meta": "drain_events"})["events"]


# --- Anti-Detection & Interception (Self-Evolving Capability) ---
def ensure_stealth_mode(target_url=None):
    """Automatically inject anti-detection scripts and intercept malicious requests.
    This is triggered automatically for sensitive domains like taobao.com."""
    sensitive_domains = ["taobao.com", "tmall.com", "sycm.taobao.com", "myseller.taobao.com"]
    
    if target_url and not any(domain in target_url for domain in sensitive_domains):
        return "Not a sensitive domain, skipping stealth mode"

    # 1. Inject script to evaluate on new document (runs before page JS)
    stealth_code = '''
    (function() {
        // Hide webdriver
        Object.defineProperty(navigator, 'webdriver', { get: () => false });
        
        // Hide chrome object
        window.chrome = { runtime: {} };
        
        // Spoof plugins
        Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
        
        // Spoof languages
        Object.defineProperty(navigator, 'languages', { get: () => ['zh-CN', 'zh', 'en-US', 'en'] });
        
        // Spoof permissions
        const origQuery = window.navigator.permissions.query;
        window.navigator.permissions.query = (p) => (
            p.name === 'notifications' ? Promise.resolve({ state: Notification.permission }) : origQuery(p)
        );
        
        // Hide DevTools detection
        window.outerWidth = window.innerWidth;
        window.outerHeight = window.innerHeight;
        
        // Spoof WebGL
        const getParam = WebGLRenderingContext.prototype.getParameter;
        WebGLRenderingContext.prototype.getParameter = function(p) {
            if (p === 37445) return 'Intel Open Source Technology Center';
            if (p === 37446) return 'Mesa DRI Intel(R) HD Graphics 620 (Kaby Lake GT2)';
            return getParam.call(this, p);
        };
        
        // Intercept baxia/alibaby SDK requests
        const origFetch = window.fetch;
        window.fetch = function(...args) {
            if (args[0] && args[0].includes && (args[0].includes('baxia') || args[0].includes('bixi') || args[0].includes('punish'))) {
                return Promise.resolve({ ok: false, status: 403 });
            }
            return origFetch.apply(this, args);
        };
        
        const origXHR = window.XMLHttpRequest.prototype.open;
        window.XMLHttpRequest.prototype.open = function(m, u) {
            if (u && u.includes && (u.includes('baxia') || u.includes('bixi') || u.includes('punish'))) {
                return;
            }
            return origXHR.apply(this, arguments);
        };
    })();
    '''
    
    try:
        cdp('Page.addScriptToEvaluateOnNewDocument', source=stealth_code)
        
        # 2. Enable network interception for baxia-related requests
        cdp('Fetch.enable', patterns=[
            {'urlPattern': '*bixi.alicdn.com*', 'requestStage': 'Request'},
            {'urlPattern': '*baxia*', 'requestStage': 'Request'},
            {'urlPattern': '*punish*', 'requestStage': 'Request'},
        ])
        
        return "Stealth mode activated: Anti-detection scripts injected and baxia requests intercepted"
    except Exception as e:
        return f"Failed to activate stealth mode: {e}"


# --- navigation / page ---
def goto_url(url):
    """Navigate to URL. Auto-activates stealth mode for sensitive domains."""
    # Self-evolving: automatically apply anti-detection for Taobao/Sycm
    ensure_stealth_mode(url)
    
    r = cdp("Page.navigate", url=url)
    d = (Path(__file__).parent / "domain-skills" / (urlparse(url).hostname or "").removeprefix("www.").split(".")[0])
    return {**r, "domain_skills": sorted(p.name for p in d.rglob("*.md"))[:10]} if d.is_dir() else r

def page_info():
    """{url, title, w, h, sx, sy, pw, ph} — viewport + scroll + page size.

    If a native dialog (alert/confirm/prompt/beforeunload) is open, returns
    {dialog: {type, message, ...}} instead — the page's JS thread is frozen
    until the dialog is handled (see interaction-skills/dialogs.md)."""
    dialog = _send({"meta": "pending_dialog"}).get("dialog")
    if dialog:
        return {"dialog": dialog}
    r = cdp("Runtime.evaluate",
            expression="JSON.stringify({url:location.href,title:document.title,w:innerWidth,h:innerHeight,sx:scrollX,sy:scrollY,pw:document.documentElement.scrollWidth,ph:document.documentElement.scrollHeight})",
            returnByValue=True)
    return json.loads(r["result"]["value"])

# --- input ---
_debug_click_counter = 0

def click_at_xy(x, y, button="left", clicks=1):
    if os.environ.get("BH_DEBUG_CLICKS"):
        global _debug_click_counter
        try:
            from PIL import Image, ImageDraw
            dpr = js("window.devicePixelRatio") or 1
            path = capture_screenshot(f"/tmp/debug_click_{_debug_click_counter}.png")
            img = Image.open(path)
            draw = ImageDraw.Draw(img)
            px, py = int(x * dpr), int(y * dpr)
            r = int(15 * dpr)
            draw.ellipse([px - r, py - r, px + r, py + r], outline="red", width=int(3 * dpr))
            draw.line([px - r - int(5 * dpr), py, px + r + int(5 * dpr), py], fill="red", width=int(2 * dpr))
            draw.line([px, py - r - int(5 * dpr), px, py + r + int(5 * dpr)], fill="red", width=int(2 * dpr))
            img.save(path)
            print(f"[debug_click] saved {path} (x={x}, y={y}, dpr={dpr})")
        except Exception as e:
            print(f"[debug_click] overlay failed: {e}")
        _debug_click_counter += 1
    cdp("Input.dispatchMouseEvent", type="mousePressed", x=x, y=y, button=button, clickCount=clicks)
    cdp("Input.dispatchMouseEvent", type="mouseReleased", x=x, y=y, button=button, clickCount=clicks)

def type_text(text):
    cdp("Input.insertText", text=text)

_KEYS = {  # key → (windowsVirtualKeyCode, code, text)
    "Enter": (13, "Enter", "\r"), "Tab": (9, "Tab", "\t"), "Backspace": (8, "Backspace", ""),
    "Escape": (27, "Escape", ""), "Delete": (46, "Delete", ""), " ": (32, "Space", " "),
    "ArrowLeft": (37, "ArrowLeft", ""), "ArrowUp": (38, "ArrowUp", ""),
    "ArrowRight": (39, "ArrowRight", ""), "ArrowDown": (40, "ArrowDown", ""),
    "Home": (36, "Home", ""), "End": (35, "End", ""),
    "PageUp": (33, "PageUp", ""), "PageDown": (34, "PageDown", ""),
}
def press_key(key, modifiers=0):
    """Modifiers bitfield: 1=Alt, 2=Ctrl, 4=Meta(Cmd), 8=Shift.
    Special keys (Enter, Tab, Arrow*, Backspace, etc.) carry their virtual key codes
    so listeners checking e.keyCode / e.key all fire."""
    vk, code, text = _KEYS.get(key, (ord(key[0]) if len(key) == 1 else 0, key, key if len(key) == 1 else ""))
    base = {"key": key, "code": code, "modifiers": modifiers, "windowsVirtualKeyCode": vk, "nativeVirtualKeyCode": vk}
    cdp("Input.dispatchKeyEvent", type="keyDown", **base, **({"text": text} if text else {}))
    if text and len(text) == 1:
        cdp("Input.dispatchKeyEvent", type="char", text=text, **{k: v for k, v in base.items() if k != "text"})
    cdp("Input.dispatchKeyEvent", type="keyUp", **base)

def scroll(x, y, dy=-300, dx=0):
    cdp("Input.dispatchMouseEvent", type="mouseWheel", x=x, y=y, deltaX=dx, deltaY=dy)


# --- visual ---
def capture_screenshot(path="/tmp/shot.png", full=False):
    r = cdp("Page.captureScreenshot", format="png", captureBeyondViewport=full)
    open(path, "wb").write(base64.b64decode(r["data"]))
    return path


# --- tabs ---
def list_tabs(include_chrome=True):
    out = []
    for t in cdp("Target.getTargets")["targetInfos"]:
        if t["type"] != "page": continue
        url = t.get("url", "")
        if not include_chrome and url.startswith(INTERNAL): continue
        out.append({"targetId": t["targetId"], "title": t.get("title", ""), "url": url})
    return out

def current_tab():
    t = cdp("Target.getTargetInfo").get("targetInfo", {})
    return {"targetId": t.get("targetId"), "url": t.get("url", ""), "title": t.get("title", "")}

def _mark_tab():
    """Prepend 🟢 to tab title so the user can see which tab the agent controls."""
    try: cdp("Runtime.evaluate", expression="if(!document.title.startsWith('\U0001F7E2'))document.title='\U0001F7E2 '+document.title")
    except Exception: pass

def switch_tab(target):
    # Accept either a raw targetId string or the dict returned by current_tab() / list_tabs(),
    # so `switch_tab(current_tab())` works without a manual ["targetId"] dance.
    target_id = target.get("targetId") if isinstance(target, dict) else target
    # Unmark old tab
    try: cdp("Runtime.evaluate", expression="if(document.title.startsWith('\U0001F7E2 '))document.title=document.title.slice(2)")
    except Exception: pass
    cdp("Target.activateTarget", targetId=target_id)
    sid = cdp("Target.attachToTarget", targetId=target_id, flatten=True)["sessionId"]
    _send({"meta": "set_session", "session_id": sid})
    _mark_tab()
    return sid

def new_tab(url="about:blank"):
    # Always create blank, then goto: passing url to createTarget races with
    # attach, so the brief about:blank is "complete" by the time the caller
    # polls and wait_for_load() returns before navigation actually starts.
    tid = cdp("Target.createTarget", url="about:blank")["targetId"]
    switch_tab(tid)
    if url != "about:blank":
        goto_url(url)
    return tid

def ensure_real_tab():
    """Switch to a real user tab if current is chrome:// / internal / stale."""
    tabs = list_tabs(include_chrome=False)
    if not tabs:
        return None
    try:
        cur = current_tab()
        if cur["url"] and not cur["url"].startswith(INTERNAL):
            return cur
    except Exception:
        pass
    switch_tab(tabs[0]["targetId"])
    return tabs[0]

def iframe_target(url_substr):
    """First iframe target whose URL contains `url_substr`. Use with js(..., target_id=...)."""
    for t in cdp("Target.getTargets")["targetInfos"]:
        if t["type"] == "iframe" and url_substr in t.get("url", ""):
            return t["targetId"]
    return None


# --- utility ---
def wait(seconds=1.0):
    time.sleep(seconds)

def wait_for_load(timeout=15.0):
    """Poll document.readyState == 'complete' or timeout."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if js("document.readyState") == "complete": return True
        time.sleep(0.3)
    return False

def js(expression, target_id=None):
    """Run JS in the attached tab (default) or inside an iframe target (via iframe_target()).

    Expressions with top-level `return` are automatically wrapped in an IIFE, so both
    `document.title` and `const x = 1; return x` are valid inputs.
    """
    sid = cdp("Target.attachToTarget", targetId=target_id, flatten=True)["sessionId"] if target_id else None
    if "return " in expression and not expression.strip().startswith("("):
        expression = f"(function(){{{expression}}})()"
    r = cdp("Runtime.evaluate", session_id=sid, expression=expression, returnByValue=True, awaitPromise=True)
    return r.get("result", {}).get("value")


_KC = {"Enter": 13, "Tab": 9, "Escape": 27, "Backspace": 8, " ": 32, "ArrowLeft": 37, "ArrowUp": 38, "ArrowRight": 39, "ArrowDown": 40}


def dispatch_key(selector, key="Enter", event="keypress"):
    """Dispatch a DOM KeyboardEvent on the matched element.

    Use this when a site reacts to synthetic DOM key events on an element more reliably
    than to raw CDP input events.
    """
    kc = _KC.get(key, ord(key) if len(key) == 1 else 0)
    js(
        f"(()=>{{const e=document.querySelector({json.dumps(selector)});if(e){{e.focus();e.dispatchEvent(new KeyboardEvent({json.dumps(event)},{{key:{json.dumps(key)},code:{json.dumps(key)},keyCode:{kc},which:{kc},bubbles:true}}));}}}})()"
    )

def upload_file(selector, path):
    """Set files on a file input via CDP DOM.setFileInputFiles. `path` is an absolute filepath (use tempfile.mkstemp if needed)."""
    doc = cdp("DOM.getDocument", depth=-1)
    nid = cdp("DOM.querySelector", nodeId=doc["root"]["nodeId"], selector=selector)["nodeId"]
    if not nid: raise RuntimeError(f"no element for {selector}")
    cdp("DOM.setFileInputFiles", files=[path] if isinstance(path, str) else list(path), nodeId=nid)

def http_get(url, headers=None, timeout=20.0):
    """Pure HTTP — no browser. Use for static pages / APIs. Wrap in ThreadPoolExecutor for bulk.

    When BROWSER_USE_API_KEY is set, routes through the fetch-use proxy (handles bot
    detection, residential proxies, retries). Falls back to local urllib otherwise."""
    if os.environ.get("BROWSER_USE_API_KEY"):
        try:
            from fetch_use import fetch_sync
            return fetch_sync(url, headers=headers, timeout_ms=int(timeout * 1000)).text
        except ImportError:
            pass
    import gzip
    h = {"User-Agent": "Mozilla/5.0", "Accept-Encoding": "gzip"}
    if headers: h.update(headers)
    with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=timeout) as r:
        data = r.read()
        if r.headers.get("Content-Encoding") == "gzip": data = gzip.decompress(data)
        return data.decode()



def get_element_text(selector):
    """Get text content of first element matching selector."""
    return js(f'document.querySelector("{selector}")?.innerText || ""')



def extract_bilibili_cards(limit=5):
    """Extract video cards from Bilibili homepage.
    
    Returns list of {title, link} dicts.
    """
    import json
    raw = js(f'''
      const cards = document.querySelectorAll(".feed-card");
      const results = [];
      cards.forEach((card, idx) => {{
        if (idx >= {limit}) return;
        const titleEl = card.querySelector(".bili-video-card__info--tit a, .bili-video-card__info--tit");
        const link = card.querySelector("a[href*='/video/']")?.href || "";
        results.push(JSON.stringify({{
          title: titleEl ? (titleEl.title || titleEl.innerText.trim()) : "",
          link: link.substring(0, 80)
        }}));
      }});
      results.join('\\n');
    ''')
    if not raw:
        return []
    return [json.loads(line) for line in raw.split('\n') if line.strip()]


# --- Anti-Detection & Human-like Behavior ---

def inject_stealth():
    """Inject JS to hide automation fingerprints (Stealth Mode)."""
    stealth_script = '''
    () => {
        // 1. Hide navigator.webdriver
        Object.defineProperty(navigator, 'webdriver', { get: () => false });
        
        // 2. Spoof plugins
        Object.defineProperty(navigator, 'plugins', { 
            get: () => [1, 2, 3, 4, 5] 
        });
        
        // 3. Spoof languages
        Object.defineProperty(navigator, 'languages', { 
            get: () => ['zh-CN', 'zh', 'en-US', 'en'] 
        });
        
        // 4. Hide chrome object (if exists)
        if (window.chrome) {
            window.chrome.runtime = undefined;
        }
        
        // 5. Spoof permissions
        const originalQuery = window.navigator.permissions.query;
        window.navigator.permissions.query = (parameters) => (
            parameters.name === 'notifications' ?
                Promise.resolve({ state: Notification.permission }) :
                originalQuery(parameters)
        );
        
        return 'Stealth injected successfully';
    }
    '''
    return js(stealth_script)


def human_scroll(duration=3.0, steps=15):
    """Simulate human-like random scrolling."""
    import random, time
    scroll_script = '''
    (y) => window.scrollBy(0, y)
    '''
    for _ in range(steps):
        # Random scroll amount (pixels)
        delta = random.randint(50, 300)
        # Sometimes scroll up slightly to mimic reading behavior
        if random.random() < 0.1:
            delta = -delta
        
        js(scroll_script.replace('(y) =>', f'() =>').replace('window.scrollBy(0, y)', f'window.scrollBy(0, {delta})'))
        
        # Random delay between scrolls
        time.sleep(random.uniform(0.5, 1.5))
    
    return "Human scroll completed"


def human_mouse_move(steps=5):
    """Simulate random mouse movements within the viewport."""
    import random
    # Note: CDP mouse movement is harder to simulate purely via JS without dispatching events
    # But we can dispatch synthetic mousemove events on document
    move_script = '''
    (x, y) => {
        const event = new MouseEvent('mousemove', {
            view: window,
            bubbles: true,
            cancelable: true,
            clientX: x,
            clientY: y
        });
        document.dispatchEvent(event);
    }
    '''
    for _ in range(steps):
        x = random.randint(100, 1000)
        y = random.randint(100, 800)
        js(move_script.replace('(x, y) =>', f'() =>').replace('clientX: x', f'clientX: {x}').replace('clientY: y', f'clientY: {y}'))
    return "Human mouse move completed"

