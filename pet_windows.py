#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# =====================================================================
#  LEDPet - desktop pet with a round LED display + dot-matrix clock  (v4)
#     - 41x41 LED matrix on a round glass + reflection + beat-pulsing ring
#     - 48..160 halo rays fed by a 32-band spectrum of system audio + peak caps + sparks
#     - beat detection: ring pulse, sparks jump, ripples across the LED matrix
#     - eyes follow the mouse across the whole screen; optional body chase
#     - faces: idle/happy/wink/surprised/dance/dizzy/sleep/love + more
#     - color: solid / rainbow / gradient / bass-reactive + 7 ready themes
#     - full settings panel (right-click -> Advanced settings)
#  ------------------------------------------------------------------
#  Full audio source separation (since v11):
#     - system output (loopback)  -> only the equalizer ring + dancing
#     - microphone               -> only the mouth (lip-sync + reactions)
#     - while the system plays sound the mouth stays calm (speaker bleed
#       can never move the mouth); your voice -> the mouth
#  Audio: native Windows WASAPI engine (pure ctypes - nothing to install);
#       SoundCard is only an optional backup
#  =====================================================================

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

IS_WINDOWS = (os.name == 'nt')
CHROMA = '#FF00FF'
CFG_DIR = os.path.join(os.environ.get('APPDATA', os.path.expanduser('~')), 'LEDPet')
CFG_FILE = os.path.join(CFG_DIR, 'config.json')
LOG_FILE = os.path.join(CFG_DIR, 'error.log')
_APP_DIR = os.path.dirname(os.path.abspath(__file__))

# --- pythonw: no stdout -> redirect to a file so errors are not lost ---
if IS_WINDOWS and (sys.stdout is None or sys.stderr is None):
    try:
        _f = open(os.path.join(_APP_DIR, 'pet_log.txt'), 'a',
                  encoding='utf-8', buffering=1)
        if sys.stdout is None:
            sys.stdout = _f
        if sys.stderr is None:
            sys.stderr = _f
    except Exception:
        pass


def _write_log(text):
    """append errors to APPDATA\\LEDPet\\error.log for debugging"""
    try:
        os.makedirs(CFG_DIR, exist_ok=True)
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            f.write('[%s] %s\n' % (time.strftime('%Y-%m-%d %H:%M:%S'),
                                    text.rstrip()))
    except Exception:
        pass


def _fatal(title, msg):
    """startup error: log + a visual message (works even without Pillow)"""
    import traceback
    _write_log('=== %s ===\n%s' % (title, traceback.format_exc()))
    try:
        import tkinter as _tk
        import tkinter.messagebox as mb
        _r = _tk.Tk()
        _r.withdraw()
        mb.showerror(title, msg)
        _r.destroy()
    except Exception:
        pass


try:
    import tkinter as tk
except Exception:
    _fatal('LEDPet', 'Python/Tkinter is not available!\n'
                     'Please install the full Python from python.org\n'
                     '(keep "tcl/tk and IDLE" ticked during setup).')
    raise SystemExit(1)

try:
    from PIL import Image, ImageDraw
    import numpy as np
    import ledpet_core as C
    from ledpet_render import Renderer
except Exception as _e:
    _fatal('LEDPet - missing libraries',
           'Pillow / numpy are not available.\n\n'
           'Fix: run run.bat (it installs them automatically),\n'
           'or type this in CMD:\n'
           '    pip install pillow numpy SoundCard\n\n'
           'Error details: %s' % repr(_e))
    raise SystemExit(1)

import json
import math
import random
import threading
import datetime

# v18.0: global expression shortcuts (LEDPET_V18_KEYS) - pure stdlib,
# imports fine on every platform (the Win32 pump only runs on Windows)
import hotkeys_win as hk
import atexit

SIZES = [('Small', 0.55), ('Medium', 0.80), ('Large', 1.00), ('Extra large', 1.30)]


def clamp(v, a, b):
    return a if v < a else (b if v > b else v)


# ---------------- v1.0 morph (LEDPET_V1_MORPH) helpers ------------------
# The first-run naming frame must not POP into the pet + home: the little
# frame GROWS into the home frame and the happy dot GROWS into the pet.
# These are the tiny math/compositing helpers for that animation.

def _ease_out_cubic(p):
    """0..1 -> 0..1, fast start, soft landing"""
    p = clamp(float(p), 0.0, 1.0)
    q = 1.0 - p
    return 1.0 - q * q * q


def _ease_out_back(p):
    """0..1 -> 0..~1.1 -> 1: a springy overshoot (the little 'pop' of a
    happy pet coming alive)"""
    p = clamp(float(p), 0.0, 1.0)
    c1, c3 = 1.70158, 2.70158
    q = p - 1.0
    return 1.0 + c3 * q * q * q + c1 * q * q


def _pm_lut(k):
    """LUT that scales a PREMULTIPLIED RGBA frame by k (all four channels -
    scaling rgb and a together keeps the premultiplication exact).  Pillow
    wants 256 entries PER BAND for a 4-band image -> 1024 entries."""
    k = clamp(float(k), 0.0, 1.0)
    b = [max(0, min(255, int(v * k + 0.5))) for v in range(256)]
    return b * 4


def _pm_over(top, bot):
    """premultiplied-alpha OVER operator: out = top + bot * (1 - a_top).
    Both inputs (and the result) are PIL RGBA images whose bytes are
    premultiplied - exactly what every renderer here produces (the 'RGBa'
    band idiom) and what UpdateLayeredWindow expects."""
    if np is not None:
        try:
            a = np.asarray(top, dtype=np.uint16)
            b = np.asarray(bot, dtype=np.uint16)
            al = a[..., 3:4]
            out = a + ((b * (255 - al)) // 255)
            return Image.fromarray(out.astype(np.uint8), 'RGBA')
        except Exception:
            pass
    # PIL-only fallback: un-premultiply, alpha_composite, re-premultiply
    ta = Image.frombytes('RGBa', top.size, top.tobytes()).convert('RGBA')
    ba = Image.frombytes('RGBa', bot.size, bot.tobytes()).convert('RGBA')
    out = Image.alpha_composite(ba, ta)
    return Image.frombytes('RGBA', out.size, out.convert('RGBa').tobytes())


def load_cfg():
    try:
        with open(CFG_FILE, 'r', encoding='utf-8') as f:
            return C.sanitize_cfg(json.load(f))
    except Exception:
        return C.sanitize_cfg({})


def load_raw_cfg():
    """v1.1 (LEDPET_V1_QUARANTINE): config.json AS IT IS on disk (no
    sanitize) - the quarantine compares it with the sanitized result to
    know whether this first load changed anything worth persisting."""
    try:
        with open(CFG_FILE, 'r', encoding='utf-8') as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def save_cfg(cfg):
    try:
        os.makedirs(CFG_DIR, exist_ok=True)
        with open(CFG_FILE, 'w', encoding='utf-8') as f:
            json.dump(cfg, f, ensure_ascii=False)
    except Exception:
        pass


# ----------------------- styles (shareable looks) -----------------------
# A style file is a small JSON document with the LOOK half of a config.
# They live in %APPDATA%\LEDPet\Styles; any .json files inside a Styles
# folder next to the app files are pulled in once automatically, so a
# zipped collection can simply be dropped there.

def styles_dir():
    """the shared Styles folder (created on demand)"""
    d = os.path.join(CFG_DIR, 'Styles')
    try:
        os.makedirs(d, exist_ok=True)
    except Exception:
        pass
    return d


def read_style(path):
    """parse + validate a style file -> {'name', 'settings'} or None.
    Every value goes through the config sanitizer, so a broken or
    hostile file can only ever produce valid settings."""
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return None
        s = data.get('settings')
        if not isinstance(s, dict):
            s = data                       # a raw settings dict is accepted too
        clean = {}
        for k in C.STYLE_KEYS:
            if k in s:
                clean[k] = s[k]
        if not clean:
            return None
        full = C.sanitize_cfg(clean)
        clean = dict((k, full[k]) for k in C.STYLE_KEYS)
        nm = str(data.get('name') or '') if isinstance(data.get('name'), str) else ''
        if not nm:
            nm = os.path.splitext(os.path.basename(path))[0]
        return {'name': nm, 'settings': clean}
    except Exception:
        return None


def list_styles():
    """[(title, path)] of every valid style, sorted by name"""
    d = styles_dir()
    try:                                   # seed from a folder next to the app
        near = os.path.join(_APP_DIR, 'Styles')
        if os.path.isdir(near):
            for fn in os.listdir(near):
                if fn.lower().endswith('.json'):
                    dst = os.path.join(d, fn)
                    if not os.path.exists(dst):
                        try:
                            import shutil
                            shutil.copyfile(os.path.join(near, fn), dst)
                        except Exception:
                            pass
    except Exception:
        pass
    out = []
    try:
        for fn in sorted(os.listdir(d)):
            if not fn.lower().endswith('.json'):
                continue
            p = os.path.join(d, fn)
            st = read_style(p)
            if st:
                out.append((st['name'], p))
    except Exception:
        pass
    out.sort(key=lambda t: t[0].lower())
    return out


def export_style_file(cfg, title):
    """save the current look as a new style file -> path (or None)"""
    title = str(title or '').strip() or 'My style'
    base = ''.join(ch if (ch.isalnum() or ch in ' -_') else '_'
                   for ch in title).strip() or 'style'
    d = styles_dir()
    path = os.path.join(d, base + '.json')
    n = 2
    while os.path.exists(path):
        path = os.path.join(d, '%s (%d).json' % (base, n))
        n += 1
    data = {'app': 'LEDPet', 'kind': 'style', 'version': 1, 'name': title,
            'saved': time.strftime('%Y-%m-%d'),
            'settings': dict((k, cfg.get(k, C.DEFAULTS.get(k)))
                             for k in C.STYLE_KEYS)}
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        return path
    except Exception:
        return None


def import_style_file(src):
    """copy a style file from anywhere into the Styles folder -> path"""
    st = read_style(src)
    if not st:
        return None
    base = ''.join(ch if (ch.isalnum() or ch in ' -_') else '_'
                   for ch in st['name']).strip() or 'style'
    dst = os.path.join(styles_dir(), base + '.json')
    n = 2
    while os.path.exists(dst):
        dst = os.path.join(styles_dir(), '%s (%d).json' % (base, n))
        n += 1
    try:
        import shutil
        shutil.copyfile(src, dst)
        return dst
    except Exception:
        return None


def delete_style(path):
    """remove a style file (only inside the Styles folder)"""
    try:
        d = os.path.abspath(styles_dir())
        p = os.path.abspath(path)
        if p.startswith(d) and os.path.isfile(p):
            os.remove(p)
            return True
    except Exception:
        pass
    return False


def _patch_numpy_fromstring(np_):
    """old SoundCard + numpy 2 breaks fromstring; patch it here"""
    try:
        orig = np_.fromstring

        def fs(string, dtype=float, count=-1, sep='', *a, **k):
            if sep == '':
                return np_.frombuffer(string, dtype=dtype, count=count).copy()
            return orig(string, dtype=dtype, count=count, sep=sep, *a, **k)
        np_.fromstring = fs
    except Exception:
        pass


class _RetryNative(Exception):
    """internal (audio/mic workers): the SoundCard backup is not delivering
    -> return to the outer loop and give the native WASAPI engine (which
    has the smart device selection) another chance"""
    pass


# ===================== Windows display layer (Win32) ======================
if IS_WINDOWS:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32

    GWL_EXSTYLE = -20
    WS_EX_LAYERED = 0x00080000
    WS_EX_TOOLWINDOW = 0x00000080
    WS_EX_TOPMOST = 0x00000008
    ULW_ALPHA = 2
    AC_SRC_OVER = 0
    AC_SRC_ALPHA = 1
    SRCCOPY = 0x00CC0020

    class BLENDFUNCTION(ctypes.Structure):
        _fields_ = [('BlendOp', ctypes.c_ubyte), ('BlendFlags', ctypes.c_ubyte),
                    ('SourceConstantAlpha', ctypes.c_ubyte), ('AlphaFormat', ctypes.c_ubyte)]

    class POINT(ctypes.Structure):
        _fields_ = [('x', ctypes.c_long), ('y', ctypes.c_long)]

    class SIZE(ctypes.Structure):
        _fields_ = [('cx', ctypes.c_long), ('cy', ctypes.c_long)]

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [('biSize', wintypes.DWORD), ('biWidth', wintypes.LONG),
                    ('biHeight', wintypes.LONG), ('biPlanes', wintypes.WORD),
                    ('biBitCount', wintypes.WORD), ('biCompression', wintypes.DWORD),
                    ('biSizeImage', wintypes.DWORD), ('biXPelsPerMeter', wintypes.LONG),
                    ('biYPelsPerMeter', wintypes.LONG), ('biClrUsed', wintypes.DWORD),
                    ('biClrImportant', wintypes.DWORD)]

    class BITMAPINFO(ctypes.Structure):
        _fields_ = [('bmiHeader', BITMAPINFOHEADER)]

    user32.UpdateLayeredWindow.argtypes = [
        wintypes.HWND, wintypes.HDC, ctypes.POINTER(POINT),
        ctypes.POINTER(SIZE), wintypes.HDC, ctypes.POINTER(POINT),
        wintypes.COLORREF, ctypes.POINTER(BLENDFUNCTION), wintypes.DWORD]
    user32.GetParent.restype = wintypes.HWND
    user32.GetParent.argtypes = [wintypes.HWND]
    user32.IsWindow.restype = wintypes.BOOL
    user32.IsWindow.argtypes = [wintypes.HWND]
    user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND,
                                    ctypes.c_int, ctypes.c_int,
                                    ctypes.c_int, ctypes.c_int, wintypes.UINT]
    user32.SetWindowPos.restype = wintypes.BOOL
    user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
    user32.GetAsyncKeyState.restype = ctypes.c_short

    _SWP_TOPMOST_FLAGS = 0x0001 | 0x0002 | 0x0010     # NOSIZE | NOMOVE | NOACTIVATE

    def _win_set_topmost(hwnd, on):
        """force the TOPMOST band on/off straight through Win32.
        Tk's attributes('-topmost') alone is not always reliable for
        layered windows drawn with UpdateLayeredWindow."""
        try:
            return bool(user32.SetWindowPos(
                hwnd, wintypes.HWND(-1 if on else -2), 0, 0, 0, 0,
                _SWP_TOPMOST_FLAGS))
        except Exception:
            return False

    def _exstyle(hwnd):
        try:
            return user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
        except AttributeError:
            return user32.GetWindowLongW(hwnd, GWL_EXSTYLE)

    def _set_exstyle(hwnd, ex):
        try:
            user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, ex)
        except AttributeError:
            user32.SetWindowLongW(hwnd, GWL_EXSTYLE, ex)

    def to_bgra(img):
        """renderer premultiplied RGBA -> BGRA byte order (NO second premult!)"""
        r, g, b, a = img.split()
        return Image.merge('RGBA', (b, g, r, a)).tobytes()

    class Win32Layer:
        """layered window: every PIL frame goes straight to the screen with real alpha"""

        def __init__(self, hwnd, w, h):
            self.hwnd, self.w, self.h = hwnd, w, h
            # if THIS window ever carried a Tk '-transparentcolor' (a
            # SetLayeredWindowAttributes color key - the Tk chroma fallback
            # sets it on the pet root), UpdateLayeredWindow fails silently
            # until the layering style is TOGGLED.  Clear the bit first,
            # then set it fresh - a no-op for brand new windows, and it
            # lets a Tk->Win32 switch actually take over.
            try:
                _set_exstyle(hwnd, _exstyle(hwnd) & ~WS_EX_LAYERED)
            except Exception:
                pass
            _set_exstyle(hwnd, _exstyle(hwnd) | WS_EX_LAYERED | WS_EX_TOOLWINDOW)
            self.hdc = user32.GetDC(0)
            self.mem = gdi32.CreateCompatibleDC(self.hdc)
            self.bmp = gdi32.CreateCompatibleBitmap(self.hdc, w, h)
            self.old = gdi32.SelectObject(self.mem, self.bmp)
            bmi = BITMAPINFO()
            bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
            bmi.bmiHeader.biWidth = w
            bmi.bmiHeader.biHeight = -h          # top-down
            bmi.bmiHeader.biPlanes = 1
            bmi.bmiHeader.biBitCount = 32
            bmi.bmiHeader.biCompression = 0
            self.bmi = bmi
            self.buf = ctypes.create_string_buffer(w * h * 4)
            self.bf = BLENDFUNCTION(AC_SRC_OVER, 0, 255, AC_SRC_ALPHA)

        def present(self, img, x, y):
            """draw one frame; returns True/False (for automatic fallback)"""
            try:
                if img.size != (self.w, self.h):
                    self._rebuild(img.size[0], img.size[1])
                raw = to_bgra(img)
                if len(raw) != len(self.buf):
                    return False
                self.buf.raw = raw
                # note: StretchDIBits draws INTO the DC; SetDIBits on a bitmap
                # selected in a DC is not allowed per Microsoft docs!
                gdi32.StretchDIBits(self.mem, 0, 0, self.w, self.h,
                                    0, 0, self.w, self.h, self.buf,
                                    ctypes.byref(self.bmi), 0, SRCCOPY)
                dst = POINT(x, y)
                src = POINT(0, 0)
                sz = SIZE(self.w, self.h)
                ok = user32.UpdateLayeredWindow(
                    self.hwnd, self.hdc, ctypes.byref(dst), ctypes.byref(sz),
                    self.mem, ctypes.byref(src), 0,
                    ctypes.byref(self.bf), ULW_ALPHA)
                return bool(ok)
            except Exception:
                return False

        def _rebuild(self, w, h):
            """if frame and window sizes differ, rebuild the buffers"""
            try:
                self.w, self.h = int(w), int(h)
                gdi32.SelectObject(self.mem, self.old)
                gdi32.DeleteObject(self.bmp)
                self.bmp = gdi32.CreateCompatibleBitmap(self.hdc, self.w, self.h)
                self.old = gdi32.SelectObject(self.mem, self.bmp)
                self.bmi.bmiHeader.biWidth = self.w
                self.bmi.bmiHeader.biHeight = -self.h
                self.buf = ctypes.create_string_buffer(self.w * self.h * 4)
            except Exception:
                pass

        def close(self):
            try:
                gdi32.SelectObject(self.mem, self.old)
                gdi32.DeleteObject(self.bmp)
                gdi32.DeleteDC(self.mem)
                user32.ReleaseDC(0, self.hdc)
            except Exception:
                pass
else:
    Win32Layer = None


class TkLayer:
    """fallback for non-Windows systems (headless tests)"""

    def __init__(self, root, w, h):
        self.root = root
        self.w, self.h = w, h
        from PIL import ImageTk
        self._ImageTk = ImageTk
        self._ref = None
        self.root.geometry('%dx%d' % (w, h))
        self.lbl = tk.Label(root, bd=0, bg=CHROMA)
        self.lbl.pack()
        try:
            root.attributes('-transparentcolor', CHROMA)
        except Exception:
            pass

    def present(self, img, x, y):
        # the birth morph presents GROWING frames (the dialog blooms into
        # the home, the pet jelly-pops) - a size change must resize the
        # window WITH the frame or the fallback clips the grown bitmap to
        # the old rect.
        if img.size != (self.w, self.h):
            self.resize(img.size[0], img.size[1])
        if getattr(self, '_pos', None) != (x, y):
            self._pos = (x, y)
            try:
                self.root.geometry('+%d+%d' % (x, y))
            except Exception:
                pass
        # img is premultiplied.  Only the FULLY transparent pixels
        # (alpha == 0) carry the exact magenta chroma (Windows knocks
        # those out -> the round silhouette stays); every other pixel
        # shows the premultiplied color itself (= composited over black),
        # which is exactly how the real alpha (Win32) window looks.
        # Compositing semi-transparent pixels OVER the chroma instead
        # would tint every soft edge pink (a white glow at alpha a would
        # display as (255, a, 255)) - this way a white glow stays white.
        a = img.split()[3]
        hole = a.point(lambda v: 255 if v == 0 else 0)
        rgb = img.convert('RGB')                  # premultiplied = over black
        bg = Image.composite(Image.new('RGB', img.size, (255, 0, 255)), rgb, hole)
        self._ref = self._ImageTk.PhotoImage(bg)
        self.lbl.configure(image=self._ref)
        return True

    def resize(self, w, h):
        self.w, self.h = w, h
        self.root.geometry('%dx%d' % (w, h))
        self.lbl.configure(width=w, height=h)

    def close(self):
        try:
            self.lbl.destroy()
        except Exception:
            pass


# ============================== the pet widget =============================

class LEDPet:

    def __init__(self, root, selftest_secs=None):
        self.root = root
        self.t0 = time.time()
        self.last_t = self.t0
        self.selftest_secs = selftest_secs
        self.running = True
        self.last_pm = None

        # v1.0 (LEDPET_V1_NAME): a missing config file = a TRUE first run
        # (an upgraded install keeps its config and is never asked again -
        # the name can always be re-picked with "Reset name" in Settings)
        self._fresh = not os.path.isfile(CFG_FILE)
        self._raw_cfg = load_raw_cfg()   # v1.1 (LEDPET_V1_QUARANTINE)
        self.cfg = load_cfg()
        # v1.1 (LEDPET_V1_QUARANTINE): if THIS first load changed anything
        # (the quarantine stamped the config and/or pulled the sound
        # switches of a poisoned one), persist the result immediately - the
        # quieted config must be on disk even if the user never touches a
        # single setting, so the poison can never come back.  (Set as a
        # flag, NOT as _save_at: later init lines reset _save_at to 0.0;
        # the first tick turns the flag into a real delayed save.)
        # v1.1 (LEDPET_V1_FINAL_QUIET): the comparison is now against the
        # sanitized values themselves (ver/audio/mic), so it also catches
        # the ver 5 pull of a config that UPDATE 4 had already stamped
        # while poisoned - those never changed quiet_lock, only ver 4 -> 5.
        self._quarantine_save = bool(
            self.cfg.get('quiet_lock')
            and (self.cfg.get('ver') != self._raw_cfg.get('ver')
                 or bool(self.cfg.get('audio')) != bool(self._raw_cfg.get('audio'))
                 or bool(self.cfg.get('mic')) != bool(self._raw_cfg.get('mic'))))
        self.name = C.sanitize_name(self.cfg.get('name', ''))
        self.naming = None             # the first-run naming dialog
        self._morph = None             # LEDPET_V1_MORPH: the grow animation

        # --- audio (equalizer <- system output) ---
        self.audio_ok = False
        self.audio_err = ''
        self.audio_running = True
        self.audio_thread = None
        self._ensure_at = 0.0       # v16.5: next periodic worker-revive check
        self.audio_engine = ''
        self.spec_lock = threading.Lock()
        self.a_bands = [0.0] * C.NB
        self.a_level = 0.0
        self.a_bass = 0.0
        self.a_beat = 0
        self.a_bstr = 0.0
        self.a_t = 0.0
        self._an = None             # SpecAnalyzer for the native engine
        self._sysbuf = None
        self._sys_log_n = 0
        self._demo_eq = False       # True = equalizer is in demo mode
        # microphone (mouth lip-sync) - the mouth reacts to the mic ONLY
        self.mic_ok = False
        self.mic_err = ''
        self.mic_name = ''
        self.mic_engine = ''
        self.mic_thread = None
        self.mic_lock = threading.Lock()
        self.m_open = 0.0
        self.m_wide = 0.35
        self.m_raw = 0.0
        self.m_t = 0.0
        self._man = None            # MicAnalyzer for the native engine
        self._micbuf = None
        self._mic_log_n = 0
        # mic mouth reactions - driven by the microphone only
        self.m_voice_t = -9.0          # last time a voice was heard
        self.m_pop_until = 0.0         # surprised 'oh!' moment
        self.m_loud_since = None       # sustained loudness (shouting/singing)
        self.m_hum_since = None        # sustained low hum (humming/whistling)
        self.m_sound_t = -9.0          # last time the system played sound
        self._last_voice_t = -9.0      # last frame with mic voice (on/off detection)
        self.m_run_t0 = 0.0            # start of the current mic voice period
        self.m_run_peak = 0.0          # loudness peak of this period
        self.m_silence_before = 0.0    # silence right before this period
        # v17: bubble / jelly body state (LEDPET_V17_BODY)
        self._bprev = None
        self._bvx = 0.0
        self._bvy = 0.0
        self._bux, self._buy = 0.0, 1.0
        self.blob_s = 0.0
        self.blob_v = 0.0
        # v17.9: last user/audio activity (for the optional sleep timer)
        self.last_active = time.time()
        # eye bounce (damped spring)
        self.bx = 0.0
        self.bv = 0.0
        self.next_bounce = time.time() + 2.0
        self.prev_state = None
        self.beat_seen = None
        self.beat_t = -9.0
        self.beat_s = 0.0
        self.loud_since = None

        # --- face state ---
        self.mode = 'idle'
        self.mode_until = 0.0
        # v18.1 (LEDPET_V18_CUSTOM): sticky shortcuts - the expression a
        # hotkey picked stays until the NEXT hotkey ('idle' = unpin).
        self.hk_pin_state = None
        self.blink_t0 = -9.0
        self.next_blink = time.time() + random.uniform(1.8, 4.0)
        self.lx = self.ly = 0.0
        self.tx = self.ty = 0.0
        self.next_wander = time.time() + 3.0
        self.last_ptr = (0, 0)
        self.ptr_t = time.time()
        self.press = None
        self.moved = False
        self.drag_samples = []
        self._btn_up_t = None          # watchdog: last time the left button was seen up
        self.last_click_t = -9.0
        self.menu_open = False
        self.settings_win = None
        self._menu_vars = []

        # --- v13: home frame (food / water / games / expressions) ---
        self.home = None
        self.face_icon = None
        self._home_errs = 0

        # --- equalizer bars / particles ---
        self.lens = None
        self.peaks = None
        self.peak_hold = None
        self.rot = 0.0
        self.sparks = []
        self.ripples = []
        # birth FX time window: birth ripples play even when the ripple
        # switch is off (a time window, never a permanent cfg change)
        self._birth_fx_until = 0.0
        self._rc_cache = None
        self._bidx = np.arange(C.NB, dtype=float)
        self._phase = None
        self._phase_n = 0

        # --- quality / saving ---
        self.frame_ms = 0.0
        self.slow_count = 0
        self.ss_run = None            # None = follow the settings
        self.bloom_run = None
        self._rebuild_at = 0.0
        self._save_at = 0.0
        self._cycle_idx = int(self.cfg.get('cidx', 0))

        # --- v18.0: global expression shortcuts (LEDPET_V18_KEYS) ---
        # the pump thread only pushes state names into hk.q; the frame
        # loop drains it, so a hotkey can never touch Tk from a thread
        self.hk_bindings = {}
        self.hk = hk.HotkeyEngine()
        hk._log = _write_log          # v18.4: hotkey problems land in error.log
        self._hk_check_at = 0.0       # v18.4: watchdog clock
        self._hk_last_fire = 0.0      # v18.4: last time a shortcut fired
        self.apply_hotkeys()

        # --- window ---
        root.title('LEDPET V1.0')
        root.overrideredirect(True)
        root.config(bg='black')

        self.scale = self.cfg['scale']
        self.ren = self._make_renderer()
        self.wx, self.wy = self.start_pos()
        self.fx, self.fy = float(self.wx), float(self.wy)
        root.geometry('%dx%d+%d+%d' % (self.ren.W, self.ren.H, self.wx, self.wy))
        # (topmost is applied below, after self.hwnd exists - v16.1 fix:
        #  calling it here crashed with AttributeError on Windows)

        # --- display layer (Windows: real alpha) ---
        self.layer = None
        self.hwnd = None
        self._win32_active = False
        self.present_fail = 0
        self._tk_retry_at = 0.0     # next Win32 self-heal try (mono time)
        self._err_count = 0
        # v1.0 (LEDPET_V1_NAME): on a true first run the pet stays HIDDEN
        # until it has a name (the centered "give me a name" frame shows)
        self._first_run = (self._fresh and not self.name
                           and self.selftest_secs is None)
        try:
            if self._first_run:
                root.withdraw()
            else:
                root.deiconify()
        except Exception:
            pass
        root.update()
        if IS_WINDOWS and Win32Layer is not None:
            wid = root.winfo_id()
            hwnd = user32.GetParent(wid)
            if not hwnd or not user32.IsWindow(hwnd):
                hwnd = wid
            self.hwnd = hwnd
            try:
                self.layer = Win32Layer(self.hwnd, self.ren.W, self.ren.H)
                self._win32_active = True
            except Exception:
                _write_log('Win32Layer creation failed')
                self.layer = None
        if self.layer is None:
            self.layer = TkLayer(root, self.ren.W, self.ren.H)

        # window + hwnd now exist -> apply "Always on top" (Tk + Win32)
        self.apply_topmost()

        # --- events (no <Motion>: mouse position is polled via winfo_pointerxy) ---
        root.bind_all('<Button-1>', self.on_press)
        root.bind_all('<B1-Motion>', self.on_drag)
        root.bind_all('<ButtonRelease-1>', self.on_release)
        root.bind_all('<Button-3>', self.on_menu)

        self.ensure_audio()
        self.ensure_mic()
        # v1.0 (LEDPET_V1_NAME): first run -> the naming dialog INSTEAD of
        # the home frame; DONE turns it into the pet + home frame
        if self._first_run:
            self._begin_naming()
        else:
            self.ensure_home()
        atexit.register(lambda: save_cfg(self._cfg_out()))
        self.tick()

    # ------------------------- renderer / settings -------------------------
    def _make_renderer(self):
        try:                                   # v17: the LED mask must match the body shape
            C.set_shape(self.cfg.get('shape', 'circle'))
        except Exception:
            pass
        q = self.cfg['quality']
        ss = 1 if q == 'low' else 2
        if q == 'auto' and self.ss_run:
            ss = self.ss_run
        bloom = (q != 'low')
        if self.bloom_run is not None and q == 'auto':
            bloom = self.bloom_run
        cols = C.clock_width('00:00:00' if self.cfg['clock_secs'] else '00:00')
        # v18.1 (LEDPET_V18_CUSTOM): deep-dark unlit grid + second fill color
        return Renderer(self.cfg['scale'], ss=ss, clock_cols=cols, rays=self.cfg['rays'],
                        clock_on=self.cfg['clock'], bloom=bloom,
                        body_fill=bool(self.cfg.get('body_fill', False)),
                        fill_rgb=tuple(self.cfg.get('body_fill_rgb', (0, 0, 0))),
                        deep_dark=bool(self.cfg.get('deep_dark', True)),
                        fill_rgb2=tuple(self.cfg.get('fill_rgb2', (30, 34, 60))))

    def rebuild_renderer(self, relayer=True):
        old = self.ren
        cxp = self.wx + old.W // 2
        cyp = self.wy + old.H // 2
        self.scale = self.cfg['scale']
        self.ren = self._make_renderer()
        W, H = self.ren.W, self.ren.H
        if (W, H) != (old.W, old.H):
            self.wx = int(cxp - W // 2)
            self.wy = int(cyp - H // 2)
            self.fx, self.fy = float(self.wx), float(self.wy)
            try:
                self.root.geometry('%dx%d+%d+%d' % (W, H, self.wx, self.wy))
            except Exception:
                pass
            try:
                self.layer.close()
            except Exception:
                pass
            self.layer = None
            if IS_WINDOWS and Win32Layer is not None and self.hwnd:
                try:
                    self.layer = Win32Layer(self.hwnd, W, H)
                    self._win32_active = True
                except Exception:
                    self.layer = None
            if self.layer is None:
                self.layer = TkLayer(self.root, W, H)
        self.lens = None          # ray lengths are rebuilt for the new count
        self._rc_cache = None
        if self.home is not None:
            try:
                self.home.on_pet_resized()
            except Exception:
                self._home_error('resize')

    def _cfg_out(self):
        c = dict(self.cfg)
        c['x'], c['y'] = int(self.wx), int(self.wy)
        c['cidx'] = self._cycle_idx
        return c

    def save_now(self):
        save_cfg(self._cfg_out())
        self._save_at = 0.0

    def apply_hotkeys(self):
        """v18.0: (re)register the global expression shortcuts
        (LEDPET_V18_KEYS). hk.status holds 'ok'/'taken' per state for the
        settings panel."""
        try:
            self.hk_bindings = hk.load_bindings(self.cfg)
            st = self.hk.apply(self.hk_bindings,
                               bool(self.cfg.get('hotkeys_on', True)))
            self.hk.status = st
        except Exception:
            import traceback
            _write_log('apply_hotkeys error\n' + traceback.format_exc())
            try:
                self.hk_bindings = {}
            except Exception:
                pass

    def cfg_changed(self, key=None):
        """called from the menu and the settings panel"""
        if key in ('scale', 'rays', 'clock', 'clock_secs', 'quality', 'shape'):
            self.ss_run = None
            self.bloom_run = None
            self.slow_count = 0
            self._rebuild_at = time.time() + 0.30
        elif key == 'topmost':
            self.apply_topmost()
            if self.home is not None:
                try:
                    self.home.apply_topmost()
                except Exception:
                    pass
        elif key == 'home':
            self.ensure_home()
        elif key == 'track':
            if self.cfg.get('track') in ('chase_slow', 'chase_fast'):
                self.cfg['follow_mode'] = self.cfg['track']
        elif key == 'audio':
            self.ensure_audio()
        elif key == 'mic':
            self.ensure_mic()
        elif key in ('hotkeys', 'hotkeys_on'):      # v18.0 (LEDPET_V18_KEYS)
            self.apply_hotkeys()
        elif key == 'hk_pin':                       # v18.1: sticky shortcuts
            if not self.cfg.get('hk_pin', True):
                self.hk_pin_state = None            # un-pin when switched off
        self._save_at = time.time() + 1.0

    def apply_theme(self, idx):
        try:
            name, th = C.THEMES[idx]
        except Exception:
            return
        self.cfg.update(th)
        self.cfg = C.sanitize_cfg(self.cfg)
        self._rc_cache = None
        self.cfg_changed('rays')
        self.set_mode('happy', 1.2)

    def apply_style_file(self, path):
        """apply a style file (a shareable look) -> style name or None.
        Only the look settings are touched: the name, the window
        position, the sound switches, the shortcuts and the needs all
        stay exactly as they are."""
        st = read_style(path)
        if not st:
            return None
        full = C.sanitize_cfg(st['settings'])
        for k in C.STYLE_KEYS:
            self.cfg[k] = full[k]
        self._rc_cache = None
        self.cfg_changed('rays')     # renderer rebuild + auto-save
        try:
            self.set_mode('happy', 1.2)
        except Exception:
            pass
        return st['name']

    def reset_cfg(self):
        keep = (self.cfg['x'], self.cfg['y'])
        _nm = getattr(self, 'name', '')      # v1.0: the name survives a reset
        self.cfg = C.sanitize_cfg({})
        self.cfg['x'], self.cfg['y'] = keep
        self.name = _nm
        self.cfg['name'] = _nm
        self._rc_cache = None
        self.cfg_changed('scale')
        self.cfg_changed('hotkeys')           # v18.0: back to the default shortcuts

    def start_pos(self):
        x, y = self.cfg['x'], self.cfg['y']
        try:
            sw = self.root.winfo_screenwidth()
            sh = self.root.winfo_screenheight()
        except Exception:
            sw, sh = 1920, 1080
        if x < 0 or y < 0:                    # first run: center of the screen
            x, y = (sw - self.ren.W) // 2, (sh - self.ren.H) // 2
        x = max(-self.ren.W + 80, min(sw - 80, x))
        y = max(0, min(sh - 80, y))
        return (int(x), int(y))

    def apply_topmost(self):
        try:
            self.root.attributes('-topmost', self.cfg['topmost'])
        except Exception:
            pass
        hwnd = getattr(self, 'hwnd', None)   # v16.1: never crash during early init
        if IS_WINDOWS and hwnd:
            _win_set_topmost(hwnd, bool(self.cfg['topmost']))

    def win_set_topmost(self, hwnd, on):
        """Win32 topmost switch for other windows (the home frame)"""
        if IS_WINDOWS and hwnd:
            return _win_set_topmost(hwnd, bool(on))
        return False

    # ----------------------------- events ------------------------------
    def _is_pet_event(self, e):
        """only events of the pet window itself; not settings/menu"""
        try:
            return e.widget.winfo_toplevel() is self.root
        except Exception:
            return False

    def _cell_at(self, xr, yr):
        lx = (xr - self.wx) / float(self.ren.W) * C.BW
        ly = (yr - self.wy) / float(self.ren.H) * C.BH
        return lx, ly, (lx - C.CX) / C.PITCH + C.HALF, (ly - C.CY) / C.PITCH + C.HALF

    def on_press(self, e):
        if self.menu_open:
            return
        if self.naming is not None and self.naming.owns_event(e):
            return              # v1.0: the naming dialog owns its own events
        if self.home is not None and self.home.owns_event(e):
            try:
                self.home.press(e)
            except Exception:
                self._home_error('press')
            return
        if not self._is_pet_event(e):
            return
        self.press = (e.x_root, e.y_root, self.wx, self.wy, time.time())
        self.moved = False
        self.drag_samples = [(time.time(), e.x_root, e.y_root)]

    def on_drag(self, e):
        if self.naming is not None and self.naming.owns_event(e):
            return              # v1.0: the naming dialog owns its own events
        if self.home is not None and self.home.capturing():
            try:
                self.home.drag(e)
            except Exception:
                self._home_error('drag')
            return
        if not self.press:
            return
        px, py, wx0, wy0, _t0 = self.press
        dx, dy = e.x_root - px, e.y_root - py
        if not self.moved and dx * dx + dy * dy > 36:
            self.moved = True
            self.set_mode('surprised', 0.8)
        if self.moved:
            self.wx, self.wy = wx0 + dx, wy0 + dy
            self.fx, self.fy = float(self.wx), float(self.wy)
            now = time.time()
            self.drag_samples.append((now, e.x_root, e.y_root))
            if len(self.drag_samples) > 14:
                self.drag_samples.pop(0)

    def on_release(self, e):
        if self.naming is not None and self.naming.owns_event(e):
            return              # v1.0: the naming dialog owns its own events
        if self.home is not None and self.home.capturing():
            try:
                self.home.release(e)
            except Exception:
                self._home_error('release')
            self.press = None
            return
        if self.menu_open:
            self.press = None
            return
        if self.press and not self.moved:
            now = time.time()
            lx, ly, gx, gy = self._cell_at(e.x_root, e.y_root)
            if self.cfg['ripples']:
                self.ripples.append((gx, gy, now, 0.95))
            if self.cfg['sparks']:
                self.spawn_sparks(14, origin=(lx, ly))
            # v17.9: optional heart burst on every click
            if self.cfg.get('click_hearts'):
                self.spawn_sparks(10, origin=(lx, ly), col=(255, 105, 145))
            if now - self.last_click_t < 0.38:           # double click -> love!
                self.set_mode('love', 2.4)
                self.spawn_sparks(18, origin=(lx, ly), col=(255, 110, 170))
            else:
                self.cycle_color()
                self.set_mode('happy', 1.5)
            self.last_click_t = now
            self.kick(1.0)
        elif self.press and self.moved:
            if len(self.drag_samples) >= 3:
                t1, x1, y1 = self.drag_samples[0]
                t2, x2, y2 = self.drag_samples[-1]
                dt = max(0.001, t2 - t1)
                dist = math.hypot(x2 - x1, y2 - y1)
                if dist / dt > 1.4 and dt < 0.5:
                    self.set_mode('dizzy', 1.6)
            self.save_now()
        self.press = None

    def on_menu(self, e):
        if self.naming is not None and self.naming.owns_event(e):
            return              # v1.0: no pet menu while the naming dialog shows
        if not (self._is_pet_event(e) or (self.home is not None and self.home.owns_event(e))):
            return
        self.menu_open = True
        m = None
        try:
            m = self.build_menu()
            m.tk_popup(e.x_root, e.y_root)
        except Exception:
            import traceback
            _write_log('menu error\n' + traceback.format_exc())
        finally:
            try:
                if m is not None:
                    m.grab_release()
            except Exception:
                pass
            # tk_popup returns when the menu is closed -> clear the flag HERE.
            # (relying on <Unmap> alone could leave menu_open stuck True, which
            #  blocked every press and made the pet/home impossible to move)
            self.menu_open = False

    def set_mode(self, m, dur):
        if time.time() < self.mode_until and self.mode == 'dizzy' and m != 'dizzy':
            return
        self.mode = m
        self.mode_until = time.time() + dur

    # ------------------------------ menu -------------------------------
    def build_menu(self):
        cfg = self.cfg
        msty = dict(tearoff=0, bg='#141821', fg='#EDEDF0',
                    activebackground='#2A3140', activeforeground='#FFFFFF', bd=0)
        self._menu_vars = []

        def bvar(key):
            v = tk.BooleanVar(value=bool(cfg[key]))
            self._menu_vars.append(v)
            return v

        m = tk.Menu(self.root, **msty)
        # live sound status - click to run the sound test (English report)
        m.add_command(label='\u25cf  ' + self.sound_menu_label(),
                      command=self.sound_test)
        m.add_separator()

        col = tk.Menu(m, **msty)
        for i, (name, rgb) in enumerate(C.PALETTE):
            col.add_command(label=name, command=lambda i=i: self.set_palette(i))
        col.add_separator()
        col.add_command(label='Rainbow', command=lambda: self.set_color_mode('rainbow'))
        col.add_command(label='Bass reactive', command=lambda: self.set_color_mode('reactive'))
        m.add_cascade(label='Light color', menu=col)

        sz = tk.Menu(m, **msty)
        for name, sc in SIZES:
            sz.add_command(label=name, command=lambda sc=sc: self.set_size(sc))
        m.add_cascade(label='Size', menu=sz)

        shp = tk.Menu(m, **msty)                 # v17: quick body shape switch
        for name, label in C.SHAPES:
            shp.add_command(label=label, command=lambda n=name: self.set_cfg('shape', n))
        m.add_cascade(label='Body shape', menu=shp)

        m.add_command(label='Follow me / Go home', command=self.toggle_follow)
        hv = tk.BooleanVar(value=bool(cfg['home']))
        self._menu_vars.append(hv)
        m.add_checkbutton(label='Home frame - feed, water, games', variable=hv,
                          command=lambda hv=hv: self.set_cfg('home', bool(hv.get())))
        ex = tk.Menu(m, **msty)
        for name, label in C.OLD_STATES + C.NEW_STATES:
            if name == 'dance':
                continue
            # v18.0: show the global shortcut next to each expression
            acc = self.hk_bindings.get(name, '')
            ex.add_command(label=label, accelerator=acc,
                           command=lambda n=name: self.show_expression(n))
        ex.add_separator()
        ex.add_command(label='Keyboard shortcuts...',
                       command=lambda: self.open_settings('keys'))
        m.add_cascade(label='Expressions', menu=ex)
        m.add_separator()

        # keep this menu short: follow-mouse mode, microphone, auto sleep and
        # idle expressions live in "Advanced settings..." now
        for label, key in (('Show clock', 'clock'), ('Always on top', 'topmost')):
            v = bvar(key)
            m.add_checkbutton(label=label, variable=v,
                              command=lambda key=key, v=v: self.set_cfg(key, bool(v.get())))
        m.add_separator()
        m.add_command(label='Advanced settings...', command=self.open_settings)
        m.add_separator()
        m.add_command(label='Quit', command=self.quit)
        try:
            m.bind('<Unmap>', lambda e: setattr(self, 'menu_open', False))
        except Exception:
            pass
        return m

    def set_cfg(self, key, val):
        self.cfg[key] = val
        self.cfg_changed(key)

    def set_palette(self, i):
        i %= len(C.PALETTE)
        self._cycle_idx = i
        self.cfg['rgb1'] = list(C.PALETTE[i][1])
        if self.cfg['color_mode'] != 'gradient':
            self.cfg['color_mode'] = 'solid'
        self._rc_cache = None
        self.set_mode('happy', 1.2)
        self.cfg_changed('color')

    def set_color_mode(self, mode):
        self.cfg['color_mode'] = mode
        self._rc_cache = None
        self.set_mode('happy', 1.2)
        self.cfg_changed('color_mode')

    def cycle_color(self):
        """click: 6 palette colors -> rainbow -> neon gradient -> repeat"""
        self._cycle_idx = (self._cycle_idx + 1) % 8
        i = self._cycle_idx
        if i < 6:
            self.cfg['color_mode'] = 'solid'
            self.cfg['rgb1'] = list(C.PALETTE[i][1])
        elif i == 6:
            self.cfg['color_mode'] = 'rainbow'
        else:
            self.cfg['color_mode'] = 'gradient'
            self.cfg['rgb1'] = [255, 90, 200]
            self.cfg['rgb2'] = [80, 220, 255]
        self._rc_cache = None
        self.cfg_changed('color')

    def set_size(self, sc):
        self.cfg['scale'] = float(sc)
        self.cfg_changed('scale')

    def open_settings(self, tab='color'):
        try:
            if self.settings_win is not None and self.settings_win.winfo_exists():
                try:
                    if tab and hasattr(self.settings_win, 'show_tab'):
                        self.settings_win.show_tab(tab)   # v18.0: deep link
                except Exception:
                    pass
                self.settings_win.lift()
                return
        except Exception:
            pass
        try:
            from settings_ui import SettingsWindow
            self.settings_win = SettingsWindow(self.root, self)
            if tab and tab != 'color':
                try:
                    self.settings_win.show_tab(tab)       # v18.0: deep link
                except Exception:
                    pass
        except Exception:
            import traceback
            _write_log('settings window error\n' + traceback.format_exc())
            try:
                from tkinter import messagebox
                messagebox.showerror('LEDPET V1.0', 'Could not open the settings window.\nDetails in:\n%s' % LOG_FILE)
            except Exception:
                pass

    # ------------ live sound status (first row of the menu) ------------
    def sound_menu_label(self):
        """one-line English status shown (and clickable) in the menu"""
        try:
            if not self.cfg['audio']:
                return 'Sound: off - tick "Equalizer" in this menu'
            if self.audio_ok:
                eng = self.audio_engine or ''
                return ('Sound: OK - equalizer reacts to system audio'
                        + (' (%s)' % eng if eng else ''))
            if self._demo_eq:
                return ('Sound: demo wave - engine unavailable'
                        ' | ' + ((self.audio_err or 'retrying...').strip())[:64])
            return ('Sound: waiting for system audio'
                    ' | ' + ((self.audio_err or 'starting...').strip())[:64])
        except Exception:
            return 'Sound'

    def sound_test(self):
        """probe both capture paths (loopback + mic) and show an English report"""
        threading.Thread(target=self._sound_test_thread, daemon=True).start()
        try:
            self.root.after(300, self._poll_sound_report)
        except Exception:
            pass

    def _sound_test_thread(self):
        lines = []
        if not IS_WINDOWS:
            lines.append('The sound test works on Windows only.')
        else:
            try:
                import wasapi_audio as WA
                st = WA.audiosrv_state()
                if st != 'running':
                    lines.append('Windows Audio service: %s'
                                 ' (press Win+R, run services.msc, start it)' % st)
            except Exception:
                pass
            for mode, label in (('loopback', 'System audio (equalizer)'),
                                ('mic', 'Microphone (mouth)')):
                if mode == 'mic':
                    try:
                        import wasapi_audio as WA
                        why = WA.mic_privacy_reason()
                        if why:
                            lines.append('Privacy: ' + why)
                    except Exception:
                        pass
                stat = {'n': 0, 'peak': 0.0}

                def cb(mono, sr, stat=stat):
                    try:
                        pk = float(np.max(np.abs(mono)))
                    except Exception:
                        pk = 0.0
                    stat['n'] += 1
                    if pk > stat['peak']:
                        stat['peak'] = pk

                try:
                    from wasapi_audio import WasapiCapture
                    if mode == 'loopback':
                        label = label + ' (PLAY MUSIC while testing!)'
                        window = 3.0
                    else:
                        window = 1.6
                    eng = WasapiCapture(cb, mode=mode,
                                        log=lambda m: _write_log(m))
                    ok, info = eng.start()
                    if ok:
                        t_end = time.time() + window
                        while time.time() < t_end:
                            time.sleep(0.05)
                        eng.stop()
                        if stat['n'] > 0:
                            lines.append('%s: OK - %s\n   %d blocks received, peak level %.3f'
                                         % (label, info, stat['n'], stat['peak']))
                        else:
                            lines.append('%s: opened but no data arrived - %s'
                                         % (label, info))
                    else:
                        lines.append('%s: FAILED - %s' % (label, info))
                except Exception as e:
                    lines.append('%s: error %r' % (label, e))
            # v16.3: where is the sound actually playing? (peak per output)
            try:
                import wasapi_audio as WA
                rows = WA.render_device_peaks(seconds=1.4)
                if rows:
                    lines.append('')
                    lines.append('Output devices (peak while testing):')
                    top = rows[0][1]
                    for nm, pk in rows:
                        tag = ('   <-- sound is playing here'
                               if pk > 0.05 and pk == top else '')
                        lines.append('   %s - %.3f%s' % (nm[:46], pk, tag))
                    if top <= 0.05:
                        lines.append('   (no output shows signal - '
                                     'nothing was playing?)')
            except Exception:
                pass
        lines.append('')
        lines.append('If the equalizer still does not move while music plays,')
        lines.append('please send the file:  %APPDATA%\\LEDPet\\error.log')
        report = '\n'.join(lines)
        _write_log('sound test report:\n' + report)
        # hand the report to the main loop through an attribute (thread-safe)
        self._sound_report = report

    def _poll_sound_report(self):
        rep = getattr(self, '_sound_report', None)
        if rep:
            self._sound_report = None
            try:
                from tkinter import messagebox
                messagebox.showinfo('LEDPet - Sound test', rep)
            except Exception:
                pass
        try:
            self.root.after(300, self._poll_sound_report)
        except Exception:
            pass

    def audio_status(self):
        if not self.cfg['audio']:
            return 'Off'
        if self.audio_ok:
            eng = ' (WASAPI native)' if self.audio_engine == 'WASAPI' \
                else (' (SoundCard)' if self.audio_engine else '')
            return 'Active — system audio drives the equalizer' + eng
        return 'Inactive: ' + (self.audio_err or 'starting…')

    def mic_status(self):
        if not self.cfg['mic']:
            return 'Off'
        if self.mic_ok:
            nm = (' \u2014 ' + self.mic_name[:44]) if self.mic_name else ''
            eng = ' (WASAPI native)' if self.mic_engine == 'WASAPI' \
                else (' (SoundCard)' if self.mic_engine else '')
            return 'Listening' + eng + nm
        return 'Inactive: ' + (self.mic_err or 'starting\u2026')

    def kick(self, amount):
        """give the eyes a little bounce"""
        if not self.cfg['eye_bounce']:
            return
        self.bv = max(-90.0, min(90.0, self.bv + 34.0 * amount))

    def quit(self):
        self.running = False
        self.audio_running = False
        try:
            self.hk.stop()                # v18.0: unregister the global hotkeys
        except Exception:
            pass
        if self.home is not None:
            try:
                self.home.close()
            except Exception:
                pass
            self.home = None
        self.save_now()
        try:
            self.layer.close()
        except Exception:
            pass
        try:
            self.root.destroy()
        except Exception:
            pass

    # ----------------------------- audio -------------------------------
    def ensure_audio(self):
        if not self.cfg['audio']:
            return
        if self.audio_thread is not None and self.audio_thread.is_alive():
            return
        self.audio_thread = threading.Thread(target=self.audio_worker, daemon=True)
        self.audio_thread.start()

    def _wait_retry(self, cond_key):
        """interruptible 3 s wait (between audio engine retries)"""
        for _ in range(30):
            if not (self.audio_running and self.cfg[cond_key]):
                return False
            time.sleep(0.1)
        return True

    def _on_sys_block(self, mono, sr):
        """system audio block from the native engine -> shared SpecAnalyzer (equalizer)"""
        an = self._an
        if an is None or getattr(an, 'sr', 0) != sr:
            an = C.SpecAnalyzer(sr=sr)
            an.set_smooth(self.cfg['smooth'])
            self._an = an
            self._sysbuf = np.zeros(2048)
        x = np.asarray(mono, dtype=float).ravel()
        if x.size == 0:
            return
        self._sysbuf = np.concatenate((self._sysbuf[len(x):], x))[-2048:]
        an.set_smooth(self.cfg['smooth'])
        an.feed(self._sysbuf)
        with self.spec_lock:
            self.a_bands = an.bands
            self.a_level = an.level
            self.a_bass = an.bass
            self.a_beat = an.beat_count
            self.a_bstr = an.beat_strength
            self.a_t = time.time()

    def audio_worker(self):
        """equalizer <- system output.
        Engine chain: 1) native WASAPI (nothing to install) 2) SoundCard (backup)
        each engine runs while healthy; on drop -> retry after 3 s."""
        native_ok = False        # did the WASAPI engine ever deliver audio?
        while self.audio_running and self.cfg['audio']:
            # --- engine 1: native WASAPI (ctypes - nothing to install) ---
            if IS_WINDOWS:
                try:
                    from wasapi_audio import WasapiCapture
                    self._an = None
                    self._sysbuf = None
                    eng = WasapiCapture(self._on_sys_block, mode='loopback',
                                        log=_write_log)
                    ok, info = eng.start()
                    if ok:
                        self.audio_ok = True
                        self.audio_err = ''
                        self.audio_engine = 'WASAPI'
                        native_ok = True
                        _write_log('audio: WASAPI loopback OK — %s' % info)
                        # v16.5: watch the OFF switch while the engine runs.
                        # Toggling the equalizer off now REALLY stops the
                        # capture, and ON later starts a FRESH engine with
                        # clean device memory (a safe manual reset - no app
                        # restart needed anymore).
                        while (self.audio_running and self.cfg['audio']
                                and eng.alive()):
                            time.sleep(0.2)
                        eng.stop()
                        self.audio_ok = False
                        _write_log('audio: WASAPI loopback stopped (%s)'
                                   % (eng.error or 'stop()'))
                    else:
                        self.audio_ok = False
                        self.audio_err = ('WASAPI: ' + info)[:80]
                        self._sys_log_n += 1
                        if self._sys_log_n <= 3 or self._sys_log_n % 20 == 0:
                            _write_log('audio: WASAPI loopback unavailable: %s'
                                       % info)
                except Exception as e:
                    self._sys_log_n += 1
                    if self._sys_log_n <= 3 or self._sys_log_n % 20 == 0:
                        _write_log('audio: WASAPI crashed: %r' % (e,))
                if not (self.audio_running and self.cfg['audio']):
                    return
                # if the native engine was working, reconnect it directly
                # (no fallthrough to the backup engine -> no 3 s gaps)
                if native_ok:
                    continue
            # --- engine 2: SoundCard backup (if installed) ---
            try:
                if IS_WINDOWS:
                    # SoundCard/comtypes needs COM on THIS worker thread;
                    # without it the backup dies with Error 0x800401F0
                    try:
                        ctypes.windll.ole32.CoInitializeEx(None, 0)   # MTA
                    except Exception:
                        pass
                import soundcard as sc
                _patch_numpy_fromstring(np)
            except Exception as e:
                self.audio_ok = False
                self.audio_err = ('SoundCard is not installed '
                                  '(optional backup — pip install SoundCard)')
                if not IS_WINDOWS or self._sys_log_n <= 3:
                    _write_log('audio: soundcard import failed: %r' % (e,))
                if not self._wait_retry('audio'):
                    return
                continue
            fails = 0
            bridge_t0 = time.time()      # v16.4: bridge health watchdog
            last_sig = bridge_t0         # last block with a real signal
            while self.audio_running and self.cfg['audio']:
                try:
                    spk = sc.default_speaker()
                    mic = None
                    for key in (lambda: str(spk.id), lambda: str(spk.name)):
                        try:
                            mic = sc.get_microphone(id=key(), include_loopback=True)
                            if mic is not None:
                                break
                        except Exception:
                            continue
                    if mic is None:
                        raise RuntimeError('Default audio output not found')
                    done = False
                    for sr in (48000, 44100):
                        try:
                            with mic.recorder(samplerate=sr, channels=2, blocksize=1024) as rec:
                                an = C.SpecAnalyzer(sr=sr)
                                an.set_smooth(self.cfg['smooth'])
                                buf = np.zeros(2048)
                                self.audio_ok = True
                                self.audio_err = ''
                                fails = 0
                                while self.audio_running and self.cfg['audio']:
                                    res = rec.record(numframes=1024)
                                    data = res[0] if isinstance(res, tuple) else res
                                    mono = np.asarray(data, dtype=float).mean(axis=1)
                                    buf = np.concatenate((buf[len(mono):], mono))[-2048:]
                                    an.set_smooth(self.cfg['smooth'])
                                    an.feed(buf)
                                    with self.spec_lock:
                                        self.a_bands = an.bands
                                        self.a_level = an.level
                                        self.a_bass = an.bass
                                        self.a_beat = an.beat_count
                                        self.a_bstr = an.beat_strength
                                        self.a_t = time.time()
                                    # v16.4: a backup bridge that hears nothing
                                    # for a long time must not block the native
                                    # engine (it has the smart device choice)
                                    pk = 0.0
                                    try:
                                        if mono.size:
                                            pk = float(np.abs(mono).max())
                                    except Exception:
                                        pk = 0.0
                                    if pk > 1e-5:
                                        last_sig = time.time()
                                    elif (time.time() - bridge_t0 > 45.0
                                            and time.time() - last_sig > 45.0):
                                        raise _RetryNative()
                                done = True
                                break
                        except _RetryNative:
                            raise
                        except Exception as e:
                            _write_log('audio sr=%s failed: %r' % (sr, e))
                            continue
                    if done:
                        return
                    raise RuntimeError('Audio capture failed (see error.log)')
                except _RetryNative:
                    # the backup is alive but has heard nothing for a long
                    # time -> retry the native engine with its device pick
                    self.audio_ok = False
                    self.audio_err = ''
                    _write_log('audio: backup heard no sound for a long time '
                               '-> retrying the native engine')
                    if not self._wait_retry('audio'):
                        return
                    break
                except Exception as e:
                    self.audio_ok = False
                    self.audio_err = str(e)[:80]
                    fails += 1
                    if fails in (1, 5) or fails % 20 == 0:
                        _write_log('audio worker error: %r' % (e,))
                    for _ in range(30):          # interruptible 3 s wait
                        if not (self.audio_running and self.cfg['audio']):
                            return
                        time.sleep(0.1)
                    if fails >= 12:              # v16.4: ~36 s of failures ->
                        # stop babysitting the backup: the native engine
                        # gets another chance (outer loop, engine 1)
                        _write_log('audio: backup keeps failing '
                                   '(%d x) -> retrying the native engine' % fails)
                        break

    # ------------------------- microphone -> mouth -------------------------
    def ensure_mic(self):
        if not self.cfg['mic']:
            return
        if self.mic_thread is not None and self.mic_thread.is_alive():
            return
        self.mic_thread = threading.Thread(target=self.mic_worker, daemon=True)
        self.mic_thread.start()

    def _on_mic_block(self, mono, sr):
        """microphone block from the native engine -> shared MicAnalyzer (mouth)"""
        an = self._man
        if an is None or getattr(an, 'sr', 0) != sr:
            an = C.MicAnalyzer(sr=sr)
            self._man = an
            self._micbuf = np.zeros(1024)
        x = np.asarray(mono, dtype=float).ravel()
        if x.size == 0:
            return
        self._micbuf = np.concatenate((self._micbuf[len(x):], x))[-1024:]
        an.feed(self._micbuf, self.cfg['mic_sens'])
        with self.mic_lock:
            self.m_open = an.open
            self.m_wide = an.wide
            self.m_raw = an.level_raw
            self.m_t = time.time()

    def mic_worker(self):
        """mouth <- default microphone only. No audio is stored or sent.
        Engine chain: 1) native WASAPI (nothing to install) 2) SoundCard (backup)
        on error -> log + retry every 3 s."""
        native_ok = False        # did the WASAPI engine ever deliver audio?
        while self.audio_running and self.cfg['mic']:
            # --- engine 1: native WASAPI (ctypes - nothing to install) ---
            if IS_WINDOWS:
                try:
                    from wasapi_audio import WasapiCapture
                    self._man = None
                    self._micbuf = None
                    eng = WasapiCapture(self._on_mic_block, mode='mic',
                                        log=_write_log)
                    ok, info = eng.start()
                    if ok:
                        self.mic_ok = True
                        self.mic_err = ''
                        self.mic_engine = 'WASAPI'
                        self.mic_name = 'Default microphone (WASAPI)'
                        native_ok = True
                        _write_log('mic: WASAPI capture OK — %s' % info)
                        # v16.5: same as the equalizer - the OFF switch must
                        # really stop the microphone capture (privacy), and
                        # ON later starts a fresh engine
                        while (self.audio_running and self.cfg['mic']
                                and eng.alive()):
                            time.sleep(0.2)
                        eng.stop()
                        self.mic_ok = False
                        _write_log('mic: WASAPI capture stopped (%s)'
                                   % (eng.error or 'stop()'))
                    else:
                        self.mic_ok = False
                        self.mic_err = ('WASAPI: ' + info)[:80]
                        self._mic_log_n += 1
                        if self._mic_log_n <= 3 or self._mic_log_n % 20 == 0:
                            _write_log('mic: WASAPI capture unavailable: %s'
                                       % info)
                except Exception as e:
                    self._mic_log_n += 1
                    if self._mic_log_n <= 3 or self._mic_log_n % 20 == 0:
                        _write_log('mic: WASAPI crashed: %r' % (e,))
                if not (self.audio_running and self.cfg['mic']):
                    return
                if native_ok:
                    continue          # the native engine was working
            # --- engine 2: SoundCard backup (if installed) ---
            try:
                if IS_WINDOWS:
                    try:
                        ctypes.windll.ole32.CoInitializeEx(None, 0)   # MTA
                    except Exception:
                        pass
                import soundcard as sc
                _patch_numpy_fromstring(np)
            except Exception as e:
                self.mic_ok = False
                self.mic_err = ('SoundCard is not installed '
                                '(optional backup — pip install SoundCard)')
                if not IS_WINDOWS or self._mic_log_n <= 3:
                    _write_log('mic: soundcard import failed: %r' % (e,))
                if not self._wait_retry('mic'):
                    return
                continue
            fails = 0
            while self.audio_running and self.cfg['mic']:
                try:
                    mic = sc.default_microphone()
                    if mic is None:
                        raise RuntimeError('No microphone found (Windows Settings > Sound > Input)')
                    done = False
                    for sr in (48000, 44100, 16000):
                        for ch in (1, 2):
                            try:
                                with mic.recorder(samplerate=sr, channels=ch, blocksize=512) as rec:
                                    an = C.MicAnalyzer(sr=sr)
                                    buf = np.zeros(1024)
                                    self.mic_name = str(getattr(mic, 'name', '') or '')
                                    self.mic_ok = True
                                    self.mic_err = ''
                                    self.mic_engine = 'SoundCard'
                                    fails = 0
                                    while self.audio_running and self.cfg['mic']:
                                        res = rec.record(numframes=512)
                                        data = res[0] if isinstance(res, tuple) else res
                                        x = np.asarray(data, dtype=float)
                                        if x.ndim > 1:
                                            x = x.mean(axis=1)
                                        buf = np.concatenate((buf[len(x):], x))[-1024:]
                                        an.feed(buf, self.cfg['mic_sens'])
                                        with self.mic_lock:
                                            self.m_open = an.open
                                            self.m_wide = an.wide
                                            self.m_raw = an.level_raw
                                            self.m_t = time.time()
                                    done = True
                                    break
                            except Exception as e:
                                _write_log('mic sr=%s ch=%s failed: %r' % (sr, ch, e))
                                continue
                        if done:
                            break
                    if done:
                        self.mic_ok = False
                        return
                    raise RuntimeError('Could not open the microphone (see error.log)')
                except Exception as e:
                    self.mic_ok = False
                    self.mic_err = str(e)[:80]
                    fails += 1
                    if fails in (1, 5) or fails % 20 == 0:
                        _write_log('mic worker error: %r' % (e,))
                    if not self._wait_retry('mic'):
                        return
                    if fails >= 12:              # v16.4: ~36 s of failures ->
                        # the native engine (engine 1) gets another chance
                        _write_log('mic: backup keeps failing '
                                   '(%d x) -> retrying the native engine' % fails)
                        break

    # ------------------------- sparks and particles ----------------------
    def spawn_sparks(self, count, origin=None, col=None):
        n = self.ren.rays
        for _ in range(count):
            if origin is None:
                if self.lens is None:
                    return
                cand = random.sample(range(n), min(6, n))
                i = max(cand, key=lambda k: self.lens[k])
                c, s = self.ren.g.cs[i]
                x, y = self.ren.g.tip(i, float(self.lens[i]))
                sp = random.uniform(40, 110)
                vx, vy = c * sp + random.uniform(-8, 8), s * sp + random.uniform(-8, 8)
                cc = self._ray_rgb[i] if getattr(self, '_ray_rgb', None) else (255, 255, 255)
            else:
                x, y = origin
                a = random.uniform(0, 2 * math.pi)
                sp = random.uniform(45, 140)
                vx, vy = math.cos(a) * sp, math.sin(a) * sp
                cc = col if col is not None else self._accent_now
            life = random.uniform(0.55, 1.1)
            self.sparks.append([x, y, vx, vy, 0.0, life, random.uniform(0.9, 2.0),
                                tuple(col) if col is not None else tuple(cc)])
        if len(self.sparks) > 180:
            del self.sparks[:len(self.sparks) - 180]

    def on_beat(self, now, strength):
        self.beat_t = now
        self.beat_s = strength
        cfg = self.cfg
        if not cfg['beat_fx']:
            return
        if self.mode != 'sleep':
            self.kick(0.45 + 0.6 * strength)
        # v17.9: beat_blink + tunable thresholds / spark density
        if cfg.get('beat_blink') and strength > max(0.5, float(cfg.get('beat_min', 0.45)) + 0.05) \
                and self.mode in ('idle', 'happy', 'dance'):
            self.blink_t0 = now                    # a quick blink on the beat
        _bmin = float(cfg.get('beat_min', 0.45))
        _sdens = max(0.0, float(cfg.get('spark_density', 1.0)))
        if cfg['sparks'] and strength > _bmin and _sdens > 0.01:
            self.spawn_sparks(int((4 + 8 * strength) * _sdens))
        if cfg['ripples'] and strength > _bmin + 0.10:
            self.ripples.append((C.HALF + random.uniform(-2, 2), C.HALF + random.uniform(-2, 2),
                                 now, 0.20 + 0.18 * strength))
        if len(self.ripples) > 6:
            del self.ripples[:len(self.ripples) - 6]

    # ----------------------- main animation loop -----------------------
    def tick(self):
        """resilient loop: errors are logged and the animation never stops"""
        if not self.running:
            return
        t_start = time.time()
        # v16.5: self-healing - if an audio worker died for any reason while
        # its switch is ON, quietly start it again (checked every ~2 s).
        if t_start >= self._ensure_at:
            self._ensure_at = t_start + 2.0
            try:
                self.ensure_audio()
                self.ensure_mic()
            except Exception:
                pass
        try:
            self.tick_frame()
            self._err_count = 0      # v16.4: a good frame clears the streak
        except Exception:
            import traceback
            self._err_count += 1
            # v16.4: rate-limited logging - the old code logged EVERY frame,
            # which grew a 22,000-line error.log that hid the real errors
            if self._err_count <= 3 or self._err_count % 50 == 0:
                _write_log('tick error #%d\n%s'
                           % (self._err_count, traceback.format_exc()))
            if self._err_count == 30:
                self._show_error_dialog()
            if self._err_count > 300:
                self.running = False
                return
        if self.running:
            budget = 1000.0 / max(10, self.cfg['fps'])
            spent = (time.time() - t_start) * 1000.0
            if spent < budget:
                delay = int(max(1, budget - spent))
            else:
                # the frame cost more than its budget (a very large pet on
                # a modest PC): keep a real idle gap between the frames
                # instead of busy-looping flat out.  The animation itself
                # is time-based, so only the frame rate eases down - the
                # CPU never runs at 100% just to hold a broken deadline.
                delay = int(max(4, spent * 0.30))
            self.root.after(delay, self.tick)

    def _show_error_dialog(self):
        try:
            from tkinter import messagebox
            messagebox.showerror(
                'LEDPET V1.0',
                'A repeated error occurred!\nFull details were saved to:\n'
                '%s\n\nPlease send this file so it can be fixed.' % LOG_FILE)
        except Exception:
            pass

    def _spectrum(self, now, t):
        """(spec(np)|None, level, bass, beat_count, beat_strength)"""
        cfg = self.cfg
        if cfg['audio'] and self.audio_ok:
            with self.spec_lock:
                bands, lv, bs = self.a_bands, self.a_level, self.a_bass
                bc, bstr, at = self.a_beat, self.a_bstr, self.a_t
            # a spectrum of the wrong size must never reach the render math
            if bands is None or len(bands) != C.NB:
                return None, 0.0, 0.0, bc, 0.0
            age = now - at
            fade = 1.0 if age < 0.35 else max(0.0, 1.0 - (age - 0.35) * 3.0)   # audio thread stalled -> fade out
            if fade <= 0.0:
                return None, 0.0, 0.0, bc, 0.0
            return np.asarray(bands, dtype=float) * fade, lv * fade, bs * fade, bc, bstr
        return None, 0.0, 0.0, None, 0.0

    def _watch_stuck_drag(self):
        """unstuck drags whose ButtonRelease was lost (a menu grab, an alert
        window or a focus change can swallow the release event). Without this
        the pet or the home could get stuck 'mid-drag' and stop moving."""
        if not IS_WINDOWS:
            return
        active = self.press is not None or \
            (self.home is not None and self.home.capturing())
        if not active:
            self._btn_up_t = None
            return
        try:
            down = bool(user32.GetAsyncKeyState(0x01) & 0x8000)   # VK_LBUTTON
        except Exception:
            return
        now = time.time()
        if down:
            self._btn_up_t = None
            return
        if self._btn_up_t is None:
            self._btn_up_t = now
            return
        if now - self._btn_up_t < 0.5:
            return                       # short grace for a normal click
        self._btn_up_t = None
        # the left button is physically up while a drag is still open -> close it
        if self.home is not None and self.home.capturing():
            try:
                self.home.abort_drag()
            except Exception:
                self._home_error('watchdog')
        if self.press is not None:
            was_moved = self.moved
            self.press = None
            self.moved = False
            self.drag_samples = []
            if was_moved:
                self.save_now()

    def _drain_hotkeys(self):
        """v18.0 (LEDPET_V18_KEYS): the pump thread only puts state names
        in the queue; here on the Tk thread they become real expressions.
        v18.1 (LEDPET_V18_CUSTOM): a shortcut PINS the expression - it stays
        until the next shortcut (or 'idle', which unpins instantly).
        Guarded everywhere - a hotkey problem must never break the frame."""
        try:
            while True:
                hkst = self.hk.q.get_nowait()
                try:
                    self.last_active = time.time()
                    if hkst == 'idle':       # back to the normal face NOW
                        self.hk_pin_state = None
                        self.face_icon = None
                        self.set_mode('idle', 0.0)
                        self.kick(0.4)
                    elif hkst in self.hk_bindings:
                        if bool(self.cfg.get('hk_pin', True)):
                            self.hk_pin_state = hkst
                        self._hk_last_fire = time.time()   # v18.4 diagnostics
                        self.show_expression(hkst)
                except Exception:
                    pass
        except Exception:
            pass

    def tick_frame(self):
        now = time.time()
        t = now - self.t0
        dt = clamp(now - self.last_t, 0.001, 0.1)
        self.last_t = now
        cfg = self.cfg
        n = self.ren.rays

        # --- v1.0 (LEDPET_V1_MORPH): watchdog - if the naming dialog's
        # tick loop died mid-morph for ANY reason, the hand-over must
        # still complete (the home must never stay veiled forever) ---
        if self._morph is not None and now - self._morph.get('t0', 0.0) > 3.5:
            try:
                self._morph_finish(self.naming)
            except Exception:
                self.naming = None
                self._morph = None

        # --- v18.0: global hotkeys -> expressions (LEDPET_V18_KEYS) ---
        self._drain_hotkeys()

        # --- v18.4 (LEDPET_V18_FIX): hotkey watchdog - if the pump thread
        # died for ANY reason (crash, GetMessageW error, lingering stop)
        # the shortcuts silently stop working. Every 3 s check it and
        # re-apply (re-register) when dead - same self-healing pattern as
        # the audio workers. Costs one is_alive() call per 3 s.
        if now >= self._hk_check_at:
            self._hk_check_at = now + 3.0
            try:
                if IS_WINDOWS and self.cfg.get('hotkeys_on', True) \
                        and self.hk_bindings and not self.hk.engine_alive():
                    _write_log('hotkey watchdog: pump dead -> re-apply')
                    self.apply_hotkeys()
            except Exception:
                pass

        if self._rebuild_at and now >= self._rebuild_at:
            self._rebuild_at = 0.0
            self.rebuild_renderer()
            n = self.ren.rays
        if getattr(self, '_quarantine_save', False):
            # v1.1 (LEDPET_V1_QUARANTINE): first tick after a quarantined
            # load -> persist the quieted + stamped config (the poison must
            # not survive on disk even if the user never opens Settings)
            self._quarantine_save = False
            self._save_at = now + 1.0
        if self._save_at and now >= self._save_at:
            self.save_now()

        # --- release any drag the OS lost (home freeze fix) ---
        self._watch_stuck_drag()

        # --- audio spectrum ---
        spec, level, bass, bc, bstr = self._spectrum(now, t)
        if spec is not None:
            # hard shape guarantee: exactly NB floats, no NaN (a bad block
            # from any thread must never reach the equalizer arithmetic)
            spec = np.asarray(spec, dtype=float).ravel()
            if spec.size != C.NB:
                spec = None
            else:
                spec = np.nan_to_num(spec, nan=0.0, posinf=0.0, neginf=0.0)
        sens = cfg['sens']
        if spec is not None:
            spec = np.clip(spec * sens * cfg['halo_gain'], 0.0, 1.15)
            level = min(1.0, level * sens)
            bass = min(1.0, bass * sens)
        if bc is not None:
            if self.beat_seen is None:
                self.beat_seen = bc
            elif bc != self.beat_seen:
                self.beat_seen = bc
                self.on_beat(now, bstr)
        else:
            self.beat_seen = None
        pulse = 0.0
        if cfg['beat_fx']:
            pulse = math.exp(-(now - self.beat_t) * 6.0) * self.beat_s

        # --- night sleep ---
        dtn = datetime.datetime.now()
        sleep_mode = cfg['autosleep'] and (dtn.hour >= 23 or dtn.hour < 7)

        # v17.9: optional heartbeat - a synthetic double thump every 3.6 s
        # (drives the ring, glow, bars and the body bob exactly like a beat)
        hb = 0.0
        if cfg.get('heartbeat') and not sleep_mode:
            _ph = t % 3.6
            if _ph < 1.2:
                hb = math.exp(-_ph * _ph / 0.0045) + 0.75 * math.exp(-(_ph - 0.30) ** 2 / 0.0045)
            hb = min(1.0, hb)
        peff = min(1.25, pulse + hb)

        # --- dancing with music ---
        music = (spec is not None) and level > 0.26
        # v18.1: a PINNED expression wins over the auto-dance (the user chose
        # a face with a shortcut - it stays until the next shortcut).
        if (not sleep_mode) and music and cfg.get('auto_dance', True) \
                and self.hk_pin_state is None:
            if self.loud_since is None:
                self.loud_since = now
            if now - self.loud_since > 0.5:
                if self.mode != 'dance' or now > self.mode_until:
                    self.set_mode('dance', 2.0)
                if self.mode == 'dance':
                    self.mode_until = max(self.mode_until, now + 1.2)
        elif self.loud_since is not None and not music:
            self.loud_since = None

        # --- face state selection ---
        if sleep_mode:
            state = 'sleep'
            self.mode = 'sleep'
        elif now < self.mode_until:
            state = self.mode
        elif self.hk_pin_state is not None:
            # v18.1 (LEDPET_V18_CUSTOM): the pinned shortcut expression is
            # re-asserted forever (until the next shortcut / 'idle').  The
            # mode window is kept in the future so the home emotes stay off.
            state = self.hk_pin_state
            self.mode = state
            self.mode_until = now + 2.5
            if state == 'hungry':
                self.face_icon = 'food'
        else:
            state = 'idle'
            if self.mode == 'sleep':
                self.mode = 'idle'

        # v17.9: optional inactivity sleep timer (0 = off)
        if state == 'idle' and not sleep_mode and int(cfg.get('sleep_after', 0)) > 0 \
                and now - self.last_active > int(cfg['sleep_after']) * 60:
            state = 'sleep'

        # --- blinking / wink ---
        blink = 1.0
        if state in ('idle', 'wink'):
            if now >= self.next_blink:
                self.blink_t0 = now
                self.next_blink = now + random.uniform(2.2, 5.5) / max(0.2, float(cfg.get('blink_rate', 1.0)))
                if random.random() < float(cfg.get('wink_chance', 0.14)):
                    self.set_mode('wink', 0.75)
                    state = 'wink'
            dtb = now - self.blink_t0
            if 0.0 <= dtb < 0.28:
                blink = max(0.15, 1.0 - math.sin(math.pi * dtb / 0.28))

        # --- eye bounce: damped spring (k=420, c=15 -> ~3 Hz, settles in ~0.4 s) ---
        if cfg['eye_bounce'] and state != 'sleep':
            if self.prev_state is not None and state != self.prev_state:
                self.kick(0.5 if state == 'dizzy' else 0.9)
            if state in ('idle', 'happy', 'wink') and now >= self.next_bounce:
                self.kick(random.uniform(0.8, 1.2))
                self.next_bounce = now + random.uniform(1.8, 3.8)
            steps = max(1, int(dt / 0.008) + 1)
            h = dt / steps
            for _ in range(steps):
                self.bv += (-420.0 * self.bx - 15.0 * self.bv) * h
                self.bx += self.bv * h
            self.bx = clamp(self.bx, -1.2, 1.2)
        else:
            self.bx = self.bv = 0.0
        self.prev_state = state

        # --- microphone -> mouth (the mouth reacts to the mic ONLY) ---
        talk = None
        mouth_ov = None
        if cfg['mic'] and self.mic_ok and state != 'sleep':
            # while the system plays sound, the mic hears it from the
            # speakers -> the mouth must stay calm; system audio only moves
            # the equalizer. The louder the system, the lower the mic gain;
            # from level>=0.16 the mouth is fully muted:
            sys_lv = level if cfg['audio'] else 0.0
            mic_gain = 1.0
            if sys_lv > 0.06:
                mic_gain = max(0.0, 1.0 - (sys_lv - 0.06) / 0.10)
                self.m_sound_t = now    # system 'sound' -> mouth surprise stays disarmed
            with self.mic_lock:
                mo, mw, mr, mt = self.m_open, self.m_wide, self.m_raw, self.m_t
            mo *= mic_gain
            mr *= mic_gain
            if now - mt < 0.5:
                voice = (mr > 0.13) or (mo > 0.10)
                if voice:
                    # start of a new mic voice period (after >=0.12 s of drop)
                    if now - self._last_voice_t > 0.12:
                        self.m_run_t0 = now
                        self.m_run_peak = 0.0
                        # real silence before this period = no mic, no system
                        self.m_silence_before = now - max(self.m_voice_t,
                                                          self.m_sound_t)
                    self.m_run_peak = max(self.m_run_peak, mr)
                self._last_voice_t = now if voice else self._last_voice_t
                self.m_voice_t = now if voice else self.m_voice_t
                if voice:
                    # sudden loud start after full silence -> surprised 'oh!'
                    if (self.m_run_peak > 0.40 and self.m_silence_before > 0.55
                            and now - self.m_run_t0 < 0.35
                            and state != 'dizzy' and now >= self.m_pop_until):
                        self.m_pop_until = now + 0.55
                        if state in ('idle', 'happy', 'dance', 'wink'):
                            self.set_mode('surprised', 0.55)
                            self.kick(1.0)
                            if cfg['ripples']:
                                self.ripples.append((C.HALF, C.HALF - 1.0, now, 0.55))
                # sustained loudness -> big mouth (shouting/singing)
                if mo > 0.60 and mr > 0.55:
                    if self.m_loud_since is None:
                        self.m_loud_since = now
                else:
                    self.m_loud_since = None
                # sustained low hum (humming/whistling) -> whistle mouth
                if voice and mw < 0.30 and mo < 0.55:
                    if self.m_hum_since is None:
                        self.m_hum_since = now
                else:
                    self.m_hum_since = None
                silence = now - self.m_voice_t
                if now < self.m_pop_until:
                    mouth_ov = 'o'
                elif self.m_loud_since is not None and now - self.m_loud_since > 0.30:
                    mouth_ov = 'big'
                elif self.m_hum_since is not None and now - self.m_hum_since > 0.45:
                    mouth_ov = 'oo'
                elif voice:
                    talk = (max(mo, 0.14), mw)     # natural lip-sync from the mic
                    mouth_ov = 'talk'
                elif 0.10 < silence < 1.1 and state == 'idle':
                    mouth_ov = 'smile'             # short smile after talking

        # --- mouse: eyes across the whole screen + body chase ---
        if talk is not None:
            self.last_active = now            # v17.9: the user is talking
        mx = my = 0
        have_ptr = False
        try:
            mx, my = self.root.winfo_pointerxy()
            have_ptr = True
        except Exception:
            pass
        if have_ptr and (mx, my) != self.last_ptr:
            self.last_ptr = (mx, my)
            self.ptr_t = now
            self.last_active = now          # v17.9: the user is around
        W, H = self.ren.W, self.ren.H
        fcx = self.wx + W / 2.0
        fcy = self.wy + H * (C.CY / C.BH)
        # v17.9: hover reaction - the eyes widen a little when the pointer
        # rests on the pet (only in the calm states)
        hov = 0.0
        if cfg.get('hover_react') and have_ptr and state in ('idle', 'happy') \
                and abs(mx - fcx) <= W * 0.55 and abs(my - fcy) <= H * 0.55:
            hov = 1.0
        sc = self.scale
        track = cfg['track']
        if state == 'sleep':
            self.lx *= 0.90
            self.ly *= 0.90
        else:
            if track != 'off' and have_ptr and now - self.ptr_t < 12.0:
                dx, dy = mx - fcx, my - fcy
                self.tx = 3.3 * math.tanh(dx / (240.0 * sc))
                self.ty = 2.7 * math.tanh(dy / (280.0 * sc))
                self.next_wander = now + 2.0
            elif now > self.next_wander:
                if cfg.get('eye_wander', True):
                    self.tx = random.uniform(-1.8, 1.8)
                    self.ty = random.uniform(-0.8, 1.4)
                    if spec is None and cfg.get('silence_pose') == 'look':
                        self.next_wander = now + random.uniform(1.2, 2.4)
                    else:
                        self.next_wander = now + random.uniform(2.5, 5.0)
                else:
                    self.next_wander = now + 2.0
                    self.tx *= 0.86
                    self.ty *= 0.86
            self.lx += (self.tx - self.lx) * 0.20
            self.ly += (self.ty - self.ly) * 0.20
            if self.home is not None:
                try:
                    self.home.drive_pet(dt, have_ptr, mx, my, fcx, fcy, track)
                except Exception:
                    self._home_error('drive')
            elif track in ('chase_slow', 'chase_fast') and have_ptr and not self.press:
                self.chase(dt, mx, my, fcx, fcy, 1.6 if track == 'chase_slow' else 4.8)

        # --- floating/bobbing ---
        _dam = max(0.0, float(cfg.get('dance_amt', 1.0)))
        if state == 'dance':
            bob = _dam * 1.1 * math.sin(t * 6.0) - 1.6 * peff
        elif state == 'sleep':
            bob = 0.35 * math.sin(t * 0.9)
        else:
            bob = 0.55 * math.sin(t * 2.1) - _dam * 1.2 * peff

        # --- equalizer bars ---
        # (the whole block is guarded: a shape error from any source resets
        #  the bar state instead of killing the animation loop - this was
        #  the "operands could not be broadcast together" crash)
        try:
            if self.lens is None or len(self.lens) != n:
                self.lens = np.full(n, 2.0)
                self.peaks = np.full(n, 2.0)
                self.peak_hold = np.zeros(n)
            if self._phase is None or self._phase_n != n:
                self._phase = np.arange(n, dtype=float) * (0.35 * 96.0 / n)
                self._phase_n = n
            self.rot += cfg['rotate'] * 12.0 * dt * (n / 96.0)
            pos = C.band_pos_arr(n, self.rot, cfg['layout'])
            demo = False
            if spec is not None and state != 'sleep':
                if cfg.get('eq_mirror'):          # v17.9: symmetric bars
                    spec = (spec + spec[::-1]) * 0.5
                tgt = np.interp(pos * (C.NB - 1), self._bidx, spec)
            else:
                # v16.2: the ring is an equalizer of the SYSTEM sound only.
                # The old demo wave is gone: with no system audio the ring
                # rests on the calm breathing base until real audio arrives.
                tgt = np.zeros(n)
            self._demo_eq = demo
            # bar base: calm breathing; the system spectrum rides on it
            base = 1.85 + 0.45 * math.sin(t * 1.5)
            mxl = (C.RAY_MAX_DOTS - 3.2) * cfg['ray_len']
            target = base + tgt * mxl
            if spec is not None and state != 'sleep':
                target = target + peff * (2.0 + 1.8 * tgt)      # the whole ring punches on the beat
            if state == 'sleep':
                target = np.full(n, 1.35) + 0.30 * math.sin(t * 0.8)
            fall = (60.0 - 45.0 * cfg['smooth']) * max(0.1, float(cfg.get('eq_fall', 1.0)))
            rise = target > self.lens
            self.lens = np.where(rise, self.lens + (target - self.lens) * 0.75,
                                 np.maximum(target, self.lens - fall * dt))
            self.lens = np.minimum(self.lens, C.RAY_MAX_DOTS - 0.01)
            if cfg.get('eq_wave'):                # v17.9: smooth wave mode
                self.lens = (0.25 * np.roll(self.lens, 1) + 0.5 * self.lens
                             + 0.25 * np.roll(self.lens, -1))
            # peak caps (hold briefly, then fall gently)
            hit = self.lens >= self.peaks
            self.peaks = np.where(hit, self.lens, self.peaks)
            self.peak_hold = np.where(hit, float(cfg.get('peak_hold_t', 0.28)), self.peak_hold - dt)
            self.peaks = np.where((~hit) & (self.peak_hold <= 0.0), self.peaks - 11.0 * dt, self.peaks)
            self.peaks = np.maximum(self.peaks, self.lens)
        except Exception:
            # never let the equalizer freeze the pet: full safe reset
            import traceback
            self._eq_err_n = getattr(self, '_eq_err_n', 0) + 1
            if self._eq_err_n <= 3 or self._eq_err_n % 50 == 0:
                _write_log('equalizer bar error (reset) #%d\n%s'
                           % (self._eq_err_n, traceback.format_exc()))
            self.lens = np.full(n, 2.0)
            self.peaks = np.full(n, 2.0)
            self.peak_hold = np.zeros(n)
            self._phase = np.arange(n, dtype=float) * (0.35 * 96.0 / n)
            self._phase_n = n
            self._demo_eq = False

        # --- colors ---
        mode = cfg['color_mode']
        rgb1, rgb2 = tuple(cfg['rgb1']), tuple(cfg['rgb2'])
        t_h = t * max(0.0, float(cfg.get('hue_speed', 1.0)))    # v17.9: hue cycle speed
        accent = C.accent_color(mode, rgb1, rgb2, t_h, bass)
        if mode == 'solid' or mode == 'gradient':
            key = (mode, rgb1, rgb2, n)
            if self._rc_cache is None or self._rc_cache[0] != key:
                self._rc_cache = (key, C.ray_colors(mode, n, rgb1, rgb2))
            ray_rgb = self._rc_cache[1]
        else:
            ray_rgb = C.ray_colors(mode, n, rgb1, rgb2, t_h, bass)
        self._ray_rgb = ray_rgb
        self._accent_now = accent

        # --- face parameters ---
        if state != 'hungry':
            self.face_icon = None
        face_kw = dict(state=state, blink=blink, lx=self.lx, ly=self.ly, bob=bob, cheek=0.75,
                       bounce=self.bx, talk=talk, bamt=cfg['bounce_amt'], mouth=mouth_ov,
                       anim=t, icon=self.face_icon)
        dim = 1.0
        if state == 'sleep':
            if cfg.get('zzz_fx', True):            # v17.9: the Zzz can be switched off
                face_kw['zz'] = (t % 2.8) / 2.8
            face_kw['cheek'] = 0.30
            dim = 0.42
        elif state in ('dance', 'happy', 'love', 'frown'):
            face_kw['cheek'] = 1.0
        elif state == 'dizzy':
            face_kw['wig'] = min(1.0, (0.5 + 0.5 * math.sin(t * 9.0)) * float(cfg.get('dizzy_amt', 1.0)))
            face_kw['cheek'] = 0.6
        elif state == 'surprised':
            face_kw['cheek'] = 0.5
        if state == 'love':
            face_kw['pulse'] = 0.78 + 0.22 * math.sin(t * 9.0)
        if state in C.CHEEK_OF:                      # newer states (v13)
            face_kw['cheek'] = C.CHEEK_OF[state]
        if state == 'star':
            face_kw['pulse'] = 0.80 + 0.20 * math.sin(t * 7.0)

        # v17.9: brightness moods - breathing body, calm silence, beat flash
        if cfg.get('body_pulse') and state != 'sleep':
            dim *= (0.93 + 0.07 * math.sin(t * 1.4))
        if cfg.get('silence_pose') == 'calm' and state == 'idle' and spec is None:
            dim *= 0.80
        if cfg.get('beat_flash'):
            dim = min(1.30, dim + 0.28 * peff)

        # --- particles and ripples ---
        sp_out = []
        if self.sparks:
            keep = []
            for sp in self.sparks:
                sp[4] += dt
                if sp[4] >= sp[5]:
                    continue
                k = 0.992 ** (dt * 60.0)
                sp[2] *= k
                sp[3] *= k
                sp[0] += sp[2] * dt
                sp[1] += sp[3] * dt
                keep.append(sp)
                sp_out.append((sp[0], sp[1], 1.0 - sp[4] / sp[5], sp[6], sp[7]))
            self.sparks = keep
        rip = None
        if self.ripples:
            self.ripples = [r for r in self.ripples if now - r[2] < 1.2]
            # the birth ripples play even when the ripple switch is off
            # (bounded by _birth_fx_until)
            if cfg['ripples'] or now < self._birth_fx_until:
                rip = C.ripple_cells(self.ripples, now)

        # --- v17: bubble / jelly body + eye options (LEDPET_V17_BODY) ---
        blob = None
        if np is not None:
            try:
                if cfg.get('blob', True) and state != 'sleep':
                    px_, py_ = float(self.wx), float(self.wy)
                    if self._bprev is None:
                        self._bprev = (px_, py_)
                    vx = (px_ - self._bprev[0]) / dt
                    vy = (py_ - self._bprev[1]) / dt
                    self._bprev = (px_, py_)
                    ak = 1.0 - math.exp(-dt * 14.0)
                    self._bvx += (vx - self._bvx) * ak
                    self._bvy += (vy - self._bvy) * ak
                    spd = math.hypot(self._bvx, self._bvy)
                    if spd > 40.0:
                        self._bux, self._buy = self._bvx / spd, self._bvy / spd
                    amt = max(0.0, cfg.get('blob_stretch', 1.0))
                    tgt = math.tanh(spd / (380.0 * max(0.3, self.scale))) * 0.15 * amt
                    tgt += 0.05 * amt * peff
                    if cfg.get('drag_squish') and self.press:   # v17.9: extra squish while dragging
                        tgt += 0.10
                    nst = max(1, int(dt / 0.01) + 1)
                    hh = dt / nst
                    for _i in range(nst):
                        self.blob_v += (300.0 * (tgt - self.blob_s) - 15.0 * self.blob_v) * hh
                        self.blob_s += self.blob_v * hh
                    self.blob_s = clamp(self.blob_s, -0.26, 0.26)
                    blob = dict(st=self.blob_s, ux=self._bux, uy=self._buy,
                                lx=self.lx / 3.3, ly=self.ly / 2.7,
                                wob=max(0.0, cfg.get('blob_wobble', 1.0)),
                                ph=t * max(0.05, float(cfg.get('wobble_speed', 1.0))),
                                lean=8.0 * max(0.0, cfg.get('blob_lean', 1.0)))
                else:
                    self._bprev = None
                    self.blob_s *= 0.9
                    self.blob_v = 0.0
            except Exception:
                blob = None
            # v17.9: bass zoom works with AND without the bubble body
            if cfg.get('bass_zoom') and bass > 0.01 and state != 'sleep':
                if blob is not None:
                    blob['zoom'] = 0.05 * bass
                else:
                    blob = dict(st=0.0, ux=1.0, uy=0.0, lx=0.0, ly=0.0, wob=0.0,
                                ph=0.0, lean=0.0, zoom=0.05 * bass)
        face_kw['eo'] = dict(count=int(cfg.get('eye_count', 2)), size=cfg.get('eye_size', 1.0),
                             gap=cfg.get('eye_gap', 1.0), pupil=cfg.get('pupil', 'none'),
                             pupil_size=cfg.get('pupil_size', 1.0),
                             pupil_follow=cfg.get('pupil_follow', True),
                             pupil_cmode=cfg.get('pupil_cmode', 'dark'),
                             glint=cfg.get('pupil_glint', False),
                             iris=cfg.get('iris', 'none'),             # v18.1
                             iris_size=cfg.get('iris_size', 1.0),      # v18.1
                             mouth=bool(cfg.get('show_mouth', True)),
                             cheeks=bool(cfg.get('show_cheeks', True)),
                             panim=t, hov=hov,
                             micv=(max(0.0, min(1.0, float(self.m_open)))
                                   if (cfg.get('mic_react_eyes') and cfg['mic'] and self.mic_ok
                                       and state != 'sleep') else 0.0))
        # v17.5: fresh per-frame dict build_face reports the eye / pupil /
        # glint cells into - the renderer needs it to paint the custom
        # eye / pupil colors (which it never did before - the settings
        # existed but had no effect).
        face_kw['ex'] = {}
        eye_rgb = tuple(cfg['eye_rgb']) if cfg.get('eye_cmode') == 'custom' else None
        pupil_rgb = tuple(cfg['pupil_rgb']) if cfg.get('pupil_cmode') == 'custom' else None

        # --- render and present ---
        colon = (int(now * 2) % 2 == 0)
        clock = None
        # during the birth morph the pet's own clock stays OFF - the
        # bitmap scales around the body, so a baked-in clock would float
        # over the header as ghost text mid-grow.  It comes back exactly
        # at the unveil (masked by the landing kiss).
        if cfg['clock'] and self._morph is None:
            if cfg['clock_secs']:
                fmt = '%I:%M:%S' if cfg['clock12'] else '%H:%M:%S'
            else:
                fmt = '%I:%M' if cfg['clock12'] else '%H:%M'
            clock = time.strftime(fmt)
        S = dict(accent=accent, ray_rgb=ray_rgb, lens=self.lens.tolist(),
                 peaks=(self.peaks.tolist() if cfg['peaks'] else None),
                 face=face_kw, clock=clock, colon=colon, dim=dim,
                 beat=peff, bass=(bass if state != 'sleep' else 0.0),
                 glow=cfg['glow'], ripple=rip, sparks=sp_out,
                 blob=blob, eye_rgb=eye_rgb, pupil_rgb=pupil_rgb,
                 # v18.1 (LEDPET_V18_CUSTOM): iris / cheeks / clock colors + 2nd fill
                 iris_rgb=(tuple(cfg['iris_rgb']) if cfg.get('iris', 'none') != 'none' else None),
                 cheek_rgb=tuple(cfg.get('cheek_rgb', (255, 52, 52))),
                 clock_cmode=cfg.get('clock_cmode', 'accent'),
                 clock_rgb=tuple(cfg.get('clock_rgb', (255, 255, 255))),
                 fill_rgb2=tuple(cfg.get('fill_rgb2', (30, 34, 60))),
                 body_fill=bool(cfg.get('body_fill', False)),
                 fill_rgb=tuple(cfg.get('body_fill_rgb', (0, 0, 0))),
                 # v17.9: the look / body options ride on the scene dict
                 t=t,
                 dot_size=float(cfg.get('dot_size', 1.0)),
                 dot_style=cfg.get('dot_style', 'circle'),
                 edge_fade=bool(cfg.get('edge_fade', False)),
                 body_outline=bool(cfg.get('body_outline', False)),
                 outline_rgb=tuple(cfg.get('outline_rgb', (90, 220, 255))),
                 outline_cycle=bool(cfg.get('outline_cycle', False)),
                 ring_pulse=bool(cfg.get('ring_pulse', False)),
                 comet=bool(cfg.get('comet', False)),
                 scan_dot=bool(cfg.get('scan_dot', False)),
                 rain_fx=bool(cfg.get('rain_fx', False)),
                 fireflies=bool(cfg.get('fireflies', False)),
                 fill_opacity=int(cfg.get('fill_opacity', 100)),
                 fill_style=cfg.get('fill_style', 'solid'))
        pm = self.ren.frame(S)
        self.last_pm = pm
        ok = False
        if self._morph is not None:      # v1.0: grow out of the happy dot
            try:
                ok = self._morph_present(pm, now)
            except Exception:
                ok = False
        elif self.naming is None:        # v1.0: stay hidden while naming
            try:
                ok = self.layer.present(pm, self.wx, self.wy)
            except Exception:
                ok = False
        if ok:
            self.present_fail = 0
        else:
            # during the naming dialog / the birth morph the pet
            # deliberately presents nothing (it is hidden while the egg
            # charges) - that silence must NOT count as presentation
            # failures, or the layer gets swapped to the Tk chroma fallback
            # mid-flow for no reason (and back via self-heal afterwards).
            if self.naming is None and self._morph is None:
                self.present_fail += 1
                if self.present_fail in (1, 5, 15):
                    _write_log('present failed (try %d)' % self.present_fail)
                if self.present_fail >= 15 and self._win32_active:
                    _write_log('fallback to TkLayer (chroma-key)')
                    try:
                        self.layer.close()
                    except Exception:
                        pass
                    self.layer = TkLayer(self.root, self.ren.W, self.ren.H)
                    self._win32_active = False
                    self.present_fail = 0

        # --- the Win32 self-heal -----------------------------------------
        # If the pet is riding the Tk chroma fallback, quietly give the
        # REAL alpha layer another chance every few seconds - a transient
        # UpdateLayeredWindow failure (typical around the naming morph -
        # the pet window is resized dozens of times per second - or after
        # a "Reset name") must not strand the pet on the fallback forever.
        # While it IS on the fallback, TkLayer.present renders the pet
        # exactly like the real alpha layer (white glow stays white).
        if (IS_WINDOWS and Win32Layer is not None and not self._win32_active
                and self.last_pm is not None and self.naming is None
                and self._morph is None and now >= self._tk_retry_at):
            self._tk_retry_at = now + 5.0
            nl = None
            try:
                nl = Win32Layer(self.hwnd, self.ren.W, self.ren.H)
                ok = False
                try:
                    ok = bool(nl.present(self.last_pm, self.wx, self.wy))
                except Exception:
                    ok = False
                if ok:
                    try:
                        self.layer.close()           # remove the Tk label
                    except Exception:
                        pass
                    self.layer = nl
                    self._win32_active = True
                    self.present_fail = 0
                    nl = None
                    _write_log('Win32 alpha layer restored '
                               '(pet left the Tk chroma fallback)')
            except Exception:
                pass
            if nl is not None:
                try:
                    nl.close()
                except Exception:
                    pass

        if self.home is not None:
            try:
                self.home.tick(now, dt)
                self._home_errs = 0
            except Exception:
                self._home_error('tick')

        if self.selftest_secs is not None and now - self.t0 >= self.selftest_secs:
            self._selftest_dump()
            return

        # --- automatic quality reduction on slow systems ---
        ms = (time.time() - now) * 1000.0
        self.frame_ms = self.frame_ms * 0.9 + ms * 0.1
        if cfg['quality'] == 'auto' and now - self.t0 > 4:
            limit = 1000.0 / max(10, cfg['fps']) * 1.25
            if self.frame_ms > limit:
                self.slow_count += 1
            else:
                self.slow_count = 0
            if self.slow_count > 8:
                self.slow_count = 0
                if self.ren.ss == 2:
                    self.ss_run = 1
                    self.ren = self._make_renderer()
                elif self.ren.bloom:
                    self.bloom_run = False
                    self.ren = self._make_renderer()

    # ----------------------- home frame (v13) -----------------------
    def ensure_home(self):
        """creates/closes the home frame per settings; errors never hurt the pet"""
        if self.cfg.get('home', True):
            if self.home is None:
                try:
                    from home_window import HomeFrame
                    self.home = HomeFrame(self)
                except Exception:
                    import traceback
                    _write_log('home frame failed to start\n' + traceback.format_exc())
                    self.home = None
        elif self.home is not None:
            h, self.home = self.home, None
            try:
                h.close()
            except Exception:
                pass
            self.save_now()

    # ---------------- v1.0 (LEDPET_V1_NAME): the naming flow ----------------
    def _begin_naming(self):
        """hide the pet and show the centered 'give me a name' frame
        (a mini home frame with a wiggling happy LED dot)"""
        try:
            self.root.withdraw()
        except Exception:
            pass
        try:
            if self.home is not None:
                self.home.close()
        except Exception:
            pass
        self.home = None
        try:
            from name_window import NameDialog
            self.naming = NameDialog(
                self.root, on_done=self._name_done,
                make_layer=self.make_layer_for,
                accent=tuple(self.cfg.get('rgb1', (246, 246, 246))))
            _write_log('naming dialog shown (first run)')
        except Exception:
            import traceback
            _write_log('naming dialog failed\n' + traceback.format_exc())
            self.naming = None
            self._name_done(self.name)   # never trap the user without a pet

    def _name_done(self, nm):
        """DONE pressed -> remember the name; v1.0 (LEDPET_V1_MORPH) the
        little frame GROWS into the home frame and the happy dot GROWS
        into the pet (no popping).  If anything fails the old plain path
        still runs - the user is never trapped without a pet."""
        nm = C.sanitize_name(nm)
        dlg = self.naming
        if dlg is not None and not dlg.closed:
            self.name = nm               # keep the name even if the morph fails
            self.cfg['name'] = nm
            try:
                if self._start_morph(dlg, nm):
                    _write_log('pet named: %r (morph)' % nm)
                    return True
            except Exception:
                import traceback
                _write_log('naming morph failed\n' + traceback.format_exc())
        self.naming = None
        self._morph = None
        self.name = nm
        self.cfg['name'] = nm
        self.save_now()
        try:
            self.root.deiconify()
        except Exception:
            pass
        self.apply_topmost()
        self.ensure_home()
        _write_log('pet named: %r' % nm)
        return False

    def _start_morph(self, dlg, nm):
        """v1.0 (LEDPET_V1_MORPH): the animated hand-over.  The naming
        frame is a MINI home frame, so it literally grows into the real
        one: the home bitmap starts at the dialog's rect (same centre) and
        expands while the dialog fades out; the happy dot grows into the
        pet with a springy pop right where it sits, then the pet is docked
        exactly in the home's slot.  Returns True when the morph took over
        (the dialog stays alive until the last frame)."""
        if not self.cfg.get('home', True):
            return False
        import name_window as NW
        import home_render as HR
        import home_logic as HL
        from home_window import HomeFrame
        # the pet becomes visible RIGHT NOW - it grows out of the dot while
        # the frame grows into the home (nothing is ever just spawned)
        try:
            self.root.deiconify()
        except Exception:
            pass
        self.apply_topmost()
        # a reset leaves the pet window holding its LAST presented frame,
        # and the tick loop presents nothing during the CHARGE - wipe the
        # layer with one fully transparent frame NOW so no stale pet frame
        # is ever visible: the window stays invisible until the newborn
        # pops into it at the burst.
        if getattr(self, 'layer', None) is not None:
            try:
                self.layer.present(Image.new('RGBA', (self.ren.W, self.ren.H),
                                             (0, 0, 0, 0)),
                                   self.wx, self.wy)
            except Exception:
                pass
        s = self.ren.W / float(C.BW)
        ss = 1 if self.cfg.get('quality') == 'low' else 2
        hren = HR.HomeRenderer(s, ss=ss)
        HW, HH = hren.W, hren.H
        try:
            sw = self.root.winfo_screenwidth()
            sh = self.root.winfo_screenheight()
        except Exception:
            sw, sh = 1920, 1080
        # same centre as the naming frame (the box 'becomes' the home)
        mcx = dlg.x + dlg.W / 2.0
        mcy = dlg.y + dlg.H / 2.0
        hx = int(round(mcx - HW / 2.0))
        hy = int(round(mcy - HH / 2.0))
        hx = (sw - HW) // 2 if sw <= HW + 16 else max(8, min(sw - HW - 8, hx))
        hy = (sh - HH) // 2 if sh <= HH + 16 else max(8, min(sh - HH - 8, hy))
        slot = (hx, hy + int(round(HR.PET_OFF[1] * hren.kf)))
        self.wx, self.wy = int(slot[0]), int(slot[1])
        self.fx, self.fy = float(slot[0]), float(slot[1])
        self.home = HomeFrame(self, veil=True, at=(hx, hy))
        # --- the intro bitmap: what the real frame will show at hand-over
        # (same brand / needs / greeting cells -> a pixel-seamless swap) ---
        # the pet is BORN, not just grown.  The timeline (seconds from t0):
        #   0.00-0.80  CHARGE  the happy dot IS the egg: on the dialog it
        #                      freezes at its centre, its heartbeat
        #                      accelerates, it squints + shivers, LED rings
        #                      ripple out and a white core charges up.
        #                      The pet window stays HIDDEN the whole time.
        #   0.80       BURST   a SHORT white flash + LED shockwave, and
        #                      the newborn pops out of the dot with a
        #                      springy jelly grow (pops OVER the flash,
        #                      never inside it)
        #   0.80-1.58  GROW    the dialog frame blooms into the home frame
        #                      (the hatch frame crossfades out in 0.12 s,
        #                      masked by the flash)
        #   1.58       LAND    the pet docks, one more spark kiss + hop
        T_CHARGE, T_GROW, T_HOME_IN, T_DLG_FADE, T_END = \
            0.80, 0.78, 0.32, 0.12, 1.58
        # the burst flash: a SHORT bright pop - gone in 0.14 s, tight
        # around the dot - so the newborn stays clearly visible.
        T_FLASH = 0.14
        accent = tuple(int(v) for v in self.cfg.get('rgb1', (246, 246, 246)))
        accent = tuple(getattr(self, '_accent_now', None) or accent)
        disp = HL.Display()
        now0 = time.time()
        disp.say(('HI ' + nm) if nm else 'HELLO!', now0, 2.8)
        needs = HL.Needs(float(self.cfg.get('n_food', 0.8)),
                         float(self.cfg.get('n_water', 0.8)),
                         float(self.cfg.get('n_fun', 0.7))).v
        home_full = hren.frame(dict(t=0.0, accent=accent,
                                    brand=(nm or 'LED PET').upper(),
                                    needs=needs,
                                    # the cells the REAL frame will show at
                                    # hand-over (scroll position predicted)
                                    cells=disp.cells(now0 + T_END),
                                    items=(), away=False, hover=None,
                                    pressed=None, disabled=(), active=()))
        # --- the pet's birth: from the happy dot (the egg) to the dock ---
        dcx, dcy = dlg.dot_screen()
        tcx = slot[0] + (C.CX / float(C.BW)) * self.ren.W
        tcy = slot[1] + (C.CY / float(C.BH)) * self.ren.H
        dot_d = 2.0 * NW.DISC_R * NW.DISC_P * dlg.kf
        pet_d = (2.0 * C.R / float(C.BW)) * self.ren.W
        # the newborn pops out at HALF size at least - smaller and
        # the glowing eyes read as a blob before the body is visible
        s0 = clamp(dot_d / max(1.0, pet_d), 0.50, 0.9)
        self._morph = dict(t0=time.time(), dur=0.60, s0=s0,
                           x0=dcx, y0=dcy, x1=tcx, y1=tcy,
                           charge=T_CHARGE, burst=False, last_img=None)
        # --- the dialog-side: the hatching scene, then the grow ---
        DW_, DH_ = dlg.W, dlg.H
        sizes = {}

        def _morph_frame(now):
            m = self._morph
            if m is None:
                self._morph_finish(dlg)
                return None
            t = now - m['t0']
            if t >= T_END or self.home is None or self.home.closed:
                self._morph_finish(dlg)
                return None
            try:
                # ---- phase 1: the CHARGE.  The dialog
                # stays at its own place and plays the hatching scene (the
                # happy dot IS the egg); the pet window shows NOTHING yet.
                if t < T_CHARGE:
                    S = dict(t=now, accent=accent, name=nm, hover=False,
                             pressed=False, birth=t, charge=T_CHARGE)
                    img = dlg.ren.frame(S)
                    m['last_img'] = img          # the burst crossfades THIS
                    return (img, dlg.x, dlg.y)
                # ---- phase 2: the frame blooms into the home, the last
                # hatching frame (plus the white flash) fades away ----
                tg = t - T_CHARGE
                e = _ease_out_cubic(clamp(tg / T_GROW, 0.0, 1.0))
                w = max(8, int(round(DW_ + (HW - DW_) * e)))
                h = max(8, int(round(DH_ + (HH - DH_) * e)))
                hs = sizes.get((w, h))
                if hs is None:
                    hs = home_full.resize((w, h), Image.NEAREST)
                    sizes[(w, h)] = hs
                kh = _ease_out_cubic(clamp(tg / T_HOME_IN, 0.0, 1.0))
                if kh < 1.0:
                    hs = hs.point(_pm_lut(kh))
                kd = 1.0 - clamp(tg / T_DLG_FADE, 0.0, 1.0)
                canvas = hs
                if kd > 0.0 and m.get('last_img') is not None:
                    base = Image.new('RGBA', (w, h), (0, 0, 0, 0))
                    dl = (m['last_img'] if kd >= 1.0
                          else m['last_img'].point(_pm_lut(kd)))
                    base.paste(dl, ((w - DW_) // 2, (h - DH_) // 2))
                    canvas = _pm_over(hs, base)
                # the birth flash: ONE short bright pop right at the dot
                # (radius ~1.6x the dot, alpha falls with fk^2) + one CRISP
                # LED shockwave that starts at the dot's edge and
                # decelerates (ease-out) while it fades.
                if tg < T_FLASH:
                    fk = 1.0 - tg / T_FLASH
                    fov = Image.new('RGBA', (w, h), (0, 0, 0, 0))
                    fd = ImageDraw.Draw(fov)
                    fx = dcx - (mcx - w / 2.0)
                    fy = dcy - (mcy - h / 2.0)
                    fr = dot_d * (0.80 + 0.80 * (1.0 - fk)) * dlg.kf
                    fa = int(245 * (fk * fk))
                    if fa > 0:
                        fd.ellipse([fx - fr, fy - fr, fx + fr, fy + fr],
                                   fill=(255, 255, 255, fa))
                    tk_ = tg / 0.30           # the LED shockwave ring
                    if tk_ < 1.0:
                        ee = 1.0 - (1.0 - tk_) ** 2.2      # ease-out
                        rr = dot_d * 0.55 + ee * (HW * 0.55)
                        fd.ellipse([fx - rr, fy - rr, fx + rr, fy + rr],
                                   outline=accent +
                                   (max(0, int(190 * (1.0 - tk_) ** 1.8)),),
                                   width=max(1, int(round(2.2 * dlg.kf))))
                    fpm = Image.frombytes('RGBA', fov.size,
                                          fov.convert('RGBa').tobytes())
                    canvas = _pm_over(fpm, canvas)
                return (canvas, mcx - w / 2.0, mcy - h / 2.0)
            except Exception:
                import traceback
                _write_log('morph frame failed\n' + traceback.format_exc())
                self._morph_finish(dlg)
                return None

        dlg.start_morph(_morph_frame)
        # the growing home bitmap must render UNDER the growing pet (the
        # dialog window was created above it) - slot it directly below the
        # pet window, exactly where the real home frame lives later
        try:
            self.place_below(getattr(dlg, 'hwnd', None))
        except Exception:
            pass
        return True

    def _morph_present(self, pm, now):
        """the pet's own side of the BORN morph.
        During the CHARGE the pet stays HIDDEN - the happy dot on the
        naming frame IS the egg.  At the BURST the shell breaks - the
        newborn smiles - and the pet pops out of the dot: alpha in, then
        a springy jelly grow to the docked size while it glides from the
        dot to its slot in the home frame."""
        m = self._morph
        t = now - m['t0']
        charge = float(m.get('charge', 0.0))
        # ---- the BURST one-shot: the moment the shell breaks.  Only the
        # mood flips here (the newborn smiles) - the celebration FX live
        # where they are actually visible: the flash + shockwave on the
        # dialog frame at the shell-break and the landing kiss at full size.
        if not m.get('burst') and t >= charge:
            m['burst'] = True
            try:
                self.set_mode('happy', 1.5)      # the newborn smiles
            except Exception:
                pass
        if t < charge:
            # ---- the egg phase: the pet is NOT on screen yet (still
            # report success so the layer's fail counter stays quiet) ----
            return True
        p = (t - charge) / float(m.get('dur', 0.60))
        if p >= 1.0:
            # grown up: present normally - the state stays until the dialog
            # engine finishes the whole morph (_morph_finish clears it)
            try:
                return self.layer.present(pm, self.wx, self.wy)
            except Exception:
                return False
        p = max(0.0, p)
        s = m['s0'] + (1.0 - m['s0']) * _ease_out_back(p)
        # the jelly wobble of a newborn (has settled away by the docking)
        wob = math.sin(p * 15.0) * math.exp(-p * 2.4) * 0.11
        sy = 1.0 + wob
        sx = 1.0 - 0.72 * wob
        e = _ease_out_cubic(p)
        w = max(8, int(round(self.ren.W * s * sx)))
        h = max(8, int(round(self.ren.H * s * sy)))
        img = pm.resize((w, h), Image.NEAREST)
        k = clamp((t - charge) / 0.06, 0.0, 1.0)   # pops in, no long fade
        if k < 1.0:
            img = img.point(_pm_lut(k))
        ax = m['x0'] + (m['x1'] - m['x0']) * e
        ay = m['y0'] + (m['y1'] - m['y0']) * e
        x = int(round(ax - (C.CX / float(C.BW)) * w))
        y = int(round(ay - (C.CY / float(C.BH)) * h))
        try:
            return self.layer.present(img, x, y)
        except Exception:
            return False

    def _morph_finish(self, dlg):
        """the last morph frame is on screen: swap in the real home frame
        (pixel-identical), dock the pet and save - nothing can jump"""
        self.naming = None
        self._morph = None
        try:
            dlg.close()
        except Exception:
            pass
        try:
            if self.home is not None:
                self.home.unveil()
        except Exception:
            pass
        try:
            self.save_now()
        except Exception:
            pass
        try:
            self.kick(0.6)               # a happy little landing hop
        except Exception:
            pass
        # the landing kiss - one more soft burst of sparks
        # and a ripple ring right where the newborn docked
        try:
            self.spawn_sparks(14, origin=(C.CX, C.CY))
            self.ripples.append((C.HALF, C.HALF, time.time(), 0.80))
            self._birth_fx_until = time.time() + 1.3
        except Exception:
            pass
        _write_log('naming morph complete: pet docked %d,%d, home unveiled'
                   % (self.wx, self.wy))

    def reset_name(self):
        """v1.0 (LEDPET_V1_RESET): Settings -> Behavior -> Reset name is a
        FULL FACTORY RESET, not a name-only wipe.  Everything goes back to
        the shipped defaults - the name AND all settings (colors, size,
        shape, shortcuts, needs...) - the pet hides, the home frame closes
        and the first-run 'give me a name' frame appears again.  The
        Settings window warns about exactly this before calling here."""
        self.name = ''
        self.cfg = C.sanitize_cfg({})        # EVERYTHING back to the defaults
        self.cfg['name'] = ''
        self._rc_cache = None
        # v1.1 (LEDPET_V1_RESET2): the reset also wipes the pet's LIVE
        # state - nothing of the old pet may leak into the fresh one.
        # A pinned shortcut face (a pinned 'surprised' = wide-open eyes!),
        # leftover beat/ripple/spark particles and the last audio snapshots
        # used to survive the factory reset and could decorate the freshly
        # re-created pet with the pink rings the user kept reporting.
        self.hk_pin_state = None             # un-pin any shortcut face
        self.mode = 'idle'
        self.mode_until = 0.0
        self.m_pop_until = 0.0
        self.beat_t = -9.0
        self.beat_s = 0.0
        self.beat_seen = None                # no stale beat on the next start
        self.ripples = []
        self.sparks = []
        self.audio_ok = False                # no spectrum until a fresh start
        try:
            with self.spec_lock:
                self.a_bands = None
                self.a_level = 0.0
                self.a_bass = 0.0
                self.a_beat = 0
                self.a_bstr = 0.0
                self.a_t = 0.0
        except Exception:
            pass
        try:
            with self.mic_lock:
                self.m_open = 0.0
                self.m_wide = 0.0
                self.m_raw = 0.0
                self.m_t = 0.0
        except Exception:
            pass
        try:
            self.wx, self.wy = self.start_pos()
            self.fx, self.fy = float(self.wx), float(self.wy)
        except Exception:
            pass
        self.cfg_changed('scale')            # default size/shape/colors again
        self.cfg_changed('topmost')
        self.cfg_changed('audio')
        self.cfg_changed('mic')
        self.cfg_changed('hotkeys')          # default shortcuts again
        try:
            self.save_now()
        except Exception:
            pass
        try:
            if self.settings_win is not None:
                self.settings_win.destroy()
        except Exception:
            pass
        self.settings_win = None
        self._begin_naming()

    def _home_error(self, where):
        import traceback
        self._home_errs += 1
        _write_log('home error (%s) #%d\n%s' % (where, self._home_errs, traceback.format_exc()))
        try:
            if self.home is not None:
                self.home.cap = None
                self.home.pressed = None
        except Exception:
            pass
        if self._home_errs >= 12 and self.home is not None:
            h, self.home = self.home, None
            try:
                h.close()
            except Exception:
                pass
            _write_log('home frame disabled after repeated errors (the pet keeps running)')

    def make_layer_for(self, top, w, h, noactivate=True):
        """display layer for another Toplevel (home frame) -> (layer, hwnd)
        noactivate=True keeps the home frame's WS_EX_NOACTIVATE (click-only
        windows); keyboard windows (the v1.0 naming frame) pass False so
        they can take the focus and receive keystrokes on Windows."""
        layer, hwnd = None, None
        if IS_WINDOWS and Win32Layer is not None:
            try:
                wid = top.winfo_id()
                hwnd = user32.GetParent(wid)
                if not hwnd or not user32.IsWindow(hwnd):
                    hwnd = wid
                layer = Win32Layer(hwnd, w, h)
                if noactivate:
                    _set_exstyle(hwnd, _exstyle(hwnd) | 0x08000000)  # WS_EX_NOACTIVATE
            except Exception:
                layer = None
        if layer is None:
            layer = TkLayer(top, w, h)
        return layer, hwnd

    def place_below(self, hwnd):
        """keeps the frame exactly below the pet window in z-order"""
        if not (IS_WINDOWS and hwnd and self.hwnd):
            return
        # NOSIZE | NOMOVE | NOACTIVATE (argtypes are preset at module level)
        user32.SetWindowPos(hwnd, self.hwnd, 0, 0, 0, 0, 0x0013)

    def set_track(self, val):
        self.cfg['track'] = val
        if val in ('chase_slow', 'chase_fast'):
            self.cfg['follow_mode'] = val
        self.cfg_changed('track')

    def toggle_follow(self):
        """FOLLOW button: the pet leaves home and follows the mouse <-> comes back"""
        if self.cfg.get('track') in ('chase_slow', 'chase_fast'):
            self.cfg['track'] = 'eyes'
        else:
            self.cfg['track'] = self.cfg.get('follow_mode', 'chase_slow')
        self.cfg_changed('track')
        self.set_mode('happy', 1.2)
        self.kick(0.8)

    def show_expression(self, name):
        self.face_icon = 'food' if name == 'hungry' else None
        self.set_mode(name, 3.5)
        self.kick(0.8)

    def chase(self, dt, mx, my, fcx, fcy, rate):
        """the body drifts toward the mouse but never sits on it"""
        dx, dy = mx - fcx, my - fcy
        dist = math.hypot(dx, dy)
        want = (C.R + 80.0) * self.scale
        if dist < want * 1.2 or dist < 1.0:
            return
        ux, uy = dx / dist, dy / dist
        tcx, tcy = mx - ux * want, my - uy * want
        k = 1.0 - math.exp(-rate * dt)
        ncx = fcx + (tcx - fcx) * k
        ncy = fcy + (tcy - fcy) * k
        self.fx = ncx - self.ren.W / 2.0
        self.fy = ncy - self.ren.H * (C.CY / C.BH)
        self.wx, self.wy = int(round(self.fx)), int(round(self.fy))

    def _selftest_dump(self):
        try:
            if self.last_pm is not None:
                out = self.ren.composite_over(self.last_pm, (14, 15, 18))
                out.save(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                      'selftest_frame.png'))
            print('SELFTEST_OK')
        except Exception:
            print('SELFTEST_OK')
        self.quit()


# ============================== main =================================
def main():
    _write_log('LEDPET V1.0 (by THEGEM) starting (pid %d, py %s)'
               % (os.getpid(), sys.version.split()[0]))
    if IS_WINDOWS:
        try:
            ctypes_ = __import__('ctypes')
            ctypes_.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            try:
                import ctypes
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

    selftest_secs = None
    if '--selftest' in sys.argv:
        try:
            selftest_secs = float(sys.argv[sys.argv.index('--selftest') + 1])
        except Exception:
            selftest_secs = 4.0

    # --- v18.4 (LEDPET_V18_FIX): one LEDPet at a time ------------------
    # A second LEDPet process silently loses EVERY shortcut to the first
    # one (RegisterHotKey is first-come-first-own) and doubles the CPU /
    # audio load. The updater never kills the old copy, so this exact
    # state was easy to reach and looked like "no shortcut works".
    # A named mutex makes it visible: the new copy says so and exits.
    if IS_WINDOWS and selftest_secs is None:
        try:
            import ctypes
            _k32 = ctypes.WinDLL('kernel32', use_last_error=True)
            _k32.CreateMutexW.restype = ctypes.c_void_p
            _k32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int,
                                          ctypes.c_wchar_p]
            _mutex = _k32.CreateMutexW(None, 0, 'LEDPet.SingleInstance.Mutex')
            if ctypes.get_last_error() == 183:    # ERROR_ALREADY_EXISTS
                _write_log('single-instance: another LEDPet owns the mutex -> '
                           'this copy exits')
                try:
                    ctypes.windll.user32.MessageBoxW(
                        0, 'LEDPET V1.0 is already running.\n\n'
                           'Close the other LEDPET window first.\n'
                           '(If you cannot see it, end python.exe / pythonw.exe '
                           'in the Task Manager, then start LEDPET again.)',
                        'LEDPET V1.0', 0x40)
                except Exception:
                    pass
                return
            globals()['_HK_MUTEX'] = _mutex   # keep the handle for the process life
        except Exception:
            pass                                  # the guard must never block the start

    root = tk.Tk()
    try:
        app = LEDPet(root, selftest_secs=selftest_secs)
        root.mainloop()
    except Exception:
        import traceback
        err = traceback.format_exc()
        _write_log('=== fatal ===\n' + err)
        try:
            root.withdraw()
            from tkinter import messagebox
            messagebox.showerror(
                'LEDPET V1.0',
                'Startup error!\nFull details were saved to:\n'
                '%s\n\nPlease send this file.\n\n%s'
                % (LOG_FILE, err[-400:]))
        except Exception:
            pass
        raise


if __name__ == '__main__':
    main()
