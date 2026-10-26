#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# =====================================================================
#  LEDPet Launcher - python stdlib only, no dependencies
#  steps: check -> auto-install missing libraries (live progress) ->
#         module tests -> launch the widget without a console window
#  every step is logged to launcher_log.txt (next to this file).
# =====================================================================
import os
import sys
import time
import subprocess

APP_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(APP_DIR, 'launcher_log.txt')
IS_WIN = (os.name == 'nt')

try:
    LOGF = open(LOG_FILE, 'a', encoding='utf-8', buffering=1)
except Exception:
    LOGF = None


def log(msg):
    line = '[%s] %s' % (time.strftime('%Y-%m-%d %H:%M:%S'), msg)
    try:
        print(line)
        sys.stdout.flush()
    except Exception:
        pass
    if LOGF:
        try:
            LOGF.write(line + '\n')
        except Exception:
            pass


def head(title):
    bar = '=' * 58
    log(bar)
    log('  ' + title)
    log(bar)


def try_import(mod):
    try:
        __import__(mod)
        return True
    except Exception:
        return False


def msg_err(text):
    """error message: console + log + a visual dialog"""
    log('ERROR: ' + text.replace('\n', ' | '))
    print()
    print('  ' + '=' * 54)
    for ln in text.splitlines():
        try:
            print('   ' + ln)
        except Exception:
            pass
    print('  ' + '=' * 54)
    try:
        sys.stdout.flush()
    except Exception:
        pass
    try:
        import tkinter.messagebox as mb
        import tkinter as tk
        r = tk.Tk()
        r.withdraw()
        mb.showerror('LEDPET V1.0', text)
        r.destroy()
    except Exception:
        pass


def msg_warn(text):
    """non-fatal warning: console + log + a yellow dialog"""
    log('WARNING: ' + text.replace('\n', ' | '))
    try:
        import tkinter.messagebox as mb
        import tkinter as tk
        r = tk.Tk()
        r.withdraw()
        mb.showwarning('LEDPET V1.0', text)
        r.destroy()
    except Exception:
        pass


def pip_stream(args, tag):
    """run pip streaming its output live to the console + log"""
    cmd = [sys.executable, '-m', 'pip', 'install',
           '--disable-pip-version-check'] + args
    log('%s cmd: %s' % (tag, ' '.join(cmd)))
    try:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT,
                             text=True, errors='replace',
                             bufsize=1, cwd=APP_DIR)
    except Exception as e:
        log('%s pip could not start: %r' % (tag, e))
        return 1
    for ln in p.stdout:
        ln = ln.rstrip()
        if ln:
            try:
                print('     ' + ln)
                sys.stdout.flush()
            except Exception:
                pass
            if LOGF:
                try:
                    LOGF.write(ln + '\n')
                except Exception:
                    pass
    rc = p.wait()
    log('%s pip exit code: %s' % (tag, rc))
    return rc


def main():
    no_audio = ('--no-audio' in sys.argv)
    head('LEDPET V1.0 (by THEGEM) - launcher started')
    log('python: %s  (%s)' % (sys.version.split()[0], sys.executable))
    log('platform: %s' % sys.platform)

    # ---------- step 1: tkinter ----------
    log('[1/4] checking tkinter ...')
    if not try_import('tkinter'):
        log('FATAL: tkinter is missing in this Python!')
        msg_err('Your Python has no Tkinter module!\n\n'
                'Please install the full Python from python.org and\n'
                'keep "tcl/tk and IDLE" ticked during setup.')
        return 1
    log('       tkinter ok')

    # ---------- step 2: pillow + numpy (SoundCard no longer required) ----------
    log('[2/4] checking Pillow / numpy ...')
    need = []
    if not try_import('PIL'):
        need.append('pillow')
    if not try_import('numpy'):
        need.append('numpy')

    if need:
        log('       missing: %s  ->  installing (needs internet)'
            % ', '.join(need))
        print()
        print('  ' + '*' * 56)
        print('   Installing required libraries, please WAIT ...')
        print('   (this takes a few minutes - do NOT close this window!)')
        print('  ' + '*' * 56)
        print()
        try:
            sys.stdout.flush()
        except Exception:
            pass
        rc = pip_stream(need, '[install]')
        print()
        if rc != 0:
            # SoundCard is optional; without it only the backup engines are missing
            still = [m for m in ('PIL', 'numpy') if not try_import(m)]
            if still:
                log('FATAL: pip install failed (rc=%s)' % rc)
                msg_err('Installing the libraries failed!\n\n'
                        '1) Check your internet connection\n'
                        '2) Or type this in CMD yourself:\n'
                        '    pip install pillow numpy\n\n'
                        'Full details: launcher_log.txt (next to run.bat)')
                return 1
        still = [m for m in ('PIL', 'numpy') if not try_import(m)]
        if still:
            log('FATAL: still missing after install: %s' % still)
            msg_err('Libraries still missing after install: %s\n\n'
                    'Type in CMD:\n    pip install pillow numpy\n\n'
                    'Details: launcher_log.txt' % ', '.join(still))
            return 1
        log('       core libraries installed & verified')
    else:
        log('       core libraries present')

    # ---------- step 3: SoundCard (backup only - Windows has a native engine) ----------
    log('[3/4] audio engine check ...')
    if no_audio:
        log('       skipped (--no-audio)')
    elif try_import('soundcard'):
        log('       soundcard present (backup engine)')
    else:
        log('       SoundCard missing -> trying a quick optional install ...')
        rc = pip_stream(['--quiet', 'SoundCard'], '[audio]')
        if rc != 0 or not try_import('soundcard'):
            log('       SoundCard unavailable -> OK: the built-in WASAPI engine '
                'handles the equalizer AND the microphone mouth without it')
            print()
            print('  Note: optional SoundCard library is not installed.')
            print('  No problem! LEDPet uses the built-in Windows audio engine')
            print('  for the equalizer ring and the microphone mouth.')

    # ---------- step 4: application module tests ----------
    log('[4/4] verifying app modules ...')
    sys.path.insert(0, APP_DIR)
    for mod in ('ledpet_core', 'ledpet_render', 'wasapi_audio',
                'home_logic', 'home_render', 'name_window'):
        if not try_import(mod):
            log('FATAL: %s.py import failed (missing/corrupt file)' % mod)
            msg_err('%s.py is missing or damaged next to the launcher!\n\n'
                    'Extract the whole LEDPet folder in one go\n'
                    '(keep all the files together).' % mod)
            return 1
    import py_compile
    for fn in ('pet_windows.py', 'settings_ui.py', 'home_window.py',
                   'home_logic.py', 'name_window.py'):
        try:
            py_compile.compile(os.path.join(APP_DIR, fn), doraise=True)
        except Exception as e:
            log('FATAL: %s broken: %r' % (fn, e))
            msg_err('%s is damaged!\n'
                    'Extract the ZIP again.\n\n%s' % (fn, e))
            return 1
    log('       app modules ok')

    # ---------- launch the widget (no console window) ----------
    log('launching pet ...')
    try:
        # the child must inherit no streams so the console/pipe does not stay open
        null = subprocess.DEVNULL
        if IS_WIN:
            DETACHED_PROCESS = 0x00000008
            CREATE_NEW_PROCESS_GROUP = 0x00000200
            subprocess.Popen(
                [sys.executable, 'pet_windows.py'],
                cwd=APP_DIR, stdin=null, stdout=null, stderr=null,
                creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP,
                close_fds=True)
        else:
            subprocess.Popen([sys.executable, 'pet_windows.py'],
                             cwd=APP_DIR, stdin=null, stdout=null,
                             stderr=null, start_new_session=True)
    except Exception as e:
        log('FATAL: launch failed: %r' % e)
        msg_err('Could not start LEDPET!\n\n%s' % e)
        return 1
    log('PET LAUNCHED OK - console closes automatically')
    print()
    print('  LEDPET V1.0 launched! (this window closes now)')
    try:
        sys.stdout.flush()
    except Exception:
        pass
    time.sleep(1.5)
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception:
        import traceback
        tb = traceback.format_exc()
        log('LAUNCHER CRASH:\n' + tb)
        msg_err('Unexpected launcher error!\n\nFull details:\n'
                'launcher_log.txt (next to run.bat)')
        sys.exit(1)
