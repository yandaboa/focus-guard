"""Native macOS settings window for FocusGuard."""

import logging

from AppKit import (
    NSApp, NSBackingStoreBuffered, NSButton, NSColor, NSFont,
    NSMakeRect, NSObject, NSScrollView, NSTextField, NSTextView,
    NSView, NSVisualEffectView, NSWindow, NSBox,
)
from Foundation import NSMakeRange

log = logging.getLogger("focusguard.settings")

_POLICY_ACCESSORY  = 1
_POLICY_PROHIBITED = 2

W, H, PAD = 560, 530, 20
COL = (W - PAD * 3) // 2   # ~250 px per column

# NSVisualEffectView constants
_BLEND_BEHIND_WINDOW = 0
_STATE_ACTIVE        = 1
_MATERIAL_SIDEBAR    = 7


# ── Helpers ───────────────────────────────────────────────────────────────────

def _label(text, frame, bold=False, size=12, color=None):
    f = NSTextField.labelWithString_(text)
    f.setFrame_(frame)
    f.setFont_(NSFont.boldSystemFontOfSize_(size) if bold else NSFont.systemFontOfSize_(size))
    f.setTextColor_(color or NSColor.labelColor())
    return f


def _section_header(text, icon, frame):
    """Bold section label with an emoji icon prefix."""
    return _label(f"{icon}  {text}", frame, bold=True, size=12,
                  color=NSColor.secondaryLabelColor())


def _textview(frame):
    scroll = NSScrollView.alloc().initWithFrame_(frame)
    scroll.setHasVerticalScroller_(True)
    scroll.setAutohidesScrollers_(True)
    scroll.setBorderType_(0)       # NSNoBorder — we style the box ourselves
    scroll.setDrawsBackground_(False)
    scroll.setWantsLayer_(True)
    scroll.layer().setCornerRadius_(8)
    scroll.layer().setMasksToBounds_(True)

    tv = NSTextView.alloc().initWithFrame_(
        NSMakeRect(0, 0, frame.size.width, frame.size.height)
    )
    tv.setFont_(NSFont.systemFontOfSize_(12))
    tv.setTextColor_(NSColor.labelColor())
    tv.setBackgroundColor_(NSColor.textBackgroundColor())
    tv.setAutomaticQuoteSubstitutionEnabled_(False)
    tv.setAutomaticDashSubstitutionEnabled_(False)
    tv.setRichText_(False)
    tv.setAutoresizingMask_(2 | 16)   # NSViewWidthSizable | NSViewHeightSizable
    tv.setTextContainerInset_((6, 6))
    scroll.setDocumentView_(tv)
    return scroll, tv


def _set_tv(tv, lines: list[str]):
    tv.textStorage().replaceCharactersInRange_withString_(
        NSMakeRange(0, tv.string().length()), "\n".join(lines)
    )


def _get_tv(tv) -> list[str]:
    return [l.strip() for l in tv.string().split("\n") if l.strip()]


def _rounded_box(frame, corner=10):
    """Invisible rounded container with a subtle fill."""
    box = NSView.alloc().initWithFrame_(frame)
    box.setWantsLayer_(True)
    box.layer().setCornerRadius_(corner)
    box.layer().setBackgroundColor_(
        NSColor.colorWithWhite_alpha_(0.5, 0.07).CGColor()
    )
    box.layer().setBorderColor_(
        NSColor.separatorColor().CGColor()
    )
    box.layer().setBorderWidth_(0.5)
    return box


# ── Button handler ────────────────────────────────────────────────────────────

class _Handler(NSObject):
    def save_(self, _):
        self._win._do_save()
    def cancel_(self, _):
        self._win._do_cancel()


# ── Settings window ───────────────────────────────────────────────────────────

class SettingsWindow:
    _open: "SettingsWindow | None" = None

    @classmethod
    def show(cls, config: dict, on_save):
        log.info("SettingsWindow.show — _open=%s", cls._open)
        if cls._open is not None:
            try:
                cls._open._window.makeKeyAndOrderFront_(None)
                NSApp.activateIgnoringOtherApps_(True)
                return
            except Exception:
                cls._open = None
        cls._open = cls(config, on_save)

    def __init__(self, config: dict, on_save):
        self._on_save = on_save

        self._window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, W, H),
            1 | 2 | 4,   # titled | closable | miniaturizable
            NSBackingStoreBuffered,
            False,
        )
        self._window.setTitle_("FocusGuard")
        self._window.center()
        self._window.setReleasedWhenClosed_(False)
        self._window.setTitlebarAppearsTransparent_(True)

        # Frosted-glass base
        vev = NSVisualEffectView.alloc().initWithFrame_(
            NSMakeRect(0, 0, W, H)
        )
        vev.setBlendingMode_(_BLEND_BEHIND_WINDOW)
        vev.setState_(_STATE_ACTIVE)
        vev.setMaterial_(_MATERIAL_SIDEBAR)
        self._window.setContentView_(vev)

        self._build_ui(vev, config)

        NSApp.setActivationPolicy_(_POLICY_ACCESSORY)
        NSApp.activateIgnoringOtherApps_(True)
        self._window.makeKeyAndOrderFront_(None)
        self._window.orderFrontRegardless()
        log.info("Window visible=%s key=%s", self._window.isVisible(), self._window.isKeyWindow())

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build_ui(self, cv, config: dict):
        inner_w = W - PAD * 2

        # ── Title bar area ────────────────────────────────────────────────────
        y = H - 52
        cv.addSubview_(_label("🎯  FocusGuard Settings", NSMakeRect(PAD, y, inner_w, 28),
                               bold=True, size=17))
        cv.addSubview_(_label("One item per line. Hit Save to apply immediately.",
                               NSMakeRect(PAD, y - 20, inner_w, 16),
                               size=11, color=NSColor.secondaryLabelColor()))

        # ── Blocked Apps card ─────────────────────────────────────────────────
        card_top = H - 80
        card_h   = 175
        card_y   = card_top - card_h

        card_a = _rounded_box(NSMakeRect(PAD, card_y, COL, card_h))
        cv.addSubview_(card_a)
        card_a.addSubview_(_section_header("Blocked Apps", "🚫",
                                            NSMakeRect(8, card_h - 24, COL - 16, 18)))
        sa, self._apps_tv = _textview(NSMakeRect(8, 6, COL - 16, card_h - 34))
        card_a.addSubview_(sa)
        _set_tv(self._apps_tv, config.get("blocked_apps", []))

        # ── Blocked Sites card ────────────────────────────────────────────────
        x2 = PAD * 2 + COL
        card_s = _rounded_box(NSMakeRect(x2, card_y, COL, card_h))
        cv.addSubview_(card_s)
        card_s.addSubview_(_section_header("Blocked Sites", "🌐",
                                            NSMakeRect(8, card_h - 24, COL - 16, 18)))
        ss, self._sites_tv = _textview(NSMakeRect(8, 6, COL - 16, card_h - 34))
        card_s.addSubview_(ss)
        _set_tv(self._sites_tv, config.get("blocked_sites", []))

        # ── Messages card ─────────────────────────────────────────────────────
        msg_card_top = card_y - 14
        msg_h        = 148
        msg_y        = msg_card_top - msg_h

        card_m = _rounded_box(NSMakeRect(PAD, msg_y, inner_w, msg_h))
        cv.addSubview_(card_m)
        card_m.addSubview_(_section_header("Reminder Messages", "💬",
                                            NSMakeRect(8, msg_h - 24, inner_w - 16, 18)))
        sm, self._msgs_tv = _textview(NSMakeRect(8, 6, inner_w - 16, msg_h - 34))
        card_m.addSubview_(sm)
        _set_tv(self._msgs_tv, config.get("reminder_messages", []))

        # ── Cooldown row ──────────────────────────────────────────────────────
        cd_y = msg_y - 38
        cv.addSubview_(_label("⏱  Cooldown between alerts:",
                               NSMakeRect(PAD, cd_y, 195, 22),
                               color=NSColor.secondaryLabelColor()))

        self._cooldown = NSTextField.alloc().initWithFrame_(
            NSMakeRect(PAD + 200, cd_y, 52, 22)
        )
        self._cooldown.setStringValue_(str(config.get("cooldown_seconds", 0)))
        self._cooldown.setFont_(NSFont.systemFontOfSize_(12))
        self._cooldown.setBezeled_(True)
        self._cooldown.setEditable_(True)
        cv.addSubview_(self._cooldown)
        cv.addSubview_(_label("seconds", NSMakeRect(PAD + 258, cd_y, 60, 22),
                               color=NSColor.secondaryLabelColor()))

        # ── Buttons ───────────────────────────────────────────────────────────
        cancel_btn = NSButton.alloc().initWithFrame_(NSMakeRect(W - 196, PAD, 80, 28))
        cancel_btn.setTitle_("Cancel")
        cancel_btn.setBezelStyle_(1)

        save_btn = NSButton.alloc().initWithFrame_(NSMakeRect(W - 104, PAD, 88, 28))
        save_btn.setTitle_("Save")
        save_btn.setBezelStyle_(1)
        save_btn.setKeyEquivalent_("\r")

        cv.addSubview_(cancel_btn)
        cv.addSubview_(save_btn)

        self._handler = _Handler.alloc().init()
        self._handler._win = self
        cancel_btn.setTarget_(self._handler)
        cancel_btn.setAction_("cancel:")
        save_btn.setTarget_(self._handler)
        save_btn.setAction_("save:")
        self._window.setDefaultButtonCell_(save_btn.cell())

    # ── Actions ───────────────────────────────────────────────────────────────

    def _do_save(self):
        try:
            cooldown = int(self._cooldown.stringValue().strip() or "0")
        except ValueError:
            cooldown = 0
        new_config = {
            "blocked_apps":      _get_tv(self._apps_tv),
            "blocked_sites":     _get_tv(self._sites_tv),
            "reminder_messages": _get_tv(self._msgs_tv),
            "cooldown_seconds":  cooldown,
        }
        self._on_save(new_config)
        self._close()

    def _do_cancel(self):
        self._close()

    def _close(self):
        SettingsWindow._open = None
        self._window.close()
        NSApp.setActivationPolicy_(_POLICY_PROHIBITED)
