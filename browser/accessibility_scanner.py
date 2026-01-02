"""
Accessibility Scanner
Generates coordinate-aware DOM representation for browser automation.
"""
from playwright.sync_api import Page
from typing import Dict, Tuple, Optional, Any

# Map element_id -> {coords: (x, y), dom_id: str | None, tag: str}
ELEMENT_MAP: Dict[int, Dict[str, Any]] = {}

def get_dom_representation(page: Page) -> str:
    """
    Generate optimized DOM representation with element coordinates.
    """
    return scan_page_elements(page)

def scan_page_elements(page: Page) -> str:
    """
    Scan page for interactive elements with coordinates.
    Uses accessibility tree, filters noise, preserves semantic order.
    """
    global ELEMENT_MAP
    ELEMENT_MAP.clear()
    
    js_builder = """
        (() => {
            let output = [];
            let mapData = {};
            let counter = -1;
            
            function isVisible(el) {
                if (!el) return false;
                const style = window.getComputedStyle(el);
                const rect = el.getBoundingClientRect();
                return rect.width > 0 && rect.height > 0 && 
                       style.visibility !== 'hidden' && 
                       style.display !== 'none' &&
                       parseFloat(style.opacity) > 0;
            }
            
            function getDirectText(node) {
                let text = '';
                for (let child of node.childNodes) {
                    if (child.nodeType === 3) text += child.textContent;
                }
                return text.replace(/\\s+/g, ' ').trim();
            }
            
            function isExcluded(node) {
                let current = node;
                for (let i = 0; i < 10 && current; i++) {
                    const tag = current.tagName?.toLowerCase();
                    const role = current.getAttribute?.('role');
                    const cls = (typeof current.className === 'string' ? current.className : '').toLowerCase();
                    
                    if (tag === 'footer' || role === 'contentinfo') return true;
                    if (tag === 'nav' && cls.includes('pagination')) return true;
                    if (cls.includes('relatedqueries') || cls.includes('recommendations')) return true;
                    
                    current = current.parentElement;
                }
                return false;
            }
            
            // CORE: Is this element worth showing?
            function isInteresting(node, tag, text, ariaLabel, role) {
                // Always show interactive elements
                if (['a', 'button', 'input', 'select', 'textarea'].includes(tag)) return true;
                
                // Show elements with meaningful roles
                if (['button', 'link', 'textbox', 'combobox', 'searchbox', 'checkbox', 'radio', 'tab'].includes(role)) return true;
                
                // Show headings
                if (['h1', 'h2', 'h3'].includes(tag)) return true;
                
                // Show form elements
                if (['form', 'fieldset', 'legend'].includes(tag)) return true;
                
                // Show scrollable containers
                const style = window.getComputedStyle(node);
                if (style.overflowY === 'auto' || style.overflowY === 'scroll') return true;
                
                // Show divs/spans ONLY if they have aria-label or meaningful text (not just whitespace)
                if ((tag === 'div' || tag === 'span') && (ariaLabel || (text && text.length > 2))) return true;
                
                return false;
            }
            
            function build(node, depth) {
                if (!node || node.nodeType !== 1) return;
                if (isExcluded(node)) return;
                
                const tag = node.tagName.toLowerCase();
                if (['svg', 'path', 'script', 'style', 'noscript', 'iframe', 'img'].includes(tag)) return;
                
                // Check visibility - but ALWAYS recurse into children (they may be visible even if parent isn't)
                const visible = isVisible(node);
                
                const rect = node.getBoundingClientRect();
                // Use VIEWPORT coordinates with centering (matches Playwright mouse.click)
                const x = Math.round(rect.left + rect.width / 2);
                const y = Math.round(rect.top + rect.height / 2);
                const text = getDirectText(node);
                const ariaLabel = node.getAttribute('aria-label') || '';
                const role = node.getAttribute('role') || '';
                
                if (visible && isInteresting(node, tag, text, ariaLabel, role)) {
                    counter++;
                    const domId = node.getAttribute('id') || null;
                    mapData[counter] = {coords: [x, y], dom_id: domId, tag: tag};
                    
                    const indent = "\\t".repeat(depth);
                    
                    // Build minimal attributes
                    let attrs = [];
                    if (ariaLabel) attrs.push(`aria-label='${ariaLabel}'`);
                    if (role) attrs.push(`role='${role}'`);
                    const cls = node.getAttribute('class');
                    if (cls) attrs.push(`class='${cls}'`);
                    const id = node.getAttribute('id');
                    if (id) attrs.push(`id='${id}'`);
                    const href = node.getAttribute('href');
                    if (href) attrs.push(`href='${href}'`);
                    if (tag === 'input') {
                        const type = node.getAttribute('type');
                        const placeholder = node.getAttribute('placeholder');
                        if (type) attrs.push(`type='${type}'`);
                        if (placeholder) attrs.push(`placeholder='${placeholder}'`);
                    }
                    
                    const attrStr = attrs.length > 0 ? ' ' + attrs.join(' ') : '';
                    
                    // Format: text inline if short, else on next line
                    if (text && text.length < 50 && text.length > 0) {
                        output.push(`${indent}[${counter}] (${x},${y})<${tag}${attrStr}>${text} />`);
                    } else {
                        output.push(`${indent}[${counter}] (${x},${y})<${tag}${attrStr} />`);
                        if (text && text.length >= 50) {
                            output.push(text.length > 200 ? text.substring(0, 197) + '...' : text);
                        }
                    }
                    
                    // Children get +1 depth only if parent has multiple children
                    const nextDepth = node.children.length > 1 ? depth + 1 : depth;
                    Array.from(node.children).forEach(child => build(child, nextDepth));
                } else {
                    // Not output-worthy but ALWAYS recurse into children (they may be visible)
                    Array.from(node.children).forEach(child => build(child, depth));
                }
            }
            
            build(document.body, 0);
            
            return { text: output.join('\\n'), map: mapData };
        })()
    """
    
    result = page.evaluate(js_builder)
    
    # Store element info (coordinates + dom_id)
    raw_map = result.get("map", {})
    for k, v in raw_map.items():
        coords = v.get("coords", [0, 0])
        ELEMENT_MAP[int(k)] = {
            "coords": (int(coords[0]), int(coords[1])),
            "dom_id": v.get("dom_id"),
            "tag": v.get("tag", "")
        }
    
    return result.get("text", "")

def get_element_info(element_id: int) -> Optional[Dict[str, Any]]:
    """Get full element info including coords and DOM id."""
    return ELEMENT_MAP.get(element_id)

def get_element_coordinates(element_id: int) -> Optional[Tuple[int, int]]:
    """Get coordinates for element ID (backwards compatible)."""
    info = ELEMENT_MAP.get(element_id)
    if info:
        return info.get("coords")
    return None

def click_element(page: Page, element_id: int) -> bool:
    """Click element by ID using stored coordinates."""
    coords = get_element_coordinates(element_id)
    if coords:
        x, y = coords
        page.mouse.click(x, y)
        return True
    return False

def fill_input(page: Page, element_id: int, text: str) -> bool:
    """Fill input field by ID."""
    coords = get_element_coordinates(element_id)
    if coords:
        x, y = coords
        page.mouse.click(x, y)
        page.keyboard.type(text)
        return True
    return False