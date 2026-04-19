#!/usr/bin/env python3
"""FocusGuard — macOS menu bar app that nudges you when you switch to distracting apps/sites."""

import json
import logging
import os
import random
import subprocess
import threading
import time

import rumps
from AppKit import (
    NSBackingStoreBuffered, NSBezierPath, NSColor, NSFloatingWindowLevel,
    NSFont, NSMakeRect, NSPanel, NSScreen, NSTextField, NSTextAlignmentCenter,
    NSView, NSWorkspace, NSWorkspaceDidActivateApplicationNotification,
)
from Foundation import NSObject, NSOperationQueue, NSThread, NSTimer

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("focusguard")

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")
BROWSERS = {"Google Chrome", "Safari", "Firefox", "Arc", "Brave Browser", "Microsoft Edge"}

BROWSER_URL_SCRIPTS = {
    "Google Chrome": 'tell application "Google Chrome" to get URL of active tab of front window',
    "Arc":           'tell application "Arc" to get URL of active tab of front window',
    "Brave Browser": 'tell application "Brave Browser" to get URL of active tab of front window',
    "Microsoft Edge":'tell application "Microsoft Edge" to get URL of active tab of front window',
    "Safari":        'tell application "Safari" to get URL of current tab of front window',
    "Firefox":       'tell application "Firefox" to get URL of active tab of front window',
}

BANNER_W = 440
BANNER_H = 80
BANNER_DURATION = 5.0

# Keep strong references so banners aren't garbage-collected before they close
_live_banners: list = []


# ── Main-thread dispatch ──────────────────────────────────────────────────────

class _Caller(NSObject):
    def call_(self, block):
        block()

_caller = _Caller.new()

def on_main(fn):
    if NSThread.isMainThread():
        fn()
    else:
        _caller.performSelectorOnMainThread_withObject_waitUntilDone_("call:", fn, False)


# ── Floating banner ───────────────────────────────────────────────────────────

class _RoundedView(NSView):
    def drawRect_(self, rect):
        path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(rect, 14, 14)
        NSColor.colorWithRed_green_blue_alpha_(0.85, 0.30, 0.05, 0.96).setFill()
        path.fill()


def _show_banner(title: str, message: str):
    """Create and display a floating banner. MUST be called on the main thread."""
    screen = NSScreen.mainScreen()
    sf = screen.frame()

    x = (sf.size.width - BANNER_W) / 2 + sf.origin.x
    # Just below the menu bar (menu bar is ~24px tall on retina; sf.origin.y is bottom)
    y = sf.origin.y + sf.size.height - BANNER_H - 48

    # NSWindowStyleMaskBorderless=0, NSWindowStyleMaskNonactivatingPanel=128
    panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
        NSMakeRect(x, y, BANNER_W, BANNER_H),
        128,  # NSWindowStyleMaskNonactivatingPanel (borderless implied)
        NSBackingStoreBuffered,
        False,
    )
    panel.setLevel_(NSFloatingWindowLevel + 1)
    panel.setOpaque_(False)
    panel.setBackgroundColor_(NSColor.clearColor())
    panel.setHasShadow_(True)
    panel.setIgnoresMouseEvents_(True)
    panel.setReleasedWhenClosed_(False)

    bg = _RoundedView.alloc().initWithFrame_(NSMakeRect(0, 0, BANNER_W, BANNER_H))
    panel.setContentView_(bg)

    title_field = NSTextField.labelWithString_(title)
    title_field.setFrame_(NSMakeRect(16, BANNER_H - 30, BANNER_W - 32, 18))
    title_field.setFont_(NSFont.boldSystemFontOfSize_(13))
    title_field.setTextColor_(NSColor.whiteColor())
    title_field.setAlignment_(NSTextAlignmentCenter)
    bg.addSubview_(title_field)

    msg_field = NSTextField.labelWithString_(message)
    msg_field.setFrame_(NSMakeRect(16, 10, BANNER_W - 32, 34))
    msg_field.setFont_(NSFont.systemFontOfSize_(12))
    msg_field.setTextColor_(NSColor.colorWithWhite_alpha_(0.85, 1.0))
    msg_field.setAlignment_(NSTextAlignmentCenter)
    msg_field.setMaximumNumberOfLines_(2)
    bg.addSubview_(msg_field)

    panel.orderFrontRegardless()
    _live_banners.append(panel)
    log.info("Banner shown: %r — %r", title, message)

    NSTimer.scheduledTimerWithTimeInterval_repeats_block_(
        BANNER_DURATION, False, lambda _: _dismiss(panel)
    )


def _dismiss(panel):
    panel.close()
    if panel in _live_banners:
        _live_banners.remove(panel)


def show_banner(title: str, message: str):
    on_main(lambda: _show_banner(title, message))


# ── Config ────────────────────────────────────────────────────────────────────

def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return json.load(f)


def get_browser_url(browser: str) -> str | None:
    script = BROWSER_URL_SCRIPTS.get(browser)
    if not script:
        return None
    result = subprocess.run(
        ["osascript", "-e", script], capture_output=True, text=True, timeout=2
    )
    return result.stdout.strip() if result.returncode == 0 else None


# ── App ───────────────────────────────────────────────────────────────────────

class FocusGuard(rumps.App):
    def __init__(self):
        super().__init__("🎯", quit_button="Quit")
        self.config = load_config()
        self.enabled = True
        self._last_notified: dict[str, float] = {}
        self._current_app: str | None = None
        self._last_url: str | None = None
        self._lock = threading.Lock()

        self.toggle_item = rumps.MenuItem("Pause monitoring", callback=self.toggle_enabled)
        self.menu = [
            self.toggle_item,
            None,
            rumps.MenuItem("Test banner", callback=self.test_banner),
            rumps.MenuItem("Edit blocked apps/sites...", callback=self.open_config),
            rumps.MenuItem("Reload config", callback=self.reload_config),
        ]

        nc = NSWorkspace.sharedWorkspace().notificationCenter()
        nc.addObserverForName_object_queue_usingBlock_(
            NSWorkspaceDidActivateApplicationNotification,
            None,
            NSOperationQueue.mainQueue(),
            self._on_app_activated,
        )
        log.info("Subscribed to NSWorkspace app-activation notifications")

        threading.Thread(target=self._browser_url_loop, daemon=True).start()

    def _on_app_activated(self, notification):
        app_obj = notification.userInfo().get("NSWorkspaceApplicationKey")
        name = app_obj.localizedName() if app_obj else None
        log.debug("App switch -> %r", name)
        self._current_app = name
        self._last_url = None

        if not self.enabled or not name:
            return
        if self._is_blocked_app(name):
            log.info("Blocked app: %r", name)
            self._maybe_notify(key=f"app:{name}", subject=name)

    def _browser_url_loop(self):
        while True:
            time.sleep(0.75)
            if not self.enabled:
                continue
            app = self._current_app
            if app not in BROWSERS:
                continue
            try:
                url = get_browser_url(app)
            except Exception:
                continue
            if not url or url == self._last_url:
                continue
            self._last_url = url
            log.debug("URL -> %s", url)
            site = self._blocked_site_for_url(url)
            if site:
                log.info("Blocked site: %r", site)
                self._maybe_notify(key=f"site:{site}", subject=site)

    def toggle_enabled(self, sender):
        self.enabled = not self.enabled
        self.title = "🎯" if self.enabled else "😴"
        sender.title = "Pause monitoring" if self.enabled else "Resume monitoring"

    def test_banner(self, _):
        show_banner("FocusGuard Test", "If you can read this, the banner works!")

    def open_config(self, _):
        subprocess.run(["open", "-e", CONFIG_PATH])

    def reload_config(self, _):
        self.config = load_config()
        show_banner("FocusGuard", "Config reloaded.")

    def _is_blocked_app(self, name: str) -> bool:
        return any(b.lower() == name.lower() for b in self.config.get("blocked_apps", []))

    def _blocked_site_for_url(self, url: str) -> str | None:
        url_lower = url.lower()
        for site in self.config.get("blocked_sites", []):
            if site.lower() in url_lower:
                return site
        return None

    def _maybe_notify(self, key: str, subject: str):
        now = time.time()
        cooldown = self.config.get("cooldown_seconds", 0)
        with self._lock:
            remaining = cooldown - (now - self._last_notified.get(key, 0))
            if remaining > 0:
                log.debug("Cooldown %r — %.0fs left", key, remaining)
                return
            self._last_notified[key] = now

        msg = random.choice(self.config.get("reminder_messages", ["Stay focused."]))
        show_banner(f"Hey — you opened {subject}", msg)


if __name__ == "__main__":
    FocusGuard().run()
