"""
Controller/Gamepad support for SaveState.
- Windows: XInput (Xbox, Steam Deck via Steam Input, any XInput-compatible device)
- Linux/SteamOS: SDL2 GameController API (Steam Deck built-in controls, Xbox via
  xpad, PlayStation via hid-playstation, any SDL2-recognized controller)

Button mapping:
  D-pad / Left Stick  → Navigate profile list up/down
  A                   → Backup selected profile
  X                   → Restore selected profile
  Y                   → Manage Backups
  B                   → Back / close current panel
  Start               → Open context menu
  View/Select         → Delete profile
  LB / RB             → Scroll profile list by page
  LT (hold)           → Switch to General section (release → back to Actions)
  LT+RT (simultaneous)→ Backup all profiles
"""

import ctypes
import logging
import platform
import time

from PySide6.QtCore import QObject, QThread, Signal, Slot


# ---------------------------------------------------------------------------
# XInput structures and constants (Windows only)
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


# Button bitmasks (used by both backends as internal representation)
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

# Analog trigger value (0‒255) above which it counts as "pressed"
TRIGGER_THRESHOLD = 128


# ---------------------------------------------------------------------------
# SDL2 constants (Linux / SteamOS)
# ---------------------------------------------------------------------------

# SDL_Init flags
_SDL_INIT_GAMECONTROLLER = 0x00002000

# SDL_GameControllerButton → our BTN_* bitmask
_SDL2_BTN_MAP = {
    0:  BTN_A,          # SDL_CONTROLLER_BUTTON_A
    1:  BTN_B,          # SDL_CONTROLLER_BUTTON_B
    2:  BTN_X,          # SDL_CONTROLLER_BUTTON_X
    3:  BTN_Y,          # SDL_CONTROLLER_BUTTON_Y
    4:  BTN_BACK,       # SDL_CONTROLLER_BUTTON_BACK
    6:  BTN_START,      # SDL_CONTROLLER_BUTTON_START
    9:  BTN_LB,         # SDL_CONTROLLER_BUTTON_LEFTSHOULDER
    10: BTN_RB,         # SDL_CONTROLLER_BUTTON_RIGHTSHOULDER
    11: BTN_DPAD_UP,    # SDL_CONTROLLER_BUTTON_DPAD_UP
    12: BTN_DPAD_DOWN,  # SDL_CONTROLLER_BUTTON_DPAD_DOWN
    13: BTN_DPAD_LEFT,  # SDL_CONTROLLER_BUTTON_DPAD_LEFT
    14: BTN_DPAD_RIGHT, # SDL_CONTROLLER_BUTTON_DPAD_RIGHT
}

_SDL_AXIS_LEFTY         = 1
_SDL_AXIS_TRIGGERLEFT   = 4
_SDL_AXIS_TRIGGERRIGHT   = 5


# ---------------------------------------------------------------------------
# Poller worker (runs in a QThread)
# ---------------------------------------------------------------------------

class ControllerPoller(QObject):
    """Polls controller state and emits signals for navigation and button presses.
    Auto-selects XInput (Windows) or SDL2 (Linux/SteamOS) backend."""

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
    btn_l1l2  = Signal()   # LT+RT combo
    lt_hold   = Signal()   # LT pressed alone (switch to General section)
    lt_release = Signal()  # LT released (switch back to Actions section)
    any_input = Signal()   # Emitted on any button/nav input
    controller_connected    = Signal(int)
    controller_disconnected = Signal(int)
    buttons_state_changed = Signal(list) # List of currently active button labels

    def __init__(self):
        super().__init__()
        self._running = False
        self._backend = None  # 'xinput' or 'sdl2'
        self._xinput = None
        self._sdl2 = None

        # Shared state tracking (used by both backends)
        self._prev_buttons: dict[int, int] = {}
        self._prev_connected: dict[int, bool] = {}
        self._prev_l1l2: dict[int, bool] = {}
        self._prev_lt_active: dict[int, bool] = {}
        self._lt_holding: dict[int, bool] = {}
        self._nav_repeat: dict[tuple, tuple] = {}
        self._prev_active_labels: dict[int, set] = {}

        # SDL2-specific state
        self._sdl2_controllers: dict[int, ctypes.c_void_p] = {}
        self._sdl2_last_scan: float = 0.0

        self._load_backend()

    # ------------------------------------------------------------------
    # Backend loading
    # ------------------------------------------------------------------

    def _load_backend(self):
        system = platform.system()
        if system == "Windows":
            self._load_xinput()
        else:
            self._load_sdl2()

    def _load_xinput(self):
        for dll_name in ("xinput1_4", "xinput1_3", "xinput9_1_0"):
            try:
                self._xinput = ctypes.windll.LoadLibrary(dll_name)
                self._backend = 'xinput'
                logging.info(f"XInput loaded: {dll_name}")
                return
            except OSError:
                continue
        logging.warning("XInput DLL not found – controller support unavailable.")

    def _load_sdl2(self):
        """Try to load SDL2 shared library (Linux / SteamOS)."""
        lib_names = (
            "libSDL2-2.0.so.0",   # Standard versioned name
            "libSDL2-2.0.so",
            "libSDL2.so",
            "libSDL2.so.0",
        )
        for lib_name in lib_names:
            try:
                self._sdl2 = ctypes.CDLL(lib_name)
                break
            except OSError:
                continue

        if self._sdl2 is None:
            logging.warning("SDL2 not found – controller support unavailable on this platform.")
            return

        # Set up function signatures for type safety
        try:
            self._sdl2.SDL_Init.argtypes = [ctypes.c_uint32]
            self._sdl2.SDL_Init.restype = ctypes.c_int
            self._sdl2.SDL_Quit.argtypes = []
            self._sdl2.SDL_Quit.restype = None
            self._sdl2.SDL_NumJoysticks.argtypes = []
            self._sdl2.SDL_NumJoysticks.restype = ctypes.c_int
            self._sdl2.SDL_IsGameController.argtypes = [ctypes.c_int]
            self._sdl2.SDL_IsGameController.restype = ctypes.c_int
            self._sdl2.SDL_GameControllerOpen.argtypes = [ctypes.c_int]
            self._sdl2.SDL_GameControllerOpen.restype = ctypes.c_void_p
            self._sdl2.SDL_GameControllerClose.argtypes = [ctypes.c_void_p]
            self._sdl2.SDL_GameControllerClose.restype = None
            self._sdl2.SDL_GameControllerGetButton.argtypes = [ctypes.c_void_p, ctypes.c_int]
            self._sdl2.SDL_GameControllerGetButton.restype = ctypes.c_ubyte
            self._sdl2.SDL_GameControllerGetAxis.argtypes = [ctypes.c_void_p, ctypes.c_int]
            self._sdl2.SDL_GameControllerGetAxis.restype = ctypes.c_int16
            self._sdl2.SDL_GameControllerGetAttached.argtypes = [ctypes.c_void_p]
            self._sdl2.SDL_GameControllerGetAttached.restype = ctypes.c_int
            self._sdl2.SDL_GameControllerUpdate.argtypes = []
            self._sdl2.SDL_GameControllerUpdate.restype = None
        except Exception as e:
            logging.warning(f"SDL2 function setup failed: {e}")
            self._sdl2 = None
            return

        # Initialize only the GameController subsystem (no video/audio needed)
        if self._sdl2.SDL_Init(_SDL_INIT_GAMECONTROLLER) != 0:
            logging.warning("SDL2 SDL_Init(GAMECONTROLLER) failed.")
            self._sdl2 = None
            return

        self._backend = 'sdl2'
        logging.info("SDL2 GameController backend loaded successfully.")

    def is_available(self) -> bool:
        return self._backend is not None

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    @Slot()
    def run(self):
        self._running = True
        while self._running:
            if self._backend:
                try:
                    self._poll()
                except Exception as e:
                    logging.error(f"ControllerPoller error: {e}")
            time.sleep(POLL_INTERVAL)
        # Cleanup SDL2 on stop
        if self._backend == 'sdl2' and self._sdl2:
            for gc in self._sdl2_controllers.values():
                self._sdl2.SDL_GameControllerClose(gc)
            self._sdl2_controllers.clear()
            self._sdl2.SDL_Quit()

    def stop(self):
        self._running = False

    # ------------------------------------------------------------------
    # Polling dispatch
    # ------------------------------------------------------------------

    def _poll(self):
        now = time.monotonic()
        if self._backend == 'xinput':
            self._poll_xinput(now)
        elif self._backend == 'sdl2':
            self._poll_sdl2(now)

    # ------------------------------------------------------------------
    # XInput backend (Windows)
    # ------------------------------------------------------------------

    def _poll_xinput(self, now: float):
        for idx in range(4):
            state = XINPUT_STATE()
            result = self._xinput.XInputGetState(idx, ctypes.byref(state))
            connected = (result == 0)

            # Connection change detection
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

            buttons  = state.Gamepad.wButtons
            lt_value = state.Gamepad.bLeftTrigger   # 0–255
            rt_value = state.Gamepad.bRightTrigger  # 0–255
            stick_ly = state.Gamepad.sThumbLY       # −32768…32767, positive=up

            self._process_controller_state(idx, buttons, lt_value, rt_value, stick_ly, now)

    # ------------------------------------------------------------------
    # SDL2 backend (Linux / SteamOS / Steam Deck)
    # ------------------------------------------------------------------

    def _poll_sdl2(self, now: float):
        # Update SDL2 internal controller state
        self._sdl2.SDL_GameControllerUpdate()

        # Periodic rescan for newly connected controllers (~every 2 seconds)
        if now - self._sdl2_last_scan > 2.0:
            self._sdl2_scan_controllers()
            self._sdl2_last_scan = now

        # Poll each open controller
        for idx in list(self._sdl2_controllers.keys()):
            gc = self._sdl2_controllers[idx]

            # Check if still attached
            if not self._sdl2.SDL_GameControllerGetAttached(gc):
                self._sdl2.SDL_GameControllerClose(gc)
                del self._sdl2_controllers[idx]
                if self._prev_connected.get(idx, False):
                    self._prev_connected[idx] = False
                    self._prev_buttons[idx] = 0
                    self.controller_disconnected.emit(idx)
                    logging.info(f"Controller {idx} disconnected (SDL2).")
                continue

            # Handle new connection signal
            if not self._prev_connected.get(idx, False):
                self._prev_connected[idx] = True
                self.controller_connected.emit(idx)
                logging.info(f"Controller {idx} connected (SDL2).")

            # Read buttons → our bitmask
            buttons = 0
            for sdl_btn, our_btn in _SDL2_BTN_MAP.items():
                if self._sdl2.SDL_GameControllerGetButton(gc, sdl_btn):
                    buttons |= our_btn

            # Read triggers (SDL2: 0–32767 → scale to 0–255 for shared logic)
            lt_raw = self._sdl2.SDL_GameControllerGetAxis(gc, _SDL_AXIS_TRIGGERLEFT)
            rt_raw = self._sdl2.SDL_GameControllerGetAxis(gc, _SDL_AXIS_TRIGGERRIGHT)
            lt_value = max(0, lt_raw) * 255 // 32767 if lt_raw > 0 else 0
            rt_value = max(0, rt_raw) * 255 // 32767 if rt_raw > 0 else 0

            # Read left stick Y (SDL2: positive=down → negate for our convention positive=up)
            raw_ly = self._sdl2.SDL_GameControllerGetAxis(gc, _SDL_AXIS_LEFTY)
            stick_ly = -raw_ly

            self._process_controller_state(idx, buttons, lt_value, rt_value, stick_ly, now)

    def _sdl2_scan_controllers(self):
        """Scan for new game controllers and open them (up to 4)."""
        num_joy = self._sdl2.SDL_NumJoysticks()
        slot = 0
        for joy_idx in range(num_joy):
            if slot >= 4:
                break
            # Skip if this slot is already occupied
            if slot in self._sdl2_controllers:
                slot += 1
                continue
            if self._sdl2.SDL_IsGameController(joy_idx):
                gc = self._sdl2.SDL_GameControllerOpen(joy_idx)
                if gc:
                    self._sdl2_controllers[slot] = gc
                    logging.info(f"SDL2: Opened game controller at joystick index {joy_idx} → slot {slot}")
            slot += 1

    # ------------------------------------------------------------------
    # Shared state processing (both backends)
    # ------------------------------------------------------------------

    def _process_controller_state(self, idx: int, buttons: int,
                                   lt_value: int, rt_value: int,
                                   stick_ly: int, now: float):
        """Process a unified controller state and emit appropriate signals.

        Parameters
        ----------
        idx       : Controller index (0–3)
        buttons   : Bitmask of currently pressed buttons (BTN_* constants)
        lt_value  : Left trigger analog value (0–255)
        rt_value  : Right trigger analog value (0–255)
        stick_ly  : Left stick Y axis (−32768…32767, positive = up)
        now       : Current time.monotonic() value
        """
        prev = self._prev_buttons.get(idx, 0)
        
        # Determine all currently pressed physical buttons (for macro checks)
        active_labels = set()
        if buttons & BTN_A:          active_labels.add("A")
        if buttons & BTN_B:          active_labels.add("B")
        if buttons & BTN_X:          active_labels.add("X")
        if buttons & BTN_Y:          active_labels.add("Y")
        if buttons & BTN_START:      active_labels.add("Start")
        if buttons & BTN_BACK:       active_labels.add("View/Select")
        if buttons & BTN_LB:         active_labels.add("LB")
        if buttons & BTN_RB:         active_labels.add("RB")
        if buttons & BTN_DPAD_UP:    active_labels.add("D-Up")
        if buttons & BTN_DPAD_DOWN:  active_labels.add("D-Down")
        if buttons & BTN_DPAD_LEFT:  active_labels.add("D-Left")
        if buttons & BTN_DPAD_RIGHT: active_labels.add("D-Right")
        if lt_value > TRIGGER_THRESHOLD: active_labels.add("LT")
        if rt_value > TRIGGER_THRESHOLD: active_labels.add("RT")
        
        prev_labels = self._prev_active_labels.get(idx, set())
        if active_labels != prev_labels:
            if active_labels:
                self.buttons_state_changed.emit(list(active_labels))
            self._prev_active_labels[idx] = active_labels

        # Rising-edge detection (button just pressed this tick)
        just_pressed = buttons & ~prev

        # ── LT+RT combo: both analog triggers pressed simultaneously ──
        lt_active = lt_value > TRIGGER_THRESHOLD
        rt_active = rt_value > TRIGGER_THRESHOLD
        ltrt_now  = lt_active and rt_active
        prev_l1l2 = self._prev_l1l2.get(idx, False)
        if ltrt_now and not prev_l1l2:
            self.btn_l1l2.emit()
        self._prev_l1l2[idx] = ltrt_now

        # ── Button signals ────────────────────────────────────────────
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

        # ── LT (analog trigger): hold / release for section toggle ────
        #    LT held alone (without RT) → lt_hold (switch to General)
        #    LT released                → lt_release (back to Actions)
        #    LT+RT together             → combo handled above, not here
        lt_alone = lt_active and not rt_active
        prev_lt_alone = self._prev_lt_active.get(idx, False)
        was_holding   = self._lt_holding.get(idx, False)

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

        # ── Thumbstick navigation with initial-delay + repeat ─────────
        for direction, active in (("up", stick_ly > THUMB_DEADZONE),
                                  ("down", stick_ly < -THUMB_DEADZONE)):
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
            logging.info("ControllerManager: No controller backend available, not starting.")
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
        if hasattr(mw, '_ctrl_on_buttons_state_changed'):
            p.buttons_state_changed.connect(mw._ctrl_on_buttons_state_changed)
