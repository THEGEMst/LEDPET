# -*- coding: utf-8 -*-
# =====================================================================
#  LEDPet - global keyboard shortcuts for the face expressions (v18.0)
#  LEDPET_V18_KEYS  (hardened v18.4: LEDPET_V18_FIX)
#  LEDPET_V18_PUMP  (engine rebuilt v18.5)
#  ------------------------------------------------------------------
#  v18.4 stopped and restarted the pump thread on EVERY apply() and
#  shot WM_QUIT at it through its raw thread id. Windows REUSES thread
#  ids, so a stale WM_QUIT could kill a freshly started pump (restart
#  storm -> "Engine: restarting..." forever, no shortcut works), and a
#  lingering old pump could unregister the combos the new pump had
#  just taken. v18.5 rebuilds the engine instead of patching it:
#
#  * ONE persistent pump thread. apply()/suspend()/resume() never kill
#    it - they swap the desired state and poke a Win32 EVENT; the pump
#    re-registers BY ITSELF and only ever unregisters the ids IT owns.
#  * A passive low-level keyboard hook (WH_KEYBOARD_LL) beside the
#    pump. It registers nothing, so a combo that another program owns
#    STILL fires the pet (the hook never consumes keys - the focused
#    program keeps seeing them too). A 0.25 s stamp makes one press
#    fire exactly once even though both paths see it.
#  * Liveness = monotonic heartbeats from both threads (bounded waits,
#    so a fresh beat every few seconds proves the loop spins); the
#    frame-loop watchdog re-applies when a beat goes stale.
#
#  Registers SYSTEM-WIDE hotkeys with user32.RegisterHotKey and pumps
#  their messages in a tiny daemon thread. No new dependencies - only
#  ctypes + the standard library.
#
#  Thread-safety contract: the worker threads NEVER touch Tk. They only
#  push the expression name into a queue.Queue; the pet's frame loop
#  drains that queue (tick_frame) and calls show_expression() on the
#  Tk thread. A broken hotkey can therefore never break the rendering.
#
#  Combo strings look like "Ctrl+Alt+1", "Alt+F5", "Shift+Alt+Num4".
#  Order-independent on parse; normalized to Ctrl+Alt+Shift+Win+Key.
#  A combo without any modifier is only allowed for F1..F24 and
#  Num0..Num9 (swallowing a normal letter/digit system-wide would
#  break typing everywhere).
# =====================================================================
import ast
import ctypes
import json
import queue
import re
import threading
import time
import traceback

# v18.4 (LEDPET_V18_FIX): the app sets this to its _write_log so every
# registration / failure / fired hotkey lands in the user's error.log.
# A hotkey problem that cannot be seen can never be fixed.
_log = None


def _log_line(s):
    try:
        f = _log
        if callable(f):
            f(s)
    except Exception:
        pass

IS_WINDOWS = False
try:
    import sys as _sys
    IS_WINDOWS = (_sys.platform == 'win32')
except Exception:
    pass

# ------------------------------------------------------------------
# combo parsing / validation (pure functions, platform-independent)
# ------------------------------------------------------------------
_MODS = {'CTRL': 0x0002, 'ALT': 0x0001, 'SHIFT': 0x0004, 'WIN': 0x0008}
_MOD_ORDER = ('Ctrl', 'Shift', 'Alt', 'Win')     # canonical display order

# token -> virtual key (tokens are UPPERCASE so parsing is case-insensitive)
# + virtual key -> display token (mixed case, shown in the UI / menu)
_VK = {}
_VK_DISP = {}


def _add_vk(tok, vk, disp=None):
    _VK[tok.upper()] = vk
    _VK_DISP[vk] = disp or tok


for _i in range(10):
    _add_vk(str(_i), 0x30 + _i)                   # main row digits
    _add_vk('Num%d' % _i, 0x60 + _i, 'Num%d' % _i)  # numpad digits
for _ch in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ':
    _add_vk(_ch, ord(_ch))
for _i in range(1, 25):
    _add_vk('F%d' % _i, 0x70 + _i - 1)            # VK_F1 .. VK_F24
_add_vk('Space', 0x20)

# keys that may be registered WITHOUT a modifier
_BARE_OK = set('F%d' % _i for _i in range(1, 25)) | set('NUM%d' % _i for _i in range(10))


def parse_combo(s):
    """'Ctrl+Alt+7' -> (mods, vk) or None if the combo is invalid."""
    if not isinstance(s, str):
        return None
    parts = [p.strip() for p in s.split('+')]
    parts = [p for p in parts if p]
    if not parts:
        return None
    mods = 0
    for p in parts[:-1]:
        m = _MODS.get(p.upper())
        if m is None or mods & m:          # unknown or duplicated modifier
            return None
        mods |= m
    key = parts[-1].upper()
    if key in _MODS:                       # a combo must end with a real key
        return None
    vk = _VK.get(key)
    if vk is None:
        return None
    if mods == 0 and key not in _BARE_OK:
        return None
    return (mods, vk)


def normalize_combo(s):
    """canonical display form, e.g. 'alt+CTRL+7' -> 'Ctrl+Alt+7' (or None)"""
    r = parse_combo(s)
    if r is None:
        return None
    mods, vk = r
    out = []
    for name in _MOD_ORDER:
        bit = _MODS[name.upper()]
        if mods & bit:
            out.append(name)
    out.append(_VK_DISP.get(vk, '?'))
    return '+'.join(out)


def combo_problems(s):
    """list of human-readable problems (empty list = usable combo)"""
    if not isinstance(s, str) or not s.strip():
        return ['empty']
    r = parse_combo(s)
    if r is None:
        parts = [p.strip().upper() for p in s.split('+') if p.strip()]
        if not parts:
            return ['empty']
        if parts[-1] in _MODS:
            return ['must end with a key (not only a modifier)']
        return ['unknown key (use A-Z, 0-9, F1-F24, Num0-Num9, Space)']
    mods, _vk = r
    if mods == 0:
        return []                          # bare F/Num keys are fine
    if not mods & (0x0001 | 0x0002):       # no Alt and no Ctrl
        return ['add Ctrl or Alt (Shift alone would block normal typing)']
    return []


# ------------------------------------------------------------------
# config glue: the cfg stores the map as a JSON string so the existing
# sanitizer (str branch) carries it untouched
# ------------------------------------------------------------------
def load_bindings(cfg):
    """cfg -> {state: 'Ctrl+Alt+1', ...}; drops unknown states/bad combos,
    normalizes everything, resolves duplicates (first state wins)."""
    raw = {}
    try:
        raw = json.loads(cfg.get('hotkeys', '{}'))
    except Exception:
        try:
            raw = ast.literal_eval(str(cfg.get('hotkeys', '{}')))
        except Exception:
            raw = {}
    known = None
    try:
        import ledpet_core
        known = set(ledpet_core.HOTKEY_STATES)
    except Exception:
        pass                                 # standalone use: accept all names
    out = {}
    if isinstance(raw, dict):
        seen = {}
        for state, combo in raw.items():
            if not isinstance(state, str) or (known is not None and state not in known):
                continue
            norm = normalize_combo(combo)
            if norm is None:
                continue
            if norm in seen:
                continue                   # two states on one combo: keep the first
            seen[norm] = state
            out[state] = norm
    return out


def save_bindings(d):
    """{state: combo} -> the JSON string stored in cfg['hotkeys']"""
    return json.dumps(dict(d), ensure_ascii=False)


def keysym_to_key(ks):
    """Tk keysym -> our key token (or None). 'KP_4'->'Num4', 'a'->'A',
    'F5'->'F5', 'space'->'Space'."""
    if not ks:
        return None
    ks = str(ks)
    m = re.match(r'^KP_(\d)$', ks)
    if m:
        return 'Num' + m.group(1)
    if re.match(r'^F([1-9]|1\d|2[0-4])$', ks):
        return ks
    if ks == 'space':
        return 'Space'
    if len(ks) == 1 and ks.isdigit():
        return ks
    if len(ks) == 1 and ks.isalpha() and ks.isascii():
        return ks.upper()
    return None


# ------------------------------------------------------------------
# the engine (v18.5, LEDPET_V18_PUMP)
# ------------------------------------------------------------------
_HK_BASE = 0xB000                       # hotkey ids (unique per thread)
_WM_HOTKEY = 0x0312
_WM_KEYDOWN = 0x0100
_WM_SYSKEYDOWN = 0x0104
_WH_KEYBOARD_LL = 13                    # low-level keyboard hook id
_MWMO_INPUTAVAILABLE = 0x0004
_QS_ALLINPUT = 0x04FF
_WAIT_TIMEOUT = 0x00000102
_WAIT_FAILED = 0xFFFFFFFF
_PM_REMOVE = 0x0001
_VK_CTRL, _VK_SHIFT, _VK_ALT = 0x11, 0x10, 0x12
_VK_LWIN, _VK_RWIN = 0x5B, 0x5C

# virtual-key -> key token for the hook path (subset that combos use)
_HOOK_VKTOK = {}
for _i in range(10):
    _HOOK_VKTOK[0x30 + _i] = str(_i)              # main row digits
    _HOOK_VKTOK[0x60 + _i] = 'Num%d' % _i         # numpad digits
for _i in range(24):
    _HOOK_VKTOK[0x70 + _i] = 'F%d' % (_i + 1)     # VK_F1 .. VK_F24
_HOOK_VKTOK[0x20] = 'Space'
for _i, _ch in enumerate('ABCDEFGHIJKLMNOPQRSTUVWXYZ'):
    _HOOK_VKTOK[0x41 + _i] = _ch

_HOOKPROC_T = None                      # WINFUNCTYPE, built on Windows only


class _KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [('vkCode', ctypes.c_ulong),
                ('scanCode', ctypes.c_ulong),
                ('flags', ctypes.c_ulong),
                ('time', ctypes.c_ulong),
                ('dwExtraInfo', ctypes.c_size_t)]


class HotkeyEngine(object):
    """v18.5 (LEDPET_V18_PUMP): ONE persistent RegisterHotKey pump plus
    ONE passive low-level hook. Public API is unchanged from v18.0:
    .q, .status, apply/suspend/resume/stop/engine_alive.

    apply()/suspend()/resume() NEVER kill a thread. They swap the
    desired state under the lock and poke a Win32 EVENT; the pump reads
    the desired state and re-registers BY ITSELF - it unregisters only
    the ids it owns, synchronously, before registering new ones. That
    removes the two v18.4 failure modes for good: a stale WM_QUIT
    killing a freshly started pump (Windows reuses thread ids) and a
    lingering old pump unregistering the NEW pump's hotkeys."""

    def __init__(self):
        self.q = queue.Queue()
        self.status = {}                # state -> 'ok' | 'hook' | 'taken'
        self._bindings = {}
        self._enabled = False
        self._lock = threading.Lock()
        self._tlock = threading.Lock()  # threads + event handles
        self._thread = None             # the persistent hotkey pump
        self._hook_thread = None        # the persistent LL hook
        self._thread_id = 0
        self._ids = {}                  # hid -> state (pump thread only)
        self._ids_combo = {}            # hid -> (mods, vk) (pump only)
        self._ev_change = None
        self._ev_exit = None
        self._beat = 0.0                # monotonic heartbeats (liveness)
        self._hook_beat = 0.0
        self._hook = None               # HHOOK (hook thread only)
        self._hook_proc = None          # keep-alive for the callback
        self._hook_ok = False           # hook installed and usable
        self._want_hook = False         # hook wanted since first enable
        self._hook_watch = {}           # (mods, vk) -> state (atomic swap)
        self._hook_vkset = frozenset()
        self._hook_fired = {}           # (mods, vk) -> monotonic stamp
        self._last_hook_err = 0.0

    # ---- public API (called from the Tk thread) ----
    def apply(self, bindings, enabled):
        """bindings: {state: combo}; sets .status = {state: 'ok'|'hook'|
        'taken'}. v18.5: NEVER restarts a thread - swaps the desired
        state and pokes the pump through an event."""
        clean = {}
        if isinstance(bindings, dict):
            for st, combo in bindings.items():
                if isinstance(st, str) and parse_combo(combo) is not None:
                    clean[st] = normalize_combo(combo)
        watch = {}
        vkset = set()
        for st, combo in clean.items():
            r = parse_combo(combo)
            if r is not None:
                mods, vk = r
                watch[(mods, vk)] = st
                vkset.add(vk)
        with self._lock:
            self._bindings = clean
            self._enabled = bool(enabled)
            self._hook_watch = watch
            self._hook_vkset = frozenset(vkset)
        self.status = dict.fromkeys(clean, 'ok')
        if IS_WINDOWS and enabled and clean:
            self._wake()
        else:
            self._poke()                # pump unregisters on the next cycle
        return self.status

    def suspend(self):
        """temporarily unregister everything (e.g. while the settings
        recorder captures the next key press). The threads STAY alive -
        no stop/start churn anymore (that churn was the v18.4 bug)."""
        with self._lock:
            self._enabled = False
        self._poke()

    def resume(self):
        with self._lock:
            self._enabled = True
        if IS_WINDOWS:
            self._wake()

    def stop(self):
        """final teardown (app exit): signal both threads and join."""
        with self._lock:
            self._enabled = False
        if not IS_WINDOWS:
            return
        with self._tlock:
            self._set_event(self._ev_exit)
            t, ht = self._thread, self._hook_thread
            self._thread = None
            self._hook_thread = None
            self._hook_ok = False
            evc, evx = self._ev_change, self._ev_exit
            self._ev_change = None
            self._ev_exit = None
        for th in (t, ht):
            if th is not None:
                try:
                    th.join(1.5)
                except Exception:
                    pass
        for ev in (evc, evx):
            if ev:
                try:
                    ctypes.windll.kernel32.CloseHandle(ev)
                except Exception:
                    pass

    def engine_alive(self):
        """v18.5: True when the workers this engine actually needs are
        alive AND their heartbeats are fresh; True when there is nothing
        to pump (never a false alarm). The frame-loop watchdog uses this
        to auto-revive a dead worker."""
        if not IS_WINDOWS:
            return True
        with self._lock:
            if not self._enabled or not self._bindings:
                return True
            need_hook = self._want_hook
        t = self._thread
        try:
            if t is None or not t.is_alive():
                return False
            if time.monotonic() - self._beat > 25.0:
                return False
            if need_hook:
                ht = self._hook_thread
                if ht is None or not ht.is_alive():
                    return False
                if time.monotonic() - self._hook_beat > 25.0:
                    return False
        except Exception:
            return True
        return True

    # ---- internals: control events + worker lifecycle ----
    def _ensure_events(self):
        """create the two control events once (Windows only)"""
        with self._tlock:
            if self._ev_exit is None or self._ev_change is None:
                k32 = ctypes.windll.kernel32
                k32.CreateEventW.restype = ctypes.c_void_p
                if self._ev_exit is None:
                    self._ev_exit = k32.CreateEventW(None, 1, 0, None)
                if self._ev_change is None:
                    self._ev_change = k32.CreateEventW(None, 1, 0, None)

    def _set_event(self, ev):
        try:
            if ev:
                k32 = ctypes.windll.kernel32
                k32.SetEvent.argtypes = [ctypes.c_void_p]
                k32.SetEvent(ev)
        except Exception:
            pass

    def _exit_set(self):
        """True when the exit event is signalled (shutdown)"""
        ev = self._ev_exit
        if not ev:
            return False
        try:
            k32 = ctypes.windll.kernel32
            k32.WaitForSingleObject.argtypes = [ctypes.c_void_p,
                                                ctypes.c_uint]
            k32.WaitForSingleObject.restype = ctypes.c_uint
            return k32.WaitForSingleObject(ev, 0) == 0
        except Exception:
            return False

    def _poke(self):
        """ask the pump to re-read the desired state (safe anytime)"""
        if not IS_WINDOWS:
            return
        with self._tlock:
            ev = self._ev_change
        if ev is not None:
            self._set_event(ev)

    def _wake(self):
        """make sure both workers exist and know the state changed.
        Idempotent and churn-free: an alive worker is NEVER restarted."""
        if not IS_WINDOWS:
            return
        self._ensure_events()
        with self._tlock:
            self._want_hook = True
            t, ht = self._thread, self._hook_thread
            try:
                t_alive = t is not None and t.is_alive()
                ht_alive = ht is not None and ht.is_alive()
            except Exception:
                t_alive = ht_alive = True
            now = time.monotonic()
            if not t_alive:
                t = threading.Thread(target=self._pump,
                                     name='LEDPet-hotkeys', daemon=True)
                self._thread = t
                self._beat = now
            if not ht_alive:
                ht = threading.Thread(target=self._hook_loop,
                                      name='LEDPet-hotkeys-hook',
                                      daemon=True)
                self._hook_thread = ht
                self._hook_beat = now
            ev = self._ev_change
        if not t_alive:
            t.start()
        if not ht_alive:
            ht.start()
        self._set_event(ev)

    # ---- the RegisterHotKey pump thread (Windows only) ----
    def _pump(self):
        # v18.4: a crash inside the pump used to kill the thread SILENTLY
        # (the registrations die with it -> "no shortcut works"). The
        # wrapper logs it; v18.5's persistent thread + watchdog keeps a
        # crash from ever being silent OR permanent.
        try:
            self._pump_body()
        except Exception:
            _log_line('hotkeys: pump crashed\n' + traceback.format_exc())

    def _register_set(self, user32, bindings):
        """register every combo on this thread; returns (ids, status)
        (same contract as v18.4 - the tests drive it with a fake user32)"""
        ids = {}
        st_used = {}
        for i, (st, combo) in enumerate(sorted(bindings.items())):
            hid = _HK_BASE + i
            mods, vk = parse_combo(combo)
            if user32.RegisterHotKey(None, hid, mods, vk):
                ids[hid] = st
                st_used[st] = 'ok'
            else:
                st_used[st] = 'taken'      # another program owns this combo
        return ids, st_used

    def _register_cycle(self, user32):
        """runs ON THE PUMP THREAD ONLY: unregister what THIS thread
        owns, then register the current desired set. Self-owned,
        synchronous unregistration can never rip out another worker's
        hotkeys (the v18.4 cross-thread bug)."""
        for hid in list(self._ids):
            try:
                user32.UnregisterHotKey(None, hid)
            except Exception:
                pass
        self._ids = {}
        self._ids_combo = {}
        with self._lock:
            enabled = self._enabled
            bindings = dict(self._bindings)
        if not enabled or not bindings:
            self.status = {}
            return
        ids, st_used = self._register_set(user32, bindings)
        combo_of = {}
        for hid, st in ids.items():
            combo = bindings.get(st)
            r = parse_combo(combo) if combo else None
            if r is not None:
                combo_of[hid] = r          # hid -> (mods, vk), owned ids only
        n_ok = sum(1 for v in st_used.values() if v == 'ok')
        _log_line('hotkeys: registered %d, taken %d' % (n_ok,
                                                        len(st_used) - n_ok))
        if n_ok == 0 and bindings:
            # EVERY combo taken is almost always our own leftover: a
            # previous LEDPet process still owns them. Wait a moment and
            # try once more - in THIS thread, without restarting anything.
            _log_line('hotkeys: every combo is taken -> retrying once '
                      'in 2 s (is another LEDPet still running?)')
            end = time.monotonic() + 2.0
            while time.monotonic() < end:
                if self._exit_set():
                    break
                time.sleep(0.1)
                self._beat = time.monotonic()
            with self._lock:
                enabled = self._enabled
                bindings = dict(self._bindings)
            if enabled and bindings:
                for hid in ids:
                    try:
                        user32.UnregisterHotKey(None, hid)
                    except Exception:
                        pass
                ids, st_used = self._register_set(user32, bindings)
                n_ok = sum(1 for v in st_used.values() if v == 'ok')
                _log_line('hotkeys: retry registered %d, taken %d'
                          % (n_ok, len(st_used) - n_ok))
        if self._hook_ok:
            for st in [s for s, v in st_used.items() if v == 'taken']:
                st_used[st] = 'hook'       # the LL hook fires these anyway
        self.status = st_used
        self._ids = ids
        self._ids_combo = combo_of

    def _pump_body(self):
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int,
                                          wintypes.UINT, wintypes.UINT]
        user32.RegisterHotKey.restype = wintypes.BOOL
        user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.UnregisterHotKey.restype = wintypes.BOOL
        user32.PeekMessageW.argtypes = [wintypes.LPMSG, wintypes.HWND,
                                        wintypes.UINT, wintypes.UINT,
                                        wintypes.UINT]
        user32.PeekMessageW.restype = wintypes.BOOL
        user32.MsgWaitForMultipleObjectsEx.argtypes = [
            wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE), wintypes.DWORD,
            wintypes.DWORD, wintypes.DWORD]
        user32.MsgWaitForMultipleObjectsEx.restype = wintypes.DWORD
        kernel32.ResetEvent.argtypes = [ctypes.c_void_p]
        self._thread_id = kernel32.GetCurrentThreadId()
        self._ensure_events()

        msg = wintypes.MSG()
        LP = ctypes.byref(msg)
        last_fire_log = 0.0
        while not self._exit_set():
            with self._tlock:
                evx, evc = self._ev_exit, self._ev_change
            if evx is None or evc is None:
                time.sleep(0.2)
                self._beat = time.monotonic()
                continue
            handles = (wintypes.HANDLE * 2)(evx, evc)
            r = user32.MsgWaitForMultipleObjectsEx(
                2, handles, 4000, _QS_ALLINPUT, _MWMO_INPUTAVAILABLE)
            self._beat = time.monotonic()
            if r == 0:                     # ev_exit -> shutdown
                break
            if r == _WAIT_FAILED:
                time.sleep(0.2)
                continue
            if r == 1:                     # ev_change -> reconfigure
                try:
                    kernel32.ResetEvent(evc)
                except Exception:
                    pass
                self._register_cycle(user32)
                continue
            if r == 2 or r == _WAIT_TIMEOUT:   # input (or 4 s heartbeat)
                while user32.PeekMessageW(LP, None, 0, 0, _PM_REMOVE):
                    if msg.message == _WM_HOTKEY:
                        hid = int(msg.wParam)
                        st = self._ids.get(hid)
                        if st is not None:
                            with self._lock:
                                on = self._enabled
                            if on:
                                key = self._ids_combo.get(hid)
                                if not self._rh_suppressed(key):
                                    # the hook did not already fire it
                                    if time.monotonic() - last_fire_log > 10.0:
                                        last_fire_log = time.monotonic()
                                        _log_line('hotkey fired: ' + st)
                                    self.q.put(st)
        # unregister everything this thread owns, then exit quietly
        for hid in list(self._ids):
            try:
                user32.UnregisterHotKey(None, hid)
            except Exception:
                pass
        self._ids = {}
        self._ids_combo = {}
        _log_line('hotkeys: pump stopped')

    # ---- the passive low-level hook thread (Windows only) ----
    def _hook_loop(self):
        """WH_KEYBOARD_LL observer. It CONSUMES nothing - it watches the
        enabled combos and fires them into .q even when RegisterHotKey
        could not own them (another program has the combo) or while the
        pump is between registrations."""
        global _HOOKPROC_T
        from ctypes import wintypes
        try:
            if _HOOKPROC_T is None:
                _HOOKPROC_T = ctypes.WINFUNCTYPE(
                    ctypes.c_ssize_t, ctypes.c_int,
                    wintypes.WPARAM, wintypes.LPARAM)
        except Exception:
            _log_line('hotkeys: hook callbacks unavailable on this OS')
            return
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        user32.SetWindowsHookExW.argtypes = [ctypes.c_int, _HOOKPROC_T,
                                             wintypes.HMODULE,
                                             wintypes.DWORD]
        user32.SetWindowsHookExW.restype = wintypes.HANDLE
        user32.UnhookWindowsHookEx.argtypes = [wintypes.HANDLE]
        user32.CallNextHookEx.argtypes = [wintypes.HHOOK, ctypes.c_int,
                                          wintypes.WPARAM, wintypes.LPARAM]
        user32.CallNextHookEx.restype = ctypes.c_ssize_t
        user32.PeekMessageW.argtypes = [wintypes.LPMSG, wintypes.HWND,
                                        wintypes.UINT, wintypes.UINT,
                                        wintypes.UINT]
        user32.PeekMessageW.restype = wintypes.BOOL
        user32.MsgWaitForMultipleObjectsEx.argtypes = [
            wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE), wintypes.DWORD,
            wintypes.DWORD, wintypes.DWORD]
        user32.MsgWaitForMultipleObjectsEx.restype = wintypes.DWORD
        kernel32.GetModuleHandleW.restype = wintypes.HMODULE
        try:
            self._hook_proc = _HOOKPROC_T(self._hook_cb)
        except Exception:
            _log_line('hotkeys: hook callback setup failed\n'
                      + traceback.format_exc())
            return
        mod = kernel32.GetModuleHandleW(None)
        self._hook_install(user32, kernel32, mod)

        msg = wintypes.MSG()
        LP = ctypes.byref(msg)
        while not self._exit_set():
            evx = self._ev_exit
            if evx is None:
                time.sleep(0.2)
                self._hook_beat = time.monotonic()
                continue
            try:
                arr = (wintypes.HANDLE * 1)(evx)
                r = user32.MsgWaitForMultipleObjectsEx(
                    1, arr, 2000, _QS_ALLINPUT, _MWMO_INPUTAVAILABLE)
            except Exception:
                time.sleep(0.5)
                self._hook_beat = time.monotonic()
                continue
            self._hook_beat = time.monotonic()
            if r == 0:                     # ev_exit -> shutdown
                break
            if r == _WAIT_FAILED:
                time.sleep(0.5)
                continue
            # input available: pump messages - this is what lets the LL
            # hook callbacks actually run
            try:
                while user32.PeekMessageW(LP, None, 0, 0, _PM_REMOVE):
                    pass
            except Exception:
                pass
            if self._hook is None:
                self._hook_install(user32, kernel32, mod)
        # teardown
        if self._hook is not None:
            try:
                user32.UnhookWindowsHookEx(self._hook)
            except Exception:
                pass
            self._hook = None
        self._hook_ok = False
        _log_line('hotkeys: fallback hook stopped')

    def _hook_install(self, user32, kernel32, mod):
        try:
            h = user32.SetWindowsHookExW(_WH_KEYBOARD_LL, self._hook_proc,
                                         mod, 0)
            if h:
                self._hook = h
                self._hook_ok = True
                _log_line('hotkeys: fallback hook installed')
                return True
            self._hook_ok = False
            now = time.monotonic()
            if now - self._last_hook_err > 60.0:
                self._last_hook_err = now
                _log_line('hotkeys: fallback hook FAILED (err %d)'
                          % kernel32.GetLastError())
        except Exception:
            self._hook_ok = False
            now = time.monotonic()
            if now - self._last_hook_err > 60.0:
                self._last_hook_err = now
                _log_line('hotkeys: fallback hook error\n'
                          + traceback.format_exc())
        return False

    def _mods_now(self):
        """the modifier flags pressed RIGHT NOW (same bits as _MODS)"""
        try:
            u = ctypes.windll.user32
            down = 0x8000
            bits = 0
            if u.GetAsyncKeyState(_VK_CTRL) & down:
                bits |= 0x0002
            if u.GetAsyncKeyState(_VK_ALT) & down:
                bits |= 0x0001
            if u.GetAsyncKeyState(_VK_SHIFT) & down:
                bits |= 0x0004
            if (u.GetAsyncKeyState(_VK_LWIN)
                    | u.GetAsyncKeyState(_VK_RWIN)) & down:
                bits |= 0x0008
            return bits
        except Exception:
            return -1                     # unknown -> never match

    def _hook_match(self, vk, mods):
        """pure decision: which state does this (mods, vk) fire (or None)
        - unit-testable without a real keyboard"""
        if mods is None or mods < 0 or not self._enabled:
            return None
        return self._hook_watch.get((mods, vk))

    def _rh_suppressed(self, key):
        """True when the hook already fired this (mods, vk) a moment ago
        - keeps one physical press from firing twice (hook path first,
        WM_HOTKEY second)"""
        try:
            if key is None:
                return False
            return time.monotonic() - self._hook_fired.get(key, 0.0) <= 0.25
        except Exception:
            return False

    def _hook_cb(self, code, wp, lp):
        """WH_KEYBOARD_LL callback - runs for EVERY keystroke on the
        system, so the hot path must be tiny and it must NEVER raise
        (an exception here could lag the whole machine's keyboard)."""
        try:
            if code == 0 and (wp == _WM_KEYDOWN or wp == _WM_SYSKEYDOWN):
                ks = ctypes.cast(lp, ctypes.POINTER(_KBDLLHOOKSTRUCT)
                                 ).contents
                vk = int(ks.vkCode)
                if vk in self._hook_vkset and self._enabled:
                    mods = self._mods_now()
                    st = self._hook_match(vk, mods)
                    if st is not None:
                        now = time.monotonic()
                        # prune old stamps (tiny dict), then stamp
                        for k in [k for k, t in self._hook_fired.items()
                                  if now - t > 2.0]:
                            self._hook_fired.pop(k, None)
                        self._hook_fired[(mods, vk)] = now
                        _log_line('hotkey fired: ' + st)
                        self.q.put(st)
        except Exception:
            pass
        try:
            return ctypes.windll.user32.CallNextHookEx(None, code, wp, lp)
        except Exception:
            return 0
