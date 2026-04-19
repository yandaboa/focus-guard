#!/usr/bin/env python3
"""FocusGuard — macOS menu bar app that nudges you when you switch to distracting apps/sites."""

import json
import os
import random
import subprocess
import threading
import time

import rumps
from AppKit import NSWorkspace

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")
BROWSERS = {"Google Chrome", "Safari", "Firefox", "Arc", "Brave Browser", "Microsoft Edge"}

# AppleScript templates per browser
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


def save_config(cfg: dict):
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)


def get_active_app() -> str | None:
    app = NSWorkspace.sharedWorkspace().frontmostApplication()
    return app.localizedName() if app else None


def get_browser_url(browser: str) -> str | None:
    script = BROWSER_URL_SCRIPTS.get(browser)
    if not script:
        return None
    result = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True, text=True, timeout=2
    )
    return result.stdout.strip() if result.returncode == 0 else None


def send_notification(title: str, message: str):
    rumps.notification(title=title, subtitle=None, message=message, sound=True)


def open_config_in_editor():
    subprocess.run(["open", "-e", CONFIG_PATH])


class FocusGuard(rumps.App):
    def __init__(self):
        super().__init__("🎯", quit_button="Quit")
        self.config = load_config()
        self.enabled = True
        self._last_notified: dict[str, float] = {}  # key -> last notification time
        self._last_app: str | None = None
        self._last_url: str | None = None
        self._lock = threading.Lock()

        self.toggle_item = rumps.MenuItem("Pause monitoring", callback=self.toggle_enabled)
        self.menu = [
            self.toggle_item,
            None,
            rumps.MenuItem("Edit blocked apps/sites...", callback=self.open_config),
            rumps.MenuItem("Reload config", callback=self.reload_config),
        ]

        t = threading.Thread(target=self._monitor_loop, daemon=True)
        t.start()

    # ── Menu actions ────────────────────────────────────────────────────────

    def toggle_enabled(self, sender):
        self.enabled = not self.enabled
        if self.enabled:
            self.title = "🎯"
            sender.title = "Pause monitoring"
        else:
            self.title = "😴"
            sender.title = "Resume monitoring"

    def open_config(self, _):
        open_config_in_editor()

    def reload_config(self, _):
        self.config = load_config()
        rumps.notification("FocusGuard", "", "Config reloaded.")

    # ── Core monitor ────────────────────────────────────────────────────────

    def _monitor_loop(self):
        interval = self.config.get("check_interval_seconds", 1.5)
        while True:
            try:
                self._tick()
            except Exception:
                pass
            time.sleep(interval)

    def _tick(self):
        if not self.enabled:
            return

        current_app = get_active_app()

        # App switch
        if current_app != self._last_app:
            self._last_app = current_app
            self._last_url = None  # reset URL tracking on app switch
            if current_app and self._is_blocked_app(current_app):
                self._maybe_notify(key=f"app:{current_app}", subject=current_app)

        # Browser URL check
        if current_app in BROWSERS:
            try:
                url = get_browser_url(current_app)
            except Exception:
                url = None

            if url and url != self._last_url:
                self._last_url = url
                blocked_site = self._blocked_site_for_url(url)
                if blocked_site:
                    self._maybe_notify(key=f"site:{blocked_site}", subject=blocked_site)

    def _is_blocked_app(self, app_name: str) -> bool:
        blocked = self.config.get("blocked_apps", [])
        return any(b.lower() == app_name.lower() for b in blocked)

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
            last = self._last_notified.get(key, 0)
            if now - last < cooldown:
                return
            self._last_notified[key] = now

        messages = self.config.get("reminder_messages", ["Stay focused."])
        msg = random.choice(messages)
        send_notification(f"Hey — you opened {subject}", msg)


if __name__ == "__main__":
    FocusGuard().run()
