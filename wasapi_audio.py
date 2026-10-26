#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# =====================================================================
#  wasapi_audio.py - native Windows audio capture (WASAPI), pure ctypes (v3)
#  ------------------------------------------------------------------
#  Needs no pip packages (numpy is optional too). Two modes:
#     mode='loopback'  <- system output (speakers) -> the equalizer
#     mode='mic'       <- microphone -> the pet's mouth
#
#  v2 hardening (built from the user's real error 0x800401F0):
#   1) explicit argtypes/restype for every ole32 call - no ctypes guessing
#   2) unsigned HRESULT + mapping of common errors for menu/log
#   3) COM ladder: if MTA hits CO_E_NOTINITIALIZED -> retry once with STA
#   4) if the "default" device is broken -> enumerate ALL active devices
#      of the same kind (EnumAudioEndpoints) and try them one by one
#   5) before each attempt: Windows Audio service + microphone privacy
#      are checked and reported
#  v3: English messages + silent-endpoint fallback - if the default
#      output stays silent for 6 s while other outputs exist, the
#      engine switches to the next one automatically (VB-Cable/HDMI etc.)
#   6) full step-by-step logging through the 'log' callback
#
#  v4 THE critical fix (real user bug, error log 2026-10-21):
#      WAVEFORMATEX / WAVEFORMATEXTENSIBLE were declared with natural
#      ctypes alignment, but Windows packs these structs to 1 byte.
#      Result: the SubFormat GUID was read 4 bytes too late, so the
#      modern 32-bit float mix format (EXTENSIBLE, tag=65534) was always
#      rejected with "mix format not supported" on EVERY device ->
#      WASAPI never delivered audio and the equalizer never reacted.
#      Both structs are now pack(1) and the format is parsed straight
#      from the raw bytes (immune to any alignment).
#
#  v5 (2026-10-21, sound test: 162 blocks but peak level 0.000):
#      The old silent-detection trusted only the AUDCLNT_BUFFERFLAGS_SILENT
#      flag. Many devices (virtual mixers like "7.1 Surround Sound", HDMI,
#      VB-Cable) deliver ZERO-FILLED packets WITHOUT that flag, so the
#      engine sat on a silent output forever and the equalizer never moved.
#      Now: 1) every output's IAudioMeterInformation peak is read and the
#      engine STARTS on the output that actually carries sound;
#      2) silence is detected by the real sample peak (flag or zeros);
#      3) a live meter watchdog switches to a louder output in ~3 s;
#      4) the Windows Audio service status no longer reports 'unknown'
#      (the advapi32 handles were truncated to 32-bit on x64).
#
#  v6 (2026-10-22, "equalizer dies after a short audio pause / toggle"):
#      The 6 s no-signal switch treated a normal MUSIC PAUSE as a dead
#      output: the output that actually played got blacklisted and the
#      engine wandered through the silent HDMI/digital/virtual outputs
#      (6 s each) -> the equalizer looked dead until the app restarted.
#      Now a "signal memory" (_signal_ids) remembers every output that
#      REALLY played the system sound: a proven output is never abandoned
#      on a pause and never blacklisted; only outputs that never played
#      anything get blacklisted; if every output ends up blacklisted the
#      list is forgotten. Recovery is instant when the sound comes back.
#  =====================================================================

import os
import struct
import time
import threading

IS_WINDOWS = (os.name == 'nt')
import ctypes
from ctypes import (POINTER, Structure, byref, c_void_p, c_uint8,
                    c_uint16, c_uint32, c_uint64, c_wchar_p, sizeof,
                    cast, string_at)
try:
    from ctypes import HRESULT          # Windows only
except ImportError:
    HRESULT = ctypes.c_long             # Linux (struct tests only)

# --------------------------- constants ---------------------------------
CLSCTX_ALL = 0x17
COINIT_APARTMENTTHREADED = 0x2
COINIT_MULTITHREADED = 0x0
RPC_E_CHANGED_MODE = 0x80010106
S_FALSE = 1
CO_E_NOTINITIALIZED = 0x800401F0

eRender = 0          # EDataFlow: playback device (for loopback)
eCapture = 1         # EDataFlow: recording device (microphone)
eConsole = 0         # ERole: default multimedia role
DEVICE_STATE_ACTIVE = 0x1

AUDCLNT_SHAREMODE_SHARED = 0
AUDCLNT_STREAMFLAGS_LOOPBACK = 0x00020000
AUDCLNT_BUFFERFLAGS_SILENT = 0x2

CLSID_MMDeviceEnumerator = '{BCDE0395-E52F-467C-8E3D-C4579291692E}'
IID_IMMDeviceEnumerator = '{A95664D2-9614-4F35-A746-DE8DB63617E6}'
IID_IAudioClient = '{1CB9AD4C-DBFA-4C32-B178-C2F568A703B2}'
IID_IAudioCaptureClient = '{C8ADBD64-E71E-48A0-A4DE-185C395CD317}'
IID_IAudioMeterInformation = '{C02216F6-8C67-4B5B-9D00-D008E73E0064}'

WAVE_FORMAT_PCM = 0x0001
WAVE_FORMAT_IEEE_FLOAT = 0x0003
WAVE_FORMAT_EXTENSIBLE = 0xFFFE

VT_EL_SLOT = 4          # IMMDeviceEnumerator::GetDefaultAudioEndpoint
VT_EL_ENUM = 3          # IMMDeviceEnumerator::EnumAudioEndpoints
VT_DEV_ACTIVATE = 3     # IMMDevice::Activate
VT_DEV_OPENPROPS = 4    # IMMDevice::OpenPropertyStore
VT_DEV_GETID = 5        # IMMDevice::GetId
VT_COLL_COUNT = 3       # IMMDeviceCollection::GetCount
VT_COLL_ITEM = 4        # IMMDeviceCollection::Item
VT_INIT, VT_GETMIXFORMAT, VT_START, VT_STOP, VT_GETSERVICE = 3, 8, 10, 11, 14
VT_GETBUFFER, VT_RELEASEBUFFER, VT_GETNEXTPACKET = 3, 4, 5
VT_PS_GETVALUE = 5      # IPropertyStore::GetValue
VT_METER_PEAK = 3       # IAudioMeterInformation::GetPeakValue (after IUnknown)

PKEY_Device_FriendlyName_FMT = '{a45c254e-df1c-4efd-8020-67d146a850e0}'
PKEY_Device_FriendlyName_PID = 14
VT_LPWSTR = 31

# ------------------- common error mapping (English) --------------------
_HR_TEXT = {
    CO_E_NOTINITIALIZED: 'Windows COM service is not available to this app',
    0x8007000E: 'system is low on memory',
    0x80070005: 'access to the audio device was denied',
    0x80070490: 'audio device not found (disconnected?)',
    0x80004005: 'unspecified Windows error',
    0x88890004: 'audio device disconnected/changed',
    0x88890008: 'device audio format is not supported',
    0x8889000A: 'audio device is busy with another app',
    0x8889000F: 're-creating the audio stream failed',
    0x88890018: 'Windows Audio service is not running',
}


def _u(hr):
    """signed ctypes HRESULT -> unsigned int for correct compares"""
    return int(hr) & 0xFFFFFFFF


def hr_fa(hr):
    """short English description for an HRESULT (or empty)"""
    return _HR_TEXT.get(_u(hr), '')


class OSErrorHR(OSError):
    """COM/WASAPI error carrying code + mapped description"""

    def __init__(self, what, hr):
        self.hr = _u(hr)
        msg = '%s = 0x%08X' % (what, self.hr)
        fa = hr_fa(self.hr)
        if fa:
            msg += ' — ' + fa
        OSError.__init__(self, msg)


class _SwitchDevice(Exception):
    """internal: the current output is silent, another output is playing"""
    pass


# ---------------- shared structs (also on Linux for tests) --------------
class GUID(Structure):
    _fields_ = [('Data1', c_uint32), ('Data2', c_uint16),
                ('Data3', c_uint16), ('Data4', c_uint8 * 8)]


class WAVEFORMATEX(Structure):
    # Windows packs the WAVEFORMATEX family to 1 byte (mmreg.h) ->
    # sizeof must be exactly 18, NOT the 20 that natural alignment gives!
    _pack_ = 1
    _fields_ = [('wFormatTag', c_uint16), ('nChannels', c_uint16),
                ('nSamplesPerSec', c_uint32), ('nAvgBytesPerSec', c_uint32),
                ('nBlockAlign', c_uint16), ('wBitsPerSample', c_uint16),
                ('cbSize', c_uint16)]


class WAVEFORMATEXTENSIBLE(Structure):
    # packed: wfx(18) + wValidBits(2) + dwChannelMask(4) + SubFormat(16) = 40
    _pack_ = 1
    _fields_ = [('wfx', WAVEFORMATEX), ('wValidBits', c_uint16),
                ('dwChannelMask', c_uint32), ('SubFormat', GUID)]


class PROPERTYKEY(Structure):
    _fields_ = [('fmtid', GUID), ('pid', c_uint32)]


class PROPVARIANT(Structure):
    # larger than the real PROPVARIANT (24 bytes) so it is always safe
    _fields_ = [('vt', c_uint16), ('res', c_uint16 * 3),
                ('p', c_uint64 * 3)]


if IS_WINDOWS:
    _ole32 = ctypes.windll.ole32
    _advapi32 = ctypes.windll.advapi32

    # ---------- explicit signatures for ole32 (no guessing) ----------
    _ole32.CoInitializeEx.argtypes = [c_void_p, c_uint32]
    _ole32.CoInitializeEx.restype = HRESULT
    _ole32.CoUninitialize.argtypes = []
    _ole32.CoUninitialize.restype = None
    _ole32.CoCreateInstance.argtypes = [POINTER(GUID), c_void_p, c_uint32,
                                        POINTER(GUID), POINTER(c_void_p)]
    _ole32.CoCreateInstance.restype = HRESULT
    _ole32.CLSIDFromString.argtypes = [ctypes.c_wchar_p, POINTER(GUID)]
    _ole32.CLSIDFromString.restype = HRESULT
    _ole32.CoTaskMemFree.argtypes = [c_void_p]
    _ole32.CoTaskMemFree.restype = None
    _ole32.PropVariantClear.argtypes = [POINTER(PROPVARIANT)]
    _ole32.PropVariantClear.restype = HRESULT

    _GUID_CACHE = {}

    def _guid(s):
        g = _GUID_CACHE.get(s)
        if g is None:
            g = GUID()
            hr = _ole32.CLSIDFromString(ctypes.c_wchar_p(s), byref(g))
            if hr != 0:
                raise OSErrorHR('CLSIDFromString(%s)' % s, hr)
            _GUID_CACHE[s] = g
        return g

    def _vtfunc(iface, index, restype, *atypes):
        """virtual function #index from a COM interface vtable"""
        if not iface:
            raise OSError('null COM interface')
        vt = cast(iface, POINTER(c_void_p)).contents.value
        if not vt:
            raise OSError('null COM vtable')
        addr = cast(vt + index * sizeof(c_void_p),
                    POINTER(c_void_p)).contents.value
        if not addr:
            raise OSError('null COM method (vtable slot %d)' % index)
        proto = ctypes.WINFUNCTYPE(restype, c_void_p, *atypes)
        return proto(addr)

    def _release(iface):
        """IUnknown::Release (vtable slot 2)"""
        try:
            if iface:
                _vtfunc(iface, 2, c_uint32)(iface)
        except Exception:
            pass

    # ---------------- Windows Audio service state ----------------
    class SERVICE_STATUS(Structure):
        _fields_ = [('dwServiceType', c_uint32), ('dwCurrentState', c_uint32),
                    ('dwControlsAccepted', c_uint32),
                    ('dwWin32ExitCode', c_uint32),
                    ('dwServiceSpecificExitCode', c_uint32),
                    ('dwCheckPoint', c_uint32), ('dwWaitHint', c_uint32)]

    # explicit signatures: SCM/service handles are POINTER-sized, but
    # without argtypes ctypes truncated them to 32-bit on x64 ->
    # OpenServiceW failed and the service always looked 'unknown' (v5 fix)
    _advapi32.OpenSCManagerW.argtypes = [c_wchar_p, c_wchar_p, c_uint32]
    _advapi32.OpenSCManagerW.restype = c_void_p
    _advapi32.OpenServiceW.argtypes = [c_void_p, c_wchar_p, c_uint32]
    _advapi32.OpenServiceW.restype = c_void_p
    _advapi32.QueryServiceStatus.argtypes = [c_void_p,
                                             POINTER(SERVICE_STATUS)]
    _advapi32.QueryServiceStatus.restype = ctypes.c_long
    _advapi32.CloseServiceHandle.argtypes = [c_void_p]
    _advapi32.CloseServiceHandle.restype = ctypes.c_long

    def audiosrv_state():
        """'running' / 'stopped' / 'unknown' for the Windows Audio service"""
        try:
            SC_MANAGER_CONNECT = 0x0001
            SERVICE_QUERY_STATUS = 0x0004
            SERVICE_RUNNING = 0x4
            adv = _advapi32
            h = adv.OpenSCManagerW(None, None, SC_MANAGER_CONNECT)
            if not h:
                return 'unknown'
            try:
                hs = adv.OpenServiceW(h, 'Audiosrv', SERVICE_QUERY_STATUS)
                if not hs:
                    return 'unknown'
                try:
                    st = SERVICE_STATUS()
                    if adv.QueryServiceStatus(hs, byref(st)):
                        return ('running' if st.dwCurrentState
                                == SERVICE_RUNNING else 'stopped')
                    return 'unknown'
                finally:
                    adv.CloseServiceHandle(hs)
            finally:
                adv.CloseServiceHandle(h)
        except Exception:
            return 'unknown'

    def mic_privacy_reason():
        """returns the reason if Windows blocks microphone access"""
        import winreg
        try:
            base = (r'SOFTWARE\Microsoft\Windows\CurrentVersion'
                    r'\CapabilityAccessManager\ConsentStore\microphone')
            for sub in ('', r'\NonPackaged'):
                try:
                    with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                        base + sub) as k:
                        v, _t = winreg.QueryValueEx(k, 'Value')
                        if str(v).strip().lower() == 'deny':
                            return ('Microphone access is disabled in Windows - '
                                    'Settings > Privacy > Microphone > '
                                    'turn on "Let desktop apps access"')
                except Exception:
                    pass
        except Exception:
            pass
        return ''

    def _dev_peak(dev):
        """IMMDevice -> IAudioMeterInformation::GetPeakValue (0..1).
        Works on render endpoints without opening a stream. 0.0 on error."""
        meter = c_void_p()
        try:
            f = _vtfunc(dev, VT_DEV_ACTIVATE, HRESULT, POINTER(GUID),
                        c_uint32, c_void_p, POINTER(c_void_p))
            hr = f(dev, byref(_guid(IID_IAudioMeterInformation)),
                   CLSCTX_ALL, None, byref(meter))
            if hr != 0 or not meter.value:
                return 0.0
            g = _vtfunc(meter.value, VT_METER_PEAK, HRESULT,
                        POINTER(c_float))
            v = ctypes.c_float(0.0)
            if g(meter.value, byref(v)) != 0:
                return 0.0
            pk = float(v.value)
            if pk != pk or pk < 0.0:            # NaN / negative guard
                return 0.0
            return min(pk, 1.0)
        except Exception:
            return 0.0
        finally:
            _release(meter.value)

    def _loudest_other(my_id):
        """(id, peak, name) of the loudest render endpoint other than my_id"""
        enum_p = c_void_p()
        try:
            hr = _ole32.CoCreateInstance(
                byref(_guid(CLSID_MMDeviceEnumerator)), None, CLSCTX_ALL,
                byref(_guid(IID_IMMDeviceEnumerator)), byref(enum_p))
            if hr != 0:
                return ('', 0.0, '')
            best = None
            for dp, did in _enum_devices(enum_p.value, eRender):
                try:
                    if my_id and did and did == my_id:
                        continue
                    pk = _dev_peak(dp)
                    if best is None or pk > best[0]:
                        best = (pk, did, _dev_name(dp) or 'other output')
                finally:
                    _release(dp)
            if best and best[0] > 0.0:
                return (best[1], best[0], best[2])
            return ('', 0.0, '')
        except Exception:
            return ('', 0.0, '')
        finally:
            _release(enum_p.value)

    def render_device_peaks(seconds=1.2):
        """for the sound test: [(name, max_peak)] of every active output,
        sampled over ~seconds, loudest first. [] on any error."""
        if not IS_WINDOWS:
            return []
        enum_p = c_void_p()
        devs = []
        inited = False
        try:
            hu = _u(_ole32.CoInitializeEx(None, COINIT_MULTITHREADED))
            inited = hu in (0, S_FALSE)
            hr = _ole32.CoCreateInstance(
                byref(_guid(CLSID_MMDeviceEnumerator)), None, CLSCTX_ALL,
                byref(_guid(IID_IMMDeviceEnumerator)), byref(enum_p))
            if hr != 0:
                return []
            for dp, did in _enum_devices(enum_p.value, eRender):
                devs.append((_dev_name(dp) or 'output', dp))
            if not devs:
                return []
            peaks = [0.0] * len(devs)
            end = time.time() + max(0.2, float(seconds))
            while time.time() < end:
                for i, (_nm, dp) in enumerate(devs):
                    pk = _dev_peak(dp)
                    if pk > peaks[i]:
                        peaks[i] = pk
                time.sleep(0.25)
            rows = [((nm, dp), pk) for (nm, dp), pk in zip(devs, peaks)]
            rows.sort(key=lambda r: -r[1])
            # keep pointers alive until after the sort (name already copied)
            return [(nm, pk) for (nm, _dp), pk in rows]
        except Exception:
            return []
        finally:
            for _nm, dp in devs:
                _release(dp)
            _release(enum_p.value)
            if inited:
                try:
                    _ole32.CoUninitialize()
                except Exception:
                    pass

else:  # ---------------- non-Windows (for tests) --------------------------
    def audiosrv_state():
        return 'unknown'

    def mic_privacy_reason():
        return ''

    def _release(iface):
        pass

    def _dev_peak(dev):
        return 0.0

    def _loudest_other(my_id):
        return ('', 0.0, '')

    def render_device_peaks(seconds=1.2):
        return []


    # ============================ main class ================================
class WasapiCapture(object):
    """native WASAPI capture - no pip dependencies.

    mode='loopback': default speaker output (everything Windows plays)
    mode='mic'     : default microphone recording

    on_audio(mono, sr) is called for every audio block.
      mono: 1-D float array (numpy) or a plain python list
      sr  : sample rate
    log (optional): logging callback (e.g. the app's _write_log)
    """

    def __init__(self, on_audio, mode='loopback', on_stop=None,
                 poll_s=0.006, buffer_ms=400, log=None):
        if mode not in ('loopback', 'mic'):
            raise ValueError("mode must be 'loopback' or 'mic'")
        self.on_audio = on_audio
        self.mode = mode
        self.on_stop = on_stop
        self.poll_s = float(poll_s)
        self.buffer_ms = int(buffer_ms)
        self._log_fn = log
        self._running = False
        self._thread = None
        self.info = ''                  # device description after success
        self.error = ''                 # last error
        self._skip_ids = set()          # devices that stayed silent (loopback)
        self._signal_ids = set()        # v6: devices that REALLY played audio
        self._last_audio_t = 0.0        # last non-silent byte seen

    def _log(self, msg):
        try:
            if self._log_fn:
                self._log_fn('wasapi[%s]: %s' % (self.mode, msg))
        except Exception:
            pass

    # ------------------------- control -----------------------------
    def start(self):
        """starts the capture thread; waits (4 s) for the first result"""
        if not IS_WINDOWS:
            return False, 'WASAPI works on Windows only'
        if self._thread is not None and self._thread.is_alive():
            return False, 'already running'
        self._running = True
        self.error = ''
        self.info = ''
        self._skip_ids = set()
        self._signal_ids = set()
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()
        deadline = time.time() + 4.0
        while time.time() < deadline:
            if self.info:
                return True, self.info
            if self.error:
                self._running = False
                return False, self.error
            time.sleep(0.02)
        self._running = False
        return False, 'WASAPI startup took too long'

    def stop(self):
        self._running = False
        t = self._thread
        if t is not None and t is not threading.current_thread() \
                and t.is_alive():
            t.join(timeout=1.5)

    def alive(self):
        t = self._thread
        return bool(t and t.is_alive())

    def wait(self):
        """waits for the capture thread to stop (called inside a thread)"""
        t = self._thread
        if t is not None and t is not threading.current_thread() \
                and t.is_alive():
            t.join()

    # ----------------------- capture thread ------------------------
    def _worker(self):
        while self._running:
            self.error = ''
            try:
                self._run_once()        # runs inside until disconnected
            except _SwitchDevice as sw:
                # a louder output was found -> reconnect immediately
                self.error = ''
                self._log('reconnecting on the output that plays: %s' % sw)
                continue
            except Exception as e:
                if not self._running:
                    break
                self.error = '%s' % (e,)
                self._log('attempt failed: %s' % (e,))
            if self._running and self.error:
                # device changed / hyphen / error -> reconnect in 2 s
                time.sleep(2.0)
        if self._running and self.on_stop is not None:
            try:
                self.on_stop(self.error)
            except Exception:
                pass

    # --------------------- one full connect ------------------------
    def _run_once(self):
        want_loopback = (self.mode == 'loopback')
        dataflow = eRender if want_loopback else eCapture
        flags = AUDCLNT_STREAMFLAGS_LOOPBACK if want_loopback else 0

        # 0) is the Windows Audio service running?
        st = audiosrv_state()
        if st == 'stopped':
            raise OSError('Windows Audio service is not running - '
                          'press Win+R, run services.msc and start it')
        if self.mode == 'mic':
            prv = mic_privacy_reason()
            if prv:
                raise OSError(prv)

        # 1) COM ladder: MTA first; on CO_E_NOTINITIALIZED -> one STA try
        last_exc = None
        for model, mname in ((COINIT_MULTITHREADED, 'MTA'),
                             (COINIT_APARTMENTTHREADED, 'STA')):
            inited = False
            try:
                hr = _ole32.CoInitializeEx(None, model)
                hu = _u(hr)
                if hu in (0, S_FALSE):
                    inited = True
                elif hu == _u(RPC_E_CHANGED_MODE):
                    inited = False       # already open with another model
                else:
                    raise OSErrorHR('CoInitializeEx(%s)' % mname, hu)
                self._open_stream(dataflow, flags, want_loopback)
                return                   # stop() or unrecoverable error
            except OSErrorHR as e:
                last_exc = e
                if e.hr == CO_E_NOTINITIALIZED and \
                        model == COINIT_MULTITHREADED:
                    self._log('COM %s broken (0x800401F0) → retrying STA'
                              % mname)
                    continue             # COM model switched, retry
                raise
            finally:
                if inited:
                    try:
                        _ole32.CoUninitialize()
                    except Exception:
                        pass
        if last_exc is not None:
            raise last_exc

    # ------------- open a stream on available devices ---------------
    def _open_stream(self, dataflow, flags, want_loopback):
        enum_p = c_void_p()
        dev_p = c_void_p()
        tried = []   # [(IMMDevice*, id)] - all freed in finally
        try:
            hr = _ole32.CoCreateInstance(
                byref(_guid(CLSID_MMDeviceEnumerator)), None, CLSCTX_ALL,
                byref(_guid(IID_IMMDeviceEnumerator)), byref(enum_p))
            if hr != 0:
                raise OSErrorHR('CoCreateInstance', hr)

            # the default device has priority
            seen_ptr = set()
            seen_id = set()

            def _consider(dp):
                """add a device without duplicates (by pointer or id)"""
                if not dp or dp in seen_ptr:
                    return
                did = _dev_id(dp)
                if did and did in seen_id:
                    return
                seen_ptr.add(dp)
                if did:
                    seen_id.add(did)
                tried.append((dp, did))

            f = _vtfunc(enum_p.value, VT_EL_SLOT, HRESULT,
                        c_uint32, c_uint32, POINTER(c_void_p))
            hr = f(enum_p.value, dataflow, eConsole, byref(dev_p))
            if hr == 0 and dev_p.value:
                _consider(dev_p.value)
                dev_p = c_void_p()
            else:
                self._log('GetDefaultAudioEndpoint failed: %s'
                          % OSErrorHR('hr', hr if hr else 0x80070490))

            # every active device of this kind (deduplicated)
            for d2, did2 in _enum_devices(enum_p.value, dataflow):
                _consider(d2)
            if not tried:
                what = 'speaker/headphone' if want_loopback else 'microphone'
                raise OSError('no active %s found' % what)

            last_err = None
            n_all = len(tried)
            # v6: if EVERY output got blacklisted at some point, the memory
            # is poisoned (one long music pause used to do exactly that)
            # -> forget it and give every output a fresh chance
            if want_loopback and self._skip_ids:
                real_ids = set(did for _dp, did in tried if did)
                if real_ids and len(self._skip_ids) >= len(real_ids):
                    self._log('all outputs were silent before '
                              '-> forgetting the skip list')
                    self._skip_ids = set()
            # v5: with several outputs, START on the one that is actually
            # carrying sound right now (peak meter). Ties keep the default
            # first (stable sort), skipped devices keep their real peak so
            # a live device always sorts to the front.
            if want_loopback and n_all > 1:
                scored = [(dp, did, _dev_peak(dp)) for dp, did in tried]
                scored.sort(key=lambda r: -r[2])
                tried = [(dp, did) for dp, did, _pk in scored]
                self._log('output peaks: ' + '; '.join(
                    '%s=%.3f' % (_dev_name(dp) or did or 'dev', pk)
                    for dp, did, pk in scored))
            for idx, (dp, did) in enumerate(tried):
                if not self._running:
                    return
                # skip devices that previously stayed silent (loopback only)
                if (want_loopback and did and did in self._skip_ids
                        and len(self._skip_ids) < n_all):
                    continue
                dname = _dev_name(dp) or ('Device %d' % (idx + 1))
                try:
                    self._pump_device(dp, flags, want_loopback, dname,
                                      did, has_others=(n_all > 1))
                    return                   # natural stop()
                except (OSErrorHR, OSError) as e:
                    last_err = e
                    self._log('device "%s" failed: %s' % (dname, e))
                    continue
            if last_err is not None:
                raise last_err
        finally:
            for dp, _did in tried:
                _release(dp)
            _release(dev_p.value)
            _release(enum_p.value)

    # ---------------- one device: Activate -> pump ------------------
    def _pump_device(self, dev_p, flags, want_loopback, dname,
                     did=None, has_others=False):
        client_p = c_void_p()
        cap_p = c_void_p()
        wfx_p = c_void_p()
        try:
            f = _vtfunc(dev_p, VT_DEV_ACTIVATE, HRESULT, POINTER(GUID),
                        c_uint32, c_void_p, POINTER(c_void_p))
            hr = f(dev_p, byref(_guid(IID_IAudioClient)), CLSCTX_ALL, None,
                   byref(client_p))
            if hr != 0:
                raise OSErrorHR('Activate', hr)
            f = _vtfunc(client_p.value, VT_GETMIXFORMAT, HRESULT,
                        POINTER(c_void_p))
            hr = f(client_p.value, byref(wfx_p))
            if hr != 0 or not wfx_p.value:
                raise OSErrorHR('GetMixFormat', hr if hr else 0x80004005)
            kind, ch, sr, bpf = _parse_format(wfx_p)
            if kind is None:
                wfx = cast(wfx_p, POINTER(WAVEFORMATEX)).contents
                raise OSError('mix format not supported (tag=%d bits=%d)'
                              % (wfx.wFormatTag, wfx.wBitsPerSample))
            f = _vtfunc(client_p.value, VT_INIT, HRESULT, c_uint32, c_uint32,
                        c_uint64, c_uint64, c_void_p, c_void_p)
            hr = f(client_p.value, AUDCLNT_SHAREMODE_SHARED, flags,
                   int(self.buffer_ms) * 10000, 0, wfx_p, None)
            if hr != 0:
                raise OSErrorHR('Initialize(%s)' % self.mode, hr)
            f = _vtfunc(client_p.value, VT_GETSERVICE, HRESULT,
                        POINTER(GUID), POINTER(c_void_p))
            hr = f(client_p.value, byref(_guid(IID_IAudioCaptureClient)),
                   byref(cap_p))
            if hr != 0:
                raise OSErrorHR('GetService(Capture)', hr)
            f = _vtfunc(client_p.value, VT_START, HRESULT)
            hr = f(client_p.value)
            if hr != 0:
                raise OSErrorHR('Start', hr)
            self.info = '%s — %dHz %dch (%s)' % (dname, sr, ch, kind)
            self._log('stream opened: %s' % self.info)
            self.error = ''
            self._pump(cap_p.value, kind, ch, sr, bpf, dev_p=dev_p,
                       did=did, has_others=(has_others and want_loopback),
                       want_loopback=want_loopback)
        finally:
            try:
                if client_p.value:
                    _vtfunc(client_p.value, VT_STOP, HRESULT)(client_p.value)
            except Exception:
                pass
            _release(cap_p.value)
            if wfx_p.value:
                try:
                    _ole32.CoTaskMemFree(wfx_p)
                except Exception:
                    pass
            _release(client_p.value)

    # ------------------------- read loop ----------------------------
    def _pump(self, cap, kind, ch, sr, bpf, dev_p=None, did=None,
              has_others=False, want_loopback=False):
        getnp = _vtfunc(cap, VT_GETNEXTPACKET, HRESULT, POINTER(c_uint32))
        getbuf = _vtfunc(cap, VT_GETBUFFER, HRESULT, POINTER(c_void_p),
                         POINTER(c_uint32), POINTER(c_uint32),
                         POINTER(c_uint64), POINTER(c_uint64))
        relbuf = _vtfunc(cap, VT_RELEASEBUFFER, HRESULT, c_uint32)
        last_audio = time.time()
        next_meter = time.time() + 1.5
        silent_checks = 0
        while self._running:
            # ---- v5 meter watchdog: is the sound playing on ANOTHER output?
            # (catches the "0.000 peak forever" case even if packets carry
            #  zero data without the SILENT flag) ----
            if want_loopback and has_others and time.time() >= next_meter:
                next_meter = time.time() + 1.5
                my_pk = _dev_peak(dev_p) if dev_p else 0.0
                silent_checks = 0 if my_pk >= 0.001 else silent_checks + 1
                if silent_checks >= 2:
                    o_id, o_pk, o_nm = _loudest_other(did)
                    if o_pk > 0.05:
                        # v6: a PROVEN output is never blacklisted - it may
                        # become the right one again right after the pause
                        if did and did not in self._signal_ids:
                            self._skip_ids.add(did)
                        self._log('this output is silent (%.3f) while "%s" '
                                  'plays at %.3f -> switching'
                                  % (my_pk, o_nm, o_pk))
                        raise _SwitchDevice(o_nm)
            avail = c_uint32(0)
            hr = getnp(cap, byref(avail))
            if hr != 0:
                raise OSErrorHR('GetNextPacketSize', hr)
            if avail.value == 0:
                time.sleep(self.poll_s)
                continue
            parts = []
            n = avail.value
            while n > 0:
                buf = c_void_p()
                frames = c_uint32(0)
                fl = c_uint32(0)
                p1 = c_uint64()
                p2 = c_uint64()
                hr = getbuf(cap, byref(buf), byref(frames), byref(fl),
                            byref(p1), byref(p2))
                if hr != 0:
                    raise OSErrorHR('GetBuffer', hr)
                nf = frames.value
                if nf:
                    if fl.value & AUDCLNT_BUFFERFLAGS_SILENT:
                        parts.append(bytes(nf * bpf))       # real silence
                    else:
                        parts.append(string_at(buf, nf * bpf))
                if relbuf(cap, nf) != 0:
                    raise OSErrorHR('ReleaseBuffer', 0x80004005)
                n -= nf
            raw = b''.join(parts)
            mono = _to_mono(raw, kind, ch) if raw else None
            # v5: judge "audio" by the REAL sample peak, not by the SILENT
            # flag - many virtual devices send zero-filled packets with the
            # flag clear, which looked like music to the old check
            pk = 0.0
            if mono is not None and len(mono):
                try:
                    if _np is not None:
                        pk = float(_np.abs(mono).max())
                    else:
                        pk = max(abs(v) for v in mono)
                except Exception:
                    pk = 0.0
                try:
                    self.on_audio(mono, sr)
                except Exception:
                    pass
            if pk > 1e-5:
                last_audio = time.time()
                self._last_audio_t = last_audio
                if did:
                    self._signal_ids.add(did)   # v6: this output PROVED it plays
            elif (has_others and did
                    and did not in self._signal_ids
                    and did not in self._skip_ids
                    and time.time() - last_audio > 6.0):
                # v6: only an output that NEVER carried a signal is switched
                # away after 6 s (VB-Cable/HDMI/virtual defaults). An output
                # that played before is just PAUSED - abandoning it used to
                # kill the equalizer until the app was restarted.
                self._skip_ids.add(did)
                self._log('output carried no signal for 6 s -> switching')
                raise _SwitchDevice('no signal')


# ------------------------ device helpers --------------------------------
def _dev_id(dev):
    """IMMDevice::GetId - id string (its buffer is freed here)"""
    try:
        f = _vtfunc(dev, VT_DEV_GETID, HRESULT, POINTER(c_wchar_p))
        p = c_wchar_p()
        if f(dev, byref(p)) != 0:
            return ''
        s = str(p.value or '')
        _ole32.CoTaskMemFree(cast(p, c_void_p))
        return s
    except Exception:
        return ''


def _dev_name(dev):
    """device friendly name from the PropertyStore (errors -> empty)"""
    try:
        store = c_void_p()
        f = _vtfunc(dev, VT_DEV_OPENPROPS, HRESULT, c_uint32, POINTER(c_void_p))
        if f(dev, 0, byref(store)) != 0 or not store.value:   # STGM_READ
            return ''
        try:
            key = PROPERTYKEY()
            key.fmtid = _guid(PKEY_Device_FriendlyName_FMT)
            key.pid = PKEY_Device_FriendlyName_PID
            pv = PROPVARIANT()
            f = _vtfunc(store.value, VT_PS_GETVALUE, HRESULT,
                        POINTER(PROPERTYKEY), POINTER(PROPVARIANT))
            if f(store.value, byref(key), byref(pv)) != 0:
                return ''
            try:
                if int(pv.vt) != VT_LPWSTR or not pv.p[0]:
                    return ''
                return ctypes.wstring_at(cast(pv.p[0], c_void_p)) or ''
            finally:
                try:
                    _ole32.PropVariantClear(byref(pv))
                except Exception:
                    pass
        finally:
            _release(store.value)
    except Exception:
        return ''


def _enum_devices(enum, dataflow):
    """every active device of this kind -> [(IMMDevice*, id)]"""
    out = []
    coll = c_void_p()
    try:
        f = _vtfunc(enum, VT_EL_ENUM, HRESULT, c_uint32, c_uint32,
                    POINTER(c_void_p))
        hr = f(enum, dataflow, DEVICE_STATE_ACTIVE, byref(coll))
        if hr != 0 or not coll.value:
            return out
        gc = _vtfunc(coll.value, VT_COLL_COUNT, HRESULT, POINTER(c_uint32))
        gi = _vtfunc(coll.value, VT_COLL_ITEM, HRESULT, c_uint32,
                     POINTER(c_void_p))
        n = c_uint32(0)
        if gc(coll.value, byref(n)) != 0:
            return out
        for i in range(min(int(n.value), 16)):
            d = c_void_p()
            if gi(coll.value, c_uint32(i), byref(d)) == 0 and d.value:
                out.append((d.value, _dev_id(d.value)))
        return out
    except Exception:
        return out
    finally:
        _release(coll.value)


# ------------------------ sample formats --------------------------------
# SubFormat GUID sits at byte offset 24 of WAVEFORMATEXTENSIBLE (packed).
# We read it straight from the raw buffer with struct.unpack_from so the
# detection can never break because of struct alignment again.
def _parse_format(wfx_p):
    wfx = cast(wfx_p, POINTER(WAVEFORMATEX)).contents
    ch = int(wfx.nChannels) or 2
    sr = int(wfx.nSamplesPerSec) or 48000
    bits = int(wfx.wBitsPerSample)
    tag = int(wfx.wFormatTag)
    kind = None
    if tag == WAVE_FORMAT_EXTENSIBLE and int(wfx.cbSize) >= 22:
        try:
            raw = string_at(wfx_p, 24 + 16)          # header + full GUID
            sub = struct.unpack_from('<I', raw, 24)[0]   # SubFormat.Data1
        except Exception:
            sub = 0
        if sub == 3:                       # KSDATAFORMAT_SUBTYPE_IEEE_FLOAT
            kind = 'f32' if bits == 32 else None
        elif sub == 1:                     # KSDATAFORMAT_SUBTYPE_PCM
            kind = {16: 'i16', 32: 'i32'}.get(bits)
    elif tag == WAVE_FORMAT_IEEE_FLOAT:
        kind = 'f32' if bits == 32 else None
    elif tag == WAVE_FORMAT_PCM:
        kind = {16: 'i16', 32: 'i32'}.get(bits)
    bytes_per = {'f32': 4, 'i32': 4, 'i16': 2}.get(kind, 4)
    return kind, ch, sr, bytes_per * ch


try:
    import numpy as _np
except Exception:
    _np = None


def _to_mono(raw, kind, ch):
    """raw bytes -> mono float"""
    import array
    if kind == 'f32':
        a = array.array('f')
    elif kind == 'i16':
        a = array.array('h')
    elif kind == 'i32':
        a = array.array('i')
    else:
        return None
    try:
        a.frombytes(raw)
    except Exception:
        return None
    if _np is not None:
        x = _np.asarray(a, dtype=_np.float32)
        if kind == 'i16':
            x = x * (1.0 / 32768.0)
        elif kind == 'i32':
            x = x * (1.0 / 2147483648.0)
        if ch > 1 and x.size:
            x = x.reshape(-1, ch).mean(axis=1)
        return x
        # pure python (when numpy is missing - slower but works)
    vals = list(a)
    if kind == 'i16':
        vals = [v * (1.0 / 32768.0) for v in vals]
    elif kind == 'i32':
        vals = [v * (1.0 / 2147483648.0) for v in vals]
    if ch > 1:
        vals = [sum(vals[i:i + ch]) / float(ch)
                for i in range(0, len(vals) - ch + 1, ch)]
    return vals
