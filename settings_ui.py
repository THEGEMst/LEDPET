# -*- coding: utf-8 -*-
# =====================================================================
#  LEDPet - settings panel (Tk, dark theme, English)
#  Every change is applied live and saved automatically.
#  Eight tabs: Colors / Effects / Audio / Behavior / Body / Face /
#  Shortcuts (v18.0 - global keys for the face expressions) / Styles
#  (shareable looks: click one to apply it, export / import / delete).
#  v17.9: every tab scrolls (60 new options) and applies live.
#  v18.1 (LEDPET_V18_CUSTOM): reorganized tabs (clear sections with
#  dividers), the Colors tab owns every color now, full eye studio
#  (cornea / iris / pupil sizes + colors), sticky shortcuts.
#  v18.2 (LEDPET_V18_RESIZE): the window is FREELY RESIZABLE (min
#  460x560) - every tab's content follows the new width, and the last
#  size/position is saved in settings_geo so it reopens the same way.
# =====================================================================
import os
import sys
import time
import tkinter as tk
from tkinter import colorchooser

import ledpet_core as C
import hotkeys_win as HK   # v18.0: expression shortcuts (LEDPET_V18_KEYS)

BG = '#10131A'
PANEL = '#171B24'
FG = '#EDEDF0'
DIM = '#8B93A5'
ACC = '#5FA8FF'
FONT = ('Segoe UI', 10)
FONT_B = ('Segoe UI', 10, 'bold')
FONT_S = ('Segoe UI', 9)


def _hex(rgb):
    return '#%02x%02x%02x' % tuple(int(v) for v in rgb)


class SettingsWindow(tk.Toplevel):
    def __init__(self, root, pet):
        tk.Toplevel.__init__(self, root)
        self.pet = pet
        self.cfg = pet.cfg
        self._lock = False
        self.vars = {}
        self.title('LEDPET V1.0 \u2014 Settings (by THEGEM)')
        self.configure(bg=BG)
        # v18.2 (LEDPET_V18_RESIZE): the panel is freely resizable now.
        self.resizable(True, True)
        self.minsize(460, 560)
        try:
            self.attributes('-topmost', True)
        except Exception:
            pass
        # v18.2: reopen at the last size/position when it is sane,
        # otherwise the classic 500x820 centred spot.
        try:
            _geo = str(self.cfg.get('settings_geo', '') or '')
        except Exception:
            _geo = ''
        if not self._restore_geo(_geo):
            try:
                sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
                self.geometry('500x820+%d+%d' % (max(0, sw // 2 - 560), max(0, sh // 2 - 410)))
            except Exception:
                self.geometry('500x820')
        # v18.2: remember the last size/position when the panel closes
        # (the destroy() override covers Close/WM_DELETE, this bind covers
        # an app-wide teardown where Tk cascades the destruction)
        self.bind('<Destroy>', self._save_geo_on_close, add='+')

        # --- tabs ---
        bar = tk.Frame(self, bg=BG)
        bar.pack(fill='x', padx=10, pady=(10, 4))
        self.body = tk.Frame(self, bg=PANEL)
        self.body.pack(fill='both', expand=True, padx=10, pady=4)
        self.tabs = {}
        self.tab_btns = {}
        self.tab_inner = {}
        self.tab_canvas = {}
        self._win_ids = {}   # v18.2: canvas window ids (width stretch)
        names = [('color', 'Colors'), ('look', 'Effects'), ('audio', 'Audio'), ('behav', 'Behavior'),
                 ('body', 'Body'), ('eyes', 'Face'), ('keys', 'Shortcuts'), ('style', 'Styles')]
        for key, label in names:
            b = tk.Button(bar, text=label, font=FONT_B, bd=0, relief='flat', padx=6, pady=5,
                          bg=PANEL, fg=DIM, activebackground=PANEL, activeforeground=FG,
                          command=lambda k=key: self.show_tab(k), cursor='hand2')
            b.pack(side='left', padx=2)
            self.tab_btns[key] = b
            f = tk.Frame(self.body, bg=PANEL)
            self.tabs[key] = f
            # v17.9: the option list grew -> every tab scrolls
            cv = tk.Canvas(f, bg=PANEL, highlightthickness=0, bd=0)
            vs = tk.Scrollbar(f, orient='vertical', command=cv.yview, width=10)
            inner = tk.Frame(cv, bg=PANEL)
            _wid = cv.create_window((0, 0), window=inner, anchor='nw')
            self._win_ids[key] = _wid
            # v18.2: while the window is resized the tab content follows
            # the canvas width (rows pack fill='x', so everything adapts)
            cv.bind('<Configure>',
                    lambda e, c=cv, w=_wid: c.itemconfigure(w, width=e.width))
            inner.bind('<Configure>', lambda e, c=cv: c.configure(scrollregion=c.bbox('all')))
            cv.configure(yscrollcommand=vs.set)
            cv.pack(side='left', fill='both', expand=True)
            vs.pack(side='right', fill='y')
            self.tab_canvas[key] = cv
            self.tab_inner[key] = inner
            self._wheel(cv)
        self._build_color(self.tab_inner['color'])
        self._build_look(self.tab_inner['look'])
        self._build_audio(self.tab_inner['audio'])
        self._build_behav(self.tab_inner['behav'])
        self._build_body(self.tab_inner['body'])
        self._build_eyes(self.tab_inner['eyes'])
        self._build_keys(self.tab_inner['keys'])          # v18.0
        self._build_style(self.tab_inner['style'])        # style library
        self.show_tab('color')

        # --- footer ---
        foot = tk.Frame(self, bg=BG)
        foot.pack(fill='x', padx=10, pady=(4, 10))
        tk.Button(foot, text='Close', font=FONT_B, bd=0, padx=16, pady=6, bg='#2A6FDB', fg='white',
                  activebackground='#3C82F0', activeforeground='white',
                  command=self.destroy, cursor='hand2').pack(side='right')
        tk.Label(foot, text='LEDPET V1.0  \u00b7  by THEGEM', font=FONT_S,
                 bg=BG, fg=DIM).pack(side='right', padx=10)
        tk.Button(foot, text='Reset to defaults', font=FONT, bd=0, padx=12, pady=6, bg='#2A3140',
                  fg=FG, activebackground='#3A4357', activeforeground='white',
                  command=self.reset, cursor='hand2').pack(side='left')

        self._poll()

    # ---------------- v18.2 (LEDPET_V18_RESIZE): window geometry ----------------
    def _restore_geo(self, geo):
        """apply a saved 'WxH+X+Y' geometry, sanity-checked against the
        screen; returns False when there is nothing usable in it."""
        try:
            import re
            m = re.match(r'^(\d+)x(\d+)\+(-?\d+)\+(-?\d+)$', str(geo or '').strip())
            if not m:
                return False
            w, h, x, y = (int(v) for v in m.groups())
            sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
            w = max(460, min(w, sw))
            h = max(560, min(h, sh))
            x = max(0, min(x, max(0, sw - 80)))
            y = max(0, min(y, max(0, sh - 80)))
            self.geometry('%dx%d+%d+%d' % (w, h, x, y))
            return True
        except Exception:
            return False

    def _save_geo_on_close(self, event):
        """store the final 'WxH+X+Y' into cfg['settings_geo'] (fires once,
        for the Toplevel itself - not for the children being torn down)"""
        if event.widget is not self:
            return
        try:
            geo = self.geometry()
            if geo and 'x' in geo:
                self.pet.cfg['settings_geo'] = geo
                self.pet.cfg_changed('settings_geo')
        except Exception:
            pass

    def destroy(self):
        """v18.2: store the final window geometry BEFORE going away, so
        the panel reopens at the same size next time."""
        try:
            geo = self.geometry()
            if geo and 'x' in geo:
                self.pet.cfg['settings_geo'] = geo
                self.pet.cfg_changed('settings_geo')
        except Exception:
            pass
        try:
            tk.Toplevel.destroy(self)
        except Exception:
            pass

    # ------------------------------------------------------------------
    def _wheel(self, cv):
        """mouse-wheel scrolling while the pointer is over this tab"""
        def _on(e):
            try:
                cv.yview_scroll(-1 * int(e.delta / 120), 'units')
            except Exception:
                pass

        def _on45(e):
            try:
                cv.yview_scroll(-1 if e.num == 4 else 1, 'units')
            except Exception:
                pass
        cv.bind('<Enter>', lambda e: (cv.bind_all('<MouseWheel>', _on),
                                      cv.bind_all('<Button-4>', _on45),
                                      cv.bind_all('<Button-5>', _on45)))

    def show_tab(self, key):
        for k, f in self.tabs.items():
            f.pack_forget()
            self.tab_btns[k].configure(bg=PANEL, fg=DIM)
        self.tabs[key].pack(fill='both', expand=True, padx=12, pady=10)
        self.tab_btns[key].configure(bg='#232938', fg=FG)
        try:
            self.tab_canvas[key].yview_moveto(0.0)
        except Exception:
            pass

    def _poll(self):
        """show live audio status"""
        try:
            if hasattr(self, 'status_lbl'):
                self.status_lbl.configure(text='Status: ' + self.pet.audio_status())
            if hasattr(self, 'mic_status_lbl'):
                self.mic_status_lbl.configure(text='Status: ' + self.pet.mic_status())
            self.after(600, self._poll)
        except Exception:
            pass

    # --------------------------- widget builders ---------------------------
    def _section(self, parent, text):
        """v18.1: every section = a small uppercase title + a divider line,
        so the crowded tabs read as clear labeled blocks."""
        tk.Label(parent, text=text.upper(), font=('Segoe UI', 9, 'bold'),
                 bg=PANEL, fg=ACC, anchor='w').pack(fill='x', pady=(12, 1))
        tk.Frame(parent, bg='#2A3140', height=1, bd=0,
                 highlightthickness=0).pack(fill='x', pady=(0, 4))

    def _set(self, key, val):
        if self._lock:
            return
        self.cfg[key] = val
        self.pet.cfg_changed(key)

    def _scale(self, parent, label, key, lo, hi, res, fmt='%.2f'):
        row = tk.Frame(parent, bg=PANEL)
        row.pack(fill='x', pady=2)
        tk.Label(row, text=label, font=FONT, bg=PANEL, fg=FG, width=16, anchor='w').pack(side='left')
        var = tk.DoubleVar(value=float(self.cfg[key]))
        self.vars[key] = var
        val_lbl = tk.Label(row, text=fmt % float(self.cfg[key]), font=FONT_S, bg=PANEL, fg=DIM, width=5)
        val_lbl.pack(side='right')

        def cb(v, key=key, var=var, val_lbl=val_lbl):
            try:
                x = float(v)
            except Exception:
                return
            val_lbl.configure(text=fmt % x)
            self._set(key, x)
        def trace(*_a, var=var, val_lbl=val_lbl):
            try:
                val_lbl.configure(text=fmt % float(var.get()))
            except Exception:
                pass
        try:
            var.trace_add('write', trace)
        except Exception:
            pass
        sc = tk.Scale(row, from_=lo, to=hi, resolution=res, orient='horizontal', variable=var,
                      showvalue=False, bg=PANEL, fg=FG, troughcolor='#252B3A', highlightthickness=0,
                      bd=0, sliderrelief='flat', activebackground=ACC, command=cb, length=200)
        sc.pack(side='left', fill='x', expand=True, padx=6)

    def _check(self, parent, label, key):
        var = tk.BooleanVar(value=bool(self.cfg[key]))
        self.vars[key] = var
        cb = tk.Checkbutton(parent, text=label, variable=var, font=FONT, bg=PANEL, fg=FG,
                            selectcolor='#252B3A', activebackground=PANEL, activeforeground=FG,
                            anchor='w', justify='left', bd=0, highlightthickness=0,
                            command=lambda: self._set(key, bool(var.get())))
        cb.pack(fill='x', pady=1)

    def _radio(self, parent, label, key, options):
        """options: [(text, value)]"""
        row = tk.Frame(parent, bg=PANEL)
        row.pack(fill='x', pady=3)
        if label:
            tk.Label(row, text=label, font=FONT, bg=PANEL, fg=FG, anchor='w').pack(side='left', padx=(0, 8))
        var = tk.StringVar(value=str(self.cfg[key]))
        self.vars[key] = var
        conv = type(self.cfg[key])
        for text, val in options:
            tk.Radiobutton(row, text=text, variable=var, value=str(val), font=FONT_S, bg=PANEL,
                           fg=FG, selectcolor='#252B3A', activebackground=PANEL, activeforeground=FG,
                           indicatoron=0, bd=0, padx=8, pady=3, highlightthickness=0,
                           command=lambda val=val: self._set(key, conv(val))).pack(side='left', padx=1)

    def _color_btn(self, parent, label, key):
        row = tk.Frame(parent, bg=PANEL)
        row.pack(fill='x', pady=3)
        tk.Label(row, text=label, font=FONT, bg=PANEL, fg=FG, anchor='w').pack(side='left', padx=(0, 8))
        btn = tk.Button(row, text='  Pick color\u2026  ', font=FONT_S, bd=0, padx=8, pady=3,
                        bg=_hex(self.cfg[key]), fg='#000000', cursor='hand2')
        btn.pack(side='left', padx=4)
        self.vars[key + '_btn'] = btn

        def pick():
            try:
                res = colorchooser.askcolor(color=_hex(self.cfg[key]), parent=self, title=label)
            except Exception:
                return
            if res and res[0]:
                rgb = [int(round(c)) for c in res[0]]
                self.cfg[key] = rgb
                self.pet._rc_cache = None
                btn.configure(bg=_hex(rgb))
                self.pet.cfg_changed(key)
        btn.configure(command=pick)

    # ---------------- v18.1 (LEDPET_V18_CUSTOM): quick swatches ----------------
    BODY_SWATCHES = [(0, 0, 0), (22, 22, 26), (238, 238, 240), (12, 18, 44),
                     (46, 8, 14), (8, 32, 20), (34, 12, 40), (40, 26, 14)]

    def _swatches(self, parent, key, colors=None):
        """a row of one-click color chips (incl. TRUE black for the body)"""
        row = tk.Frame(parent, bg=PANEL)
        row.pack(fill='x', pady=2)
        tk.Label(row, text='Quick picks:', font=FONT_S, bg=PANEL, fg=DIM,
                 anchor='w').pack(side='left', padx=(0, 6))
        for rgb in (colors or self.BODY_SWATCHES):
            tk.Button(row, bg=_hex(rgb), width=3, bd=0, relief='flat',
                      activebackground=_hex(rgb), cursor='hand2',
                      command=lambda rgb=rgb: self._pick_swatch(key, rgb)
                      ).pack(side='left', padx=2)

    def _pick_swatch(self, key, rgb):
        self.cfg[key] = list(rgb)
        btn = self.vars.get(key + '_btn')
        if btn is not None:
            try:
                btn.configure(bg=_hex(rgb))
            except Exception:
                pass
        self.pet._rc_cache = None
        self.pet.cfg_changed(key)

    # ------------------------------ tabs ------------------------------
    def _note(self, parent, text, pady=(2, 6)):
        tk.Label(parent, text=text, font=FONT_S, bg=PANEL, fg=DIM, justify='left', anchor='w',
                 wraplength=410).pack(fill='x', pady=pady)

    def _build_color(self, p):
        # ---- v18.1: the Colors tab now owns EVERY color of the pet ----
        self._section(p, 'Preset themes')
        grid = tk.Frame(p, bg=PANEL)
        grid.pack(fill='x')
        for i, (name, _d) in enumerate(C.THEMES):
            b = tk.Button(grid, text=name, font=FONT_S, bd=0, padx=8, pady=5, bg='#232938', fg=FG,
                          activebackground='#33405A', activeforeground='white', cursor='hand2',
                          command=lambda i=i: self.apply_theme(i))
            b.grid(row=i // 2, column=i % 2, padx=3, pady=3, sticky='ew')
        grid.grid_columnconfigure(0, weight=1)
        grid.grid_columnconfigure(1, weight=1)

        self._section(p, 'LED color')
        sw = tk.Frame(p, bg=PANEL)
        sw.pack(fill='x', pady=2)
        for i, (name, rgb) in enumerate(C.PALETTE):
            tk.Button(sw, bg=_hex(rgb), width=4, bd=0, activebackground=_hex(rgb), cursor='hand2',
                      command=lambda i=i: self.pick_palette(i)).pack(side='left', padx=3)
        self._color_btn(p, 'Custom LED color', 'rgb1')
        self._radio(p, 'Color mode', 'color_mode', [('Solid', 'solid'), ('Rainbow', 'rainbow'),
                                                    ('Gradient', 'gradient'), ('Reactive', 'reactive')])
        self._color_btn(p, 'Second color (gradient)', 'rgb2')
        self._scale(p, 'Hue cycle speed (rainbow/reactive)', 'hue_speed', 0.0, 3.0, 0.05)
        self._note(p, '"Reactive": the color shifts with the bass of the music.\n'
                      '"Gradient": from the main color (top) to the second color (bottom).', pady=6)

        self._section(p, 'Body panel colors (fill)')
        self._check(p, 'Fill the body (solid panel, not see-through)', 'body_fill')
        self._swatches(p, 'body_fill_rgb')          # v18.1: TRUE black + friends
        self._color_btn(p, 'Body fill color', 'body_fill_rgb')
        self._color_btn(p, 'Second fill color (gradient styles)', 'fill_rgb2')
        self._scale(p, 'Fill opacity', 'fill_opacity', 0, 100, 5, fmt='%.0f')
        self._grid(p, 'fill_style', [('solid', 'Solid'), ('panel', 'Panel'), ('scan', 'Scan'),
                                     ('gradient', 'Gradient'), ('stripes', 'Stripes'),
                                     ('checker', 'Checker'), ('rings', 'Rings'),
                                     ('sparkle', 'Sparkle'), ('waves', 'Waves'),
                                     ('bricks', 'Bricks'), ('plasma', 'Plasma'),
                                     ('aurora', 'Aurora')], cols=4)
        self._note(p, 'The fill is a solid panel behind the LEDs. "Gradient" blends\n'
                      'the fill color into the second color; Plasma / Aurora are live\n'
                      'animated color washes; Stripes / Waves / Sparkle / Rings move;\n'
                      'Checker / Bricks / Panel are textures. The default fill color\n'
                      'is now TRUE black (0,0,0).', pady=(4, 2))

        self._section(p, 'Neon outline')
        self._check(p, 'Bright outline inside the LED edge', 'body_outline')
        self._color_btn(p, 'Outline color', 'outline_rgb')
        self._check(p, 'Rainbow-cycling outline', 'outline_cycle')

        self._section(p, 'Face & clock colors')
        self._color_btn(p, 'Cheeks (blush) color', 'cheek_rgb')
        self._radio(p, 'Clock color', 'clock_cmode', [('Same as LED', 'accent'),
                                                      ('Custom', 'custom')])
        self._color_btn(p, 'Custom clock color', 'clock_rgb')

    def _build_look(self, p):
        # ---- v18.1: renamed to "Effects" - everything that MOVES lives here
        self._section(p, 'Size and glow')
        self._scale(p, 'Size', 'scale', 0.40, 1.60, 0.05)
        self._scale(p, 'Glow intensity', 'glow', 0.0, 2.0, 0.05)
        self._section(p, 'Equalizer ring')
        self._radio(p, 'Count', 'rays', [(str(v), v) for v in C.CHOICES['rays']])
        self._scale(p, 'Bar length', 'ray_len', 0.5, 1.4, 0.05)
        self._scale(p, 'Rotation speed', 'rotate', -1.0, 1.0, 0.05)
        self._radio(p, 'Bass at', 'layout', [('Bottom', 'bottom'), ('Top', 'top')])
        self._check(p, 'Peak caps (floating white dots)', 'peaks')
        self._check(p, 'Sparks', 'sparks')
        self._check(p, 'Ripple wave across the LED matrix', 'ripples')
        self._scale(p, 'Spark amount', 'spark_density', 0.0, 2.0, 0.05)
        self._scale(p, 'Peak cap hold time', 'peak_hold_t', 0.0, 1.2, 0.05)
        self._section(p, 'Dynamic effects')
        self._check(p, 'Ring pulses with the beat', 'ring_pulse')
        self._check(p, 'Comet chasing around the ring', 'comet')
        self._check(p, 'Radar scan sweep', 'scan_dot')
        self._check(p, 'Matrix rain', 'rain_fx')
        self._check(p, 'Fireflies (wandering glow dots)', 'fireflies')
        self._check(p, 'Heartbeat (double thump every few seconds)', 'heartbeat')
        self._check(p, 'Mirror equalizer (symmetric bars)', 'eq_mirror')
        self._note(p, 'All dynamic effects are gentle by default and switch off\n'
                      'when the pet sleeps. Colors of every effect follow the\n'
                      '"Colors" tab (hue cycle speed lives there too).', pady=(4, 2))
        self._section(p, 'Clock')
        self._check(p, 'Show clock', 'clock')
        self._check(p, 'Show seconds', 'clock_secs')
        self._check(p, '12-hour format', 'clock12')

    def _build_audio(self, p):
        self._section(p, 'Equalizer (what your speakers play)')
        self._check(p, 'Equalizer and dance react to system audio', 'audio')
        self.status_lbl = tk.Label(p, text='', font=FONT_S, bg=PANEL, fg=DIM, anchor='w', justify='left',
                                   wraplength=410)
        self.status_lbl.pack(fill='x', pady=(0, 4))
        self._scale(p, 'EQ strength', 'halo_gain', 0.5, 3.0, 0.05)
        self._scale(p, 'Sensitivity', 'sens', 0.3, 3.0, 0.05)
        self._scale(p, 'Motion smoothing', 'smooth', 0.0, 1.0, 0.05)
        self._check(p, 'Beat effects (ring pulse, sparks, ripples)', 'beat_fx')
        self._section(p, 'Reaction options')
        self._check(p, 'Dance to the music', 'auto_dance')
        self._scale(p, 'Dance intensity', 'dance_amt', 0.0, 2.0, 0.05)
        self._check(p, 'Body zooms with the bass', 'bass_zoom')
        self._check(p, 'LED flash on the beat', 'beat_flash')
        self._check(p, 'Blink on strong beats', 'beat_blink')
        self._check(p, 'Eyes widen while I talk (mic level)', 'mic_react_eyes')
        self._check(p, 'Smooth wave ring (melts the bars together)', 'eq_wave')
        self._radio(p, 'In silence', 'silence_pose', [('Breathe', 'breathe'),
                                                      ('Look around', 'look'),
                                                      ('Calm (dimmed)', 'calm')])
        self._scale(p, 'Beat threshold', 'beat_min', 0.1, 0.9, 0.05)
        self._scale(p, 'Bar fall speed', 'eq_fall', 0.4, 1.6, 0.05)
        self._note(p, '"Beat threshold": how strong a beat must be before sparks\n'
                      'and ripples fire. "Bar fall speed": how fast the bars drop\n'
                      'after a sound ends.', pady=(4, 2))
        self._note(p, 'The ring shows ONLY the system sound as an equalizer.\n'
                      'With no sound playing it rests on a calm breathing ring.\n'
                      'The live status is the first row of the right-click menu\n'
                      '(click it for a sound test).',
                   pady=(0, 2))

        self._section(p, 'Microphone → mouth (the ONLY mouth source)')
        self._check(p, 'Mouth moves when I talk (uses the microphone)', 'mic')
        self.mic_status_lbl = tk.Label(p, text='', font=FONT_S, bg=PANEL, fg=DIM, anchor='w',
                                       justify='left', wraplength=410)
        self.mic_status_lbl.pack(fill='x', pady=(0, 4))
        self._scale(p, 'Mic sensitivity', 'mic_sens', 0.3, 3.0, 0.05)
        row = tk.Frame(p, bg=PANEL)
        row.pack(fill='x', pady=(2, 2))
        tk.Label(row, text='Input level', font=FONT, bg=PANEL, fg=FG, width=16, anchor='w').pack(side='left')
        self.meter = tk.Canvas(row, width=230, height=12, bg='#252B3A', highlightthickness=0, bd=0)
        self.meter.pack(side='left', padx=6)
        self._meter_bar = self.meter.create_rectangle(0, 0, 0, 12, fill=ACC, width=0)
        self._meter_tick()
        self._note(p, 'The mouth reacts ONLY to the microphone — never to the speakers.\n'
                      'While the system itself is playing sound, the mouth stays calm\n'
                      '(the equalizer ring handles the speakers), so speaker bleed\n'
                      'can never move the mouth. Stop the music, talk \u2192 mouth moves.\n'
                      'Reactions: lip-sync while you talk \u00b7 surprised "O" on sudden sounds \u00b7\n'
                      'big mouth while shouting \u00b7 whistle "oo" while humming \u00b7 smile after talking.\n'
                      'Uses your default recording device (Windows Settings \u2192 System \u2192 Sound \u2192 Input).\n'
                      'Nothing is recorded, saved or sent anywhere \u2014 only the loudness is read.\n'
                      'If the meter stays empty: Windows Settings \u2192 Privacy & security \u2192 Microphone \u2192 '
                      'allow desktop apps.', pady=(6, 2))
        row = tk.Frame(p, bg=PANEL)
        row.pack(fill='x', pady=(4, 0))
        tk.Button(row, text='Run sound test', font=FONT_S, bd=0, padx=10, pady=4,
                  bg='#232938', fg=FG, activebackground='#33405A', activeforeground='white',
                  cursor='hand2', command=self.pet.sound_test).pack(side='left')

    def _meter_tick(self):
        """live microphone level bar"""
        try:
            on = bool(self.cfg['mic']) and self.pet.mic_ok
            v = max(0.0, min(1.0, float(self.pet.m_open))) if on else 0.0
            self.meter.coords(self._meter_bar, 0, 0, int(230 * v), 12)
            self.after(70, self._meter_tick)
        except Exception:
            pass

    def _build_behav(self, p):
        self._section(p, 'Home frame')
        # v1.0 (LEDPET_V1_NAME): the pet's name + the Reset name control
        nm_row = tk.Frame(p, bg=PANEL)
        nm_row.pack(fill='x', pady=2)
        self._name_lbl = tk.Label(nm_row, text='', font=FONT, bg=PANEL, fg=FG, anchor='w')
        self._name_lbl.pack(side='left')
        tk.Button(nm_row, text='Reset name', font=FONT_S, bd=0, padx=10, pady=4,
                  bg='#2A3140', fg=FG, activebackground='#3A4357',
                  activeforeground='white', command=self._reset_name,
                  cursor='hand2').pack(side='right')
        # v1.0 (LEDPET_V1_RESET): the warning under the button says exactly
        # what "Reset name" really does - it resets EVERYTHING
        self._note(p, 'WARNING: "Reset name" resets EVERYTHING, not just the\n'
                      'name. All settings go back to the defaults and LEDPET\n'
                      'starts again exactly like the very first time.')
        self._check(p, 'Show the home frame: feed, water, mini-games', 'home')
        self._check(p, 'Random expressions while idle', 'idle_emotes')
        self._note(p, 'The pet lives inside the frame. Drag the frame (or the pet) to move both.\n'
                      'Drag FOOD / WATER onto the pet, or just click them. PLAY = 3 tiny games.\n'
                      'FOLLOW button (or \"Chase\" below): the pet leaves home and follows your mouse;\n'
                      'switch it off and the pet walks back home.')
        self._section(p, 'Follow mouse')
        self._radio(p, '', 'track', [('Off', 'off'), ('Eyes', 'eyes'),
                                      ('Slow chase', 'chase_slow'), ('Fast chase', 'chase_fast')])
        self._note(p, '"Eyes": the pet looks at your mouse anywhere on screen.\n'
                      '"Chase": the pet also drifts toward the mouse (without sitting on it).')
        self._section(p, 'Personality')
        self._check(p, 'Bouncy eyes (squash & stretch)', 'eye_bounce')
        self._scale(p, 'Bounce amount', 'bounce_amt', 0.3, 2.5, 0.05)
        self._section(p, 'More personality')
        self._scale(p, 'Blink rate', 'blink_rate', 0.3, 2.5, 0.05)
        self._scale(p, 'Wink chance', 'wink_chance', 0.0, 1.0, 0.05)
        self._check(p, 'Eyes wander around when idle', 'eye_wander')
        self._scale(p, 'Emote frequency', 'emote_rate', 0.0, 2.0, 0.05)
        self._check(p, 'Zzz bubbles while asleep', 'zzz_fx')
        self._scale(p, 'Dizzy wobble', 'dizzy_amt', 0.5, 2.0, 0.05)
        self._check(p, 'Eyes widen when the mouse hovers the pet', 'hover_react')
        self._check(p, 'Heart sparks on every click', 'click_hearts')
        self._scale(p, 'Auto sleep after (minutes of quiet)', 'sleep_after', 0, 120, 5, fmt='%.0f')
        self._note(p, 'Blink rate 1.0 = normal. Wink chance 0.14 = the classic\n'
                      'wink. "Auto sleep after" 0 = never (the night sleep stays\n'
                      'separate, see the switch below).', pady=(4, 2))
        self._section(p, 'Window')
        self._check(p, 'Always on top of other windows', 'topmost')
        self._check(p, 'Auto sleep (11 PM \u2013 7 AM)', 'autosleep')
        self._section(p, 'Performance')
        self._radio(p, 'Frame rate', 'fps', [(str(v), v) for v in C.CHOICES['fps']])
        self._radio(p, 'Quality', 'quality', [('Auto', 'auto'), ('High', 'high'), ('Low (fast)', 'low')])
        self._section(p, 'Controls')
        self._note(p, 'Click: change color + ripple          Double-click: falls in love\n'
                      'Drag: move anywhere                   Shake while dragging: gets dizzy\n'
                      'Speakers: the ring becomes a live equalizer, body dances\n'
                      'Microphone: the ONLY thing that moves the mouth\n'
                      '(while speakers play, the mouth stays calm automatically)\n'
                      'Right-click: quick menu', pady=4)

    # --------------- v18.0: expression shortcuts (LEDPET_V18_KEYS) ---------------
    def _hk_bindings(self):
        """the current map {state: combo} straight from the config"""
        try:
            return dict(HK.load_bindings(self.cfg))
        except Exception:
            return {}

    def _build_keys(self, p):
        pet = self.pet
        self._hk_rows = {}                    # state -> (bind_lbl, status_lbl)

        self._section(p, 'Keyboard shortcuts')
        # v18.4 (LEDPET_V18_FIX): live engine status - shows whether the
        # shortcuts really are registered and when one last fired, so a
        # problem is visible instead of silent.
        self._hk_engine_lbl = tk.Label(p, text='', font=FONT_S, bg=PANEL,
                                       fg=ACC, anchor='w', justify='left')
        self._hk_engine_lbl.pack(fill='x', padx=2, pady=(0, 2))
        self._check(p, 'Keyboard shortcuts enabled (work everywhere in Windows)',
                    'hotkeys_on')
        # v18.1 (LEDPET_V18_CUSTOM): sticky expressions
        self._check(p, 'A shortcut HOLDS the expression until the next shortcut',
                    'hk_pin')
        self._note(p, 'When "holds" is on, the face a shortcut picked STAYS on the\n'
                      'pet - even with music playing - until you press another\n'
                      'shortcut (Alt+0 = back to normal). When it is off, every\n'
                      'expression lasts a few seconds and the pet returns to idle.')
        self._note(p, 'Every face expression can have its own key combination '
                      'and it works SYSTEM-WIDE - while you are in any program, '
                      'not only here. Click "Set", then press the combination '
                      '(hold Ctrl / Alt / Shift and a key, or a single F1-F24 / '
                      'Num0-Num9 key). Esc cancels.')

        # the 21 expressions, in the same order as the right-click menu
        self._section(p, 'Expressions')
        labels = dict(C.OLD_STATES + C.NEW_STATES)
        box = tk.Frame(p, bg=PANEL)
        box.pack(fill='x')
        for i, state in enumerate(C.HOTKEY_STATES):
            row = tk.Frame(box, bg='#1B2130' if i % 2 == 0 else PANEL)
            row.pack(fill='x', pady=1, padx=2)
            tk.Label(row, text=labels.get(state, state), font=FONT, bg=row['bg'],
                     fg=FG, width=13, anchor='w').pack(side='left', padx=(4, 4))
            bind_lbl = tk.Label(row, text='', font=FONT_B, bg=row['bg'],
                                fg=ACC, width=11, anchor='w')
            bind_lbl.pack(side='left')
            status_lbl = tk.Label(row, text='', font=FONT_S, bg=row['bg'],
                                  fg=DIM, anchor='w')
            status_lbl.pack(side='left', padx=(0, 4))
            self._hk_rows[state] = (bind_lbl, status_lbl)
            tk.Button(row, text='Set', font=FONT_S, bd=0, padx=8, pady=2,
                      bg='#232938', fg=FG, activebackground='#33405A',
                      activeforeground='white', cursor='hand2',
                      command=lambda s=state: self._hk_record(s)).pack(side='right', padx=2)
            tk.Button(row, text='Clear', font=FONT_S, bd=0, padx=8, pady=2,
                      bg='#232938', fg=DIM, activebackground='#33405A',
                      activeforeground='white', cursor='hand2',
                      command=lambda s=state: self._hk_clear(s)).pack(side='right', padx=2)
        self._hk_refresh_rows()

        row2 = tk.Frame(p, bg=PANEL)
        row2.pack(fill='x', pady=(8, 2))
        tk.Button(row2, text='Reset all to defaults', font=FONT_S, bd=0, padx=10, pady=4,
                  bg='#232938', fg=FG, activebackground='#33405A',
                  activeforeground='white', cursor='hand2',
                  command=self._hk_reset_all).pack(side='left')
        tk.Button(row2, text='Clear all', font=FONT_S, bd=0, padx=10, pady=4,
                  bg='#232938', fg=FG, activebackground='#33405A',
                  activeforeground='white', cursor='hand2',
                  command=self._hk_clear_all).pack(side='left', padx=6)
        self._note(p, 'Defaults: Alt+1..6 = the classic moods, Alt+0 = back to '
                      'the normal face, Ctrl+Alt+1..0 = the emotions, '
                      'Shift+Alt+1..4 = eating / drinking / hungry / smirk. '
                      'The shortcuts also appear in the right-click menu. If a '
                      'combination is already taken by another program, its row '
                      'shows it and you can pick a different one.', pady=(2, 4))

    def _hk_refresh_rows(self):
        """re-paint the 21 rows from cfg + engine status"""
        try:
            binds = self._hk_bindings()
            st = getattr(self.pet, 'hk', None)
            status = dict(getattr(st, 'status', {}) or {})
            for state, (bind_lbl, status_lbl) in self._hk_rows.items():
                combo = binds.get(state, '')
                bind_lbl.configure(text=combo if combo else '\u2014')
                if not combo:
                    status_lbl.configure(text='')
                elif self.cfg.get('hotkeys_on', True) is False:
                    status_lbl.configure(text='(shortcuts are off)')
                elif status.get(state) == 'hook':
                    # v18.5 (LEDPET_V18_PUMP): RegisterHotKey could not own
                    # this combo (another program has it) but the passive
                    # LL hook fires it anyway - it still WORKS.
                    status_lbl.configure(text='(active \u00b7 fallback)')
                elif status.get(state) == 'taken':
                    status_lbl.configure(text='(taken by another program)')
                else:
                    status_lbl.configure(text='(active)')
            self._hk_refresh_engine(binds, st, status)
        except Exception:
            pass

    def _hk_refresh_engine(self, binds=None, st=None, status=None):
        """v18.4: the live status line of the shortcut engine"""
        try:
            lbl = getattr(self, '_hk_engine_lbl', None)
            if lbl is None:
                return
            if binds is None:
                binds = self._hk_bindings()
            if st is None:
                st = getattr(self.pet, 'hk', None)
            if self.cfg.get('hotkeys_on', True) is False:
                lbl.configure(text='Engine: shortcuts are switched off', fg=DIM)
                return
            alive = True
            try:
                alive = st.engine_alive()
            except Exception:
                pass
            sts = status if status is not None \
                else getattr(st, 'status', {}) or {}
            n_ok = sum(1 for v in sts.values() if v in ('ok', 'hook'))
            n_hook = sum(1 for v in sts.values() if v == 'hook')
            if not alive:
                lbl.configure(text='Engine: restarting... (if this stays, '
                                   'another program may own the keys)',
                              fg='#FFB259')
                return
            txt = 'Engine: running \u00b7 %d of %d shortcut(s) active' \
                  % (n_ok, len(binds))
            if n_hook:
                # v18.5: some combos are fired by the passive hook (they
                # are owned by another program) - still fully active
                txt += ' \u00b7 %d via fallback hook' % n_hook
            last = getattr(self.pet, '_hk_last_fire', 0.0)
            if last:
                age = int(max(0.0, time.time() - last))
                txt += ' \u00b7 last fired %s ago' % (
                    'just now' if age < 3 else '%ds' % age)
            lbl.configure(text=txt, fg=ACC)
        except Exception:
            pass

    def _hk_save(self, binds):
        """store + re-register (the pet also refreshes the menu + saves)"""
        self.cfg['hotkeys'] = HK.save_bindings(binds)
        self.pet.cfg_changed('hotkeys')
        self._hk_refresh_rows()

    def _hk_clear(self, state):
        binds = self._hk_bindings()
        binds.pop(state, None)
        self._hk_save(binds)

    def _hk_reset_all(self):
        self._hk_save(dict(C.HOTKEY_DEFAULTS))

    def _hk_clear_all(self):
        self._hk_save({})

    def _hk_record(self, state):
        """capture the next key press as the new shortcut for this state"""
        try:
            win = tk.Toplevel(self)
            win.title('Press a key combination')
            win.configure(bg=BG)
            win.resizable(False, False)
            try:
                win.attributes('-topmost', True)
            except Exception:
                pass
            win.geometry('+%d+%d' % (self.winfo_rootx() + 90,
                                     self.winfo_rooty() + 260))
            tk.Label(win, text='Press the key combination for\n"%s"\n'
                               '(hold Ctrl / Alt / Shift and a key,\n'
                               'or a single F1-F24 / Num0-Num9 key)'
                               % state.replace('_', ' '),
                     font=FONT, bg=BG, fg=FG, justify='left').pack(padx=18, pady=(14, 6))
            hint = tk.Label(win, text='Esc = cancel', font=FONT_S, bg=BG, fg=DIM)
            hint.pack(pady=(0, 6))
            cur = tk.Label(win, text='', font=FONT_B, bg=BG, fg=ACC)
            cur.pack(pady=(0, 10))

            # ---- v18.4 (LEDPET_V18_FIX): single-key buttons ---------
            # One click = this ONE key becomes the shortcut, no modifier.
            # Only the Windows-safe bare keys are offered (F1-F24,
            # Num0-Num9): a bare letter/digit would be swallowed while
            # typing everywhere. This also sidesteps NumLock: with NumLock
            # ON the keyboard reports numpad keys as plain digits, so
            # "press it" cannot tell them apart - the buttons can.
            sk = tk.Frame(win, bg=BG)
            sk.pack(padx=14, pady=(0, 8))
            tk.Label(sk, text='Or click a single key:', font=FONT_S,
                     bg=BG, fg=DIM, anchor='w').pack(fill='x', pady=(0, 3))
            for row_i, group in enumerate(('numpad', 'funcs')):
                fr = tk.Frame(sk, bg=BG)
                fr.pack(pady=1)
                if group == 'numpad':
                    keys = ['Num%d' % i for i in range(10)]
                else:
                    keys = ['F%d' % i for i in range(1, 13)]
                for j, k in enumerate(keys):
                    tk.Button(fr, text=k, font=FONT_S, bd=0, padx=4, pady=2,
                              width=4, bg='#232938', fg=FG,
                              activebackground='#33405A',
                              activeforeground='white', cursor='hand2',
                              command=lambda k=k: _single(k)
                              ).grid(row=0, column=j, padx=1)
            tk.Label(sk, text='Numpad works with or without NumLock (buttons '
                              'always mean the numpad keys)',
                     font=FONT_S, bg=BG, fg=DIM, justify='left'
                     ).pack(anchor='w', pady=(3, 0))

            # while recording, the global hotkeys stand down so the press
            # is not "eaten" twice (suspend unregisters them temporarily)
            try:
                self.pet.hk.suspend()
            except Exception:
                pass

            def _restore():
                try:
                    self.pet.hk.apply(self._hk_bindings(),
                                      bool(self.cfg.get('hotkeys_on', True)))
                except Exception:
                    pass
                try:
                    win.grab_release()
                except Exception:
                    pass
                try:
                    win.destroy()
                except Exception:
                    pass

            def _apply_combo(combo):
                # one combo = one expression: take it away from any other state
                binds = self._hk_bindings()
                for s2 in [s for s, c in binds.items() if c == combo]:
                    binds.pop(s2, None)
                binds[state] = combo
                self._hk_save(binds)
                _restore()

            def _single(key):
                combo = key                       # a bare single key
                probs = HK.combo_problems(combo)
                if probs:
                    cur.configure(text=combo + '  \u2192  ' + probs[0])
                    return
                cur.configure(text=combo + '   OK!')
                win.after(150, lambda c=combo: _apply_combo(c))

            def _key(e):
                if e.keysym == 'Escape':
                    _restore()
                    return
                key = None
                # v18.4: numpad keys with NumLock ON arrive as plain digit
                # keysyms - the Windows virtual-key code is the only thing
                # that always identifies them (VK_NUMPAD0..9 = 96..105).
                try:
                    if str(self.tk.call('tk', 'windowingsystem')) == 'win32' \
                            and 96 <= int(e.keycode) <= 105:
                        key = 'Num%d' % (int(e.keycode) - 96)
                except Exception:
                    key = None
                if key is None:
                    key = HK.keysym_to_key(e.keysym)
                if key is None:
                    cur.configure(text='?  use a letter, digit, F1-F24 or Num0-9')
                    return
                ctrl = bool(e.state & 0x0004)
                shift = bool(e.state & 0x0001)
                alt = bool(e.state & (0x20000 | 0x0008))   # Alt (Win) / Mod1 (X11)
                parts = []
                if ctrl:
                    parts.append('Ctrl')
                if alt:
                    parts.append('Alt')
                if shift:
                    parts.append('Shift')
                parts.append(key)
                combo = '+'.join(parts)
                probs = HK.combo_problems(combo)
                if probs:
                    cur.configure(text=combo + '  \u2192  ' + probs[0])
                    return
                cur.configure(text=combo + '   OK!')
                win.after(250, lambda c=combo: _apply_combo(c))

            win.bind('<KeyPress>', _key)
            win.protocol('WM_DELETE_WINDOW', _restore)
            try:
                win.transient(self)
                win.grab_set()
                win.focus_force()
            except Exception:
                pass
        except Exception:
            # never let the recorder kill the settings window
            try:
                self.pet.hk.resume()
            except Exception:
                pass

    def refresh_keys_rows(self):
        """public hook (also called by refresh())"""
        self._hk_refresh_rows()

    # ------------------- v17: body shape / bubble / eyes -------------------
    def _grid(self, parent, key, options, cols=4):
        """options: [(value, label)] shown as a grid of toggle buttons"""
        box = tk.Frame(parent, bg=PANEL)
        box.pack(fill='x', pady=3)
        var = tk.StringVar(value=str(self.cfg[key]))
        self.vars[key] = var
        conv = type(self.cfg[key])
        for i, (val, text) in enumerate(options):
            tk.Radiobutton(box, text=text, variable=var, value=str(val), font=FONT_S,
                           bg='#232938', fg=FG, selectcolor='#33507F',
                           activebackground='#33405A', activeforeground='white',
                           indicatoron=0, bd=0, padx=4, pady=6, highlightthickness=0,
                           cursor='hand2',
                           command=lambda val=val: self._set(key, conv(val))
                           ).grid(row=i // cols, column=i % cols, padx=2, pady=2, sticky='ew')
        for c in range(cols):
            box.grid_columnconfigure(c, weight=1, uniform='g' + key)

    def _build_body(self, p):
        # ---- v18.1: Body = shape + LED style + motion (the FILL COLORS
        # moved to the Colors tab so every color lives in one place)
        self._section(p, 'Body shape')
        self._grid(p, 'shape', C.SHAPES, cols=4)
        self._note(p, 'The face always stays inside the shape and the equalizer\n'
                      'ring hugs the shape outline.\n'
                      'Quick switch: right-click the pet -> Body shape.')
        self._section(p, 'LED style')
        self._grid(p, 'dot_style', [('circle', 'Circle'), ('square', 'Square'),
                                    ('diamond', 'Diamond'), ('ring', 'Ring'),
                                    ('hex', 'Hexagon'), ('tri', 'Triangle'),
                                    ('star', 'Star'), ('plus', 'Plus'),
                                    ('pixel', 'Pixel'), ('roundsq', 'Soft square'),
                                    ('heart', 'Heart')], cols=4)
        self._scale(p, 'Dot size', 'dot_size', 0.7, 1.3, 0.05)
        self._check(p, 'Dim the outer edge (depth effect)', 'edge_fade')
        self._check(p, 'Deep dark unlit grid (TRUE black off-state)', 'deep_dark')
        self._note(p, 'The unlit LED dots can stay the classic warm gray or go\n'
                      'near-black ("Deep dark") so the dark body reads as real\n'
                      'black on the desktop.')
        self._section(p, 'Bubble / jelly motion')
        self._check(p, 'Soft bubble body (not a perfect circle)', 'blob')
        self._scale(p, 'Stretch (when it moves)', 'blob_stretch', 0.0, 2.5, 0.05)
        self._scale(p, 'Wobble (soap bubble)', 'blob_wobble', 0.0, 2.5, 0.05)
        self._scale(p, 'Wobble speed', 'wobble_speed', 0.3, 2.5, 0.05)
        self._scale(p, 'Pull toward the mouse', 'blob_lean', 0.0, 2.0, 0.05)
        self._check(p, 'Breathing brightness (gentle glow pulse)', 'body_pulse')
        self._check(p, 'Extra squish while dragging', 'drag_squish')
        self._note(p, 'Stretch: the body stretches along its motion (follow, drag,\n'
                      'music beat) and wobbles back like jelly.\n'
                      'Wobble: the outline slowly breathes like a soap bubble.\n'
                      'Pull: the side facing your mouse stretches toward it.',
                   pady=(6, 2))

    def _build_eyes(self, p):
        # ---- v18.1 (LEDPET_V18_CUSTOM): the FULL eye studio ----
        # the eye is three layers now: cornea -> iris -> pupil, each with
        # its own size and color.
        self._section(p, 'Eyes (cornea)')
        self._radio(p, 'Count', 'eye_count', [('Single eye', 1), ('Two eyes', 2),
                                              ('Three eyes', 3)])
        self._scale(p, 'Cornea size (the eye itself)', 'eye_size', 0.6, 1.6, 0.05)
        self._scale(p, 'Eye distance', 'eye_gap', 0.7, 1.4, 0.05)
        self._radio(p, 'Cornea color', 'eye_cmode', [('Same as LED', 'same'),
                                                     ('Custom', 'custom')])
        self._color_btn(p, 'Custom cornea color', 'eye_rgb')
        self._section(p, 'Iris (NEW - behind the pupil)')
        self._grid(p, 'iris', [('none', 'None'), ('circle', 'Circle'), ('ring', 'Ring'),
                               ('square', 'Square'), ('diamond', 'Diamond'),
                               ('heart', 'Heart'), ('star5', 'Star')], cols=4)
        self._scale(p, 'Iris size', 'iris_size', 0.5, 1.6, 0.05)
        self._color_btn(p, 'Iris color', 'iris_rgb')
        self._note(p, 'The iris is the colored ring between the eye and the pupil\n'
                      '(like a real eye). It follows the pupil, the pupil hole\n'
                      'punches through it, and it never leaves the eye.')
        self._section(p, 'Pupil')
        self._grid(p, 'pupil', C.PUPILS, cols=3)
        self._scale(p, 'Pupil size', 'pupil_size', 0.5, 1.6, 0.05)
        self._radio(p, 'Pupil color', 'pupil_cmode', [('Dark (hole)', 'dark'),
                                                      ('Custom', 'custom')])
        self._color_btn(p, 'Custom pupil color', 'pupil_rgb')
        self._check(p, 'Pupil follows the mouse inside the eye', 'pupil_follow')
        self._check(p, 'Shiny glint in the pupil (painted over the iris)', 'pupil_glint')
        self._note(p, 'Pupils are drawn on the open eyes (normal, surprised, ...).\n'
                      '"Dark (hole)" punches a hole through iris + eye; Custom\n'
                      'draws a colored pupil on top of the iris. The last three\n'
                      'pupils are LIVE: Scanning orbits, Beating breathes, and\n'
                      'Wandering hops around every second.', pady=(2, 4))
        self._section(p, 'Mouth & cheeks')
        self._check(p, 'Show the mouth', 'show_mouth')
        self._check(p, 'Show the cheeks (blush)', 'show_cheeks')
        self._note(p, 'Turn the mouth off for a calm, minimal face - the pet\n'
                      'keeps blinking and looking around, it just never opens\n'
                      'its mouth. The cheek COLOR lives in the Colors tab.')

    # ------------------------------ actions ------------------------------
    def pick_palette(self, i):
        self.pet.set_palette(i)
        self.refresh()

    def apply_theme(self, i):
        self.pet.apply_theme(i)
        self.refresh()

    def reset(self):
        self.pet.reset_cfg()
        self.cfg = self.pet.cfg
        self.refresh()

    def _reset_name(self):
        """v1.0 (LEDPET_V1_RESET): confirm first - "Reset name" is a FULL
        FACTORY RESET.  The warning below the title says exactly that:
        everything goes back to the defaults, the name is erased and LEDPET
        starts again like the very first time.  (The settings window closes
        itself inside pet.reset_name)"""
        try:
            import tkinter.messagebox as mb
            ok = mb.askyesno(
                'Reset name',
                "Reset the pet's name?\n\n"
                "WARNING: this resets EVERYTHING, not just the name!\n"
                "All settings go back to the defaults, the name is erased\n"
                "and LEDPET starts again exactly like the very first time.\n\n"
                "Continue?",
                icon='warning', parent=self)
            if not ok:
                return
        except Exception:
            pass
        try:
            self.pet.reset_name()
        except Exception:
            pass

    def refresh(self):
        """re-read widget values from cfg (after theme/reset)"""
        self.cfg = self.pet.cfg
        self._lock = True
        try:
            # v1.0 (LEDPET_V1_NAME): keep the name row current
            try:
                self._name_lbl.configure(text='Pet name: %s'
                                         % (getattr(self.pet, 'name', '') or '-'))
            except Exception:
                pass
            for key, var in self.vars.items():
                if key.endswith('_btn'):
                    try:
                        var.configure(bg=_hex(self.cfg[key[:-4]]))
                    except Exception:
                        pass
                    continue
                try:
                    v = self.cfg[key]
                    if isinstance(var, tk.StringVar):
                        var.set(str(v))
                    else:
                        var.set(v)
                except Exception:
                    pass
        finally:
            self._lock = False
        self._hk_refresh_rows()           # v18.0: repaint the shortcut rows

    # ------------------------- style library --------------------------------
    def _pw(self):
        """the pet_windows module (the app runs it as __main__)"""
        import sys
        m = sys.modules.get('pet_windows')
        if m is not None and hasattr(m, 'list_styles'):
            return m
        return sys.modules.get('__main__')

    def _build_style(self, p):
        self._section(p, 'Style library')
        self._note(p,
                   'A style is a shareable look: colors, size, body shape,\n'
                   'fills, dots, eyes, effects and clock options. Click a\n'
                   'style to apply it. The name, the sounds, the shortcuts\n'
                   'and the needs are never touched by a style.',
                   pady=(0, 6))
        self.style_list = tk.Listbox(p, bg='#1B2029', fg=FG, font=FONT,
                                     selectbackground='#2A6FDB',
                                     selectforeground='white', relief='flat',
                                     highlightthickness=0, height=8,
                                     activestyle='none')
        self.style_list.pack(fill='x', pady=(0, 4))
        self.style_list.bind('<<ListboxSelect>>', self._style_on_click)
        self._style_paths = []

        row = tk.Frame(p, bg=PANEL)
        row.pack(fill='x', pady=(0, 2))

        def btn(text, cmd, r, c, col='#232938'):
            tk.Button(r, text=text, font=FONT_S, bd=0, padx=9, pady=6, bg=col,
                      fg=FG, activebackground='#33405A', activeforeground='white',
                      cursor='hand2', command=cmd).grid(row=r and 1 or 0, column=c,
                                                        padx=3, pady=3, sticky='ew')
        # two tidy rows of actions
        grid = tk.Frame(p, bg=PANEL)
        grid.pack(fill='x')
        acts = [('Apply selected', self._style_apply),
                ('Save current look...', self._style_export),
                ('Import a file...', self._style_import),
                ('Open styles folder', self._style_open_folder),
                ('Delete selected', self._style_delete)]
        for i, (txt, cmd) in enumerate(acts):
            tk.Button(grid, text=txt, font=FONT_S, bd=0, padx=9, pady=6,
                      bg='#232938', fg=FG, activebackground='#33405A',
                      activeforeground='white', cursor='hand2',
                      command=cmd).grid(row=i // 2, column=i % 2, padx=3,
                                        pady=3, sticky='ew')
        grid.grid_columnconfigure(0, weight=1)
        grid.grid_columnconfigure(1, weight=1)
        self.style_status = tk.Label(p, text='', font=FONT_S, bg=PANEL,
                                     fg=DIM, anchor='w', wraplength=420,
                                     justify='left')
        self.style_status.pack(fill='x', pady=(4, 0))
        self._style_refresh()

    def _style_refresh(self):
        """re-list every style file in the Styles folder"""
        try:
            sel = self.style_list.curselection()
        except Exception:
            sel = ()
        self.style_list.delete(0, 'end')
        self._style_paths = []
        styles = self._pw().list_styles()
        for (nm, path) in styles:
            self.style_list.insert('end', nm)
            self._style_paths.append(path)
        if not styles:
            self.style_list.insert('end', '(no styles yet - save your look)')
            self.style_list.itemconfigure('end', fg=DIM)
            self._style_paths.append(None)
        self.style_status.configure(
            text='%d style(s) in the library' % len(styles))

    def _style_on_click(self, _e=None):
        """single click = apply that style right away"""
        try:
            sel = self.style_list.curselection()
        except Exception:
            return
        if not sel:
            return
        self._style_apply()

    def _style_selected_path(self):
        try:
            sel = self.style_list.curselection()
        except Exception:
            return None
        if not sel:
            return None
        return self._style_paths[sel[0]]

    def _style_apply(self):
        path = self._style_selected_path()
        if not path:
            self.style_status.configure(text='Select a style first.')
            return
        try:
            nm = self.pet.apply_style_file(path)
        except Exception as e:
            nm = None
            self.style_status.configure(text='Applying failed: %r' % (e,))
        if nm:
            try:
                self.refresh()
            except Exception:
                pass
            self.style_status.configure(text="Applied style: %s" % nm)

    def _style_export(self):
        from tkinter import simpledialog, messagebox
        nm = simpledialog.askstring(
            'Save current look as a style',
            'Style name:', parent=self, initialvalue='My style')
        if not nm:
            return
        path = self._pw().export_style_file(self.cfg, nm)
        if path:
            self._style_refresh()
            self.style_status.configure(text='Saved: %s' % path)
        else:
            messagebox.showerror('LEDPET V1.0', 'The style file could not '
                                 'be saved (see error.log).', parent=self)

    def _style_import(self):
        from tkinter import filedialog, messagebox
        fn = filedialog.askopenfilename(
            parent=self, title='Import a style file',
            filetypes=[('LEDPet style', '*.json'), ('All files', '*.*')])
        if not fn:
            return
        path = self._pw().import_style_file(fn)
        if path:
            self._style_refresh()
            nm = self.pet.apply_style_file(path)
            self.style_status.configure(
                text=('Imported + applied: %s' % nm) if nm
                else 'Imported: %s' % path)
        else:
            messagebox.showerror(
                'LEDPET V1.0', 'This file is not a valid LEDPet style.',
                parent=self)

    def _style_open_folder(self):
        import subprocess
        d = self._pw().styles_dir()
        try:
            if os.name == 'nt':
                os.startfile(d)            # noqa - Windows only
            elif sys.platform == 'darwin':
                subprocess.Popen(['open', d])
            else:
                subprocess.Popen(['xdg-open', d])
            self.style_status.configure(text='Folder: %s' % d)
        except Exception as e:
            self.style_status.configure(text='Could not open: %s' % d)

    def _style_delete(self):
        from tkinter import messagebox
        path = self._style_selected_path()
        if not path:
            self.style_status.configure(text='Select a style first.')
            return
        if messagebox.askyesno('Delete style',
                               'Delete this style from the library?',
                               parent=self):
            self._pw().delete_style(path)
            self._style_refresh()
