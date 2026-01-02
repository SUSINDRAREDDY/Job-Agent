"""
Browser Automation Tools
"""
from langchain_core.tools import tool
from typing import Dict, Any, Optional
import time
import os
import json
import base64
import html

from browser.playwright_manager import get_playwright_manager
from config import get_vision_llm
from langchain_core.messages import HumanMessage



USE_REAL_CHROME = True
CDP_PORT = 9222

VISUAL_REFS: Dict[str, tuple] = {}

KEY_MAP = {
    "ctrl": "Control", "control": "Control",
    "cmd": "Meta", "command": "Meta", "meta": "Meta",
    "alt": "Alt", "option": "Alt", "shift": "Shift",
    "enter": "Enter", "return": "Enter", "tab": "Tab",
    "delete": "Delete", "backspace": "Backspace",
    "escape": "Escape", "esc": "Escape", "space": " ",
    "up": "ArrowUp", "down": "ArrowDown",
    "left": "ArrowLeft", "right": "ArrowRight",
}



def ensure_browser_connected():
    """Ensure browser is connected."""
    pm = get_playwright_manager()
    try:
        page = pm.get_page()
        if page and not page.is_closed():
            return page
    except Exception:
        pass
    return _connect_to_browser_impl(use_real_chrome=USE_REAL_CHROME, port=CDP_PORT)


def _connect_to_browser_impl(use_real_chrome: bool = False, port: int = 9222):
    """Connect to browser."""
    pm = get_playwright_manager()
    if use_real_chrome:
        chrome_path = os.path.expanduser("~/Library/Application Support/Google/Chrome")
        return pm.connect_real_chrome(chrome_base=chrome_path, profile_name="Default")
    return pm.connect_persistent()


def show_status(message: str, status_type: str = "info") -> None:
    """Show status overlay."""
    try:
        pm = get_playwright_manager()
        pm.show_status(message, status_type)
    except Exception:
        pass


def _map_key(key: str) -> str:
    """Map key name to Playwright format."""
    return KEY_MAP.get(key.lower(), key)



@tool
def navigate_to_url(url: str) -> str:
    """Navigate browser to a URL."""
    print(f"[TOOL] navigate_to_url: {url}")
    try:
        show_status(f"Navigating...", "info")
        page = ensure_browser_connected()
        page.goto(url, wait_until='domcontentloaded', timeout=30000)
        time.sleep(2)
        title = page.title()
        show_status(f"{title[:30]}", "success")
        return f"Navigated to {url}\nTitle: {title}"
    except Exception as e:
        return f"Navigation failed: {str(e)}"


@tool  
def scroll_page(direction: str, amount: int = 500) -> str:
    """Scroll page. Directions: up, down, top, bottom (loads all lazy content)."""
    print(f"[TOOL] scroll_page: {direction}, {amount}")
    try:
        page = ensure_browser_connected()
        if direction == "down":
            page.mouse.wheel(0, amount)
            time.sleep(0.5)
            return f"Scrolled down {amount}px"
        elif direction == "up":
            page.mouse.wheel(0, -amount)
            time.sleep(0.5)
            return f"Scrolled up {amount}px"
        elif direction == "top":
            page.evaluate("window.scrollTo(0, 0)")
            time.sleep(0.5)
            return "Scrolled to top"
        elif direction == "bottom":
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(1.0)
            return "Scrolled to bottom"
        else:
            return f"Invalid direction: {direction}. Use: up, down, top, bottom"
    except Exception as e:
        return f"Scroll failed: {str(e)}"


@tool
def wait_seconds(duration: float) -> str:
    """Wait for specified seconds."""
    try:
        if duration < 0 or duration > 30:
            return "Duration must be 0-30 seconds"
        time.sleep(duration)
        return f"Waited {duration}s"
    except Exception as e:
        return f"Wait failed: {str(e)}"






def _click_at_impl(x: Optional[int] = None, y: Optional[int] = None, ref: Optional[str] = None) -> str:
    """Internal implementation of click_at."""
    """Click at coordinates (x, y) OR by element ref. Returns info about what changed including URL.
    
    Ways to use:
    1. By Ref (Recommended): click_at(ref="ref_12") - Robust to layout shifts, auto-scrolls to element.
    2. By Coords: click_at(x=500, y=300) - For when you only have coordinates (e.g. from vision or JS search).

    IMPORTANT: 
    - Do NOT call this tool multiple times in the same turn (parallel execution race conditions).
    - To click multiple items or mix clicks with inputs, use `execute_action_sequence`!
    """
    print(f"[TOOL] click_at(x={x}, y={y}, ref={ref})")
    try:
        page = ensure_browser_connected()
        
        if ref:
            if '_load_script' in globals():
                script = globals()['_load_script']("element_ref_script.js")
                if script:
                    ref_res = page.evaluate(f"({script})('{ref}')")
                    if ref_res.get("success"):
                        x = ref_res["x"]
                        y = ref_res["y"]
                        print(f"  Resolved {ref} -> ({x}, {y})")
                    else:
                        return f"Failed to resolve ref '{ref}': {ref_res.get('message', 'Unknown error')}"
                else:
                    return "Internal Error: element_ref_script.js not found"
            else:
                return "Internal Error: _load_script helper not available"
        
        if x is None or y is None:
             return "Error: You must provide either 'ref' (recommended) or 'x' and 'y' coordinates."
        
        url_before = page.url
        
        viewport = page.evaluate("() => ({ width: window.innerWidth, height: window.innerHeight })")
        vh = viewport['height']
        
        if y < 0:
            scroll_amount = y - (vh // 2)
            print(f"  Auto-scrolling up by {abs(int(scroll_amount))}px to reach Y={y}")
            page.mouse.wheel(0, scroll_amount)
            time.sleep(0.3)
            y = int(y - scroll_amount)
            
        elif y > vh:
            scroll_amount = y - (vh // 2)
            print(f"  Auto-scrolling down by {int(scroll_amount)}px to reach Y={y}")
            page.mouse.wheel(0, scroll_amount)
            time.sleep(0.3)
            y = int(y - scroll_amount)

        if not (0 <= y <= vh):
             print(f"  Recalculated Y={y} is still OOB. Clamping to viewport edge.")
             y = max(1, min(y, vh - 1))
        
        before_state = page.evaluate("""() => {
            const activeEl = document.activeElement;
            const overlays = document.querySelectorAll('[role="listbox"], [role="menu"], [role="dialog"], .dropdown-menu, [class*="dropdown"], [class*="popup"], [class*="overlay"], [class*="modal"]');
            const visibleOverlays = Array.from(overlays).filter(el => el.offsetParent !== null && el.getBoundingClientRect().height > 0);
            return {
                activeTag: activeEl ? activeEl.tagName : null,
                activeType: activeEl ? activeEl.type : null,
                overlayCount: visibleOverlays.length
            };
        }""")
        
        page.mouse.move(x, y)
        page.mouse.click(x, y)
        time.sleep(0.4)
        
        url_after = page.url
        
        after_state = page.evaluate("""() => {
            const activeEl = document.activeElement;
            const overlays = document.querySelectorAll('[role="listbox"], [role="menu"], [role="dialog"], .dropdown-menu, [class*="dropdown"], [class*="popup"], [class*="overlay"], [class*="modal"], [class*="filter"]');
            const visibleOverlays = Array.from(overlays).filter(el => el.offsetParent !== null && el.getBoundingClientRect().height > 0);
            
            // Get popup title/heading if any
            let popupTitle = null;
            for (const overlay of visibleOverlays) {
                const heading = overlay.querySelector('h1, h2, h3, h4, [class*="title"], [class*="header"], legend');
                if (heading) {
                    popupTitle = heading.textContent.trim().substring(0, 50);
                    break;
                }
            }
            
            // Initialize refs if not exists
            if (!window.__elementMap) window.__elementMap = {};
            if (!window.__refCounter) window.__refCounter = 0;
            
            // Get ALL interactive elements inside the popup overlays - no filtering!
            // Each website works differently, so don't assume what's there
            let popupElements = [];
            for (const overlay of visibleOverlays) {
                // Get all clickable/interactive elements inside this overlay
                const els = overlay.querySelectorAll('a, button, label, input, li, [role="option"], [role="menuitem"], [role="checkbox"], [role="button"]');
                els.forEach(el => {
                    if (!el.offsetParent) return;  // Skip hidden elements
                    const text = el.textContent.trim();
                    if (!text || text.length < 2) return;  // Skip empty elements
                    
                    const ref = 'ref_' + (++window.__refCounter);
                    window.__elementMap[ref] = new WeakRef(el);
                    const rect = el.getBoundingClientRect();
                    
                    // Check if this is a checkbox/selected item
                    let isChecked = false;
                    if (el.tagName === 'INPUT' && el.type === 'checkbox') {
                        isChecked = el.checked;
                    } else if (el.getAttribute('aria-checked') === 'true' || el.getAttribute('aria-selected') === 'true') {
                        isChecked = true;
                    } else {
                        const nestedCheckbox = el.querySelector('input[type="checkbox"]');
                        if (nestedCheckbox) isChecked = nestedCheckbox.checked;
                    }
                    
                    // Determine element type
                    const tag = el.tagName.toLowerCase();
                    const isButton = tag === 'button' || el.getAttribute('role') === 'button';
                    
                    popupElements.push({
                        ref: ref,
                        text: text.substring(0, 50),
                        type: isButton ? 'button' : (isChecked !== undefined ? 'option' : 'link'),
                        checked: isChecked,
                        x: Math.round(rect.left + rect.width/2),
                        y: Math.round(rect.top + rect.height/2)
                    });
                });
            }
            
            return {
                activeTag: activeEl ? activeEl.tagName : null,
                activeType: activeEl ? activeEl.type : null,
                activeId: activeEl ? activeEl.id : null,
                overlayCount: visibleOverlays.length,
                popupTitle: popupTitle,
                popupElements: popupElements.slice(0, 20)  // Return up to 20 elements
            };
        }""")
        
        changes = []
        
        if url_after != url_before:
            changes.append(f"URL CHANGED: {url_after}")
        
        if after_state['activeTag'] == 'INPUT' and after_state.get('activeType') == 'checkbox':
            checkbox_result = page.evaluate("""() => {
                const el = document.activeElement;
                if (el && el.type === 'checkbox') {
                    // Just report the state - don't click again!
                    return { 
                        checked: el.checked, 
                        id: el.id,
                        text: el.closest('label')?.textContent?.trim() || el.nextElementSibling?.textContent?.trim() || ''
                    };
                }
                return null;
            }""")
            if checkbox_result:
                state = "CHECKED" if checkbox_result['checked'] else "UNCHECKED"
                text = checkbox_result.get('text', '')[:30]
                changes.append(f"Checkbox is now: {state} - '{text}'")
                changes.append("Wait for page to update, or click 'Apply'/'Update' button if present")
        elif after_state['activeTag'] == 'INPUT':
            input_type = after_state.get('activeType', 'text')
            input_id = after_state.get('activeId', '')
            changes.append(f"Input focused ({input_type}, id='{input_id}'). Ready to type.")
        
        overlay_diff = after_state['overlayCount'] - before_state['overlayCount']
        if overlay_diff > 0:
            popup_elements = after_state.get('popupElements', [])
            popup_title = after_state.get('popupTitle')
            
            if not popup_elements:
                time.sleep(1.0)  # Wait for dynamic content
                retry_state = page.evaluate("""() => {
                    const overlays = document.querySelectorAll('[role="listbox"], [role="menu"], [role="dialog"], .dropdown-menu, [class*="dropdown"], [class*="popup"], [class*="overlay"], [class*="modal"], [class*="filter"]');
                    const visibleOverlays = Array.from(overlays).filter(el => el.offsetParent !== null && el.getBoundingClientRect().height > 0);
                    
                    let popupTitle = null;
                    for (const overlay of visibleOverlays) {
                        const heading = overlay.querySelector('h1, h2, h3, h4, [class*="title"], [class*="header"], legend');
                        if (heading) {
                            popupTitle = heading.textContent.trim().substring(0, 50);
                            break;
                        }
                    }
                    
                    if (!window.__elementMap) window.__elementMap = {};
                    if (!window.__refCounter) window.__refCounter = 0;
                    
                    let popupElements = [];
                    for (const overlay of visibleOverlays) {
                        // Get ALL interactive elements - no assumptions about content type
                        const els = overlay.querySelectorAll('a, button, label, input, select, textarea, li, [role="option"], [role="menuitem"], [role="checkbox"], [role="button"], [tabindex]');
                        els.forEach(el => {
                            if (!el.offsetParent) return;
                            const text = (el.textContent || el.placeholder || el.name || el.id || el.ariaLabel || '').trim();
                            if (!text || text.length < 1) return;
                            
                            const ref = 'ref_' + (++window.__refCounter);
                            window.__elementMap[ref] = new WeakRef(el);
                            const rect = el.getBoundingClientRect();
                            const tag = el.tagName.toLowerCase();
                            
                            popupElements.push({
                                ref: ref,
                                text: text.substring(0, 60),
                                type: tag,
                                x: Math.round(rect.left + rect.width/2),
                                y: Math.round(rect.top + rect.height/2)
                            });
                        });
                    }
                    
                    return { popupTitle, popupElements: popupElements.slice(0, 30) };
                }""")
                popup_elements = retry_state.get('popupElements', [])
                popup_title = retry_state.get('popupTitle') or popup_title
            
            if popup_title:
                changes.append(f"POPUP: \"{popup_title}\"")
            else:
                changes.append("POPUP OPENED")
            
            if popup_elements:
                changes.append(f"ELEMENTS ({len(popup_elements)}):")
                for el in popup_elements:
                    check_mark = "*" if el.get('checked') else " "
                    el_type = el.get('type', '')
                    if el_type == 'button':
                        changes.append(f"  [BTN] {el['ref']}: '{el['text']}'")
                    elif el_type == 'input':
                        changes.append(f"  [INPUT] {el['ref']}: '{el['text']}'")
                    elif el_type == 'a':
                        changes.append(f"  [LINK] {el['ref']}: '{el['text']}'")
                    else:
                        changes.append(f"  [{el_type}] {el['ref']}: '{el['text']}'")
            else:
                changes.append("No elements detected. Use get_page_elements() to scan full page.")
        elif overlay_diff < 0:
            changes.append("Popup closed.")
        
        if before_state['overlayCount'] > 0 and after_state['overlayCount'] == 0 and url_after != url_before:
            changes.append("Filter applied (URL updated).")
        
        if changes:
            result = f"Clicked at ({x},{y}). " + " ".join(changes)
        else:
            result = f"Clicked at ({x},{y}). No visible UI change."
        
        result += f" [Current URL: {url_after}]"
        return result
    except Exception as e:
        return f"Click failed: {str(e)}"



@tool
def click_at(x: Optional[int] = None, y: Optional[int] = None, ref: Optional[str] = None) -> str:
    """Click at coordinates (x, y) OR by element ref. Returns info about what changed including URL.
    
    Ways to use:
    1. By Ref (Recommended): click_at(ref="ref_12") - Robust to layout shifts, auto-scrolls to element.
    2. By Coords: click_at(x=500, y=300) - For when you only have coordinates (e.g. from vision or JS search).

    IMPORTANT: 
    - Do NOT call this tool multiple times in the same turn (parallel execution race conditions).
    - To click multiple items or mix clicks with inputs, use `execute_action_sequence`!
    """
    return _click_at_impl(x, y, ref)


@tool
def type_at(x: int, y: int, text: str) -> str:
    """Click at coordinates then type text. Clears existing content first."""
    print(f"[TOOL] type_at({x}, {y}, '{text}')")
    try:
        page = ensure_browser_connected()
        
        page.mouse.move(x, y)
        page.mouse.click(x, y, click_count=3)
        time.sleep(0.15)
        
        page.keyboard.press("Backspace")
        time.sleep(0.1)
        
        page.keyboard.type(text, delay=30)
        
        return f"Typed '{text}' at ({x},{y}) (cleared existing content first)"
    except Exception as e:
        return f"Type failed: {str(e)}"




@tool
def get_page_elements() -> str:
    """Get all visible interactive elements in viewport (expensive, use sparingly)."""
    print(f"[TOOL] get_page_elements")
    try:
        page = ensure_browser_connected()
        show_status("Scanning elements...", "info")
        
        from browser.accessibility_scanner import ELEMENT_MAP
        ELEMENT_MAP.clear()
        
        result = page.evaluate("""
            (() => {
                // Initialize or reuse WeakRef element map for stable refs
                if (!window.__elementMap) window.__elementMap = {};
                if (!window.__refCounter) window.__refCounter = 0;
                
                let output = [];
                let mapData = {};
                
                function isVisible(el) {
                    const style = window.getComputedStyle(el);
                    const rect = el.getBoundingClientRect();
                    return rect.width > 0 && rect.height > 0 && 
                           style.visibility !== 'hidden' && 
                           style.display !== 'none';
                }
                
                function getText(el) {
                    return (el.getAttribute('aria-label') || el.textContent || '').trim().substring(0, 60);
                }
                
                // Detect if element is a dropdown/expandable container
                function isDropdown(el) {
                    // Check aria attributes
                    const hasPopup = el.getAttribute('aria-haspopup');
                    if (hasPopup && hasPopup !== 'false') return true;
                    
                    const expanded = el.getAttribute('aria-expanded');
                    if (expanded !== null) return true;  // Has expandable state
                    
                    // Check roles
                    const role = el.getAttribute('role');
                    if (['combobox', 'listbox', 'menu', 'menubutton'].includes(role)) return true;
                    
                    // Check if it's a select element
                    if (el.tagName.toLowerCase() === 'select') return true;
                    
                    // Check class names for dropdown indicators
                    const className = (el.className || '').toLowerCase();
                    if (className.includes('dropdown') || className.includes('select') || 
                        className.includes('expand') || className.includes('toggle') ||
                        className.includes('filter') || className.includes('menu-trigger')) return true;
                    
                    return false;
                }
                
                // Check if dropdown is currently expanded
                function isExpanded(el) {
                    return el.getAttribute('aria-expanded') === 'true';
                }
                
                // Only scan these element types
                const selectors = 'a, button, input, textarea, select, h1, h2, h3, [role="button"], [role="combobox"], [aria-haspopup]';
                
                document.querySelectorAll(selectors).forEach(el => {
                    if (!isVisible(el)) return;
                    
                    const tag = el.tagName.toLowerCase();
                    const rect = el.getBoundingClientRect();
                    // Use VIEWPORT coordinates directly (no scroll offset)
                    // This matches what Playwright's mouse.click() expects
                    const x = Math.round(rect.left + rect.width / 2);
                    const y = Math.round(rect.top + rect.height / 2);
                    
                    // VIEWPORT-ONLY FILTER: Skip elements far outside viewport
                    // Keep elements slightly outside (+100px buffer) for scroll hints
                    const vh = window.innerHeight;
                    const vw = window.innerWidth;
                    if (y < -100 || y > vh + 100) return;  // Above/below viewport
                    if (x < -100 || x > vw + 100) return;  // Left/right of viewport
                    
                    const text = getText(el);
                    const domId = el.id || null;
                    
                    // Skip empty elements (except inputs)
                    if (!text && !['input', 'textarea', 'select'].includes(tag)) return;
                    
                    // Create stable ref using WeakRef
                    const ref = 'ref_' + (++window.__refCounter);
                    window.__elementMap[ref] = new WeakRef(el);
                    
                    // Detect dropdown status
                    const dropdown = isDropdown(el);
                    const expanded = isExpanded(el);
                    
                    mapData[ref] = { coords: [x, y], dom_id: domId, tag: tag, dropdown: dropdown };
                    
                    // Format: (x,y) tag#id: text
                    let label = tag;
                    if (domId) label += '#' + domId.substring(0, 25);
                    const type = el.getAttribute('type');
                    if (type) label += '[' + type + ']';
                    
                    // Add dropdown indicator
                    let dropdownMark = '';
                    if (dropdown) {
                        dropdownMark = expanded ? ' [▼ OPEN]' : ' [▼ dropdown]';
                    }
                    
                    if (['input', 'textarea'].includes(tag)) {
                        // For inputs: show placeholder AND current value
                        const placeholder = el.getAttribute('placeholder') || '';
                        const value = el.value || '';
                        let inputInfo = '';
                        if (placeholder) inputInfo += 'placeholder="' + placeholder.substring(0, 30) + '"';
                        if (value) {
                            if (inputInfo) inputInfo += ' ';
                            inputInfo += 'value="' + value.substring(0, 30) + '"';
                        }
                        if (!inputInfo) inputInfo = 'empty';
                        output.push(`${ref}: (${x},${y}) ${label}: [${inputInfo}]`);
                    } else if (tag === 'select') {
                        // Select is always a dropdown
                        const selectedText = el.options[el.selectedIndex]?.text || 'no selection';
                        output.push(`${ref}: (${x},${y}) ${label} [▼ dropdown]: ${text || selectedText}`);
                    } else if (text) {
                        output.push(`${ref}: (${x},${y}) ${label}${dropdownMark}: ${text}`);
                    }
                });
                
                return { text: output.join('\\n'), map: mapData };
            })()
        """)
        
        raw_map = result.get("map", {})
        for ref, v in raw_map.items():
            coords = v.get("coords", [0, 0])
            ELEMENT_MAP[ref] = {
                "coords": (int(coords[0]), int(coords[1])),
                "dom_id": v.get("dom_id"),
                "tag": v.get("tag", "")
            }
        
        output = result.get("text", "")
        
        formatted_elements = output.split('\n')
        count = len(formatted_elements)
        
        if count > 50:
            summary = [
                f"Found {count} interactive elements. Showing top 50:",
                *formatted_elements[:50],
                f"... and {count - 50} more elements (buttons, links, inputs).",
                "TIP: Use execute_javascript to find specific elements not listed here."
            ]
            return "\n".join(summary)
        
        show_status(f"Found {len(raw_map)} elements", "success")
        return output
        
    except Exception as e:
        return f"Scan failed: {str(e)}"



@tool
def analyze_page_visually(question: str) -> str:
    """Use AI vision to understand page layout and structure."""
    print(f"[TOOL] analyze_page_visually: {question}")
    try:
        page = ensure_browser_connected()
        show_status("Analyzing...", "info")
        
        screenshot = page.screenshot(type="jpeg", quality=70)
        b64_screenshot = base64.b64encode(screenshot).decode()
        
        vlm = get_vision_llm(max_tokens=500)
        
        msg = HumanMessage(content=[
            {"type": "text", "text": f"""Analyze this browser screenshot.
Question: {question}

IMPORTANT: 
- Describe what you see (elements, layout, structure)
- Do NOT provide coordinates - they will be inaccurate
- The agent will use JavaScript to get accurate coordinates after understanding the page"""},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64_screenshot}"}}
        ])
        
        resp = vlm.invoke([msg])
        answer = resp.content.strip()
        
        show_status("Vision done", "success")
        return answer
        
    except Exception as e:
        return f"Vision failed: {str(e)}"



_extraction_session = {"file_path": None, "jobs": [], "pages_scraped": 0}

@tool
def extract_jobs() -> str:
    """Extract job listings from the current page. Works on Indeed, LinkedIn, Glassdoor, etc.
    
    Saves full job data to JSON file. On repeated calls, APPENDS to same file (for pagination).
    Returns only counts and summary (saves tokens).
    Call scroll_page('bottom') first to load all jobs.
    """
    global _extraction_session
    print("[TOOL] extract_jobs")
    try:
        page = ensure_browser_connected()
        current_url = page.evaluate("window.location.href")
        
        result = page.evaluate("""() => {
            const jobs = [];
            const seen = new Set();
            
            // Most job sites use ul li or article for listings
            document.querySelectorAll('ul li, article').forEach(el => {
                const link = el.querySelector('a[href*="job"], a[href*="jk="], a[href*="career"], a[href*="position"]');
                const title = el.querySelector('h2, h3, h4, [class*="title"], [class*="Title"]');
                if (!link || !title) return;
                
                const text = title.textContent.trim();
                if (text.length < 3 || seen.has(text)) return;
                seen.add(text);
                
                // Extract job ID from URL if present
                const url = link.href;
                const idMatch = url.match(/[?&]jk=([^&]+)/);
                const id = idMatch ? idMatch[1] : null;
                
                jobs.push({ 
                    title: text.slice(0, 80), 
                    url: url,
                    id: id
                });
            });
            
            return { jobs: jobs.slice(0, 50), total: jobs.length };
        }""")
        
        pagination = page.evaluate("""() => {
            const pages = [];
            document.querySelectorAll('a[aria-label*="page"], a[aria-label*="next"], nav[aria-label*="pagination"] a, [data-testid*="pagination"] a').forEach(a => {
                const text = a.textContent?.trim();
                if (text && (text.match(/^\\d+$/) || /next|prev/i.test(text))) {
                    pages.push({ text, href: a.href });
                }
            });
            return pages.slice(0, 10);
        }""")
        
        jobs = result.get('jobs', [])
        page_total = result.get('total', 0)
        
        if not jobs:
            return "No job listings found on this page. Try calling scroll_page('bottom') first to load lazy content."
        
        from datetime import datetime
        
        if _extraction_session["file_path"] is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            project_root = os.path.realpath(os.path.join(os.path.dirname(__file__), ".."))
            extractions_dir = os.path.join(project_root, "logs", "extractions")
            os.makedirs(extractions_dir, exist_ok=True)
            _extraction_session["file_path"] = os.path.join(extractions_dir, f"jobs_{timestamp}.json")
            _extraction_session["jobs"] = []
            _extraction_session["pages_scraped"] = 0
        
        existing_ids = {j.get('id') or j['title'] for j in _extraction_session["jobs"]}
        new_jobs = [j for j in jobs if (j.get('id') or j['title']) not in existing_ids]
        _extraction_session["jobs"].extend(new_jobs)
        _extraction_session["pages_scraped"] += 1
        
        total_jobs = len(_extraction_session["jobs"])
        pages_scraped = _extraction_session["pages_scraped"]
        
        data = {
            "timestamp": datetime.now().isoformat(),
            "url": current_url,
            "jobs": _extraction_session["jobs"],
            "pagination": pagination,
            "summary": {
                "total_jobs": total_jobs,
                "pages_scraped": pages_scraped,
                "total_pages_available": len(pagination)
            }
        }
        
        with open(_extraction_session["file_path"], "w") as f:
            json.dump(data, f, indent=2)
        
        relative_path = _extraction_session["file_path"].replace(os.path.dirname(os.path.dirname(__file__)) + "/", "")
        
        output = f"Page {pages_scraped}: +{len(new_jobs)} new jobs (total: {total_jobs})\n"
        output += f"Data saved: {relative_path}\n"
        if pagination:
            output += f"Pagination available: {len(pagination)} pages"
        else:
            output += "No more pages"
        
        return output
        
    except Exception as e:
        return f"Job extraction failed: {str(e)}"


def reset_extraction_session():
    """Reset the extraction session for a new search."""
    global _extraction_session
    _extraction_session = {"file_path": None, "jobs": [], "pages_scraped": 0}



@tool
def press_key(key: str) -> str:
    """Press a keyboard key (Enter, Escape, Tab, etc)."""
    try:
        page = ensure_browser_connected()
        
        if "+" in key:
            parts = [_map_key(p.strip()) for p in key.split("+")]
            page.keyboard.press("+".join(parts))
        else:
            page.keyboard.press(_map_key(key.strip()))
        
        time.sleep(0.3)
        return f"Pressed {key}"
    except Exception as e:
        return f"Key press failed: {str(e)}"



@tool
def execute_action_sequence(actions: str) -> str:
    """Execute multiple browser actions in a single call to reduce round-trips.
    
    HIGHLY EFFICIENT: Use this to batch ANY sequence of actions!
    
    Args:
        actions: Multi-line string with one action per line
    
    Supported actions:
    - click ref_12          - Click element by ref (RECOMMENDED)
    - fill ref_12 value     - Fill form field by ref (RECOMMENDED)
    - click x,y             - Click at coordinates
    - type x,y text         - Type text at coordinates  
    - press KEY             - Press a key (Enter, Tab, Escape, etc.)
    - wait SECONDS          - Wait for specified seconds
    - scroll up/down        - Scroll the page
    
    Example 1 - Form filling:
    ```
    fill ref_9 AI internship
    fill ref_10 remote
    click ref_11
    wait 3
    ```
    
    Example 2 - General workflow (clicks, waits, scrolls):
    ```
    click ref_45
    wait 2
    scroll down
    click ref_52
    press Enter
    wait 3
    ```
    """
    print(f"[TOOL] execute_action_sequence: {len(actions.split(chr(10)))} actions")
    try:
        page = ensure_browser_connected()
        show_status("Executing action sequence...", "info")
        
        results = []
        lines = [l.strip() for l in actions.strip().split('\n') if l.strip()]
        
        for i, line in enumerate(lines):
            parts = line.split(None, 2)  # Split into max 3 parts
            if not parts:
                continue
                
            action = parts[0].lower()
            
            try:
                if action == "click" and len(parts) >= 2 and parts[1].startswith("ref_"):
                    ref = parts[1]
                    res = _click_at_impl(ref=ref) 
                    results.append(f"OK: {res}")
                    
                elif action in ["fill", "input", "set"] and len(parts) >= 3 and parts[1].startswith("ref_"):
                    ref = parts[1]
                    value = parts[2]
                    res = _form_input_impl(ref=ref, value=value)
                    results.append(f"OK: {res}")

                elif action == "click" and len(parts) >= 2:
                    coords = parts[1].split(",")
                    x, y = int(coords[0]), int(coords[1])
                    
                    before_overlays = page.evaluate("""() => {
                        const overlays = document.querySelectorAll('[role="listbox"], [role="menu"], [role="dialog"], [class*="dropdown"], [class*="popup"]');
                        return Array.from(overlays).filter(el => el.offsetParent !== null).length;
                    }""")
                    
                    page.mouse.move(x, y)
                    page.mouse.click(x, y)
                    time.sleep(0.3)
                    
                    after_state = page.evaluate("""() => {
                        const activeEl = document.activeElement;
                        const overlays = document.querySelectorAll('[role="listbox"], [role="menu"], [role="dialog"], [class*="dropdown"], [class*="popup"]');
                        const visibleOverlays = Array.from(overlays).filter(el => el.offsetParent !== null);
                        const options = document.querySelectorAll('[role="option"], [role="menuitem"], li[tabindex]');
                        const visibleOptions = Array.from(options).filter(el => el.offsetParent !== null);
                        return {
                            overlayCount: visibleOverlays.length,
                            optionCount: visibleOptions.length,
                            focusedInput: activeEl?.tagName === 'INPUT',
                            url: window.location.href
                        };
                    }""")
                    
                    feedback = f"click ({x},{y})"
                    if after_state['overlayCount'] > before_overlays:
                        feedback += f" - dropdown opened ({after_state['optionCount']} options)"
                    elif after_state['focusedInput']:
                        feedback += " - input focused"
                    results.append(f"OK: {feedback}")
                    
                elif action == "type" and len(parts) >= 3:
                    coords = parts[1].split(",")
                    x, y = int(coords[0]), int(coords[1])
                    text = parts[2]
                    page.mouse.move(x, y)
                    page.mouse.click(x, y, click_count=3)
                    time.sleep(0.15)
                    page.keyboard.press("Backspace")
                    time.sleep(0.1)
                    page.keyboard.type(text, delay=20)
                    results.append(f"OK: type '{text}' at ({x},{y}) (cleared first)")
                    
                elif action == "press" and len(parts) >= 2:
                    key = _map_key(parts[1])
                    page.keyboard.press(key)
                    time.sleep(0.2)
                    results.append(f"OK: press {parts[1]}")
                    
                elif action == "wait" and len(parts) >= 2:
                    seconds = float(parts[1])
                    time.sleep(min(seconds, 10))
                    results.append(f"OK: wait {seconds}s")
                    
                elif action == "scroll" and len(parts) >= 2:
                    direction = parts[1].lower()
                    if direction == "down":
                        page.mouse.wheel(0, 500)
                    elif direction == "up":
                        page.mouse.wheel(0, -500)
                    time.sleep(0.3)
                    results.append(f"OK: scroll {direction}")
                    
                else:
                    results.append(f"? unknown/invalid: {line}")
                    
            except Exception as e:
                results.append(f"✗ {action} error: {str(e)}")
        
        return "\n".join(results)
    except Exception as e:
        return f"Sequence failed: {str(e)}"



@tool
def fill_form(fields: str) -> str:
    """Fill multiple form fields in a single call.
    
    HIGHLY EFFICIENT: Use this instead of making separate type_at calls!
    
    Format: One field per line, in format: x,y = value
    
    Example:
    ```
    400,150 = AI internship
    600,150 = remote
    300,300 = john.doe@email.com
    ```
    
    After filling all fields, you may want to press Enter or click Submit.
    
    Args:
        fields: Multi-line string with one field per line (x,y = value)
    """
    print(f"[TOOL] fill_form: {len(fields.split(chr(10)))} fields")
    try:
        page = ensure_browser_connected()
        show_status("Filling form fields...", "info")
        
        results = []
        lines = [l.strip() for l in fields.strip().split('\n') if l.strip() and '=' in l]
        
        for line in lines:
            try:
                coords_part, value = line.split('=', 1)
                coords = coords_part.strip().split(',')
                x, y = int(coords[0].strip()), int(coords[1].strip())
                text = value.strip()
                
                page.mouse.move(x, y)
                page.mouse.click(x, y)
                time.sleep(0.15)
                
                focused = page.evaluate("""() => {
                    const el = document.activeElement;
                    return el ? { tag: el.tagName, type: el.type || '', placeholder: el.placeholder || '' } : null;
                }""")
                
                page.keyboard.press("Control+a")  # Select all
                time.sleep(0.05)
                page.keyboard.type(text, delay=20)
                
                if focused and focused['tag'] in ['INPUT', 'TEXTAREA']:
                    results.append(f"OK: ({x},{y}): '{text}' - filled {focused['tag'].lower()}[{focused['type']}]")
                else:
                    results.append(f"WARN: ({x},{y}): '{text}' - typed but no input focused (focused: {focused})")
                
            except Exception as e:
                results.append(f"✗ {line}: {str(e)}")
        
        final_url = page.evaluate("window.location.href")
        
        show_status(f"{len(results)} fields filled", "success")
        return f"Filled {len(results)} fields:\n" + "\n".join(results) + f"\nCurrent URL: {final_url}"
        
    except Exception as e:
        return f"Form fill failed: {str(e)}"



@tool
def list_browser_tabs() -> str:
    """List all open browser tabs."""

    try:
        pm = get_playwright_manager()
        page = pm.get_page()
        pages = pm.get_all_pages()
        
        result = f"Tabs: {len(pages)}\n"
        for i, p in enumerate(pages):
            try:
                title = p.title()[:35] if not p.is_closed() else "CLOSED"
            except:
                title = "Unknown"
            current = " ← CURRENT" if p == page else ""
            result += f"  [{i}] {title}{current}\n"
        
        if len(pages) > 1:
            result += "\nUse switch_to_tab(index) to switch."
        return result
    except Exception as e:
        return f"Failed: {str(e)}"


@tool
def switch_to_tab(index: int) -> str:
    """Switch to tab by index. Use -1 for last tab."""
    try:
        pm = get_playwright_manager()
        pages = pm.get_all_pages()
        
        if index < 0:
            index = len(pages) + index
        
        if index < 0 or index >= len(pages):
            return f"Invalid index. Available: 0-{len(pages)-1}"
        
        target = pages[index]
        if target.is_closed():
            return f"Tab {index} is closed"
        
        pm.set_page(target)
        target.bring_to_front()
        time.sleep(0.5)
        return f"Switched to tab {index}: {target.title()}"
    except Exception as e:
        return f"Failed: {str(e)}"


@tool
def close_current_tab() -> str:
    """Close current tab."""
    try:
        pm = get_playwright_manager()
        pages = pm.get_all_pages()
        
        if len(pages) <= 1:
            return "Cannot close the last tab."
        
        pm.close_page(pm.get_page())
        time.sleep(0.5)
        return "Closed tab."
    except Exception as e:
        return f"Error: {str(e)}"


@tool
def execute_javascript(script: str) -> str:
    """Execute JavaScript on the page and return the result.
    
    IMPORTANT RULES:
    1. Input `script` MUST be a valid JavaScript string, NOT a JSON object or array.
    2. GOOD: "return document.title"
    3. BAD: "['return document.title']" or "{\"script\": ...}"
    4. The script is executed inside an async function. Use 'return' to pass data back.
    5. Return simple JSON-serializable data (strings, numbers, lists, dicts).
    
    IMPORTANT - Write complete, valid JavaScript:
    1. DO NOT use :contains() - it's jQuery, not valid CSS
    2. ALWAYS close all brackets and braces
    3. ALWAYS include a return statement
    """
    print(f"[TOOL] execute_javascript: {script[:50]}...")
    try:
        script = script.strip()
        if (script.startswith('[') and script.endswith(']')) or (script.startswith('{') and script.endswith('}')):
             if len(script) > 100 or '"' in script or "'" in script:
                 return "Error: You passed a JSON object/array. You MUST pass a valid JavaScript string to be executed. Example: \"return document.title;\""

        page = ensure_browser_connected()
        show_status("Running JS...", "info")
        
        script = html.unescape(script)
        
        import re
        if re.search(r':contains\s*\(', script):
            return """INVALID SELECTOR: :contains() is jQuery, not CSS!

Your script used :contains() which will ALWAYS fail.

FIX: Replace querySelector(':contains("text")') with:
Array.from(document.querySelectorAll('button')).find(el => el.textContent.includes('text'))

Example fix:
```javascript
// WRONG (what you wrote):
document.querySelector('button:contains("Apply")')

// CORRECT (use this instead):
Array.from(document.querySelectorAll('button')).find(el => el.textContent.includes('Apply'))
```

Rewrite your script WITHOUT :contains() and try again."""
        
    except Exception as e:
        return f"JavaScript error: {str(e)}"
        
    try:
        wrapped_script = f"(() => {{ {script} }})()"
        
        result = page.evaluate(wrapped_script)
        show_status("JS done", "success")
        
        if result is None:
            return "null"
        elif isinstance(result, (dict, list)):
            return json.dumps(result, indent=2, ensure_ascii=False)
        else:
            return str(result)
    except Exception as e:
        return f"JavaScript error: {str(e)}"



_SCRIPT_DIR = os.path.dirname(__file__)
_ELEMENT_REF_SCRIPT = None
_FORM_INPUT_SCRIPT = None

def _load_script(filename: str) -> str:
    """Load a JS script file."""
    global _ELEMENT_REF_SCRIPT, _FORM_INPUT_SCRIPT
    script_path = os.path.join(_SCRIPT_DIR, "browser_scripts", filename)
    if os.path.exists(script_path):
        with open(script_path, 'r') as f:
            return f.read()
    return None


@tool
def get_element_by_ref(ref: str) -> str:
    """Get fresh coordinates for a previously scanned element.
    
    Use this when:
    - You need to interact with an element after scrolling
    - The page may have updated and you need fresh coordinates
    - You want to verify an element is still visible
    
    Args:
        ref: Element reference from get_page_elements (e.g., "ref_15")
    
    Returns:
        JSON with x, y coordinates and element info, or error message.
    """
    print(f"[TOOL] get_element_by_ref: {ref}")
    try:
        page = ensure_browser_connected()
        
        script = _load_script("element_ref_script.js")
        if not script:
            return f"Script file not found: element_ref_script.js"
        
        result = page.evaluate(f"({script})('{ref}')")
        
        if not result.get("success", False):
            return f"{result.get('message', 'Element not found')}"
        
        info = f"Found {ref}:\n"
        info += f"  Coordinates: ({result['x']}, {result['y']})\n"
        info += f"  Tag: {result['tag']}"
        if result.get('id'):
            info += f"#{result['id']}"
        if result.get('text'):
            info += f"\n  Text: \"{result['text']}\""
        if result.get('isDropdown'):
            info += f"\n  Dropdown: {'OPEN' if result.get('isExpanded') else 'closed'}"
        if not result.get('isVisible'):
            info += "\n  Note: Element may not be visible"
        
        return info
    except Exception as e:
        return f"Error getting element: {str(e)}"


def _form_input_impl(ref: str, value: str) -> str:
    """Fill a form field by ref. Handles select dropdowns, checkboxes, radio buttons, and text inputs.
    
    Use this instead of click_at + type_at for form fields - it's more reliable!
    
    For text inputs on React-based sites (like Indeed, LinkedIn), this uses Playwright's 
    native fill() which properly triggers all events.
    
    Smart form filling for various input types.
    
    IMPORTANT: 
    - Do NOT call this tool multiple times in the same turn (parallel execution race conditions).
    - To fill multiple fields, YOU MUST USE `execute_action_sequence`!

    Supported element types:
    - SELECT: Pass the option text or value (e.g., "Remote", "Entry Level")
    - CHECKBOX: Pass "true" or "false"
    - RADIO: Pass "true" to select
    - TEXT/TEXTAREA: Pass the text value
    - DATE/TIME: Pass in correct format (e.g., "2024-01-15")
    - NUMBER/RANGE: Pass the numeric value
    
    Args:
        ref: Element reference from get_page_elements (e.g., "ref_8")
        value: Value to set (string, will be converted as needed)
    
    Example:
        form_input(ref="ref_12", value="Remote")  # For a location dropdown
        form_input(ref="ref_15", value="true")    # For a checkbox
    """
    print(f"[TOOL] form_input: {ref} = {value}")
    try:
        page = ensure_browser_connected()
        show_status(f"Setting {ref}...", "info")
        
        script = _load_script("element_ref_script.js")
        if not script:
            return f"Script file not found: element_ref_script.js"
        
        ref_res = page.evaluate(f"({script})('{ref}')")
        
        if not ref_res.get("success"):
            return f"Failed to find element: {ref_res.get('message', 'Unknown error')}"
        
        tag = ref_res.get("tag", "").upper()
        input_type = ref_res.get("type", "").lower()
        x, y = ref_res["x"], ref_res["y"]
        
        if tag == "INPUT" and input_type in ["text", "search", "email", "password", "tel", "url", ""]:
            page.mouse.click(x, y)
            time.sleep(0.1)
            
            page.mouse.click(x, y, click_count=3)
            time.sleep(0.05)
            page.keyboard.type(value, delay=10)  # Small delay between keystrokes
            time.sleep(0.1)
            
            show_status("Form filled", "success")
            return f"Set text to \"{value}\" (was: {ref_res.get('value', '')})"
        
        if tag == "TEXTAREA":
            page.mouse.click(x, y)
            time.sleep(0.1)
            page.mouse.click(x, y, click_count=3)
            time.sleep(0.05)
            page.keyboard.type(value, delay=10)
            time.sleep(0.1)
            
            return f"Set textarea to \"{value[:30]}{'...' if len(value) > 30 else ''}\""
        
        script = _load_script("form_input_script.js")
        if not script:
            return f"Script file not found: form_input_script.js"
        
        js_value = value
        if value.lower() == "true":
            js_value = True
        elif value.lower() == "false":
            js_value = False
        elif value.isdigit():
            js_value = int(value)
        
        value_json = json.dumps(js_value)
        result = page.evaluate(f"({script})('{ref}', {value_json})")
        
        if not result.get("success", False):
            return f"{result.get('message', 'Failed to set form value')}"
        
        show_status("Form filled", "success")
        
        msg = result.get('message', f"Set {ref} to {value}")
        response = f"{msg}"
        if result.get('previous') is not None:
            response += f" (was: {result['previous']})"
        
        return response
    except Exception as e:
        return f"Form input error: {str(e)}"

@tool
def form_input(ref: str, value: str) -> str:
    """Fill a form field by ref. Handles select dropdowns, checkboxes, radio buttons, and text inputs.
    
    Use this instead of click_at + type_at for form fields - it's more reliable!
    
    For text inputs on React-based sites (like Indeed, LinkedIn), this uses Playwright's 
    native fill() which properly triggers all events.
    
    Smart form filling for various input types.
    
    IMPORTANT: 
    - Do NOT call this tool multiple times in the same turn (parallel execution race conditions).
    - To fill multiple fields, YOU MUST USE `execute_action_sequence`!

    Supported element types:
    - SELECT: Pass the option text or value (e.g., "Remote", "Entry Level")
    - CHECKBOX: Pass "true" or "false"
    - RADIO: Pass "true" to select
    - TEXT/TEXTAREA: Pass the text value
    - DATE/TIME: Pass in correct format (e.g., "2024-01-15")
    - NUMBER/RANGE: Pass the numeric value
    
    Args:
        ref: Element reference from get_page_elements (e.g., "ref_8")
        value: Value to set (string, will be converted as needed)
    
    Example:
        form_input(ref="ref_12", value="Remote")  # For a location dropdown
        form_input(ref="ref_15", value="true")    # For a checkbox
    """
    return _form_input_impl(ref, value)
