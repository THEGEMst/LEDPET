# -*- coding: utf-8 -*-
# =====================================================================
#  LEDPet - 'home frame' renderer with a Nothing OS vibe (v13)
#     Pillow only (no Tk) -> every frame outputs a premultiplied RGBA image
#     three bands: header (needs) / body (pet slot) / dock (display + buttons)
#     each band is redrawn only when it changes (low cost)
# =====================================================================
import math

from PIL import Image, ImageDraw

import ledpet_core as C

# ------------------------- geometry (design units) ----------------------
FW, HEAD, BODY = 520, 56, 548
FH = 822
PET_OFF = (0, HEAD)                       # pet window corner inside the frame
DISP_COLS, DISP_ROWS = 60, 11
DP = dict(x0=20.0, y0=HEAD + BODY + 8.0, x1=500.0, y1=HEAD + BODY + 112.0)
CELL = (480.0 - 28.0) / DISP_COLS
GRID_X0 = 34.0
GRID_Y0 = DP['y0'] + ((DP['y1'] - DP['y0']) - DISP_ROWS * CELL) / 2.0
BTN_R = 27.0
BTN_Y = DP['y1'] + 16.0 + BTN_R
BUTTONS = (('food', 104.0), ('water', 208.0), ('play', 312.0), ('follow', 416.0))
PET_CENTER = (C.CX, HEAD + C.CY)          # pet circle center in the frame

RED = (255, 52, 52)
WHITE = (240, 240, 244)
FOOD_RGB = (255, 196, 110)
WATER_RGB = (120, 205, 255)

ICONS = {
    'food': ('001111100', '011111110', '111111111', '000000000',
             '111111111', '000000000', '011111110', '001111100'),
    'water': ('000010000', '000010000', '000111000', '000111000', '001111100',
              '011111110', '011111110', '011111110', '001111100'),
    'play': ('110000000', '111100000', '111111000', '111111110', '111111111',
             '111111110', '111111000', '111100000', '110000000'),
    'stop': ('111111111', '111111111', '111111111', '111111111', '111111111',
             '111111111', '111111111', '111111111', '111111111'),
    'follow': ('10000000', '11000000', '11100000', '11110000', '11111000', '11111100',
               '11111110', '11111000', '11011000', '10011000', '00001100'),
    'fun': ('01010', '01010', '00000', '10001', '01110'),
    'mini_food': ('01110', '11111', '10101', '11111', '01110'),
    'mini_water': ('00100', '00100', '01110', '11111', '01110'),
}
LABELS = {'food': 'FOOD', 'water': 'WATER', 'play': 'PLAY', 'follow': 'FOLLOW'}


def button_at(x, y):
    for name, bx in BUTTONS:
        if math.hypot(x - bx, y - BTN_Y) <= BTN_R + 4.0:
            return name
    return None


def button_center(name):
    for n, bx in BUTTONS:
        if n == name:
            return bx, BTN_Y
    return None


def in_display(x, y):
    return DP['x0'] <= x <= DP['x1'] and DP['y0'] <= y <= DP['y1']


def disp_xy(c, r):
    return GRID_X0 + (c + 0.5) * CELL, GRID_Y0 + (r + 0.5) * CELL


def disp_cell_at(x, y):
    """design-unit position -> (float) display cell coords; cell c spans [c, c+1)"""
    return (x - GRID_X0) / CELL, (y - GRID_Y0) / CELL


def _clamp(v, a, b):
    return a if v < a else (b if v > b else v)


def _mix_white(rgb, k):
    return (int(rgb[0] + (255 - rgb[0]) * k), int(rgb[1] + (255 - rgb[1]) * k),
            int(rgb[2] + (255 - rgb[2]) * k))


def _fit_pitch(text, want, max_w):
    """shrink the LED font pitch until the text fits max_w design units"""
    n = max(1.0, text_w(text, 1.0))
    return max(1.6, min(want, max_w / n))


def text_w(text, pitch):
    w = 0
    for ch in text:
        rows = C.FONT5.get(ch)
        if rows:
            w += len(rows[0]) + 1
    return max(0, w - 1) * pitch


class HomeRenderer:
    def __init__(self, scale=0.8, ss=2):
        self.scale = float(scale)
        self.ss = max(1, int(ss))
        self.W = max(8, int(round(FW * self.scale)))
        kf = self.W / float(FW)                       # final px per design unit
        self.H = max(8, int(round(FH * kf)))
        self.kf = kf
        self.k = kf * self.ss                         # ss px per design unit
        self.b = [0, int(round(HEAD * kf)), int(round((HEAD + BODY) * kf)), self.H]
        self.static = self._build_static()
        self.sband = [self.static.crop((0, self.b[i] * self.ss, self.W * self.ss, self.b[i + 1] * self.ss))
                      for i in range(3)]
        self._cache = {}

    # ----------------------------- draw tools -----------------------------
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

    def _bitmap(self, d, rows, cx, cy, pitch, col, oy=0, rr=0.42):
        h, w = len(rows), len(rows[0])
        x0 = cx - (w - 1) * pitch / 2.0
        y0 = cy - (h - 1) * pitch / 2.0
        for r, row in enumerate(rows):
            for c, bit in enumerate(row):
                if bit == '1':
                    self._circ(d, x0 + c * pitch, y0 + r * pitch, pitch * rr, col, oy)

    def _text(self, d, text, x, y, pitch, col, oy=0, align='left', rr=0.42):
        w = text_w(text, pitch)
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
    # v17.8 FIX (the "contents are hard to see" bug): every dim detail used to
    # be drawn DIRECTLY onto the glass with ImageDraw. Pillow does not blend
    # there - it REPLACES the pixels, so each faint dot/ring punched a tiny
    # SEE-THROUGH HOLE into the dark glass. ~1500 holes let the wallpaper
    # shine through and drowned everything the frame actually shows. Now the
    # bases are drawn first and every detail goes on its own layer that is
    # alpha-BLENDED over them (a faint dot ON the glass, not a hole IN it).
    def _build_static(self):
        ss = self.ss
        img = Image.new('RGBA', (self.W * ss, self.H * ss), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        # ---- 1) the opaque-ish bases (drawn directly) ----
        # body: black glass
        self._rrect(d, 1.0, 1.0, FW - 1.0, FH - 1.0, 38.0, fill=(9, 9, 11, 242))
        # the dot display (solid black screen)
        self._rrect(d, DP['x0'], DP['y0'], DP['x1'], DP['y1'], 16.0, fill=(3, 3, 4, 255))
        # button disks
        for name, bx in BUTTONS:
            self._circ(d, bx, BTN_Y, BTN_R, (20, 20, 24, 255))
        # ---- 2) printed details, alpha-blended over the bases ----
        ov = Image.new('RGBA', img.size, (0, 0, 0, 0))
        o = ImageDraw.Draw(ov)
        # glass rim + inner hairline (blended -> a solid faint edge, no holes)
        self._rrect(o, 1.0, 1.0, FW - 1.0, FH - 1.0, 38.0,
                    outline=(255, 255, 255, 96), w=1.8)
        self._rrect(o, 5.0, 5.0, FW - 5.0, FH - 5.0, 34.0, outline=(255, 255, 255, 30), w=1.0)
        # faint dot grid of the 'screen'
        for gy in range(int(HEAD + 12), int(HEAD + BODY - 8), 14):
            for gx in range(18, FW - 12, 14):
                self._circ(o, gx, gy, 1.15, (255, 255, 255, 22))
        # dotted separator lines between sections
        for yy in (HEAD, HEAD + BODY):
            x = 26.0
            while x < FW - 20:
                self._circ(o, x, yy, 1.3, (255, 255, 255, 90))
                x += 6.0
        # brand mark + corners
        for cx, cy in ((18, HEAD + 14), (FW - 18, HEAD + 14), (18, HEAD + BODY - 14), (FW - 18, HEAD + BODY - 14)):
            for dx, dy in ((0, 0), (-3, 0), (3, 0), (0, -3), (0, 3)):
                self._circ(o, cx + dx, cy + dy, 1.0, (255, 255, 255, 105))
        # display screen rim + its faint unlit dot grid
        self._rrect(o, DP['x0'], DP['y0'], DP['x1'], DP['y1'], 16.0,
                    outline=(255, 255, 255, 110), w=1.8)
        for r in range(DISP_ROWS):
            for c in range(DISP_COLS):
                x, y = disp_xy(c, r)
                self._circ(o, x, y, CELL * 0.32, (255, 255, 255, 30))
        # button rings
        for name, bx in BUTTONS:
            self._ring(o, bx, BTN_Y, BTN_R, 1.5, (255, 255, 255, 120))
        img = Image.alpha_composite(img, ov)
        return img

    # -------------------------------- bands ---------------------------------
    def _draw_header(self, d, oy, S):
        acc = tuple(S.get('accent', WHITE))
        t = S.get('t', 0.0)
        away = S.get('away', False)
        # pulsing red LED
        pulse = 0.55 + 0.45 * math.sin(t * 3.0)
        col = (110, 110, 118) if away else RED
        a = int((90 + 165 * pulse) if not away else 120)
        self._circ(d, 30, 28, 11.0, col + (int(22 * pulse) if not away else 0,), oy)
        self._circ(d, 30, 28, 4.4, col + (a,), oy)
        # brand mark = the pet's name once it has one (v1.0 LEDPET_V1_NAME);
        # the LED font pitch shrinks so even a 12-char name fits the header
        brand = str(S.get('brand', '') or '') or 'LED PET'
        bp = _fit_pitch(brand, 4.2, 182.0)
        self._text(d, brand, 46.0, 28.0 - 3.5 * bp, bp, WHITE + (255,), oy)
        # needs bars
        needs = S.get('needs', {})
        for i, (key, icon, rgb) in enumerate((('food', 'mini_food', FOOD_RGB),
                                              ('water', 'mini_water', WATER_RGB),
                                              ('fun', 'fun', acc))):
            gx = 236.0 + i * 94.0
            v = _clamp(float(needs.get(key, 0.5)), 0.0, 1.0)
            low = v < 0.25
            blink = (int(t * 2.5) % 2 == 0)
            self._bitmap(d, ICONS[icon], gx + 8, 28.0, 3.8, (255, 255, 255, 255), oy)
            for j in range(8):
                f = _clamp(v * 8.0 - j, 0.0, 1.0)
                cx = gx + 30.0 + j * 7.6
                if f <= 0.0:
                    self._circ(d, cx, 28.0, 2.4, (255, 255, 255, 60), oy)
                else:
                    c = RED if low else rgb
                    al = int(255 * f * (1.0 if (not low or blink) else 0.35))
                    self._circ(d, cx, 28.0, 2.8, c + (al,), oy)
        self._draw_items(d, oy, S)

    def _draw_items(self, d, oy, S):
        for (kind, x, y, size, alpha) in S.get('items', ()):
            rows = ICONS['food'] if kind == 'food' else ICONS['water']
            rgb = FOOD_RGB if kind == 'food' else WATER_RGB
            al = int(255 * _clamp(alpha, 0.0, 1.0))
            if al <= 3 or size <= 0.05:
                continue
            self._circ(d, x, y, 30.0 * size, rgb + (int(al * 0.16),), oy)
            self._bitmap(d, rows, x, y, 4.6 * size, rgb + (al,), oy, rr=0.44)

    def _draw_body(self, d, oy, S):
        if S.get('away'):
            cx, cy = PET_CENTER
            for k in range(72):
                ang = 2 * math.pi * k / 72.0
                self._circ(d, cx + 150.0 * math.cos(ang), cy + 150.0 * math.sin(ang), 1.7,
                           (255, 255, 255, 70 if k % 2 == 0 else 40), oy)
            self._text(d, 'OUT', cx, cy - 26.0, 7.0, WHITE + (210,), oy, align='center')
            self._text(d, 'TAP FOLLOW TO CALL BACK', cx, cy + 36.0, 3.0, WHITE + (170,), oy, align='center')
        self._draw_items(d, oy, S)

    def _draw_dock(self, d, oy, S):
        acc = tuple(S.get('accent', WHITE))
        cells = S.get('cells', {})
        glow = (acc[0], acc[1], acc[2])
        for (c, r), b in cells.items():
            if not (0 <= c < DISP_COLS and 0 <= r < DISP_ROWS):
                continue
            b = _clamp(b, 0.0, 1.0)
            x, y = disp_xy(c, r)
            self._circ(d, x, y, CELL * 0.66, glow + (int(34 * b),), oy)
            self._circ(d, x, y, CELL * 0.37, acc + (int(255 * b),), oy)
            if b > 0.85:
                self._circ(d, x, y, CELL * 0.20, _mix_white(acc, 0.6) + (255,), oy)
        hover, pressed = S.get('hover'), S.get('pressed')
        disabled = S.get('disabled', ())
        active = S.get('active', ())
        t = S.get('t', 0.0)
        for name, bx in BUTTONS:
            off = name in disabled
            on = name in active
            if pressed == name and not off:
                self._circ(d, bx, BTN_Y, BTN_R - 1.0, (255, 255, 255, 48), oy)
            ring = (255, 255, 255, 120)
            if hover == name and not off:
                ring = (255, 255, 255, 255)
            if on:
                ring = (RED + (255,)) if name == 'follow' else (acc + (255,))
            self._ring(d, bx, BTN_Y, BTN_R, 1.9 if (on or hover == name) else 1.5, ring, oy)
            icon = 'stop' if (name == 'play' and on) else name
            rows = ICONS[icon]
            pitch = 3.0 if icon in ('play', 'stop', 'food', 'water') else 2.9
            ic = (255, 255, 255, 110 if off else 255)
            if on and name == 'follow':
                ic = RED + (255,)
            self._bitmap(d, rows, bx - (1.2 if icon == 'follow' else 0.0), BTN_Y, pitch, ic, oy)
            if on and name == 'follow':
                pu = 0.6 + 0.4 * math.sin(t * 5.0)
                self._circ(d, bx + 19.0, BTN_Y - 19.0, 3.4, RED + (int(110 + 145 * pu),), oy)
            label = 'STOP' if (name == 'play' and on) else LABELS[name]
            self._text(d, label, bx, BTN_Y + BTN_R + 8.0, 2.7,
                       (255, 255, 255, 120 if off else (255 if hover == name else 235)), oy, align='center')

    # ------------------------------ one frame ------------------------------
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

    def frame(self, S):
        t = S.get('t', 0.0)
        acc = tuple(int(v) for v in S.get('accent', WHITE))
        needs = S.get('needs', {})
        nq = tuple(int(_clamp(needs.get(k, 0.5), 0, 1) * 16) for k in ('food', 'water', 'fun'))
        low = tuple(v < 4 for v in nq)
        items = tuple((k, int(x), int(y), round(s, 2), round(a, 2)) for (k, x, y, s, a) in S.get('items', ()))
        sig_h = (acc, nq, S.get('away', False), int(t * 3.0) if not S.get('away') else 0,
                 int(t * 2.5) if any(low) else 0, items,
                 str(S.get('brand', '') or ''))
        sig_b = (S.get('away', False), items)
        cells = S.get('cells', {})
        sig_d = (acc, tuple(sorted(cells.items())), S.get('hover'), S.get('pressed'),
                 tuple(S.get('disabled', ())), tuple(S.get('active', ())),
                 int(t * 4.0) if ('follow' in S.get('active', ())) else 0, items)
        hdr = self._cached(0, sig_h, self._draw_header, S)
        body = self._cached(1, sig_b, self._draw_body, S)
        dock = self._cached(2, sig_d, self._draw_dock, S)
        out = Image.new('RGBA', (self.W, self.H), (0, 0, 0, 0))
        out.paste(hdr, (0, self.b[0]))
        out.paste(body, (0, self.b[1]))
        out.paste(dock, (0, self.b[2]))
        return out

    @staticmethod
    def composite_over(pm, bg_rgb):
        import numpy as np
        a = np.asarray(pm, dtype=np.float32) / 255.0
        bg = np.array(bg_rgb, dtype=np.float32)[None, None, :]
        rgb = a[..., :3] * 255.0 + bg * (1.0 - a[..., 3:4])
        return Image.fromarray(np.clip(rgb, 0, 255).astype('uint8'), 'RGB')
