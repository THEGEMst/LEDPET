# -*- coding: utf-8 -*-
# =====================================================================
#  LEDPET V1.0 (by THEGEM) - the first-run "give me a name" frame
#  (LEDPET_V1_NAME, rebuilt as a true MINI HOME FRAME)
#  It is deliberately written with the SAME structures as the pet's own
#  home frame (home_render.py / home_window.py), just smaller:
#    - NameRenderer: a mini HomeRenderer - same draw tools (_circ/_ring/
#      _rrect/_bitmap/_text with the very same formulas), same three-band
#      layout (header / screen / dock), same band caching, and the same
#      v17.8 layered static build: the opaque bases (glass, screen, button
#      disk) are drawn first and EVERY faint detail (rim, hairline, dot
#      grids, separators, corner marks) is alpha-BLENDED on its own
#      overlay - so nothing ever punches see-through holes into the glass.
#    - NameDialog: a mini HomeFrame - same cap-dict press/drag/release
#      state machine, same hover/_dirty/_pos_sent tick loop, same guarded
#      close; the name text is cleaned by ledpet_core.sanitize_name (ONE
#      source of truth).
#  The frame appears EXACTLY in the middle of the monitor the first time
#  LEDPet starts:
#    - a happy LED dot (a circle with two eyes) wiggles at the top of the
#      dot screen, drawn exactly like the home frame's lit cells
#      (glow + core + white center)
#    - "GIVE ME A NAME" + the typed name in big LED dots with a blinking
#      LED cursor
#    - a DONE disk in the exact home-button style (base disk, ring, LED
#      eyes, label) - or the Enter key - finishes it
#  On Done the dialog does NOT close any more: the pet app takes it over
#  (LEDPET_V1_MORPH) and plays an animated morph - the little frame GROWS
#  into the real home frame (same centre) while the happy dot GROWS into
#  the pet (a springy pop, then it settles docked in the home).  Nothing
#  ever pops/spawns out of nowhere.  Pillow-rendered exactly like the
#  home frame; guarded so a failure can never keep the pet from starting.
# =====================================================================
import math
import os
import time

import tkinter as tk

from PIL import Image, ImageDraw

import ledpet_core as C

# ------------------------- geometry (design units) ----------------------
# (the home frame is 520 x 822 - this one is its little sibling)
FW, FH = 348.0, 430.0
HEAD = 52.0                            # header band (LED + brand)
SEP2 = 320.0                           # second dotted separator
SCR = dict(x0=26.0, y0=64.0, x1=322.0, y1=308.0)   # the mini dot screen
SCR_R = 14.0                           # screen corner radius
GRID_P = 8.0                           # screen cell pitch
BTN_C = (174.0, 362.0)                 # DONE button centre
BTN_R = 22.0
LBL_Y = BTN_C[1] + BTN_R + 8.0         # 'DONE' label under the disk

GLASS = (9, 9, 11, 242)                # same glass as the home frame
SCREEN = (3, 3, 4, 255)                # same solid black screen
DISK = (20, 20, 24, 255)               # same button disk base
RED = (255, 52, 52)
WHITE = (240, 240, 244)

DISC_C = (FW / 2.0, 118.0)             # the happy dot, resting centre
DISC_R = 6.0                           # disc radius in screen cells
DISC_P = 8.0                           # cell pitch inside the disc
EYES = {(-2, -2), (-2, -1), (-2, 0), (2, -2), (2, -1), (2, 0)}

T_WANT = 186.0                         # 'GIVE ME A NAME' centre y
N_WANT = 228.0                         # the typed name centre y
H_WANT = 272.0                         # the hint centre y


def _fit_pitch(text, want, max_w):
    """shrink the LED font pitch until the text fits max_w design units
    (the home frame's own helper, same rule)"""
    n = max(1.0, _text_w(text, 1.0))
    return max(1.6, min(want, max_w / n))


def _text_w(text, pitch):
    """LED dot text width (same rule as home_render.text_w)"""
    w = 0
    for ch in text:
        rows = C.FONT5.get(ch)
        if rows:
            w += len(rows[0]) + 1
    return max(0, w - 1) * pitch


def _mix_white(rgb, k):
    return (int(rgb[0] + (255 - rgb[0]) * k), int(rgb[1] + (255 - rgb[1]) * k),
            int(rgb[2] + (255 - rgb[2]) * k))


def _scr_cell(c, r):
    """screen cell (c, r) -> design-unit centre"""
    return (SCR['x0'] + (c + 0.5) * GRID_P, SCR['y0'] + (r + 0.5) * GRID_P)


class NameRenderer:
    """a mini HomeRenderer: same tools, same layered static, same bands"""

    def __init__(self, scale=1.0, ss=2):
        self.scale = float(scale)
        self.ss = max(1, int(ss))
        self.W = max(8, int(round(FW * self.scale)))
        kf = self.W / float(FW)               # final px per design unit
        self.H = max(8, int(round(FH * kf)))
        self.kf = kf
        self.k = kf * self.ss                 # ss px per design unit
        self.b = [0, int(round(HEAD * kf)), int(round(SEP2 * kf)), self.H]
        self.static = self._build_static()
        self.sband = [self.static.crop((0, self.b[i] * self.ss, self.W * self.ss, self.b[i + 1] * self.ss))
                      for i in range(3)]
        self._cache = {}

    # ----------------------------- draw tools -----------------------------
    # (verbatim home_render idioms)
    def _circ(self, d, x, y, r, fill, oy=0):
        k = self.k
        d.ellipse([(x - r) * k, (y - r) * k - oy, (x + r) * k, (y + r) * k - oy], fill=fill)

    def _ring(self, d, x, y, r, w, col, oy=0):
        k = self.k
        d.ellipse([(x - r) * k, (y - r) * k - oy, (x + r) * k, (y + r) * k - oy],
                  outline=col, width=max(1, int(round(w * k))))

    def _rrect(self, d, x0, y0, x1, y1, rad, fill=None, outline=None, w=1.0, oy=0):
        k = self.k
        box = [x0 * k, y0 * k - oy, x1 * k, y1 * k - oy]
        try:
            d.rounded_rectangle(box, radius=rad * k, fill=fill, outline=outline,
                                width=max(1, int(round(w * k))))
        except AttributeError:
            d.rectangle(box, fill=fill, outline=outline)

    def _text(self, d, text, x, y, pitch, col, oy=0, align='left', rr=0.42):
        w = _text_w(text, pitch)
        if align == 'center':
            x -= w / 2.0
        elif align == 'right':
            x -= w
        cx = x
        for ch in text:
            rows = C.FONT5.get(ch)
            if not rows:
                continue
            for r, row in enumerate(rows):
                for c, bit in enumerate(row):
                    if bit == '1':
                        self._circ(d, cx + c * pitch + pitch / 2, y + r * pitch + pitch / 2,
                                   pitch * rr, col, oy)
            cx += (len(rows[0]) + 1) * pitch

    # ------------------------------ static layer ----------------------------
    # v17.8 FIX, the home frame's own lesson (kept exactly here): every dim
    # detail must be alpha-BLENDED over the bases. Pillow does not blend
    # when you draw directly - it REPLACES the pixels, so each faint
    # dot/ring would punch a tiny SEE-THROUGH HOLE into the dark glass.
    # Bases first, details on their own overlay, then alpha_composite.
    def _build_static(self):
        ss = self.ss
        img = Image.new('RGBA', (self.W * ss, self.H * ss), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        # ---- 1) the opaque-ish bases (drawn directly) ----
        # body: black glass
        self._rrect(d, 1.0, 1.0, FW - 1.0, FH - 1.0, 26.0, fill=GLASS)
        # the dot screen (solid black, like the home display)
        self._rrect(d, SCR['x0'], SCR['y0'], SCR['x1'], SCR['y1'], SCR_R, fill=SCREEN)
        # the DONE button disk
        self._circ(d, BTN_C[0], BTN_C[1], BTN_R, DISK)
        # ---- 2) printed details, alpha-blended over the bases ----
        ov = Image.new('RGBA', img.size, (0, 0, 0, 0))
        o = ImageDraw.Draw(ov)
        # glass rim + inner hairline (blended -> a solid faint edge, no holes)
        self._rrect(o, 1.0, 1.0, FW - 1.0, FH - 1.0, 26.0,
                    outline=(255, 255, 255, 96), w=1.8)
        self._rrect(o, 5.0, 5.0, FW - 5.0, FH - 5.0, 22.0,
                    outline=(255, 255, 255, 30), w=1.0)
        # faint dot grid on the dock glass (the home body grid, mini)
        for gy in range(int(SEP2) + 10, int(FH) - 8, 14):
            for gx in range(18, int(FW) - 12, 14):
                self._circ(o, gx, gy, 1.15, (255, 255, 255, 22))
        # dotted separator lines between the sections
        for yy in (HEAD, SEP2):
            x = 24.0
            while x < FW - 18:
                self._circ(o, x, yy, 1.3, (255, 255, 255, 90))
                x += 6.0
        # corner marks (the home frame's registration corners)
        for cx, cy in ((20, HEAD + 14), (FW - 20, HEAD + 14),
                       (20, SEP2 - 14), (FW - 20, SEP2 - 14)):
            for dx, dy in ((0, 0), (-3, 0), (3, 0), (0, -3), (0, 3)):
                self._circ(o, cx + dx, cy + dy, 1.0, (255, 255, 255, 105))
        # screen rim + its faint unlit dot grid (exactly the home display)
        self._rrect(o, SCR['x0'], SCR['y0'], SCR['x1'], SCR['y1'], SCR_R,
                    outline=(255, 255, 255, 110), w=1.8)
        cols = int((SCR['x1'] - SCR['x0']) / GRID_P)
        rows = int((SCR['y1'] - SCR['y0']) / GRID_P)
        ox = (SCR['x1'] - SCR['x0'] - cols * GRID_P) / 2.0
        oy = (SCR['y1'] - SCR['y0'] - rows * GRID_P) / 2.0
        for r in range(rows):
            for c in range(cols):
                x = SCR['x0'] + ox + (c + 0.5) * GRID_P
                y = SCR['y0'] + oy + (r + 0.5) * GRID_P
                self._circ(o, x, y, GRID_P * 0.32, (255, 255, 255, 30))
        img = Image.alpha_composite(img, ov)
        return img

    # -------------------------------- bands ---------------------------------
    def _band(self, i, drawfn, S):
        base = self.sband[i].copy()
        ov = Image.new('RGBA', base.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(ov)
        drawfn(d, self.b[i] * self.ss, S)
        comp = Image.alpha_composite(base, ov)
        pm = comp.convert('RGBa')
        if self.ss > 1:
            pm = pm.reduce(self.ss)
        return Image.frombytes('RGBA', pm.size, pm.tobytes())

    def _cached(self, i, sig, drawfn, S):
        hit = self._cache.get(i)
        if hit is not None and hit[0] == sig:
            return hit[1]
        img = self._band(i, drawfn, S)
        self._cache[i] = (sig, img)
        return img

    # ------------------------------- header ---------------------------------
    def _draw_header(self, d, oy, S):
        t = S.get('t', 0.0)
        # pulsing red LED (same formula as the home header)
        pulse = 0.55 + 0.45 * math.sin(t * 3.0)
        self._circ(d, 26, 26, 7.6, RED + (int(22 * pulse),), oy)
        self._circ(d, 26, 26, 3.2, RED + (int(90 + 165 * pulse),), oy)
        # brand mark - here the app itself; the pet's real name (or 'LED PET'
        # when it stays unnamed) shows in the home frame header later
        brand = 'LEDPET'
        bp = _fit_pitch(brand, 3.4, 150.0)
        self._text(d, brand, 40.0, 26.0 - 3.5 * bp, bp, WHITE + (255,), oy)

    # ------------------------------- screen ---------------------------------
    def _draw_screen(self, d, oy, S):
        acc = tuple(S.get('accent', WHITE))
        t = S.get('t', 0.0)
        glow = (acc[0], acc[1], acc[2])
        birth = S.get('birth')             # None, or seconds since the
                                           # birth sequence started

        def dot(x, y, b):
            """one lit cell - exactly how the home dock draws lit cells"""
            self._circ(d, x, y, GRID_P * 0.66, glow + (int(34 * b),), oy)
            self._circ(d, x, y, GRID_P * 0.37, acc + (int(255 * b),), oy)
            if b > 0.85:
                self._circ(d, x, y, GRID_P * 0.20, _mix_white(acc, 0.6) + (255,), oy)

        if birth is not None:
            self._draw_birth(d, oy, S, birth, dot)
            return

        # ---- the happy dot, wiggling at the top ----
        bob = math.sin(t * 3.4) * 4.0
        sway = math.sin(t * 1.9) * 2.2
        blink = (t % 4.2) < 0.14
        dcx, dcy = DISC_C[0] + sway, DISC_C[1] + bob
        c0 = (dcx - SCR['x0']) / GRID_P - 0.5
        r0 = (dcy - SCR['y0']) / GRID_P - 0.5
        R2 = DISC_R * DISC_R
        for gy in range(-int(DISC_R) - 1, int(DISC_R) + 2):
            for gx in range(-int(DISC_R) - 1, int(DISC_R) + 2):
                if gx * gx + gy * gy > R2:
                    continue
                if (gx, gy) in EYES:
                    if blink:
                        b = 0.22               # closed lids for a moment
                    else:
                        continue               # the dark eye cutouts
                else:
                    b = 1.0
                # soft edge: the outermost ring of the disc dims a little
                if gx * gx + gy * gy > R2 - 2.0:
                    b = min(b, 0.78)
                x, y = _scr_cell(c0 + gx, r0 + gy)
                if SCR['x0'] <= x <= SCR['x1'] and SCR['y0'] <= y <= SCR['y1']:
                    dot(x, y, b)

        # ---- the words ----
        self._text(d, 'GIVE ME A NAME', FW / 2, T_WANT - 3.5 * 3.4, 3.4,
                   WHITE + (235,), oy, align='center')
        # ---- the typed name + blinking LED cursor ----
        nm = S.get('name', '')
        pn = _fit_pitch(nm + 'I', 3.8, SCR['x1'] - SCR['x0'] - 28.0)
        if nm:
            self._text(d, nm, FW / 2, N_WANT - 3.5 * pn, pn, WHITE + (255,),
                       oy, align='center')
        if int(t * 2.2) % 2 == 0:
            cu = _text_w(nm, pn)
            cx = FW / 2 + cu / 2 - pn * 0.45
            cy = N_WANT + 3.5 * pn + 3.0
            self._circ(d, cx, cy, pn * 0.34, acc + (200,), oy)
            self._circ(d, cx - pn * 0.55, cy, pn * 0.30, acc + (150,), oy)
        # ---- the hint ----
        self._text(d, 'TYPE + PRESS ENTER', FW / 2, H_WANT - 2.5 * 2.2, 2.2,
                   (255, 255, 255, 120), oy, align='center')

    # --------------------------- birth scene --------------------------------
    # the hatching scene: the happy dot IS the egg and it stays CRISP -
    # everything plays on the dialog's own LED cells.
    #   - the words fade away (nobody is typing any more)
    #   - the dot freezes at its resting centre, its heartbeat accelerates
    #   - it squints (shuts its eyes) and shivers ... straining to hatch
    #   - LED rings ripple out of it, faster and brighter
    #   - a white core charges up inside it ... until the BURST
    RING_PERIOD, RING_LIFE = 0.22, 0.60

    def _draw_birth(self, d, oy, S, bt, dot):
        acc = tuple(S.get('accent', WHITE))
        glow = (acc[0], acc[1], acc[2])
        dot_d = DISC_R * DISC_P            # the happy dot's radius (design px)
        charge = max(0.5, float(S.get('charge', 0.80)))

        # ---- 1) the words fade away in the first moments ----
        ta = max(0.0, 1.0 - bt / 0.25)
        if ta > 0.0:
            self._text(d, 'GIVE ME A NAME', FW / 2, T_WANT - 3.5 * 3.4, 3.4,
                       WHITE + (int(235 * ta),), oy, align='center')
            nm = S.get('name', '')
            if nm:
                pn = _fit_pitch(nm + 'I', 3.8, SCR['x1'] - SCR['x0'] - 28.0)
                self._text(d, nm, FW / 2, N_WANT - 3.5 * pn, pn,
                           WHITE + (int(255 * ta),), oy, align='center')
            self._text(d, 'TYPE + PRESS ENTER', FW / 2, H_WANT - 2.5 * 2.2, 2.2,
                       (255, 255, 255, int(120 * ta)), oy, align='center')

        # ---- 1b) the egg's vitals: the heartbeat accelerates, the disc
        # breathes with it, and the last moments add shivers ----
        pk = 0.5 + 0.5 * math.sin(bt * (10.0 + bt * 12.0))    # accelerating
        kr = 1.0 + 0.10 * pk               # the disc breathes with the heart
        bb = min(1.0, 0.92 + 0.30 * pk)    # cells brighten on the squeeze
        jx = jy = 0.0
        if bt > charge - 0.15:             # the last nervous shivers
            jk = (bt - (charge - 0.15)) / 0.15
            jx = math.sin(bt * 88.0) * 1.6 * jk
            jy = math.cos(bt * 73.0) * 1.2 * jk

        # ---- 2) the charging aura BEHIND the egg + the expanding rings.
        # PIL's ImageDraw REPLACES pixels (no blending!), so everything
        # faint MUST be drawn BEFORE the bright cell cores or it wipes
        # them into a dim fog ----
        gr = dot_d * (1.00 + 0.22 * pk)
        self._circ(d, DISC_C[0], DISC_C[1], gr * 1.30,
                   acc + (int(10 + 12 * pk),), oy)
        self._circ(d, DISC_C[0], DISC_C[1], gr * 1.12,
                   acc + (int(16 + 20 * pk),), oy)
        self._circ(d, DISC_C[0], DISC_C[1], gr * 0.90,
                   acc + (int(26 + 30 * pk),), oy)
        for i in range(3):
            age = bt - i * self.RING_PERIOD
            if age < 0.0 or age > self.RING_LIFE:
                continue
            k = age / self.RING_LIFE
            rr = dot_d * (0.85 + 2.35 * k)
            al = int(175 * (1.0 - k) ** 1.5)
            if al > 4:
                self._ring(d, DISC_C[0], DISC_C[1], rr, 1.1, acc + (al,), oy)
                self._ring(d, DISC_C[0], DISC_C[1], rr + 2.6, 0.7,
                           acc + (max(0, int(al * 0.35)),), oy)

        # ---- 3) the egg itself: the happy dot holds its centre while
        # its heart pounds faster and faster; near the end it squints
        # and shivers.  Drawn ON TOP of the aura + rings ----
        squint = bt > charge - 0.42        # eyes shut: it is straining
        c0 = (DISC_C[0] + jx - SCR['x0']) / GRID_P - 0.5
        r0 = (DISC_C[1] + jy - SCR['y0']) / GRID_P - 0.5
        R2 = DISC_R * DISC_R * kr * kr
        for gy in range(-int(DISC_R) - 2, int(DISC_R) + 3):
            for gx in range(-int(DISC_R) - 2, int(DISC_R) + 3):
                if gx * gx + gy * gy > R2:
                    continue
                if (gx, gy) in EYES:
                    if not squint:
                        continue           # the dark eye cutouts
                    b = 0.22               # shut lids for the final effort
                else:
                    b = bb
                # soft edge: the outermost ring of the disc dims a little
                if gx * gx + gy * gy > R2 - 2.0:
                    b = min(b, 0.78)
                x, y = _scr_cell(c0 + gx, r0 + gy)
                if SCR['x0'] <= x <= SCR['x1'] and SCR['y0'] <= y <= SCR['y1']:
                    dot(x, y, b)

        # ---- 4) the white core charging ... about to burst ----
        if bt > charge - 0.30:
            fk = min(1.0, (bt - (charge - 0.30)) / 0.30)
            cr = dot_d * (0.26 + 1.10 * fk)
            self._circ(d, DISC_C[0], DISC_C[1], cr,
                       _mix_white(acc, 0.55) + (int(145 * fk),), oy)
            self._circ(d, DISC_C[0], DISC_C[1], cr * 0.55,
                       (255, 255, 255, int(225 * fk)), oy)

    # -------------------------------- dock ----------------------------------
    def _draw_dock(self, d, oy, S):
        bx, by = BTN_C
        hover = S.get('hover', False)
        pressed = S.get('pressed', False)
        if pressed:
            self._circ(d, bx, by, BTN_R - 1.0, (255, 255, 255, 48), oy)
        ring = (255, 255, 255, 255) if hover else (255, 255, 255, 120)
        self._ring(d, bx, by, BTN_R, 1.9 if hover else 1.5, ring, oy)
        # the pet's two eyes inside the disk (the little guy says yes)
        for side in (-1, 1):
            for r in range(3):
                self._circ(d, bx + side * 4.2, by - 2.8 + r * 2.8, 1.15,
                           WHITE + (255,), oy)
        self._text(d, 'DONE', bx, LBL_Y, 2.7,
                   (255, 255, 255, 255 if hover else 235), oy, align='center')

    # ------------------------------ one frame ------------------------------
    def frame(self, S):
        acc = tuple(int(v) for v in S.get('accent', WHITE))
        t = S.get('t', 0.0)
        sig_h = (acc, int(t * 3.0))
        # the birth screen has its own cache signature
        sig_s = (acc, S.get('name', ''), int(t * 100.0),
                 'B' if S.get('birth') is not None else '')
        sig_d = (acc, bool(S.get('hover')), bool(S.get('pressed')))
        hdr = self._cached(0, sig_h, self._draw_header, S)
        scr = self._cached(1, sig_s, self._draw_screen, S)
        dck = self._cached(2, sig_d, self._draw_dock, S)
        out = Image.new('RGBA', (self.W, self.H), (0, 0, 0, 0))
        out.paste(hdr, (0, self.b[0]))
        out.paste(scr, (0, self.b[1]))
        out.paste(dck, (0, self.b[2]))
        return out


class NameDialog:
    """the centered first-run naming frame - a mini HomeFrame (same cap-
    dict input state machine, same tick loop, same guarded close)"""

    TICK = 1.0 / 20.0               # same active rate as the home frame

    def __init__(self, root, on_done=None, make_layer=None,
                 accent=(246, 246, 246), scale=1.0):
        self.root = root
        self.on_done = on_done
        self.accent = tuple(int(v) for v in accent)
        self.name = ''
        self.closed = False
        self.hover = False
        self.pressed = False
        self.cap = None
        self.morphing = False          # LEDPET_V1_MORPH: animating the
        self.morph_fn = None           # hand-over to the home frame
        self.ss = 2
        self.kf = float(scale)                  # final px per unit
        self.W = max(8, int(round(FW * self.kf)))
        self.H = max(8, int(round(FH * self.kf)))
        self._after = None
        self._pos_sent = None
        self._pm = None
        self._last_render = 0.0

        self.ren = NameRenderer(self.kf, ss=self.ss)

        self.top = tk.Toplevel(root)
        self.top.title('LEDPET')
        self.top.overrideredirect(True)
        self.top.config(bg='black')
        try:
            sw = root.winfo_screenwidth()
            sh = root.winfo_screenheight()
        except Exception:
            sw, sh = 1920, 1080
        # EXACTLY the middle of the (primary) monitor
        self.x = (sw - self.W) // 2
        self.y = (sh - self.H) // 2
        self.top.geometry('%dx%d+%d+%d' % (self.W, self.H, self.x, self.y))
        try:
            self.top.attributes('-topmost', True)
        except Exception:
            pass
        self.top.update()

        self.layer = None
        if make_layer is not None:
            # the naming frame must accept KEYBOARD focus: unlike the home
            # frame it is created WITHOUT WS_EX_NOACTIVATE (that style is
            # what silently ate every keystroke on Windows)
            try:
                self.layer, self.hwnd = make_layer(self.top, self.W, self.H,
                                                   noactivate=False)
            except TypeError:
                try:
                    self.layer, self.hwnd = make_layer(self.top, self.W, self.H)
                except Exception:
                    self.layer = None
            except Exception:
                self.layer = None
        if self.layer is None:
            try:
                from pet_windows import TkLayer      # lazy: no import cycle
                self.layer = TkLayer(self.top, self.W, self.H)
            except Exception:
                self.layer = None

        # --- input (the HomeFrame state machine, mini) ---
        self.top.bind('<Button-1>', self.press_ev)
        self.top.bind('<B1-Motion>', self.drag_ev)
        self.top.bind('<ButtonRelease-1>', self.release_ev)
        self.top.bind('<Motion>', self.motion_ev)
        self.top.bind('<Key>', self.key_ev)
        self._grab_focus()

        self._dirty = True
        self.tick()

    # --------------------------- focus (typing!) ---------------------------
    def _grab_focus(self):
        """force the keyboard to the naming frame (Tk + the Win32 truth)"""
        try:
            self.top.lift()
            self.top.focus_set()
            self.top.focus_force()
        except Exception:
            pass
        if os.name == 'nt':
            try:
                import ctypes
                u = ctypes.windll.user32
                hwnd = int(self.top.winfo_id() or 0)
                ph = u.GetParent(hwnd) if hwnd else 0
                if ph:
                    hwnd = ph
                if hwnd and u.SetForegroundWindow(hwnd):
                    u.SetFocus(hwnd)
            except Exception:
                pass

    # ------------------------------ events ------------------------------
    def owns_event(self, e):
        try:
            return e.widget.winfo_toplevel() is self.top
        except Exception:
            return False

    def _unit(self, ex, ey):
        return ex / self.kf, ey / self.kf

    def _on_btn(self, ux, uy, slack):
        return math.hypot(ux - BTN_C[0], uy - BTN_C[1]) <= BTN_R + slack

    def press_ev(self, e):
        self._grab_focus()
        if self.closed or self.morphing:
            return
        ux, uy = self._unit(e.x, e.y)
        if self._on_btn(ux, uy, 4.0):
            self.cap = {'kind': 'btn', 'name': 'done', 'moved': False}
            self.pressed = True
            self._dirty = True
            return
        self.cap = {'kind': 'drag', 'x0': e.x_root, 'y0': e.y_root,
                    'x0w': self.x, 'y0w': self.y, 'moved': False}

    def drag_ev(self, e):
        cap = self.cap
        if cap is None or self.closed or self.morphing:
            return
        dx, dy = e.x_root - cap['x0'], e.y_root - cap['y0']
        if not cap['moved'] and dx * dx + dy * dy > 16:
            cap['moved'] = True
            self.pressed = False
            self._dirty = True
        if cap['moved'] and cap['kind'] == 'drag':
            # the layered window is moved by layer.present (the home frame's
            # way) - never by a second Tk geometry call (that double-move
            # race was a v1.0 bug)
            self.x = cap['x0w'] + dx
            self.y = cap['y0w'] + dy

    def release_ev(self, e):
        cap, self.cap = self.cap, None
        if self.closed or self.morphing:
            return
        self.pressed = False
        self._dirty = True
        if cap is None:
            return
        if cap['kind'] == 'btn' and not cap['moved']:
            ux, uy = self._unit(e.x, e.y)
            if self._on_btn(ux, uy, 6.0):
                self.done()

    def motion_ev(self, e):
        if self.closed or self.morphing:
            return
        ux, uy = self._unit(e.x, e.y)
        hov = self._on_btn(ux, uy, 4.0)
        if hov != self.hover:
            self.hover = hov
            self._dirty = True

    def key_ev(self, e):
        if self.closed or self.morphing:
            return
        ks = getattr(e, 'keysym', '')
        if ks in ('Return', 'KP_Enter'):
            self.done()
            return
        if ks == 'Escape':
            self.done()                      # skip = stay unnamed
            return
        if ks in ('BackSpace', 'Delete'):
            self.name = self.name[:-1]
            self._dirty = True
            return
        try:
            ch = e.char
        except Exception:
            ch = ''
        if isinstance(ch, str) and len(ch) == 1 and 32 <= ord(ch) < 127:
            # ONE source of truth: ledpet_core.sanitize_name does the
            # uppercase / glyph filter / collapse / 12-char cap
            self.name = C.sanitize_name(self.name + ch)
            self._dirty = True

    # ------------------------------ finish ------------------------------
    def dot_screen(self):
        """the happy dot's centre in SCREEN coordinates (the pet grows
        exactly here when the morph plays)"""
        return (self.x + DISC_C[0] * self.kf, self.y + DISC_C[1] * self.kf)

    def start_morph(self, fn):
        """LEDPET_V1_MORPH: hand the frame over to the morph engine.
        fn(t_seconds) -> (img, x, y) presented every tick, or None when the
        morph is over (the app has already closed/took over everything).
        While morphing all input is blocked and the own rendering stops."""
        if self.closed:
            return
        self.morphing = True
        self.morph_fn = fn
        self.cap = None
        self.pressed = False
        self.hover = False
        if self._after is None and not self.closed:
            self.tick()          # a dead loop must keep the morph running

    def done(self):
        if self.closed or self.morphing:
            return
        nm = C.sanitize_name(self.name)
        cb = self.on_done
        taken = False
        if cb is not None:
            try:
                # v1.0 morph: the app may KEEP this frame alive to animate
                # it into the home frame (returns True = taken over)
                taken = bool(cb(nm))
            except Exception:
                taken = False
        if not taken:
            self.close()

    def close(self):
        if self.closed:
            return
        self.closed = True
        try:
            if self._after is not None:
                self.top.after_cancel(self._after)
        except Exception:
            pass
        try:
            if self.layer is not None:
                self.layer.close()
        except Exception:
            pass
        try:
            self.top.destroy()
        except Exception:
            pass

    # --------------------------- render / present ---------------------------
    def tick(self):
        """the HomeFrame tick loop: render when dirty or due, present when
        the frame moved or was re-rendered"""
        if self.closed:
            return
        self._after = None
        try:
            # ---- LEDPET_V1_MORPH: the engine drives the frames ----
            if self.morphing and self.morph_fn is not None:
                try:
                    fr = self.morph_fn(time.time())
                except Exception:
                    fr = None
                if fr is None:
                    # the app finished/closed everything; if we are still
                    # here for any reason, quietly resume the own loop
                    self.morphing = False
                    if not self.closed:
                        self._dirty = True
                        self._after = self.top.after(int(1000 * self.TICK), self.tick)
                    return
                img, mx, my = fr
                try:
                    self.layer.present(img, int(round(mx)), int(round(my)))
                except Exception:
                    pass
                self._after = self.top.after(int(1000 * self.TICK), self.tick)
                return
            now = time.time()
            if self._dirty or now - self._last_render >= self.TICK:
                self._render(now)
            pos = (int(round(self.x)), int(round(self.y)))
            if self._pm is not None and (pos != self._pos_sent
                                         or self._last_render == now):
                self._present(pos)
            self._after = self.top.after(int(1000 * self.TICK), self.tick)
        except Exception:
            self.closed = True

    def _render(self, now):
        self._last_render = now
        self._dirty = False
        S = dict(t=now, accent=self.accent, name=self.name,
                 hover=self.hover, pressed=self.pressed)
        try:
            self._pm = self.ren.frame(S)
        except Exception:
            self._pm = None

    def _present(self, pos):
        ok = False
        try:
            ok = self.layer.present(self._pm, pos[0], pos[1])
        except Exception:
            ok = False
        self._pos_sent = pos if ok else None
