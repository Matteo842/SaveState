"""
Controller/Gamepad support for SaveState via XInput (Windows).
Supports Xbox controllers, Steam Deck in gamepad mode, and any XInput-compatible device.

Button mapping:
  D-pad / Left Stick  → Navigate profile list up/down
  A                   → Backup selected profile
  X                   → Restore selected profile
  Y                   → Manage Backups
  B                   → Back / close current panel
  Start               → Backup (alternative)
  LB / RB             → Scroll profile list by page
"""

import ctypes
import logging
import platform
import time

from PySide6.QtCore import QObject, QThread, Signal, Slot


# ---------------------------------------------------------------------------
# XInput structures and constants
# ---------------------------------------------------------------------------

class XINPUT_GAMEPAD(ctypes.Structure):
    _fields_ = [
        ("wButtons",      ctypes.c_ushort),
        ("bLeftTrigger",  ctypes.c_ubyte),
        ("bRightTrigger", ctypes.c_ubyte),
        ("sThumbLX",      ctypes.c_short),
        ("sThumbLY",      ctypes.c_short),
        ("sThumbRX",      ctypes.c_short),
        ("sThumbRY",      ctypes.c_short),
    ]


class XINPUT_STATE(ctypes.Structure):
    _fields_ = [
        ("dwPacketNumber", ctypes.c_ulong),
        ("Gamepad",        XINPUT_GAMEPAD),
    ]


# Button bitmasks
BTN_DPAD_UP     = 0x0001
BTN_DPAD_DOWN   = 0x0002
BTN_DPAD_LEFT   = 0x0004
BTN_DPAD_RIGHT  = 0x0008
BTN_START       = 0x0010
BTN_BACK        = 0x0020
BTN_LB          = 0x0100
BTN_RB          = 0x0200
BTN_A           = 0x1000
BTN_B           = 0x2000
BTN_X           = 0x4000
BTN_Y           = 0x8000

THUMB_DEADZONE      = 8000   # XInput default deadzone
REPEAT_INITIAL_DELAY = 0.45  # seconds before first repeat
REPEAT_RATE          = 0.12  # seconds between repeats while held

POLL_INTERVAL = 1 / 30      # ~30 fps polling


# ---------------------------------------------------------------------------
# Poller worker (runs in a QThread)
# ---------------------------------------------------------------------------

TRIGGER_THRESHOLD = 128  # Analog trigger value (0-255) above which it counts as "pressed"


class ControllerPoller(QObject):
    """Polls XInput state and emits signals for navigation and button presses."""

    nav_up    = Signal()
    nav_down  = Signal()
    nav_left  = Signal()
    nav_right = Signal()
    btn_a     = Signal()   # Backup
    btn_b     = Signal()   # Back
    btn_x     = Signal()   # Restore
    btn_y     = Signal()   # Manage Backups
    btn_start = Signal()   # Backup (alt)
    btn_back  = Signal()   # View / Select button
    btn_lb    = Signal()   # Page up
    btn_rb    = Signal()   # Page down
    btn_l1l2  = Signal()   # L1+L2 combo (LB + Left Trigger simultaneously)
    lt_hold   = Signal()   # LT pressed alone (switch to General section)
    lt_release = Signal()  # LT released (switch back to Actions section)
    any_input = Signal()   # Emitted on any button/nav input (to switch to controller mode)
    controller_connected    = Signal(int)
    controller_disconnected = Signal(int)

    def __init__(self):
        super().__init__()
        self._running = False
        self._xinput = None
        self._prev_buttons: dict[int, int] = {}
        self._prev_connected: dict[int, bool] = {}
        self._prev_l1l2: dict[int, bool] = {}   # combo state per controller
        self._prev_lt_active: dict[int, bool] = {}  # per-controller previous LT-alone state
        self._lt_holding: dict[int, bool] = {}      # True while LT hold signal has been emitted

        # Per-controller, per-direction repeat tracking
        # Key: (controller_idx, direction_str)  Value: (first_press_time, last_repeat_time)
        self._nav_repeat: dict[tuple, tuple] = {}

        self._load_xinput()

    def _load_xinput(self):
        if platform.system() != "Windows":
            logging.info("XInput: not on Windows, controller support disabled.")
            return
        for dll_name in ("xinput1_4", "xinput1_3", "xinput9_1_0"):
            try:
                self._xinput = ctypes.windll.LoadLibrary(dll_name)
                logging.info(f"XInput loaded: {dll_name}")
                return
            except OSError:
                continue
        logging.warning("XInput DLL not found – controller support unavailable.")

    def is_available(self) -> bool:
        return self._xinput is not None

    @Slot()
    def run(self):
        self._running = True
        while self._running:
            if self._xinput:
                try:
                    self._poll()
                except Exception as e:
                    logging.error(f"ControllerPoller error: {e}")
            time.sleep(POLL_INTERVAL)

    def stop(self):
        self._running = False

    # ------------------------------------------------------------------
    def _poll(self):
        now = time.monotonic()
        for idx in range(4):
            state = XINPUT_STATE()
            result = self._xinput.XInputGetState(idx, ctypes.byref(state))

            connected = (result == 0)
            was_connected = self._prev_connected.get(idx, False)

            if connected != was_connected:
                self._prev_connected[idx] = connected
                if connected:
                    self.controller_connected.emit(idx)
                    logging.info(f"Controller {idx} connected.")
                else:
                    self.controller_disconnected.emit(idx)
                    self._prev_buttons[idx] = 0
                    logging.info(f"Controller {idx} disconnected.")

            if not connected:
                continue

            buttons = state.Gamepad.wButtons
            prev    = self._prev_buttons.get(idx, 0)

            # Rising-edge detection (button just pressed this tick)
            just_pressed = buttons & ~prev

            # ── LT+RT combo: both analog triggers pressed simultaneously ──
            lt_active   = state.Gamepad.bLeftTrigger  > TRIGGER_THRESHOLD
            rt_active   = state.Gamepad.bRightTrigger > TRIGGER_THRESHOLD
            ltrt_now    = lt_active and rt_active
            prev_l1l2   = self._prev_l1l2.get(idx, False)
            if ltrt_now and not prev_l1l2:
                self.btn_l1l2.emit()   # signal name kept for compatibility
                self._lt_press_time.pop(idx, None)  # cancel LT long press if RT joined
            self._prev_l1l2[idx] = ltrt_now

            _any = False
            if just_pressed & BTN_DPAD_UP:    self.nav_up.emit();    _any = True
            if just_pressed & BTN_DPAD_DOWN:  self.nav_down.emit();  _any = True
            if just_pressed & BTN_DPAD_LEFT:  self.nav_left.emit();  _any = True
            if just_pressed & BTN_DPAD_RIGHT: self.nav_right.emit(); _any = True
            if just_pressed & BTN_A:          self.btn_a.emit();     _any = True
            if just_pressed & BTN_B:          self.btn_b.emit();     _any = True
            if just_pressed & BTN_X:          self.btn_x.emit();     _any = True
            if just_pressed & BTN_Y:          self.btn_y.emit();     _any = True
            if just_pressed & BTN_START:      self.btn_start.emit(); _any = True
            if just_pressed & BTN_BACK:       self.btn_back.emit();  _any = True
            if just_pressed & BTN_LB:         self.btn_lb.emit();    _any = True
            if just_pressed & BTN_RB:         self.btn_rb.emit();    _any = True

            # ── LT (analog trigger): hold / release for section toggle ─
            #    LT held alone (without RT) → lt_hold (switch to General)
            #    LT released                → lt_release (back to Actions)
            #    LT+RT together             → combo handled above, not here
            lt_alone = lt_active and not rt_active
            prev_lt_alone = self._prev_lt_active.get(idx, False)
            was_holding = self._lt_holding.get(idx, False)

            if lt_alone and not prev_lt_alone:
                # LT just pressed alone → switch to General
                self.lt_hold.emit()
                self._lt_holding[idx] = True
                _any = True
            elif not lt_active and was_holding:
                # LT released after being held → switch back to Actions
                self.lt_release.emit()
                self._lt_holding[idx] = False
            elif rt_active and was_holding:
                # RT pressed while LT held → cancel hold (LT+RT combo takes over)
                self.lt_release.emit()
                self._lt_holding[idx] = False

            self._prev_lt_active[idx] = lt_alone

            if _any:
                self.any_input.emit()

            self._prev_buttons[idx] = buttons

            # ----------------------------------------------------------
            # Thumbstick navigation with initial-delay + repeat
            # ----------------------------------------------------------
            ly = state.Gamepad.sThumbLY

            for direction, active in (("up", ly > THUMB_DEADZONE),
                                      ("down", ly < -THUMB_DEADZONE)):
                key = (idx, direction)
                if active:
                    if key not in self._nav_repeat:
                        # First frame in this direction → emit immediately
                        self._nav_repeat[key] = (now, now)
                        if direction == "up":
                            self.nav_up.emit()
                        else:
                            self.nav_down.emit()
                        self.any_input.emit()
                    else:
                        first_press, last_repeat = self._nav_repeat[key]
                        held = now - first_press
                        since_last = now - last_repeat
                        if held >= REPEAT_INITIAL_DELAY and since_last >= REPEAT_RATE:
                            self._nav_repeat[key] = (first_press, now)
                            if direction == "up":
                                self.nav_up.emit()
                            else:
                                self.nav_down.emit()
                else:
                    self._nav_repeat.pop(key, None)


# ---------------------------------------------------------------------------
# ControllerManager – lifecycle management
# ---------------------------------------------------------------------------

class ControllerManager:
    """
    Manages the controller polling thread and connects its signals
    to the main window's navigation/action slots.
    """

    def __init__(self, main_window):
        self.main_window = main_window
        self._thread: QThread | None = None
        self._poller: ControllerPoller | None = None
        self._started = False

    # ------------------------------------------------------------------
    def start(self):
        if self._started:
            return
        self._poller = ControllerPoller()
        if not self._poller.is_available():
            logging.info("ControllerManager: XInput unavailable, not starting.")
            return
        self._thread = QThread()
        self._poller.moveToThread(self._thread)
        self._thread.started.connect(self._poller.run)
        self._connect_signals()
        self._thread.start()
        self._started = True
        logging.info("ControllerManager started.")

    def stop(self):
        if not self._started:
            return
        if self._poller:
            self._poller.stop()
        if self._thread:
            self._thread.quit()
            self._thread.wait(2000)
        self._thread = None
        self._poller = None
        self._started = False
        logging.info("ControllerManager stopped.")

    def is_running(self) -> bool:
        return self._started

    # ------------------------------------------------------------------
    def _connect_signals(self):
        mw = self.main_window
        p  = self._poller
        p.nav_up.connect(mw._ctrl_nav_up)
        p.nav_down.connect(mw._ctrl_nav_down)
        p.btn_a.connect(mw._ctrl_btn_a)
        p.btn_b.connect(mw._ctrl_btn_b)
        p.btn_x.connect(mw._ctrl_btn_x)
        p.btn_y.connect(mw._ctrl_btn_y)
        p.btn_start.connect(mw._ctrl_btn_start)
        p.btn_back.connect(mw._ctrl_btn_delete)
        p.btn_lb.connect(mw._ctrl_btn_lb)
        p.btn_rb.connect(mw._ctrl_btn_rb)
        p.btn_l1l2.connect(mw._ctrl_btn_l1l2)
        p.lt_hold.connect(mw._ctrl_on_lt_hold)
        p.lt_release.connect(mw._ctrl_on_lt_release)
        p.any_input.connect(mw._ctrl_on_any_input)
        p.controller_connected.connect(mw._ctrl_on_connected)
        p.controller_disconnected.connect(mw._ctrl_on_disconnected)
