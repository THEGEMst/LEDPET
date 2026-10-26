# -*- coding: utf-8 -*-
# =====================================================================
#  LEDPet renderer - Pillow only (no Tk) -> testable and previewable
#  every frame outputs a 'premultiplied' RGBA image ready for UpdateLayeredWindow
#
#  transparent version:
#    static  : invisible click/drag disk + very dim unlit dots (built once)
#              - dark glass and the red half-circle were removed (fully transparent)
#    lit     : base ring + equalizer bars + peak caps + clock + face + sparks
#    glow    : narrow glow (2 px) + wide bloom (on the beat) - premultiplied
# =====================================================================
import math

from PIL import Image, ImageDraw, ImageFilter, ImageChops
try:
    import numpy as np
except Exception:
    np = None

import ledpet_core as C

try:
    _OFF = Image.Resampling.BOX
except AttributeError:
    _OFF = getattr(Image, 'BOX', 4)


def _pm(rgb, a):
    """premultiplied color (for the glow layer)"""
    a = max(0, min(255, int(a)))
    k = a / 255.0
    return (int(rgb[0] * k), int(rgb[1] * k), int(rgb[2] * k), a)


def _mix_white(rgb, k):
    return (int(rgb[0] + (255 - rgb[0]) * k), int(rgb[1] + (255 - rgb[1]) * k),
            int(rgb[2] + (255 - rgb[2]) * k))


class Renderer:
    def __init__(self, scale=0.80, ss=2, clock_cols=25, rays=96, clock_on=True, bloom=True,
                 body_fill=False, fill_rgb=(10, 10, 14), deep_dark=False,
                 fill_rgb2=(30, 34, 60)):
        self.scale = float(scale)
        self.ss = max(1, int(ss))
        self.clock_on = bool(clock_on)
        self.clock_cols = int(clock_cols)
        self.bloom = bool(bloom)
        # v17.8 (LEDPET_V17_FILL): optional solid silhouette behind the LEDs
        self.body_fill = bool(body_fill)
        self.fill_rgb = (int(fill_rgb[0]), int(fill_rgb[1]), int(fill_rgb[2]))
        # v18.1 (LEDPET_V18_CUSTOM): second fill color + the deep-dark unlit grid
        self.fill_rgb2 = (int(fill_rgb2[0]), int(fill_rgb2[1]), int(fill_rgb2[2]))
        self.deep_dark = bool(deep_dark)
        # unlit LED grid: the classic warm gray, or a near-black grid that
        # reads as TRUE black on the desktop (the user-visible "black is not
        # really black" fix)
        self._unlit = (34, 34, 38, 34) if self.deep_dark else (118, 112, 118, 44)
        self.s = self.scale * self.ss
        self.W = max(2, int(round(C.BW * self.scale)))
        self.H = max(2, int(round(C.BH * self.scale)))
        self.rw = self.W * self.ss
        self.rh = self.H * self.ss
        self.s = self.rw / float(C.BW)          # exact scale (matches the real width)
        self.sy = self.rh / float(C.BH)
        self.g = C.RayGeom(rays, C.ray_starts(rays))
        self.rays = int(rays)
        self.static = self._build_static()
        # v17 (LEDPET_V17_BODY): warped-position tables + per-frame unlit layer
        self._cell_list = sorted(C.CELLS)
        self._disk = self._build_disk()
        if np is not None:
            self._cx = np.array([C.cell_xy(a, b)[0] for (a, b) in self._cell_list])
            self._cy = np.array([C.cell_xy(a, b)[1] for (a, b) in self._cell_list])
            self._bx = np.array([p[0] for xy in self.g.xy for p in xy])
            self._by = np.array([p[1] for xy in self.g.xy for p in xy])
        else:
            self._cx = self._cy = None
            self._bx = self._by = None
        # --- v18.3 (LEDPET_V18_PERF): pre-computed constants + reused buffers.
        # Every value is identical to what the old per-frame code produced,
        # so the rendered frames stay byte-identical - only the repeated
        # work and the per-frame allocations are gone.
        self._lit = Image.new('RGBA', (self.rw, self.rh), (0, 0, 0, 0))
        self._base = self.static.copy()
        # --- glow layers at a CAPPED internal resolution -----------------
        # The glow is a low-frequency blur field: drawing + blurring it in
        # a small buffer and upscaling the blurred result looks the same
        # (the blur sigma in design units is kept exactly), while the blur
        # cost stops growing with the window size - the single most
        # expensive step on big pets.
        _glmax = 288.0
        _gf = min(1.0, _glmax / max(1.0, float(max(self.W, self.H))))
        self._gw = max(24, int(round(self.W * _gf)))
        self._gh = max(24, int(round(self.H * _gf)))
        self._gk = self.scale * (self._gw / float(self.W))
        self._gl1 = Image.new('RGBA', (self._gw, self._gh), (0, 0, 0, 0))
        self._gl2 = (Image.new('RGBA', (self._gw, self._gh), (0, 0, 0, 0))
                     if self.bloom else None)
        _k1 = self._gk          # glow layer scale (no supersampling)
        self._blur1 = ImageFilter.GaussianBlur(max(0.6, 2.2 * _k1))
        self._blur2 = ImageFilter.GaussianBlur(max(1.5, 8.0 * _k1))
        self._g2_full = None                 # bloom layer upscaled for compose
        self._cellpos = dict((cell, C.cell_xy(*cell)) for cell in C.CELLS)
        self._label_pts = [C.label_xy(cc, rr, self.clock_cols)
                           for cc in range(self.clock_cols) for rr in range(7)]
        self._label_map = dict(((cc, rr), C.label_xy(cc, rr, self.clock_cols))
                               for cc in range(self.clock_cols + 8)
                               for rr in range(7))
        self._g2_key = None                   # blurred eye-halo layer cache
        self._g2_blur = None
        self._orad = {}                       # outline radii arrays per shape
        self._oang = None
        self._ocos = None
        self._osin = None
        self._opath_flat = None               # no-blob ring path cache
        self._opath_key = None
        self._bo_rad = {}                     # body_outline radii/cos/sin cache
        self._bo_cos = {}
        self._bo_sin = {}

    # ---------------------- draw helpers (logical -> px) ----------------------
    def _circ(self, dr, x, y, r, fill, k=None):
        k = self.s if k is None else k
        dr.ellipse([(x - r) * k, (y - r) * k, (x + r) * k, (y + r) * k], fill=fill)

    def _ring(self, dr, x, y, r, w, col, k=None):
        k = self.s if k is None else k
        dr.ellipse([(x - r) * k, (y - r) * k, (x + r) * k, (y + r) * k],
                   outline=col, width=max(1, int(round(w * k))))

    def _dot(self, dr, x, y, r, col, k=None, style='circle'):
        """v17.9 (LEDPET_V17_9_RENDER): one LED dot - circle (classic),
        square or diamond.  v18.1 (LEDPET_V18_CUSTOM): +8 more shapes
        (ring / hex / tri / star / plus / pixel / roundsq / heart).
        The circle branch calls the very same _circ as before, so a default
        config rasterizes byte-identically."""
        if style == 'circle':                # v18.3: fast path (the default)
            self._circ(dr, x, y, r, col, k)
            return
        if style == 'square':
            k = self.s if k is None else k
            dr.rectangle([(x - r) * k, (y - r) * k, (x + r) * k, (y + r) * k], fill=col)
        elif style == 'diamond':
            k = self.s if k is None else k
            rr = r * 1.12
            dr.polygon([(x * k, (y - rr) * k), ((x + rr) * k, y * k),
                        (x * k, (y + rr) * k), ((x - rr) * k, y * k)], fill=col)
        elif style == 'hex':                    # v18.1
            k = self.s if k is None else k
            rr = r * 1.06
            dr.polygon([(x + rr * math.cos(math.pi / 6.0 + i * math.pi / 3.0) * k,
                         y + rr * math.sin(math.pi / 6.0 + i * math.pi / 3.0) * k)
                        for i in range(6)], fill=col)
        elif style == 'tri':                    # v18.1
            k = self.s if k is None else k
            dr.polygon([(x * k, (y - r * 1.18) * k), ((x + r * 1.05) * k, (y + r * 0.74) * k),
                        ((x - r * 1.05) * k, (y + r * 0.74) * k)], fill=col)
        elif style == 'star':                   # v18.1: 4-point sparkle
            k = self.s if k is None else k
            a, b = r * 1.30, r * 0.36
            dr.polygon([(x * k, (y - a) * k), ((x + b) * k, (y - b) * k),
                        ((x + a) * k, y * k), ((x + b) * k, (y + b) * k),
                        (x * k, (y + a) * k), ((x - b) * k, (y + b) * k),
                        ((x - a) * k, y * k), ((x - b) * k, (y - b) * k)], fill=col)
        elif style == 'plus':                   # v18.1
            k = self.s if k is None else k
            w = r * 0.40
            dr.rectangle([(x - w) * k, (y - r) * k, (x + w) * k, (y + r) * k], fill=col)
            dr.rectangle([(x - r) * k, (y - w) * k, (x + r) * k, (y + w) * k], fill=col)
        elif style == 'ring':                   # v18.1: hollow dot
            k = self.s if k is None else k
            dr.ellipse([(x - r) * k, (y - r) * k, (x + r) * k, (y + r) * k],
                       outline=col, width=max(1, int(round(r * 0.62 * k))))
        elif style == 'pixel':                  # v18.1: sharp tiny square
            k = self.s if k is None else k
            rr = r * 0.66
            dr.rectangle([(x - rr) * k, (y - rr) * k, (x + rr) * k, (y + rr) * k], fill=col)
        elif style == 'roundsq':                # v18.1: soft square
            k = self.s if k is None else k
            try:
                dr.rounded_rectangle([(x - r) * k, (y - r) * k, (x + r) * k, (y + r) * k],
                                     radius=max(1, int(r * 0.45 * k)), fill=col)
            except Exception:
                dr.rectangle([(x - r) * k, (y - r) * k, (x + r) * k, (y + r) * k], fill=col)
        elif style == 'heart':                  # v18.1
            k = self.s if k is None else k
            hr = r * 0.52
            self._circ(dr, x - hr * 0.82, y - hr * 0.62, hr, col, k)
            self._circ(dr, x + hr * 0.82, y - hr * 0.62, hr, col, k)
            dr.polygon([((x - hr * 1.32) * k, (y - hr * 0.28) * k),
                        ((x + hr * 1.32) * k, (y - hr * 0.28) * k),
                        (x * k, (y + hr * 1.55) * k)], fill=col)
        else:
            self._circ(dr, x, y, r, col, k)

    # ------------------------------ static layer ------------------------------
    def _build_static(self):
        img = Image.new('RGBA', (self.rw, self.rh), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        # an 'invisible' disk for click/drag: ~2% alpha is not visible on the
        # desktop yet the pet area stays grabbable. Magenta + low alpha also
        # keeps the chroma key exact in the Tk fallback mode.
        self._circ(d, C.CX, C.CY, C.R - 0.5, (255, 0, 255, 6))
        # unlit matrix dots (very dim - just to see the LED grid)
        # v17.1: every body is built exactly like the circle - no bright rim
        # v18.1: deep_dark swaps them for a near-black grid (true black look)
        for (gx, gy) in C.CELLS:
            x, y = C.cell_xy(gx, gy)
            self._circ(d, x, y, C.DOT_R * 0.30, self._unlit)
        return img

    def _build_disk(self):
        img = Image.new('RGBA', (self.rw, self.rh), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        self._circ(d, C.CX, C.CY, C.R - 0.5, (255, 0, 255, 6))
        return img

    def _draw_unlit(self, d, pos):
        for cell in self._cell_list:
            x, y = pos[cell]
            self._circ(d, x, y, C.DOT_R * 0.30, self._unlit)

    # ---------------- v17: bubble / jelly warp (LEDPET_V17_BODY) ----------------
    def _warp(self, X, Y, B):
        dx = X - C.CX
        dy = Y - C.CY
        # v17.9: bass zoom (0.0 by default -> identical)
        _zm = float(B.get('zoom', 0.0))
        if abs(_zm) > 1e-6:
            dx = dx * (1.0 + _zm)
            dy = dy * (1.0 + _zm)
        r = np.hypot(dx, dy)
        th = np.arctan2(dy, dx)
        rn = np.minimum(r / C.RMAX, 1.0)
        ph = B.get('ph', 0.0)
        wob = B.get('wob', 1.0)
        a = wob * (0.020 * np.sin(2 * th + ph * 1.6)
                   + 0.015 * np.sin(3 * th - ph * 1.1 + 1.0)
                   + 0.007 * np.sin(5 * th + ph * 2.1 + 2.0))
        k = 1.0 + a * rn * rn
        dx = dx * k
        dy = dy * k
        st = B.get('st', 0.0)
        if abs(st) > 1e-4:                    # stretch along the motion, squash across
            ux, uy = B.get('ux', 1.0), B.get('uy', 0.0)
            p = dx * ux + dy * uy
            q = -dx * uy + dy * ux
            p = p * (1.0 + st)
            q = q / (1.0 + 0.8 * abs(st))
            dx = p * ux - q * uy
            dy = p * uy + q * ux
        lxv, lyv = B.get('lx', 0.0), B.get('ly', 0.0)
        lm = math.hypot(lxv, lyv)
        lean = B.get('lean', 0.0)
        if lm > 1e-3 and lean > 1e-3:         # the leading edge reaches to the mouse
            nx, ny = lxv / lm, lyv / lm
            w = 0.5 * (1.0 + np.clip((dx * nx + dy * ny) / C.RMAX, -1.0, 1.0))
            w = w * w
            dx = dx + lxv * lean * w
            dy = dy + lyv * lean * w
        return C.CX + dx, C.CY + dy

    def _pos_fn(self, B):
        """(pos dict or None, P) - P maps (gx, gy) to the warped (x, y)"""
        if not B or np is None or self._cx is None:
            return None, C.cell_xy
        nx, ny = self._warp(self._cx, self._cy, B)
        pos = dict(zip(self._cell_list, zip(nx.tolist(), ny.tolist())))

        def P(gx, gy):
            p = pos.get((gx, gy))
            if p is not None:
                return p
            x, y = C.cell_xy(gx, gy)
            wx, wy = self._warp(np.array([x]), np.array([y]), B)
            return float(wx[0]), float(wy[0])
        return pos, P

    def _outline(self, blob):
        """[(x, y)] path of the base ring; None = use the classic circle ellipse"""
        if blob is None and C.SHAPE == 'circle':
            return None
        # v18.3 (LEDPET_V18_PERF): the radii table + angle grid only depend
        # on the shape -> cached (identical values, computed once)
        key = C.SHAPE
        if blob is None and self._opath_key == key and self._opath_flat is not None:
            return self._opath_flat
        rad = self._orad.get(key)
        if rad is None:
            rad = np.asarray(C.outline_radii())
            self._orad[key] = rad
        ang = self._oang
        if ang is None or len(ang) != len(rad):
            ang = np.linspace(0.0, 2.0 * math.pi, len(rad), endpoint=False)
            self._oang = ang
            self._ocos = np.cos(ang)
            self._osin = np.sin(ang)
        X = C.CX + rad * self._ocos
        Y = C.CY + rad * self._osin
        if blob is not None and np is not None:
            X, Y = self._warp(X, Y, blob)
        out = list(zip(X.tolist(), Y.tolist()))
        if blob is None:
            # v18.3: the unwarped path never changes until the shape does
            # (callers never mutate the list in place -> safe to share)
            self._opath_key = key
            self._opath_flat = out
        return out

    # ------------------------------ one frame ------------------------------
    def frame(self, S):
        """S: scene-state dict (optional keys with defaults)"""
        s = self.s
        gk = S.get('glow', 1.0)
        dim = S.get('dim', 1.0)
        beat = S.get('beat', 0.0)
        bass = S.get('bass', 0.0)
        accent = tuple(S.get('accent', (246, 246, 246)))
        lens = S.get('lens')
        rcol = S.get('ray_rgb')
        peaks = S.get('peaks')
        n = self.rays
        G = self.g
        MAXD = C.RAY_MAX_DOTS
        # --- v17.9 per-frame options (all neutral by default) ---
        tnow = float(S.get('t', 0.0))
        dsty = S.get('dot_style', 'circle') or 'circle'
        dsk = max(0.5, float(S.get('dot_size', 1.0)))
        fad = bool(S.get('edge_fade'))
        fstyle = S.get('fill_style', 'solid') or 'solid'
        fopa = max(0, min(100, int(S.get('fill_opacity', 100))))
        RMAX = C.RMAX
        # v18.3 (LEDPET_V18_PERF): the wide bloom layer is CACHEABLE when it
        # can only receive the eye halos (no beat ring: beat<=0.02/bass<=0.05,
        # no central bass glow: bass<=0.04).  Its blurred result then only
        # changes when the eyes move or the halo color/alpha changes.
        g2c = (self.bloom and beat <= 0.02 and bass <= 0.04)
        _g2_hit = False
        _g2_key = None

        def _fk(gx, gy):
            # edge_fade: outer cells dimmer (1.0 when off -> identical)
            if not fad:
                return 1.0
            dist = math.hypot(gx - C.HALF, gy - C.HALF) * C.PITCH
            if dist <= 0.62 * RMAX:
                return 1.0
            return max(0.55, 1.0 - 0.5 * (dist - 0.62 * RMAX) / (0.38 * RMAX))

        blob = S.get('blob')
        bpos, P = self._pos_fn(blob)
        # v18.3 (LEDPET_V18_PERF): the three scratch layers + the composite
        # base are REUSED buffers (cleared per frame) instead of fresh
        # allocations - same pixels, far less allocator/GC churn.
        lit = self._lit
        lit.paste((0, 0, 0, 0), (0, 0, self.rw, self.rh))
        d = ImageDraw.Draw(lit)

        # --- v17.8: solid body fill (LEDPET_V17_FILL) -----------------------
        # paints a filled silhouette under every LED so the body can be a
        # solid panel instead of a see-through dot matrix. Drawn from the
        # (possibly warped) cell positions, so the fill follows the bubble /
        # jelly motion exactly; the equalizer ring, bars, clock and face all
        # stay on top of it.
        if S.get('body_fill', self.body_fill):
            _frgb = tuple(S.get('fill_rgb', self.fill_rgb))
            _frgb2 = tuple(S.get('fill_rgb2', self.fill_rgb2))
            fcol = (int(_frgb[0]), int(_frgb[1]), int(_frgb[2]), int(255 * fopa / 100.0))
            fr = C.PITCH * 0.62          # overlaps neighbours -> truly solid
            scan_y = (tnow * 3.2) % (2.0 * C.N)
            _spk_t = math.floor(tnow * 2.5)   # sparkle re-seeds ~2.5x per second
            # v18.3 (LEDPET_V18_PERF): unwarped cell positions come from a
            # pre-computed table (identical values), and 'solid' skips the
            # whole per-style if-chain
            _bp = bpos if bpos is not None else self._cellpos
            _circ = self._circ
            _fancy = fstyle != 'solid'
            for _cell in self._cell_list:
                _x, _y = _bp[_cell]
                _gx, _gy = _cell
                # v18.1 (LEDPET_V18_CUSTOM): the new fill styles.  'solid'
                # keeps the exact v17.8 base color; gradient / plasma /
                # aurora REPLACE the base color per cell, the rest draw a
                # light/dark overlay ON the base.
                _bcol = fcol
                if _fancy:
                    if fstyle == 'gradient':
                        _tt = _gy / (C.N - 1.0)
                        _bcol = (int(_frgb[0] + (_frgb2[0] - _frgb[0]) * _tt),
                                 int(_frgb[1] + (_frgb2[1] - _frgb[1]) * _tt),
                                 int(_frgb[2] + (_frgb2[2] - _frgb[2]) * _tt),
                                 fcol[3])
                    elif fstyle == 'plasma':
                        _v = (math.sin(_gx * 0.42 + tnow * 0.9)
                              + math.sin(_gy * 0.50 - tnow * 0.7)
                              + math.sin((_gx + _gy) * 0.28 + tnow * 0.5)
                              + math.sin(math.hypot(_gx - C.HALF, _gy - C.HALF) * 0.55 - tnow * 1.2))
                        _pc = C.hsv((_v * 0.125 + tnow * 0.02) % 1.0, 0.55, 0.85)
                        _bcol = (int(_pc[0]), int(_pc[1]), int(_pc[2]), fcol[3])
                    elif fstyle == 'aurora':
                        _hu = (0.52 + 0.10 * math.sin(tnow * 0.22) + _gy * 0.008) % 1.0
                        _vv = 0.50 + 0.16 * math.sin(tnow * 0.4 + _gx * 0.22)
                        _ac = C.hsv(_hu, 0.45, max(0.2, _vv))
                        _bcol = (int(_ac[0]), int(_ac[1]), int(_ac[2]), fcol[3])
                _circ(d, _x, _y, fr, _bcol)
                if _fancy:
                    if fstyle == 'panel' and ((_cell[0] + _cell[1]) & 1):
                        # faint checker texture = an LED panel look
                        _circ(d, _x, _y, fr, (0, 0, 0, 26))
                    elif fstyle == 'scan' and abs(_cell[1] - scan_y) < 1.7:
                        # a bright band sweeps down the panel
                        _circ(d, _x, _y, fr, (255, 255, 255, 22))
                    # --- v18.1 overlay styles (LEDPET_V18_CUSTOM) ---
                    elif fstyle == 'stripes':
                        _ph = (_gx + _gy * 1.5 - tnow * 3.0) % 8.0
                        if _ph < 2.6:
                            _circ(d, _x, _y, fr, (255, 255, 255, 26))
                    elif fstyle == 'checker':
                        if ((_gx // 3) + (_gy // 3)) & 1:
                            _circ(d, _x, _y, fr, (0, 0, 0, 34))
                    elif fstyle == 'rings':
                        _rr = math.hypot(_gx - C.HALF, _gy - C.HALF)
                        if (int(_rr / 2.4) & 1) == 0:
                            _circ(d, _x, _y, fr, (255, 255, 255, 20))
                    elif fstyle == 'sparkle':
                        _h1 = math.sin(_gx * 12.9898 + _gy * 78.233 + _spk_t * 37.13) * 43758.5453
                        if (_h1 - math.floor(_h1)) > 0.80:
                            _circ(d, _x, _y, fr, (255, 255, 255, 46))
                    elif fstyle == 'waves':
                        _bn = abs((_gy + 2.6 * math.sin(_gx * 0.55 + tnow * 1.8)) % 26.0 - 13.0)
                        if _bn < 1.3:
                            _circ(d, _x, _y, fr, (255, 255, 255, 24))
                    elif fstyle == 'bricks':
                        if (_gy % 5) == 0 or ((_gx + (_gy // 5) * 3) % 7) == 0:
                            _circ(d, _x, _y, fr, (0, 0, 0, 44))

        gl1 = self._gl1
        gl1.paste((0, 0, 0, 0), (0, 0, self._gw, self._gh))
        g1 = ImageDraw.Draw(gl1)
        gl2 = None
        g2 = None
        if self.bloom:
            gl2 = self._gl2
            gl2.paste((0, 0, 0, 0), (0, 0, self._gw, self._gh))
            g2 = ImageDraw.Draw(gl2)
        k1 = self._gk          # glow layer scale (capped-resolution buffer)

        # --- v17.9: bright inner outline (shape-hugging, optional) ---
        if S.get('body_outline'):
            _ocol = S.get('outline_rgb') or (90, 220, 255)
            if S.get('outline_cycle'):
                _ocol = C.hsv(tnow * 0.10, 0.75, 1.0)
            # v18.3 (LEDPET_V18_PERF): the outline table is cached per shape
            _bkey = C.SHAPE
            _orad = self._bo_rad.get(_bkey)
            if _orad is None:
                _orad = np.asarray(C.outline_radii()) * 0.90
                _oang = np.linspace(0.0, 2.0 * math.pi, len(_orad), endpoint=False)
                self._bo_rad[_bkey] = _orad
                self._bo_cos[_bkey] = np.cos(_oang)
                self._bo_sin[_bkey] = np.sin(_oang)
            _ox = (C.CX + _orad * self._bo_cos[_bkey]).tolist()
            _oy = (C.CY + _orad * self._bo_sin[_bkey]).tolist()
            _opts = [(x * s, y * s) for (x, y) in zip(_ox, _oy)]
            d.line(_opts + _opts[:1], fill=tuple(_ocol) + (185,),
                   width=max(1, int(round(1.3 * s))), joint='curve')

        # --- equalizer base ring (hugs the body shape; glows with the beat) ---
        ring_a = int(min(255, (118 + 96 * beat) * dim))
        opath = self._outline(blob)
        _rps = (1.0 + 0.020 * beat) if S.get('ring_pulse') else 1.0
        if opath is None:
            self._ring(d, C.CX, C.CY, (C.R + 7.0) * _rps, 2.0, _mix_white(accent, 0.30) + (ring_a,))
        else:
            if _rps != 1.0:
                opath = [(C.CX + (x - C.CX) * _rps, C.CY + (y - C.CY) * _rps)
                         for (x, y) in opath]
            pts = [(x * s, y * s) for (x, y) in opath]
            d.line(pts + pts[:1], fill=_mix_white(accent, 0.30) + (ring_a,),
                   width=max(1, int(round(2.0 * s))), joint='curve')

        # --- v17.9 dynamic ring / matrix effects (all off by default) ---
        if S.get('comet'):
            _cpt = opath
            if _cpt is None:
                _cr = C.R + 7.0
                _cn = 96
                _cpt = [(C.CX + _cr * math.cos(2.0 * math.pi * i / _cn),
                         C.CY + _cr * math.sin(2.0 * math.pi * i / _cn)) for i in range(_cn)]
            _ci = (tnow * 1.5 % 1.0) * len(_cpt)
            for _j in range(14):
                _fi = (_ci - _j * 1.25) % len(_cpt)
                _i0 = int(_fi)
                _fr = _fi - _i0
                _p0 = _cpt[_i0 % len(_cpt)]
                _p1 = _cpt[(_i0 + 1) % len(_cpt)]
                _x = _p0[0] + (_p1[0] - _p0[0]) * _fr
                _y = _p0[1] + (_p1[1] - _p0[1]) * _fr
                _al = int(215 * (1.0 - _j / 14.0))
                _col = _mix_white(accent, 0.75 - 0.55 * _j / 14.0) + (_al,)
                self._circ(d, _x, _y, 2.5 - 0.10 * _j, _col)
                if gk > 0 and _j < 4:
                    self._circ(g1, _x, _y, 7.0, _pm(accent, 26 * gk), k1)
        if S.get('scan_dot'):
            _sa = tnow * 1.2
            for _cell in self._cell_list:
                _x, _y = bpos[_cell] if bpos is not None else C.cell_xy(*_cell)
                _da = (math.atan2(_y - C.CY, _x - C.CX) - _sa) % (2.0 * math.pi)
                if _da < 0.9:
                    _al = int(85 * (1.0 - _da / 0.9))
                    self._circ(d, _x, _y, C.DOT_R * 0.80 * dsk, accent + (_al,))
        if S.get('rain_fx'):
            _fall = int(tnow * 5.0)
            for _cell in self._cell_list:
                _p = (_cell[1] + _fall + _cell[0] * 3) % 11
                if _p == 0:
                    _al = 74
                elif _p == 1:
                    _al = 40
                else:
                    continue
                _x, _y = bpos[_cell] if bpos is not None else C.cell_xy(*_cell)
                self._circ(d, _x, _y, C.DOT_R * 0.75 * dsk, accent + (_al,))
        if g2 is not None and (beat > 0.02 or bass > 0.05):
            gcol = _pm(accent, (30 * bass + 120 * beat) * gk * dim)
            if opath is None:
                self._ring(g2, C.CX, C.CY, C.R + 8, 5 + 6 * beat, gcol, k1)
            else:
                g2.line([(x * k1, y * k1) for (x, y) in opath]
                        + [(opath[0][0] * k1, opath[0][1] * k1)],
                        fill=gcol, width=max(1, int(round((5 + 6 * beat) * k1))),
                        joint='curve')

        # --- equalizer bars (start at the body outline; bass bottom, treble top) ---
        if lens is not None:
            radii = C.RAY_RADII
            bwx = bwy = None
            if blob is not None and self._bx is not None:
                w1, w2 = self._warp(self._bx, self._by, blob)
                bwx, bwy = w1.tolist(), w2.tolist()
            # v18.3 (LEDPET_V18_PERF): the per-dot-index constants are the
            # exact same expressions, evaluated once per index instead of
            # once per (ray, dot)
            dot = self._dot
            circ = self._circ
            r_tab = [G.r0 * (1.06 - 0.040 * j) * dsk for j in range(MAXD)]
            f_tab = [1.0 - 0.03 * j for j in range(MAXD)]
            r_peak = G.r0 * 0.9 * dsk
            for i in range(n):
                L = lens[i]
                if L <= 0.02:
                    continue
                col = rcol[i] if rcol is not None else accent
                xy = G.xy[i]
                jm = min(MAXD, int(math.ceil(L)))
                bi = i * MAXD
                for j in range(jm):
                    a = L - j
                    if a > 1.0:
                        a = 1.0
                    al = int(min(255, 255 * a * f_tab[j] * dim))
                    if al <= 0:
                        continue
                    if bwx is not None:
                        x, y = bwx[bi + j], bwy[bi + j]
                    else:
                        x, y = xy[j]
                    dot(d, x, y, r_tab[j], col + (al,), style=dsty)
                if L > 3.0 and gk > 0:
                    if bwx is not None:
                        x, y = bwx[bi + jm - 1], bwy[bi + jm - 1]
                    else:
                        x, y = xy[jm - 1]
                    circ(g1, x, y, 5.0, _pm(col, min(60, 9 * (L - 2.5)) * gk * dim), k1)
                if peaks is not None:
                    pj = int(peaks[i] + 0.5)
                    if jm + 1 < pj < MAXD:
                        if bwx is not None:
                            x, y = bwx[bi + pj], bwy[bi + pj]
                        else:
                            x, y = xy[pj]
                        dot(d, x, y, r_peak,
                            _mix_white(col, 0.55) + (min(255, int(235 * dim)),), style=dsty)

        # --- clock ---
        clock = S.get('clock')
        if clock and self.clock_on:
            # v18.1: the clock can keep the accent color or use its own color
            _ckc = accent
            if S.get('clock_cmode') == 'custom' and S.get('clock_rgb'):
                _ckc = tuple(S.get('clock_rgb'))
            # v18.3 (LEDPET_V18_PERF): the label grid is a pre-computed table
            for (x, y) in self._label_pts:
                self._dot(d, x, y, 3.0 * dsk, (255, 255, 255, 20), style=dsty)
            on, colons, cols = C.clock_cells(clock)
            colon_on = S.get('colon', True)
            ca = min(255, int(255 * dim))
            lmap = self._label_map
            for (cc, rr) in on:
                if (cc in colons) and not colon_on:
                    continue
                pt = lmap.get((cc, rr))
                if pt is None:
                    pt = C.label_xy(cc, rr, self.clock_cols)
                x, y = pt
                self._dot(d, x, y, 3.2 * dsk, _ckc + (ca,), style=dsty)
                self._dot(d, x, y, 1.6 * dsk, _mix_white(_ckc, 0.5) + (ca,), style=dsty)
                if gk > 0:
                    self._circ(g1, x, y, 6.5, _pm(_ckc, 42 * gk * dim), k1)

        # --- face + ripples ---
        main, red, eyes = C.build_face(**S['face'])
        rip = S.get('ripple')
        if rip:
            for key, v in rip.items():
                if v > main.get(key, 0.0):
                    main[key] = v
        core_k = 0.62
        # v18.3 (LEDPET_V18_PERF): local bindings + the pre-computed cell
        # position table (identical values); with edge_fade off the fade
        # factor is exactly 1.0 so it is skipped (x*1.0 == x in IEEE 754)
        dot = self._dot
        circ = self._circ
        mw = _mix_white
        cpos = self._cellpos
        for (gx, gy), b in main.items():
            b = 1.0 if b > 1.0 else b
            p = cpos.get((gx, gy))
            if p is None:
                p = C.cell_xy(gx, gy)
            x, y = p
            if fad:
                al = min(255, int(255 * b * dim * _fk(gx, gy)))
            else:
                al = min(255, int(255 * b * dim))
            dot(d, x, y, C.DOT_R * dsk, accent + (al,), style=dsty)
            if b > 0.5:
                dot(d, x, y, C.DOT_R * core_k * dsk,
                    mw(accent, 0.55) + (al,), style=dsty)
            if b > 0.35 and gk > 0:
                circ(g1, x, y, C.DOT_R * 1.9, _pm(accent, 46 * b * gk * dim), k1)
                circ(g1, x, y, C.DOT_R * 3.0, _pm(accent, 14 * b * gk * dim), k1)
        for (gx, gy), b in red.items():
            b = 1.0 if b > 1.0 else b
            p = cpos.get((gx, gy))
            if p is None:
                p = C.cell_xy(gx, gy)
            x, y = p
            # v18.1: the cheeks can have their own color (default = C.RED)
            _ckcol = tuple(S.get('cheek_rgb') or C.RED)
            dot(d, x, y, C.DOT_R * dsk, _ckcol + (int(255 * b),), style=dsty)
            if gk > 0:
                circ(g1, x, y, C.DOT_R * 2.9, _pm(_ckcol, 64 * b * gk), k1)
        # --- v17.5: custom eye / pupil colours -----------------------------
        # The settings (Settings -> Eyes) already had "Eye color: Custom" and
        # "Pupil color: Custom" + color buttons, and pet_windows passed
        # eye_rgb / pupil_rgb into the scene - but this renderer never read
        # them, so picking a color changed nothing.  build_face reports the
        # eye / pupil / glint cell sets through face_kw['ex']; repaint those
        # cells here (the glint stays in the eye set -> it keeps the eye
        # color, the pupil paints on top of it).
        # v18.1 (LEDPET_V18_CUSTOM): the IRIS layer paints between the eye
        # and the pupil, and the glint is painted LAST (over everything) so
        # the iris can never cover the sparkle.
        _ex = S['face'].get('ex') if isinstance(S['face'], dict) else None
        _erc = S.get('eye_rgb')
        _prc = S.get('pupil_rgb')
        _irc = S.get('iris_rgb')
        if _ex is not None and (_erc is not None or _prc is not None
                                or _irc is not None or _ex.get('glint')):
            if _erc is not None:
                _erc = tuple(_erc)
                for (gx, gy) in (_ex.get('eye') or ()):
                    b = main.get((gx, gy), 0.0)
                    if b <= 0.02:
                        continue
                    b = 1.0 if b > 1.0 else b
                    p = cpos.get((gx, gy))
                    if p is None:
                        p = C.cell_xy(gx, gy)
                    x, y = p
                    if fad:
                        al = min(255, int(255 * b * dim * _fk(gx, gy)))
                    else:
                        al = min(255, int(255 * b * dim))
                    dot(d, x, y, C.DOT_R * dsk, _erc + (al,), style=dsty)
                    if b > 0.5:
                        dot(d, x, y, C.DOT_R * core_k * dsk,
                            mw(_erc, 0.55) + (al,), style=dsty)
            if _irc is not None:
                _irc = tuple(_irc)
                for (gx, gy), iv in (_ex.get('iris') or {}).items():
                    b = 1.0 if iv > 1.0 else (0.0 if iv < 0.02 else iv)
                    if b <= 0.0:
                        continue
                    p = cpos.get((gx, gy))
                    if p is None:
                        p = C.cell_xy(gx, gy)
                    x, y = p
                    dot(d, x, y, C.DOT_R * dsk, _irc + (int(255 * b * dim),), style=dsty)
            if _prc is not None:
                _prc = tuple(_prc)
                for (gx, gy), pv in (_ex.get('pupil') or {}).items():
                    b = 1.0 if pv > 1.0 else (0.0 if pv < 0.02 else pv)
                    if b <= 0.0:
                        continue
                    p = cpos.get((gx, gy))
                    if p is None:
                        p = C.cell_xy(gx, gy)
                    x, y = p
                    dot(d, x, y, C.DOT_R * dsk, _prc + (int(255 * b * dim),), style=dsty)
            # v18.1: the glint on TOP of iris + pupil (a real sparkle now,
            # before it was just a hole in the eye).  Only drawn when the
            # glint option is on, so the default look is unchanged.
            _glc = _ex.get('glint') or {}
            if _glc:
                _gc = _erc if _erc is not None else tuple(accent)
                _gc = mw(_gc, 0.85)
                for (gx, gy), gv in _glc.items():
                    b = 1.0 if gv > 1.0 else (0.0 if gv < 0.02 else gv)
                    if b <= 0.0:
                        continue
                    p = cpos.get((gx, gy))
                    if p is None:
                        p = C.cell_xy(gx, gy)
                    x, y = p
                    dot(d, x, y, C.DOT_R * dsk, _gc + (int(255 * b * dim),), style=dsty)
        # big halo behind the eyes + central glow with the bass
        # v18.3 (LEDPET_V18_PERF): in the cacheable calm case (no beat ring,
        # no central bass glow) the blurred halo layer is reused while the
        # eyes, the halo color and the halo alpha (an int) all stay the same
        if g2 is not None and gk > 0:
            _ha = max(0, min(255, int((12 + 26 * bass) * gk * dim)))
            if g2c:
                _g2_key = (eyes, accent, _ha)
                if self._g2_key == _g2_key and self._g2_blur is not None:
                    _g2_hit = True          # blurred layer reused at compose
                else:
                    for (ex, ey) in eyes:
                        x, y = C.cell_xy(ex, ey)
                        circ(g2, x, y, 40, _pm(accent, _ha), k1)
            else:
                for (ex, ey) in eyes:
                    x, y = C.cell_xy(ex, ey)
                    circ(g2, x, y, 40, _pm(accent, _ha), k1)
        if g2 is not None and bass > 0.04 and gk > 0:
            circ(g2, C.CX, C.CY, C.R * 0.95, _pm(accent, 26 * bass * gk * dim), k1)

        # --- v17.9: fireflies - wandering glow dots inside the body ---
        if S.get('fireflies'):
            for _i in range(6):
                _fx = C.CX + 0.60 * RMAX * math.sin(tnow * (0.23 + 0.05 * _i) + _i * 2.4)
                _fy = C.CY + 0.60 * RMAX * math.sin(tnow * (0.31 + 0.04 * _i) + _i * 1.7 + 1.0)
                _al = int(88 + 66 * math.sin(tnow * 1.3 + _i * 2.1))
                _al = max(20, min(170, _al))
                self._circ(d, _fx, _fy, 2.0, _mix_white(accent, 0.5) + (_al,))
                if gk > 0:
                    self._circ(g1, _fx, _fy, 6.0, _pm(accent, 30 * gk), k1)

        # --- sparks ---
        sp = S.get('sparks')
        if sp:
            for (x, y, a, size, col) in sp:
                al = int(min(255, 255 * max(0.0, min(1.0, a)) * dim))
                if al <= 2:
                    continue
                self._circ(d, x, y, size, tuple(col) + (al,))
                if gk > 0:
                    self._circ(g1, x, y, size * 2.6, _pm(col, al * 0.22 * gk), k1)

        # --- compose: lit over static (non-premult) -> premult -> downscale -> + glow ---
        # v18.3 (LEDPET_V18_PERF): the composite target is a reused buffer
        # (re-pasted with the static layer, then composited in place) and
        # the premultiplied frame is relabelled RGBA with frombuffer (a
        # zero-copy view) instead of the old frombytes(tobytes()) double
        # copy.  All byte sequences are identical.
        base = self._base
        base.paste(self.static, (0, 0))
        base.alpha_composite(lit)
        pm = base.convert('RGBa')
        if self.ss > 1:
            pm = pm.reduce(self.ss)
        out = Image.frombuffer('RGBA', pm.size, pm.tobytes())   # same bytes, RGBA label
        if out.size != (self.W, self.H):
            out = out.resize((self.W, self.H), Image.BILINEAR)
        if gk > 0:
            gl1 = gl1.filter(self._blur1)
            if gl2 is not None:
                if _g2_hit and self._g2_blur is not None:
                    gl2b = self._g2_blur
                else:
                    gl2b = gl2.filter(self._blur2)
                    if _g2_key is not None:
                        self._g2_key = _g2_key
                        self._g2_blur = gl2b
                # merge the two glow fields at the small glow resolution -
                # the saturating add is associative, so the result is the
                # same as adding both to the frame, but only ONE upscale
                # and ONE full-size add are needed per frame
                if gl2b.size != gl1.size:
                    gl2b = gl2b.resize(gl1.size, Image.BILINEAR)
                gl1 = ImageChops.add(gl1, gl2b)
            if gl1.size != out.size:
                gl1 = gl1.resize(out.size, Image.BILINEAR)
            out = ImageChops.add(out, gl1)
        return out

    def composite_over(self, pm, bg_rgb):
        """composite the premultiplied frame over an RGB background (for PNG preview)"""
        import numpy as np
        a = np.asarray(pm, dtype=np.float32) / 255.0
        bg = np.array(bg_rgb, dtype=np.float32)[None, None, :]
        rgb = a[..., :3] * 255.0 + bg * (1.0 - a[..., 3:4])
        return Image.fromarray(np.clip(rgb, 0, 255).astype('uint8'), 'RGB')
