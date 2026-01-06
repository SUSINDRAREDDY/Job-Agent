"""
Playwright Manager - Singleton manager for browser automation.

Supports two modes:
1. Connect to existing Chrome via CDP (uses your real profile with logins)
2. Launch fresh Playwright browser (guest profile)
"""
from playwright.sync_api import sync_playwright, Browser, Page, BrowserContext, Playwright
from typing import Optional
import time
import os
import threading

# Global lock to prevent multiple threads from racing to launch/connect to browser
_BROWSER_LAUNCH_LOCK = threading.Lock()


# Default Chrome debugging port
DEFAULT_CDP_PORT = 9222


class PlaywrightManager:
    """
    Thread-local manager for Playwright browser instance.
    
    Features:
    - Connect to existing Chrome (use your real profile!)
    - Or launch fresh Playwright browser
    - Tab management via Playwright pages
    - Stealth mode to avoid detection
    
    Note: Use get_playwright_manager() to get a thread-local instance.
    Each thread needs its own instance due to greenlet requirements.
    """
    
    # Global active page tracking shared across threads
    _global_active_page_index = 0
    _global_active_page_url = ""  # URL is more reliable than index across CDP connections
    
    def __init__(self):
        """Initialize a fresh PlaywrightManager for this thread."""
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
        self._headless: bool = False
        self._connected_via_cdp: bool = False
        self._quiet_mode: bool = False  # Suppress repeated connection logs
    
    def connect_to_chrome(self, port: int = DEFAULT_CDP_PORT) -> Page:
        """
        Connect to existing Chrome instance via CDP.
        
        This uses YOUR REAL Chrome profile with all your logins!
        
        First, start Chrome with remote debugging:
        
        Mac:
            /Applications/Google\\ Chrome.app/Contents/MacOS/Google\\ Chrome \\
                --remote-debugging-port=9222
        
        Windows:
            "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe" --remote-debugging-port=9222
        
        Linux:
            google-chrome --remote-debugging-port=9222
        
        Args:
            port: CDP port (default 9222)
        
        Returns:
            Current active Page
        """
        if self._page and not self._page.is_closed():
            return self._page
        
        if not self._playwright:
            print(f"Connecting to Chrome on port {port}...")
            self._playwright = sync_playwright().start()
            
            try:
                self._browser = self._playwright.chromium.connect_over_cdp(
                    f"http://127.0.0.1:{port}"
                )
                self._connected_via_cdp = True
                
                contexts = self._browser.contexts
                if contexts:
                    self._context = contexts[0]
                    pages = self._context.pages
                    if pages:
                        self._page = pages[0]
                        print(f"Connected to Chrome! Using existing tab: {self._page.title()[:40]}")
                    else:
                        self._page = self._context.new_page()
                        print("Connected to Chrome! Created new tab.")
                else:
                    self._context = self._browser.new_context()
                    self._page = self._context.new_page()
                    print("Connected to Chrome! Created new context.")
                    
            except Exception as e:
                print(f"Failed to connect to Chrome on port {port}")
                print(f"   Error: {e}")
                print(f"\nChrome 136+ requires --user-data-dir with remote debugging.")
                print(f"   Run this command (quit Chrome first!):")
                print(f'   /Applications/Google\\ Chrome.app/Contents/MacOS/Google\\ Chrome --remote-debugging-port={port} --user-data-dir="$HOME/Library/Application Support/Google/Chrome"')
                raise ConnectionError(f"Could not connect to Chrome. Start Chrome with --remote-debugging-port={port} --user-data-dir=...")
        
        return self._page
    
    def connect(self, headless: bool = False) -> Page:
        """
        Launch fresh Playwright browser (guest profile).
        
        For using your real Chrome profile, use connect_to_chrome() instead!
        
        Args:
            headless: Run browser without GUI (default: False for debugging)
        
        Returns:
            Current active Page
        """
        self._headless = headless
        
        if self._page and not self._page.is_closed():
            return self._page
        
        if not self._playwright:
            print("Launching Playwright browser (guest profile)...")
            self._playwright = sync_playwright().start()
            
            self._browser = self._playwright.chromium.launch(
                headless=headless,
                args=[
                    '--disable-blink-features=AutomationControlled',
                    '--disable-infobars',
                    '--disable-dev-shm-usage',
                    '--no-sandbox',
                    '--disable-setuid-sandbox',
                    '--disable-web-security',
                    '--disable-features=IsolateOrigins,site-per-process',
                    '--ignore-certificate-errors',
                ]
            )
            
            self._context = self._browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                locale='en-US',
                timezone_id='America/New_York',
                java_script_enabled=True,
                has_touch=False,
                is_mobile=False,
                device_scale_factor=2,
            )
            
            self._context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                });
                
                Object.defineProperty(navigator, 'plugins', {
                    get: () => [1, 2, 3, 4, 5]
                });
                
                Object.defineProperty(navigator, 'languages', {
                    get: () => ['en-US', 'en']
                });
                
                window.chrome = { runtime: {} };
            """)
            
            self._page = self._context.new_page()
            print("Playwright browser launched successfully")
        
        return self._page
    
    def connect_persistent(self, profile_path: str = None) -> Page:
        """
        Launch Chrome with a persistent profile directory OR connect to existing instance.
        
        Strategy:
        1. Try connecting to localhost:9222 (remote debugging)
        2. If fails, LAUNCH new persistent context with --remote-debugging-port=9222
           so future calls can connect to it.
        
        This solves the "SingletonLock" error when multiple threads try to use the profile.
        """
        if self._page and not self._page.is_closed():
            return self._page
            
        if not self._playwright:
            self._playwright = sync_playwright().start()

        # 1. Try connecting to existing browser (shared instance)
        try:
            print("Checking for existing browser connection...")
            browser = self._playwright.chromium.connect_over_cdp("http://127.0.0.1:9222")
            self._context = browser.contexts[0]
            
            # Determine which page to select based on global index
            all_pages_in_context = []
            # We should check ALL contexts for correctness, mirroring get_all_pages
            for ctx in browser.contexts:
                all_pages_in_context.extend(ctx.pages)
            
            if all_pages_in_context:
                target_idx = PlaywrightManager._global_active_page_index
                if 0 <= target_idx < len(all_pages_in_context):
                    self._page = all_pages_in_context[target_idx]
                else:
                    self._page = all_pages_in_context[0]
            else:
                 self._page = self._context.new_page()
            print("Connected to existing browser session!")
            return self._page
        except Exception:
            print("No existing browser found. Launching new one...")

        # 2. Launch new persistent instance (Primary)
        if profile_path is None:
            profile_path = os.path.expanduser("~/job_agent_chrome_profile")
        
        os.makedirs(profile_path, exist_ok=True)
        
        print(f"Launching Chrome with your profile...")
        print(f"   Profile location: {profile_path}")
        
        self._context = self._playwright.chromium.launch_persistent_context(
            user_data_dir=profile_path,
            headless=False,
            channel="chrome",
            viewport={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            locale='en-US',
            timezone_id='America/New_York',
            args=[
                '--remote-debugging-port=9222',
                '--disable-blink-features=AutomationControlled',
                '--disable-infobars',
                '--disable-dev-shm-usage',
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-extensions',
            ]
        )
        
        pages = self._context.pages
        if pages:
            self._page = pages[0]
        else:
            self._page = self._context.new_page()

        try:
            from playwright_stealth import stealth_sync
            stealth_sync(self._page)
            print("Stealth mode activated!")
        except ImportError:
            print("playwright-stealth not found. Run: pip install playwright-stealth")
        
        print(f"Chrome launched with your profile on port 9222!")
        
        return self._page
    
    def connect_real_chrome(self, chrome_base: str, profile_name: str = "Default") -> Page:
        """
        Connect to your REAL Chrome profile via CDP (Chrome DevTools Protocol).
        
        REQUIREMENT: Chrome must be running with --remote-debugging-port=9222
        Run ./launch_agent_browser.sh first to start Chrome in agent mode.
        
        Args:
            chrome_base: Base Chrome directory (e.g., ~/Library/Application Support/Google/Chrome)
            profile_name: Profile folder name (e.g., "Default", "Profile 1")
        
        Returns:
            Current active Page
        """
        if self._page and not self._page.is_closed():
            return self._page
            
        # Use Global Lock to ensure only ONE thread attempts to launch/connect at a time
        with _BROWSER_LAUNCH_LOCK:
            # Check again inside lock in case another thread just succeeded
            if self._page and not self._page.is_closed():
                return self._page

            if not self._playwright:
                self._playwright = sync_playwright().start()

            # Connect to existing browser via CDP
            try:
                if not self._quiet_mode:
                    print("Connecting to Chrome via CDP on port 9222...")
                browser = self._playwright.chromium.connect_over_cdp(
                    "http://127.0.0.1:9222",
                    timeout=10000
                )
                self._browser = browser
                self._connected_via_cdp = True
                
                if browser.contexts:
                    self._context = browser.contexts[0]
                else:
                    self._context = browser.new_context()
                
                if self._context.pages:
                    # CRITICAL: Check if there's already a global URL set from another thread
                    # If so, find and use that page instead of blindly using first page
                    existing_global_url = PlaywrightManager._global_active_page_url
                    selected_page = None
                    
                    if existing_global_url:
                        # Try to find the page matching the global URL
                        for page in self._context.pages:
                            if page.url == existing_global_url:
                                selected_page = page
                                break
                        # Also check other contexts for CDP connections
                        if not selected_page:
                            for context in self._browser.contexts:
                                for page in context.pages:
                                    if page.url == existing_global_url:
                                        selected_page = page
                                        break
                                if selected_page:
                                    break
                    
                    if selected_page:
                        # Found the page matching global URL - use it without overwriting global state
                        self._page = selected_page
                        if not self._quiet_mode:
                            print(f"Connected to Chrome via CDP! Synced to active tab: {self._page.title()[:40]}")
                    else:
                        # No existing global URL or page not found - use first page and set global
                        self.set_page(self._context.pages[0])
                        if not self._quiet_mode:
                            print(f"Connected to Chrome via CDP! Using existing tab: {self._page.title()[:40]}")
                else:
                    new_page = self._context.new_page()
                    self.set_page(new_page)
                    if not self._quiet_mode:
                        print("Connected to Chrome via CDP! Created new tab.")
                
                return self._page
                
            except Exception as e:
                error_msg = f"""Failed to connect to Chrome via CDP.

Error: {e}

To fix this:
   1. Run: ./launch_agent_browser.sh
   2. Wait for Chrome to fully open
   3. Then run the agent again

   The script will close existing Chrome and reopen it with remote debugging enabled."""
            print(error_msg)
            raise ConnectionError(error_msg)
    
    def get_page(self) -> Page:
        """
        Get current active page.
        
        Returns None if not connected - the caller should handle connection.
        
        Returns:
            Current active Page or None
        """
        # CRITICAL: Sync with global URL for CDP connections
        # This ensures that if another thread/tool called switch_to_tab,
        # we update our local _page reference to match.
        # NOTE: We use URL matching instead of index because each thread's CDP
        #       connection creates DIFFERENT Page objects for the same tabs!
        if self._connected_via_cdp and self._browser:
             target_url = PlaywrightManager._global_active_page_url
             try:
                 # Check if current page URL matches the global URL
                 if target_url and (not self._page or self._page.url != target_url):
                     all_pages = self.get_all_pages()
                     # Find the page that matches the target URL
                     for page in all_pages:
                         if page.url == target_url:
                             self._page = page
                             break
             except Exception:
                 pass # Be robust against CDP errors during sync

        if self._page and not self._page.is_closed():
            return self._page
        return None
    
    
    def set_page(self, page: Page) -> None:
        """
        Set the active page (used for tab switching).
        
        Args:
            page: The page to set as active
        """
        self._page = page
        
        # Update global state with BOTH index and URL for reliable cross-thread sync
        if self._browser and self._connected_via_cdp:
            try:
                # Store the URL - this is the KEY fix for cross-thread sync
                # Each thread has different Page objects, but URLs are strings that match
                PlaywrightManager._global_active_page_url = page.url
                
                all_pages = []
                for context in self._browser.contexts:
                    all_pages.extend(context.pages)
                
                for i, p in enumerate(all_pages):
                    if p == page:
                        PlaywrightManager._global_active_page_index = i
                        break
            except Exception:
                pass

    def set_active_page_index(self, index: int) -> None:
        """Set the global active page index."""
        PlaywrightManager._global_active_page_index = index
        # Also try to set local page if connected
        if self._browser and self._connected_via_cdp:
            try:
                all_pages = []
                for context in self._browser.contexts:
                    all_pages.extend(context.pages)
                
                if 0 <= index < len(all_pages):
                    self._page = all_pages[index]
            except Exception:
                pass

    def get_context(self) -> Optional[BrowserContext]:
        """
        Get the browser context (contains all pages/tabs).
        
        Returns:
            Current BrowserContext or None
        """
        return self._context
    
    def get_all_pages(self) -> list[Page]:
        """
        Get all open pages (tabs) in the context.
        
        For CDP connections, queries ALL browser contexts since new tabs
        opened by clicking links may be in different contexts.
        
        Returns:
            List of all Page objects
        """
        # For CDP connections, get pages from ALL contexts
        if self._browser and self._connected_via_cdp:
            all_pages = []
            for context in self._browser.contexts:
                all_pages.extend(context.pages)
            return all_pages
        # For regular connections, just use the main context
        elif self._context:
            return self._context.pages
        return []
    
    def new_page(self, url: Optional[str] = None) -> Page:
        """
        Open a new page (tab) in the browser.
        
        Args:
            url: Optional URL to navigate to
        
        Returns:
            The new Page object
        """
        if not self._context:
            self.connect()
        
        new_page = self._context.new_page()
        
        if url:
            new_page.goto(url, wait_until='domcontentloaded', timeout=30000)
            time.sleep(2)
        
        self._page = new_page
        return new_page
    
    def close_page(self, page: Optional[Page] = None) -> None:
        """
        Close a specific page or the current page.
        
        Args:
            page: Page to close (defaults to current page)
        """
        target = page or self._page
        
        if target and not target.is_closed():
            target.close()
        
        # Switch to first remaining page if any
        pages = self.get_all_pages()
        if pages:
            self._page = pages[0]
        else:
            self._page = None
    
    def close(self) -> None:
        """Close browser and cleanup all resources."""
        if not self._quiet_mode:
            print("Closing Playwright connection...")
        
        # Don't close context/browser if connected via CDP (it's the user's browser!)
        if not self._connected_via_cdp:
            if self._context:
                try:
                    self._context.close()
                except Exception:
                    pass
            
            if self._browser:
                try:
                    self._browser.close()
                except Exception:
                    pass
        
        if self._playwright:
            try:
                self._playwright.stop()
            except Exception:
                pass
        
        self._page = None
        self._context = None
        self._browser = None
        self._playwright = None
        self._connected_via_cdp = False
        
        if not self._quiet_mode:
            print("Playwright connection closed")
    
    def take_screenshot(self, path: Optional[str] = None, full_page: bool = False) -> bytes:
        """
        Take a screenshot of the current page.
        
        Args:
            path: Optional file path to save screenshot
            full_page: Capture full scrollable page (default: False)
        
        Returns:
            Screenshot as bytes
        """
        page = self.get_page()
        
        if path:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            return page.screenshot(path=path, type='jpeg', quality=70, full_page=full_page)
        else:
            return page.screenshot(type='jpeg', quality=70, full_page=full_page)
    
    def scale_coordinates(self, x: int, y: int) -> tuple[int, int]:
        """
        Scale coordinates from vision resolution to actual viewport.
        
        Args:
            x: X coordinate from vision model
            y: Y coordinate from vision model
        
        Returns:
            Tuple of (scaled_x, scaled_y) in actual viewport coordinates
        """
        page = self.get_page()
        if not page:
            return (x, y)
        
        viewport = page.viewport_size
        if not viewport:
            return (x, y)
        
        BASE_WIDTH = 1456
        BASE_HEIGHT = 819
        
        actual_width = viewport['width']
        actual_height = viewport['height']
        
        scale_x = actual_width / BASE_WIDTH
        scale_y = actual_height / BASE_HEIGHT
        
        scaled_x = int(x * scale_x)
        scaled_y = int(y * scale_y)
        
        return (scaled_x, scaled_y)
    
    def show_status(self, message: str, status_type: str = "info") -> None:
        """
        Show a status notification overlay on the page (like the old CDP version).
        
        Args:
            message: Message to display
            status_type: 'info', 'success', 'warning', or 'error'
        """
        page = self.get_page()
        
        color_map = {
            "info": "#2196F3",
            "success": "#4CAF50",
            "warning": "#FF9800",
            "error": "#F44336"
        }
        color = color_map.get(status_type, "#333")
        
        js_code = f"""
        (function() {{
            let container = document.getElementById('agent-status-container');
            if (!container) {{
                container = document.createElement('div');
                container.id = 'agent-status-container';
                container.style.cssText = 'position:fixed;top:20px;right:20px;z-index:999999;font-family:sans-serif;display:flex;flex-direction:column;gap:10px;pointer-events:none;';
                document.body.appendChild(container);
            }}
            
            let notif = document.createElement('div');
            notif.innerText = "{message.replace('"', '\\"')}";
            notif.style.cssText = 'background:{color};color:white;padding:12px 24px;border-radius:8px;box-shadow:0 4px 12px rgba(0,0,0,0.15);opacity:0;transform:translateX(20px);transition:all 0.3s ease;';
            container.appendChild(notif);
            
            setTimeout(() => {{ notif.style.opacity='1'; notif.style.transform='translateX(0)'; }}, 50);
            setTimeout(() => {{ notif.style.opacity='0'; notif.style.transform='translateX(20px)'; setTimeout(() => notif.remove(), 300); }}, 4000);
        }})();
        """
        
        try:
            page.evaluate(js_code)
        except Exception:
            pass  # Ignore if page is navigating or closed


# Thread-local storage for PlaywrightManager instances  
# IMPORTANT: Playwright's sync_api uses greenlets which have strict thread affinity.
# Each thread MUST have its own Playwright instance - you cannot share across threads.
#
# Why thread-local is REQUIRED:
# - Deepagents uses ThreadPoolExecutor for tool calls
# - Each tool call may run in a DIFFERENT thread  
# - Playwright greenlets ERROR if accessed from different thread
# - So each thread needs its own Playwright, but they all connect to SAME Chrome via CDP
#
# The \"Connecting...\" messages are expected - each thread connects independently
# but they all connect to the SAME browser instance, so it's not really "reconnecting"

import threading
import atexit

_thread_local = threading.local()
_all_managers: list = []  # Track all managers for cleanup
_managers_lock = threading.Lock()
_connection_count = 0  # Track connections for quieter logging


def get_playwright_manager() -> PlaywrightManager:
    """
    Get a thread-local PlaywrightManager instance.
    
    Each thread gets its own manager because Playwright's sync_api uses greenlets
    which have strict thread affinity - you cannot use a Playwright instance
    created in one thread from a different thread.
    
    All managers connect to the SAME Chrome browser via CDP - they just need
    separate Playwright instances due to greenlet requirements.
    """
    global _connection_count
    
    if not hasattr(_thread_local, 'manager'):
        _thread_local.manager = PlaywrightManager()
        # Quiet mode after first connection - don't spam logs
        _connection_count += 1
        if _connection_count > 1:
            _thread_local.manager._quiet_mode = True
        # Track for cleanup
        with _managers_lock:
            _all_managers.append(_thread_local.manager)
    return _thread_local.manager


def _cleanup_all_managers():
    """Cleanup all thread-local Playwright managers on exit."""
    with _managers_lock:
        for manager in _all_managers:
            try:
                manager.close()
            except Exception:
                pass  # Ignore errors during cleanup
        _all_managers.clear()

# Register cleanup handler to prevent EPIPE errors
atexit.register(_cleanup_all_managers)


def connect_to_real_chrome(port: int = DEFAULT_CDP_PORT) -> Page:
    """
    Connect to your REAL Chrome browser with all your logins!
    
    Step 1: Start Chrome with remote debugging:
    
        Mac:
        /Applications/Google\\ Chrome.app/Contents/MacOS/Google\\ Chrome --remote-debugging-port=9222
        
        Or use the helper command saved in rn_command.txt
    
    Step 2: Call this function:
        from playwright_manager import connect_to_real_chrome
        page = connect_to_real_chrome()
    
    Args:
        port: CDP port (default 9222)
    
    Returns:
        Playwright Page connected to your Chrome
    """
    pm = get_playwright_manager()
    return pm.connect_to_chrome(port)


def get_chrome_launch_command(port: int = DEFAULT_CDP_PORT) -> str:
    """
    Get the command to launch Chrome with remote debugging.
    
    Chrome 136+ requires --user-data-dir when using --remote-debugging-port.
    
    Returns:
        Shell command string for your platform
    """
    import platform
    
    system = platform.system()
    
    if system == "Darwin":  # macOS
        return f'/Applications/Google\\ Chrome.app/Contents/MacOS/Google\\ Chrome --remote-debugging-port={port} --user-data-dir="$HOME/Library/Application Support/Google/Chrome"'
    elif system == "Windows":
        return f'"C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe" --remote-debugging-port={port} --user-data-dir="%LOCALAPPDATA%\\Google\\Chrome\\User Data"'
    else:  # Linux
        return f'google-chrome --remote-debugging-port={port} --user-data-dir="$HOME/.config/google-chrome"'


# Save the launch command to a file for easy access
def save_chrome_command():
    """Save the Chrome launch command to rn_command.txt"""
    cmd = get_chrome_launch_command()
    with open("rn_command.txt", "w") as f:
        f.write(f"# Run this command to start Chrome with remote debugging:\n{cmd}\n")
    print(f"Chrome command saved to rn_command.txt")
    print(f"   {cmd}")

