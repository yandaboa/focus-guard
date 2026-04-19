"""Native macOS settings window for FocusGuard."""

from AppKit import (
    NSApp, NSBackingStoreBuffered, NSButton, NSColor, NSFont,
    NSMakeRect, NSObject, NSScrollView, NSTextField, NSTextView,
    NSView, NSWindow,
)
from Foundation import NSMakeRange

# Activation policy constants
_POLICY_REGULAR   = 0  # shows in Dock
_POLICY_ACCESSORY = 1  # no Dock icon, but can own windows/key focus
_POLICY_PROHIBITED = 2  # LSUIElement default — cannot become active

W, H, PAD = 560, 510, 20
COL = (W - PAD * 3) // 2  # ~250 px per column


# ── Helpers ───────────────────────────────────────────────────────────────────

def _label(text, frame, bold=False, size=12, alpha=1.0):
    f = NSTextField.labelWithString_(text)
    f.setFrame_(frame)
    f.setFont_(NSFont.boldSystemFontOfSize_(size) if bold else NSFont.systemFontOfSize_(size))
    if alpha < 1.0:
        f.setTextColor_(NSColor.secondaryLabelColor())
    return f


def _textview(frame):
    """NSScrollView containing an editable plain-text NSTextView."""
    scroll = NSScrollView.alloc().initWithFrame_(frame)
    scroll.setHasVerticalScroller_(True)
    scroll.setAutohidesScrollers_(True)
    scroll.setBorderType_(2)  # NSBezelBorder

    tv = NSTextView.alloc().initWithFrame_(
        NSMakeRect(0, 0, frame.size.width, frame.size.height)
    )
    tv.setFont_(NSFont.monospacedSystemFontOfSize_(12, 0))  # weight 0 = regular
    tv.setAutomaticQuoteSubstitutionEnabled_(False)
    tv.setAutomaticDashSubstitutionEnabled_(False)
    tv.setRichText_(False)
    tv.setAutoresizingMask_(2 | 16)  # NSViewWidthSizable | NSViewHeightSizable
    scroll.setDocumentView_(tv)
    return scroll, tv


def _set_tv(tv, lines: list[str]):
    text = "\n".join(lines)
    tv.textStorage().replaceCharactersInRange_withString_(
        NSMakeRange(0, tv.string().length()), text
    )


def _get_tv(tv) -> list[str]:
    return [l.strip() for l in tv.string().split("\n") if l.strip()]


def _button(title, frame, key_equiv=""):
    btn = NSButton.alloc().initWithFrame_(frame)
    btn.setTitle_(title)
    btn.setBezelStyle_(1)  # NSBezelStyleRounded
    if key_equiv:
        btn.setKeyEquivalent_(key_equiv)
    return btn


# ── Button handler (needs to be an NSObject to receive actions) ───────────────

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
        """Open the settings window (or bring it to front if already open)."""
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
            1 | 2 | 4,  # titled | closable | miniaturizable
            NSBackingStoreBuffered,
            False,
        )
        self._window.setTitle_("FocusGuard — Settings")
        self._window.center()
        self._window.setReleasedWhenClosed_(False)

        cv = self._window.contentView()
        self._build_ui(cv, config)

        # LSUIElement apps can't own key windows by default — temporarily
        # switch to Accessory policy so the settings window gets focus.
        NSApp.setActivationPolicy_(_POLICY_ACCESSORY)
        NSApp.activateIgnoringOtherApps_(True)
        self._window.makeKeyAndOrderFront_(None)

    def _build_ui(self, cv: NSView, config: dict):
        # ── Header ────────────────────────────────────────────────────────────
        cv.addSubview_(_label("Settings", NSMakeRect(PAD, H - 42, W - PAD * 2, 24), bold=True, size=16))
        cv.addSubview_(_label(
            "One item per line in each list.",
            NSMakeRect(PAD, H - 60, W - PAD * 2, 16), size=11, alpha=0.6,
        ))

        # ── Blocked Apps ──────────────────────────────────────────────────────
        cv.addSubview_(_label("Blocked Apps", NSMakeRect(PAD, H - 80, COL, 16), bold=True))
        sa, self._apps_tv = _textview(NSMakeRect(PAD, H - 240, COL, 155))
        cv.addSubview_(sa)
        _set_tv(self._apps_tv, config.get("blocked_apps", []))

        # ── Blocked Sites ─────────────────────────────────────────────────────
        x2 = PAD * 2 + COL
        cv.addSubview_(_label("Blocked Sites", NSMakeRect(x2, H - 80, COL, 16), bold=True))
        ss, self._sites_tv = _textview(NSMakeRect(x2, H - 240, COL, 155))
        cv.addSubview_(ss)
        _set_tv(self._sites_tv, config.get("blocked_sites", []))

        # ── Reminder Messages ─────────────────────────────────────────────────
        cv.addSubview_(_label("Reminder Messages", NSMakeRect(PAD, H - 260, W - PAD * 2, 16), bold=True))
        sm, self._msgs_tv = _textview(NSMakeRect(PAD, H - 400, W - PAD * 2, 135))
        cv.addSubview_(sm)
        _set_tv(self._msgs_tv, config.get("reminder_messages", []))

        # ── Cooldown ──────────────────────────────────────────────────────────
        cv.addSubview_(_label("Cooldown between alerts:", NSMakeRect(PAD, H - 428, 175, 20)))
        self._cooldown = NSTextField.alloc().initWithFrame_(NSMakeRect(PAD + 180, H - 430, 55, 22))
        self._cooldown.setStringValue_(str(config.get("cooldown_seconds", 0)))
        self._cooldown.setFont_(NSFont.systemFontOfSize_(12))
        cv.addSubview_(self._cooldown)
        cv.addSubview_(_label("seconds", NSMakeRect(PAD + 242, H - 428, 60, 20)))

        # ── Buttons ───────────────────────────────────────────────────────────
        cancel_btn = _button("Cancel", NSMakeRect(W - 200, PAD, 80, 28))
        save_btn   = _button("Save",   NSMakeRect(W - 108, PAD, 88, 28), key_equiv="\r")
        cv.addSubview_(cancel_btn)
        cv.addSubview_(save_btn)

        self._handler = _Handler.alloc().init()
        self._handler._win = self
        cancel_btn.setTarget_(self._handler)
        cancel_btn.setAction_("cancel:")
        save_btn.setTarget_(self._handler)
        save_btn.setAction_("save:")
        self._window.setDefaultButtonCell_(save_btn.cell())

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
        # Revert to background-only mode so we stay out of the Dock/app switcher
        NSApp.setActivationPolicy_(_POLICY_PROHIBITED)
