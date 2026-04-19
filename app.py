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
from AppKit import NSWorkspace, NSWorkspaceDidActivateApplicationNotification
from Foundation import NSOperationQueue

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


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return json.load(f)


def get_browser_url(browser: str) -> str | None:
    script = BROWSER_URL_SCRIPTS.get(browser)
    if not script:
        return None
    result = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True, text=True, timeout=2
    )
    return result.stdout.strip() if result.returncode == 0 else None


TERMINAL_NOTIFIER = "/usr/local/bin/terminal-notifier"

def send_notification(title: str, message: str):
    """Must be called from a background thread — subprocess.run blocks the main run loop."""
    log.info("NOTIFY  %r — %r", title, message)
    try:
        result = subprocess.run(
            [TERMINAL_NOTIFIER, "-title", title, "-message", message,
             "-sound", "default", "-group", "focusguard"],
            capture_output=True, timeout=5
        )
        log.info("NOTIFY  returncode=%d stderr=%r", result.returncode, result.stderr.decode())
    except Exception as e:
        log.error("NOTIFY  failed: %s", e)


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
            rumps.MenuItem("Test notification", callback=self.test_notification),
            rumps.MenuItem("Edit blocked apps/sites...", callback=self.open_config),
            rumps.MenuItem("Reload config", callback=self.reload_config),
        ]

        # Subscribe to NSWorkspace app-activation events (fires instantly on every switch)
        nc = NSWorkspace.sharedWorkspace().notificationCenter()
        nc.addObserverForName_object_queue_usingBlock_(
            NSWorkspaceDidActivateApplicationNotification,
            None,
            NSOperationQueue.mainQueue(),
            self._on_app_activated,
        )
        log.info("Subscribed to NSWorkspace app-activation notifications")

        # Browser URL polling (only matters while a browser is active)
        t = threading.Thread(target=self._browser_url_loop, daemon=True)
        t.start()

    # ── NSWorkspace callback ─────────────────────────────────────────────────

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

    # ── Browser URL polling ──────────────────────────────────────────────────

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

    # ── Menu actions ─────────────────────────────────────────────────────────

    def toggle_enabled(self, sender):
        self.enabled = not self.enabled
        if self.enabled:
            self.title = "🎯"
            sender.title = "Pause monitoring"
        else:
            self.title = "😴"
            sender.title = "Resume monitoring"

    def test_notification(self, _):
        threading.Thread(
            target=send_notification,
            args=("FocusGuard Test", "If you see this, notifications work!"),
            daemon=True
        ).start()

    def open_config(self, _):
        subprocess.run(["open", "-e", CONFIG_PATH])

    def reload_config(self, _):
        self.config = load_config()
        rumps.notification("FocusGuard", "", "Config reloaded.")

    # ── Helpers ──────────────────────────────────────────────────────────────

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
        cooldown = self.config.get("cooldown_seconds", 300)
        with self._lock:
            remaining = cooldown - (now - self._last_notified.get(key, 0))
            if remaining > 0:
                log.debug("Cooldown %r — %.0fs left", key, remaining)
                return
            self._last_notified[key] = now

        msg = random.choice(self.config.get("reminder_messages", ["Stay focused."]))
        threading.Thread(
            target=send_notification,
            args=(f"Hey — you opened {subject}", msg),
            daemon=True
        ).start()


if __name__ == "__main__":
    FocusGuard().run()
