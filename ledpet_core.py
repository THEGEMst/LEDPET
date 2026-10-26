# -*- coding: utf-8 -*-
# =====================================================================
#  LEDPet core - geometry, face shapes and font (no Qt dependency)
#  v4 - reference design + audio/beat/color/settings
# =====================================================================
import math
import time
import colorsys
try:
    import numpy as np
except Exception:          # numpy is installed by the launcher
    np = None

# ------------------------- design canvas (logical px) ---------------------
BW, BH = 520, 600          # window size at scale 1 (bigger: room for long rays + sparks)
CX, CY = 260.0, 318.0      # circle center
R = 128.0                  # glass radius
N = 27                     # NxN matrix (like the clip: fewer, chunkier dots)
HALF = (N - 1) / 2.0
RMAX = R - 9.0
PITCH = 2 * RMAX / (N - 1)
DOT_R = 3.45

RAY_N = 96                 # default ray count
RAY_DOTS = 9               # (legacy)
RAY_MAX_DOTS = 12          # max dots per ray (v5 halo)
RAY_R0 = R + 19.0
NB = 32                    # number of spectrum bands

LABEL_PITCH = 9.0
LABEL_Y = 12.0

PALETTE = [
    ('Pure white',     (246, 246, 246)),
    ('Neon green',     (90, 255, 130)),
    ('Ice blue',       (110, 220, 255)),
    ('Neon pink',    (255, 120, 200)),
    ('Sunset orange',   (255, 165, 80)),
    ('Galaxy purple',  (190, 130, 255)),
]
RED = (255, 52, 52)


def cell_xy(gx, gy):
    return CX + (gx - HALF) * PITCH, CY + (gy - HALF) * PITCH


CELLS = frozenset(
    (gx, gy) for gy in range(N) for gx in range(N)
    if math.hypot(gx - HALF, gy - HALF) * PITCH <= RMAX)

# ------------------------------ SDFs ------------------------------------


def sd_rbox(px, py, bx, by, rtl, rtr, rbr, rbl):
    if px > 0:
        r = rtr if py < 0 else rbr
    else:
        r = rtl if py < 0 else rbl
    r = min(r, bx, by)
    qx = abs(px) - bx + r
    qy = abs(py) - by + r
    return min(max(qx, qy), 0.0) + math.hypot(max(qx, 0.0), max(qy, 0.0)) - r


def sd_seg(px, py, ax, ay, bx, by, th):
    pax, pay = px - ax, py - ay
    bax, bay = bx - ax, by - ay
    h = max(0.0, min(1.0, (pax * bax + pay * bay) / (bax * bax + bay * bay + 1e-9)))
    return math.hypot(pax - bax * h, pay - bay * h) - th / 2.0


def sd_ring(px, py, cx, cy, rad, th):
    return abs(math.hypot(px - cx, py - cy) - rad) - th / 2.0


def cov(d):
    return max(0.0, min(1.0, 0.5 - d))


# ---------------------------- shapes -------------------------------------
def _scaled(f, sx, sy):
    """scale a shape function around its centre (used for the bounce squash & stretch)"""
    if abs(sx - 1.0) < 1e-3 and abs(sy - 1.0) < 1e-3:
        return f
    sx = max(0.2, sx)
    sy = max(0.05, sy)
    return lambda px, py: f(px / sx, py / sy)


def eye_fn(kind, sy=1.0, sx=1.0):
    if kind in ('open', 'wide'):
        # blocky eye like the clip: ~7 columns x ~10 rows, rounded corners, slightly dimmer at the bottom
        w, h = 3.5 * sx, 4.8 * sy
        rr = 1.7

        def f(px, py):
            d = sd_rbox(px, py, w, h, rr, rr, rr, rr)
            c = cov(d * 1.15)
            if c <= 0.0:
                return 0.0
            return c * (1.0 - 0.22 * max(0.0, min(1.0, (py + h) / (2 * h))))
        return f
    if kind == 'happy':          # thick arch with two feet (like the clip)
        return _scaled(bmp_fn(_HAPPY), sx, sy)
    if kind == 'sleep':
        return _scaled(bmp_fn(_SLEEP), sx, sy)
    if kind == 'love':
        return _scaled(bmp_fn(_HEART), sx, sy)
    if kind == 'x':
        return _scaled(bmp_fn(_XEYE), sx, sy)
    if kind == 'frownL':         # pouty / annoyed: thick bar slanting down toward the nose
        return _scaled(bmp_fn(_FROWN_L), sx, sy)
    if kind == 'frownR':
        return _scaled(bmp_fn(_FROWN_R), sx, sy)
    if kind in _EYE_BMP:                      # newer states (v13)
        return _scaled(bmp_fn(_EYE_BMP[kind]), sx, sy)
    return lambda px, py: 0.0


# --- newer eyes (v13): sad, angry, star, heavy lid, glasses ---
_EYE_BMP = {
    'sadL':   ('0000111', '0011111', '0111111', '1111111', '1111111', '0111110', '0011100'),
    'sadR':   ('1110000', '1111100', '1111110', '1111111', '1111111', '0111110', '0011100'),
    'angryL': ('1110000', '1111110', '1111111', '1111111', '1111111', '0111110', '0011100'),
    'angryR': ('0000111', '0111111', '1111111', '1111111', '1111111', '0111110', '0011100'),
    'star':   ('0001000', '0001000', '0011100', '1111111', '0111110', '0110110', '1100011'),
    'sadC':   ('0011100', '0111110', '1111111', '1111111', '1111111', '0111110', '0011100'),
    'angryC': ('1100011', '1111111', '1111111', '1111111', '1111111', '0111110', '0011100'),
    'frownC': ('1111111', '0111110', '0011100'),
    'lid':    ('1111111', '1111111', '1111111', '0111110'),
    'shade':  ('1111111', '1111111', '1111111', '0111110', '0011100'),
}


_HAPPY = ('0111110',
          '1111111',
          '1111111',
          '1100011',
          '1100011')
_SLEEP = ('1100011',
          '0111110',
          '0011100')
_XEYE = ('1100011',
         '0110110',
         '0011100',
         '0110110',
         '1100011')

_FROWN_L = ('1100000',
            '0111100',
            '0001111')
_FROWN_R = ('0000011',
            '0011110',
            '1111000')

_HEART = ('0110110',
          '1111111',
          '1111111',
          '0111110',
          '0011100',
          '0001000')


def bmp_fn(rows):
    """small bitmap -> soft function (bilinear interpolation)"""
    h, w = len(rows), len(rows[0])

    def at(ix, iy):
        return 1.0 if (0 <= ix < w and 0 <= iy < h and rows[iy][ix] == '1') else 0.0

    def f(px, py):
        u = px + w / 2.0 - 0.5
        v = py + h / 2.0 - 0.5
        x0, y0 = math.floor(u), math.floor(v)
        fx, fy = u - x0, v - y0
        return (at(x0, y0) * (1 - fx) * (1 - fy) + at(x0 + 1, y0) * fx * (1 - fy)
                + at(x0, y0 + 1) * (1 - fx) * fy + at(x0 + 1, y0 + 1) * fx * fy)
    return f


EQ_BARS = 7


def mouth_fn(kind, wig=0.0, eq=None):
    if kind == 'idle':          # tiny mouth like the clip: 3 dots on top + 2 dim dots below
        def f(px, py):
            ax = abs(px)
            if abs(py) < 0.5:                     # top row
                if ax < 0.5:
                    return 1.0
                if 0.5 <= ax < 1.5:
                    return 0.55
                return 0.0
            if 0.5 <= py < 1.5 and 0.5 <= ax < 1.5:   # bottom row (two dim dots)
                return 0.30
            return 0.0
        return f
    if kind == 'talk':          # microphone lip-sync: open = 0..1, wide = 0..1 ("ee" wide / "oo" narrow)
        o = max(0.0, min(1.0, eq if isinstance(eq, (int, float)) else 0.0))
        wd = max(0.0, min(1.0, wig))
        rx = 1.5 + 1.9 * wd + 0.8 * o
        ry = 0.55 + 2.35 * o

        def f(px, py):
            py = py - (ry - 0.55) * 0.55          # open downwards (top lip stays)
            d = (math.hypot(px / rx, py / ry) - 1.0) * min(rx, ry)
            c = cov(d * 1.25)
            if c <= 0.0:
                return 0.0
            return c * (0.78 + 0.22 * o)
        return f
    if kind == 'frown':
        return bmp_fn(_FROWN_M)
    if kind == 'smile':
        return bmp_fn(_SMILE)
    if kind == 'big':
        return bmp_fn(_BIGMOUTH)
    if kind == 'eq':             # mouth = tiny equalizer (moves with sound)
        hs = list(eq) if eq else [0.2] * EQ_BARS

        def f(px, py):
            i = int(round(px)) + EQ_BARS // 2
            if i < 0 or i >= EQ_BARS:
                return 0.0
            if abs(px - round(px)) > 0.5:
                return 0.0
            h = 0.5 + 2.6 * max(0.0, min(1.0, hs[i]))
            return 1.0 if abs(py) < h else 0.0
        return f
    if kind == 'o':
        return bmp_fn(_OMOUTH)
    if kind == 'oo':             # whistle/hum mouth: small filled oval (mic reaction)
        def f(px, py):
            d = (math.hypot(px / 1.55, py / 1.85) - 1.0) * 1.55
            return cov(d * 1.3) * 0.92
        return f
    if kind == 'sleep':
        return bmp_fn(('111',))
    if kind in _MOUTH_BMP:                    # newer states (v13)
        return bmp_fn(_MOUTH_BMP[kind])
    if kind == 'dizzy':
        pts = [(-3.0, 0.0), (-1.5, -1.0 + wig), (0.0, 1.0 - wig), (1.5, -1.0 + wig), (3.0, 0.0)]

        def f(px, py):
            d = 9.0
            for i in range(4):
                d = min(d, sd_seg(px, py, pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1], 0.9))
            return cov(d)
        return f
    return lambda px, py: 0.0


_MOUTH_BMP = {
    'smirk': ('0000011', '0011100', '1100000'),
    'grr':   ('1111111', '1010101'),
    'kiss':  ('010', '101', '010'),
    'side':  ('0001111',),
}
_SMILE = ('1000001',
          '0111110')
_FROWN_M = ('0111110',
            '1000001')
_BIGMOUTH = ('1111111',
             '0111110',
             '0011100')
_OMOUTH = ('01110',
           '10001',
           '10001',
           '01110')


def _shape(out, cx, cy, rx, ry, fn, level=1.0):
    # v18.3 (LEDPET_V18_PERF): the CELLS lookup + out.get are hoisted into
    # locals (set_shape can never run in the middle of this call, so the
    # snapshot is safe) - identical semantics, less per-cell overhead
    cells = CELLS
    out_get = out.get
    for gy in range(int(math.floor(cy - ry)), int(math.ceil(cy + ry)) + 1):
        for gx in range(int(math.floor(cx - rx)), int(math.ceil(cx + rx)) + 1):
            if (gx, gy) not in cells:
                continue
            v = fn(gx - cx, gy - cy) * level
            if v > 0.01 and v > out_get((gx, gy), 0.0):
                out[(gx, gy)] = v


EX, EY, MY = 5.0, -1.0, 7.0
CHEEK_X, CHEEK_Y = 8.5, 6.0    # v16.6: cheeks sit clearly BELOW the eyes
                               # (was 4.0 = touching the eye bottoms)
# v17.2: per-shape cheek fit (x factor, y offset, size scale) so the blush
# stays inside narrower silhouettes; every other shape uses the v16.6 spot.
# v17.5: bunny removed (the user asked to drop it entirely).
# v17.6: star/mug faces scaled DOWN - the Mario-Galaxy star and the cup keep
# a clear LED margin around the face so the BODY reads big (user: the star
# looked small because the face filled it completely).
_CHEEK_OFF = {'star': (0.56, -2.0, 0.74), 'mug': (0.58, -1.0, 0.82),
              'heart': (0.76, -2.0, 0.85), 'cloud': (0.66, 0.0, 0.9)}
# v17.4: the Mario-Galaxy star is fat enough (valley vertex ~ (0, +9.25))
# to hold the mouth at its natural height - the leg valley stays open.
_MOUTH_DY = {}
# v17.6: the star/mug get a Galaxy-style small face (gap/size factors);
# cloud and every approved shape keep the full-size default eyes.
_EYE_FIT = {'star': (0.78, 0.74), 'mug': (0.80, 0.78)}
# v17.5: where the THIRD eye sits per shape - (dy from the eye row, size).
# The mug's rim, the heart's cleft and the cat's ear gap leave no room at
# the old spot (ecy - 9), so those shapes get a lower / smaller third eye;
# every other shape keeps the classic spot untouched.
_EYE3_FIT = {'mug': (-4.4, 0.42), 'heart': (-2.4, 0.40), 'cat': (-5.4, 0.45),
             'star': (-6.5, 0.45), 'cloud': (-8.0, 0.55)}
_ZZ = ('11111', '00010', '00100', '01000', '11111')


# --- newer face states (v13) ---
# state name -> menu label (English)
NEW_STATES = [
    ('sad', 'Sad'), ('cry', 'Cry'), ('angry', 'Angry'),
    ('laugh', 'Laugh'), ('cool', 'Cool'), ('star', 'Star eyes'),
    ('think', 'Thinking'), ('sleepy', 'Sleepy / yawn'),
    ('shy', 'Shy'), ('kiss', 'Kiss'), ('smirk', 'Smirk'),
    ('eat', 'Eating'), ('drink', 'Drinking'), ('hungry', 'Hungry'),
]
OLD_STATES = [
    ('idle', 'Normal'), ('happy', 'Happy'), ('wink', 'Wink'),
    ('surprised', 'Surprised'), ('love', 'Love'), ('frown', 'Pout'),
    ('dizzy', 'Dizzy'), ('dance', 'Dance'),
]
CHEEK_OF = {'sad': 0.55, 'cry': 0.80, 'angry': 1.0, 'laugh': 1.0, 'cool': 0.35, 'star': 0.9,
            'think': 0.55, 'sleepy': 0.30, 'shy': 1.0, 'kiss': 1.0, 'eat': 1.0, 'drink': 0.8,
            'hungry': 0.5, 'smirk': 0.7}
# states whose mouth has its own animation (the mic does not touch it)
_OWN_MOUTH = ('sleep', 'dizzy', 'eat', 'drink', 'laugh', 'kiss', 'cry')
_ICONS = {
    'food': ('01110', '11111', '10101', '11111', '01110'),
    'drop': ('00100', '00100', '01110', '11111', '01110'),
    'heart': ('01010', '11111', '11111', '01110', '00100'),
}


def _blit_bitmap(out, rows, x0, y0, level):
    for r, row in enumerate(rows):
        for c, ch in enumerate(row):
            if ch == '1' and (x0 + c, y0 + r) in CELLS:
                k = (x0 + c, y0 + r)
                out[k] = max(out.get(k, 0.0), level)


def build_face(state, blink=1.0, lx=0.0, ly=0.0, bob=0.0, zz=None, wig=0.0, cheek=0.75,
               eq=None, pulse=1.0, bounce=0.0, talk=None, bamt=1.0, mouth=None,
               anim=0.0, icon=None, eo=None, ex=None):
    """returns: (main dots, red cheek dots, eye centres)
    bounce: eye spring (+ = stretched tall / narrow, - = squashed flat / wide)
    talk:   (open 0..1, wide 0..1) from the microphone, or None
    mouth:  explicit mouth kind override from the microphone reactions
            ('talk' is handled by talk, this covers 'o'/'big'/'oo'/'smile')
    anim:   animation clock (seconds) for animated states (eating, crying, laughing, ...)
    icon:   'food' / 'drop' -> state icon bubble for hungry/thirsty"""
    main, red = {}, {}
    if state == 'shy':                       # shy: looking down and aside
        lx, ly = lx - 1.3, ly + 0.8
    ecy = round(HALF + EY + ly * 0.8 + bob)          # real LED: centre sits on cells
    ecl, ecr = round(HALF - EX + lx), round(HALF + EX + lx)
    own_talk = None
    m_wig_new = None
    esc = [(1.0, 1.0), (1.0, 1.0)]           # (sx, sy) per eye
    if state == 'sleep':
        kl = kr = 'sleep'; mk = 'sleep'
    elif state == 'dizzy':
        kl = kr = 'x'; mk = 'dizzy'
    elif state == 'surprised':
        kl = kr = 'wide'; mk = 'o'
    elif state == 'dance':
        # dance moves the body and eyes only; the mouth ignores system audio -
        # the mouth reacts to the microphone only
        kl = kr = 'happy'; mk = 'idle'
    elif state == 'love':
        kl = kr = 'love'; mk = 'smile'
    elif state == 'happy':
        kl = kr = 'happy'; mk = 'smile'
    elif state == 'wink':
        kl, kr = 'happy', 'open'; mk = 'smile'
    elif state == 'frown':
        kl, kr = 'frownL', 'frownR'; mk = 'frown'
    # ---------------- newer states ----------------
    elif state == 'sad':
        kl, kr = 'sadL', 'sadR'; mk = 'frown'
    elif state == 'cry':
        kl, kr = 'sadL', 'sadR'; mk = 'dizzy'
        m_wig_new = 0.35 + 0.35 * math.sin(anim * 10.0)
    elif state == 'hungry':
        kl, kr = 'sadL', 'sadR'; mk = 'dizzy'
        m_wig_new = 0.5 + 0.5 * math.sin(anim * 9.0)          # wiggling (happy squirm)
    elif state == 'angry':
        kl, kr = 'angryL', 'angryR'; mk = 'grr'
    elif state == 'laugh':
        kl = kr = 'happy'; mk = 'talk'
        own_talk = (0.45 + 0.5 * abs(math.sin(anim * 9.0)), 0.9)
    elif state == 'eat':
        kl = kr = 'happy'; mk = 'talk'
        own_talk = (0.22 + 0.5 * abs(math.sin(anim * 7.0)), 0.55)   # chewing
    elif state == 'drink':
        kl = kr = 'sleep'; mk = 'talk'
        own_talk = (0.25 + 0.30 * abs(math.sin(anim * 4.5)), 0.05)  # gulping
    elif state == 'sleepy':
        kl = kr = 'lid'; mk = 'talk'
        own_talk = (0.15 + 0.6 * (0.5 + 0.5 * math.sin(anim * 1.4)), 0.25)   # yawning
    elif state == 'cool':
        kl = kr = 'shade'; mk = 'smirk'
    elif state == 'star':
        kl = kr = 'star'; mk = 'smile'
    elif state == 'think':
        kl = kr = 'open'; mk = 'side'
        esc[0] = (1.0, 0.55)
    elif state == 'shy':
        kl = kr = 'open'; mk = 'dizzy'
        m_wig_new = 0.15
        esc = [(0.75, 0.55), (0.75, 0.55)]
    elif state == 'kiss':
        kl = kr = 'happy'; mk = 'kiss'
    elif state == 'smirk':
        kl = kr = 'open'; mk = 'smirk'
        esc = [(1.0, 0.80), (1.0, 0.55)]
    else:
        kl = kr = 'open'; mk = 'idle'
    if mouth is not None and state not in _OWN_MOUTH:
        mk = mouth
    m_eq, m_wig = eq, wig
    if own_talk is not None:
        m_eq, m_wig = own_talk
    if m_wig_new is not None:
        m_wig = m_wig_new
    if talk is not None and state not in _OWN_MOUTH and talk[0] > 0.06:
        mk = 'talk'
        m_eq, m_wig = talk[0], talk[1]
    # bounce: squash & stretch + a tiny hop (fractional offsets -> neighbouring dots fade smoothly)
    b = max(-1.4, min(1.4, bounce))
    sy_b = max(0.45, 1.0 + 0.32 * bamt * b)
    sx_b = max(0.6, 1.0 - 0.22 * bamt * b)
    hop = -1.7 * bamt * b if state != 'sleep' else 0.0
    # ---- v17: eye layout / size / colour / pupils (defaults = the old look) ----
    eo = eo or {}
    ex = ex if isinstance(ex, dict) else None
    n_eyes = int(eo.get('count', 2))
    e_sz = max(0.5, float(eo.get('size', 1.0)))
    e_gap = max(0.5, float(eo.get('gap', 1.0)))
    pk = eo.get('pupil', 'none')
    ps = max(0.3, float(eo.get('pupil_size', 1.0)))
    p_follow = bool(eo.get('pupil_follow', True))
    p_color = bool(eo.get('pupil_cmode', 'dark') == 'custom')
    p_glint = bool(eo.get('glint', False))
    # v17.9: live inputs - mic level widens the eyes, hover widens a little
    # too, panim drives the three animated pupils (scan/pulse/wander).
    # Both default to 0.0 -> wsc is exactly 1.0 -> identical rendering.
    micv = max(0.0, min(1.0, float(eo.get('micv', 0.0))))
    hov = max(0.0, min(1.0, float(eo.get('hov', 0.0))))
    panim = float(eo.get('panim', 0.0))
    wsc = 1.0 + 0.14 * micv + 0.09 * hov
    # v17.3: the mouth and the cheeks can be switched off in the settings
    show_mouth = bool(eo.get('mouth', True))
    show_cheeks = bool(eo.get('cheeks', True))
    _ef = _EYE_FIT.get(SHAPE, (1.0, 1.0))   # v17.2: shape-specific eye fit
    e_sz = max(0.5, e_sz * _ef[1])
    e_gap = e_gap * _ef[0]
    if e_gap != 1.0 and n_eyes != 1:
        ecl, ecr = round(HALF - EX * e_gap + lx), round(HALF + EX * e_gap + lx)
    if n_eyes == 1:
        specs = [(_SYM_EYE.get(kl, kl), round(HALF + lx), ecy,
                  1.55 * e_sz, 1.2 * e_sz, esc[0])]
    elif n_eyes == 3:
        # v17.5: per-shape third-eye fit (_EYE3_FIT) - shapes with a rim /
        # cleft / ear gap get a lower or smaller third eye so it never gets
        # clipped; the default stays the classic spot right above.  The top
        # eye also follows the horizontal gaze only a little (x0.3) - it is
        # a forehead eye and the narrow shapes have no room for it to wander.
        _e3 = _EYE3_FIT.get(SHAPE, (-9.0, 0.55))
        specs = [(kl, ecl, ecy, e_sz, e_sz, esc[0]),
                 (kr, ecr, ecy, e_sz, e_sz, esc[1]),
                 (_SYM_EYE.get(kl, kl), round(HALF + lx * 0.3), round(ecy + _e3[0]),
                  _e3[1] * e_sz, _e3[1] * e_sz, esc[0])]
    else:
        specs = [(kl, ecl, ecy, e_sz, e_sz, esc[0]),
                 (kr, ecr, ecy, e_sz, e_sz, esc[1])]
    # v18.1 (LEDPET_V18_CUSTOM): the IRIS - a NEW colored layer between the
    # cornea (the eye shape) and the pupil.  iris='none' keeps the old look.
    iris_kind = eo.get('iris', 'none')
    isz = max(0.5, min(1.6, float(eo.get('iris_size', 1.0))))
    eye_cells, pup_cells, glint_cells, iris_cells, eye_centers = set(), {}, {}, {}, []
    for (kind, ecx, eyc, scx, scy, (esx, esy)) in specs:
        if kind == 'wide':
            fn = eye_fn('wide', sy=1.22 * sy_b * scy * wsc, sx=1.1 * sx_b * scx)
        elif kind == 'open':
            fn = eye_fn('open', sy=blink * sy_b * esy * scy * wsc, sx=sx_b * esx * scx)
        else:
            fn = eye_fn(kind, sy=sy_b * scy, sx=sx_b * scx)
        lvl = 0.55 if state == 'sleep' else (pulse if kind in ('love', 'star') else 1.0)
        ed = {}
        _shape(ed, ecx, eyc + hop, 6.0 * max(1.0, scx), 7.6 * max(1.0, scy), fn, lvl)
        # v18.1: pupil target centre + scale, hoisted out of the pupil branch
        # so the iris layer can share them (the math is unchanged).
        pcx = ecx + (max(-1.6, min(1.6, lx * 0.35)) if p_follow else 0.0)
        pcy = eyc + hop + (max(-2.0, min(2.0, ly * 0.5)) if p_follow else 0.0)
        psc = ps * max(0.6, min(scx, scy)) * (0.8 if kind == 'wide' else 1.0)
        pd = {}
        if pk != 'none' and kind in ('open', 'wide') and ed:
            # v17.9: the three LIVE pupils - driven by the animation clock
            pk_draw = pk
            if pk == 'pulse':              # the pupil breathes
                psc = psc * (1.0 + 0.20 * math.sin(panim * 3.4))
                pk_draw = 'dot'
            elif pk == 'scan':             # the pupil orbits inside the eye
                pcx = pcx + 1.45 * math.cos(panim * 2.3)
                pcy = pcy + 1.10 * math.sin(panim * 2.3)
                pk_draw = 'dot'
            elif pk == 'wander':           # the pupil jumps around
                _sd = int(panim * 0.9)
                _fa = math.sin(_sd * 127.1) * 43758.5453
                _fb = math.sin(_sd * 311.7) * 12543.8523
                pcx = pcx + (_fa - math.floor(_fa) - 0.5) * 3.2
                pcy = pcy + (_fb - math.floor(_fb) - 0.5) * 2.4
                pk_draw = 'dot'
            _shape(pd, pcx, pcy, 5.5 * psc + 1.0, 5.5 * psc + 1.0, pupil_fn(pk_draw, psc), 1.0)
        ed0 = dict(ed)                     # full eye coverage (before any carve)
        pcov = {}                          # effective pupil coverage per cell
        for k_, pv in pd.items():
            ev = ed.get(k_, 0.0)
            if ev <= 0.02:
                continue
            pv = pv * min(1.0, ev * 2.5)
            if pv <= 0.02:
                continue
            ed[k_] = ev * (1.0 - pv)
            pcov[k_] = pv * ev
            if p_color:
                pup_cells[k_] = max(pup_cells.get(k_, 0.0), pv * ev)
        # v18.1: the iris is carved out of the cornea; the pupil hole punches
        # through the iris (a dark pupil stays a hole, a colored pupil is
        # painted on top by the renderer).
        if iris_kind != 'none' and kind in ('open', 'wide') and ed:
            irad = (1.15 + 1.55 * isz) * psc
            idsh = {}
            _shape(idsh, pcx, pcy, irad + 1.3, irad + 1.3, iris_fn(iris_kind, irad), 1.0)
            for k_, iv in idsh.items():
                ev0 = ed0.get(k_, 0.0)
                if ev0 <= 0.02:
                    continue
                if pcov.get(k_, 0.0) >= 0.02:
                    continue              # the pupil owns this cell
                iv = iv * min(1.0, ev0 * 2.5)
                if iv <= 0.02:
                    continue
                iris_cells[k_] = max(iris_cells.get(k_, 0.0), iv)
                ev = ed.get(k_, 0.0)
                if ev > 0.02:
                    ed[k_] = ev * (1.0 - iv)
        if p_glint and pk != 'none' and kind in ('open', 'wide') and ed:
            gk_ = (round(pcx - 0.9), round(pcy - 1.1))
            if ed0.get(gk_, 0.0) > 0.5:
                glint_cells[gk_] = ed0[gk_]
                pup_cells.pop(gk_, None)
        for k_, v_ in ed.items():
            if v_ > main.get(k_, 0.0):
                main[k_] = v_
            eye_cells.add(k_)
        eye_centers.append((ecx, eyc))
    if ex is not None:
        ex['eye'] = eye_cells
        ex['pupil'] = pup_cells
        ex['glint'] = glint_cells
        ex['iris'] = iris_cells            # v18.1 (LEDPET_V18_CUSTOM)
    if state == 'cool' and n_eyes == 2:      # glasses bridge between the lenses
        by = int(round(ecy + hop - 2.0))
        for gx in range(int(ecl + 4), int(ecr - 3)):
            if (gx, by) in CELLS:
                main[(gx, by)] = 1.0
    mcx = round(HALF + lx * 0.45)
    mcy = round(HALF + MY + _MOUTH_DY.get(SHAPE, 0.0) + ly * 0.35 + bob * 0.8)
    if show_mouth:      # v17.3: the mouth can be turned off in the settings
        _shape(main, mcx, mcy + hop * 0.35, 8.0, 5.0, mouth_fn(mk, m_wig, m_eq), 0.6 if state == 'sleep' else 1.0)
    # red cheeks (two dots side by side)
    # v16.6: the cheeks follow the vertical gaze a little (like the eyes do)
    # so the gap below the eyes survives looking down; the follow is capped
    # so the dots never leave the round display
    if show_cheeks:     # v17.3: the cheeks (blush) can be turned off
        cko = _CHEEK_OFF.get(SHAPE, (1.0, 0.0, 1.0))   # v17.2: per-shape cheek fit
        ccy = round(HALF + CHEEK_Y + cko[1] + bob * 0.6 + min(ly * 0.8, 1.6))
        ckx = CHEEK_X * cko[0]
        for sgn in (-1, 1):
            ccx = round(HALF + sgn * ckx + lx * 0.6) + 0.5
            fn = lambda px, py: cov(min(math.hypot(px + 0.5, py), math.hypot(px - 0.5, py)) - 0.78)
            _shape(red, ccx, ccy, 3.0 * cko[2], 2.0 * cko[2], fn, cheek)
    # sleep zZ
    if zz is not None:
        zx = int(HALF + 5 + zz * 2)
        zy = int(HALF - 9 - zz * 3)
        lv = math.sin(math.pi * zz)
        for r, row in enumerate(_ZZ):
            for c, ch in enumerate(row):
                if ch == '1' and (zx + c, zy + r) in CELLS:
                    main[(zx + c, zy + r)] = max(main.get((zx + c, zy + r), 0.0), lv)
    # ---------------- newer state details ----------------
    if state == 'cry':                       # falling tears
        for ecx in (ecl, ecr):
            for k in range(3):
                ph = (anim * 1.6 + k / 3.0) % 1.0
                tx = round(ecx + (-2 if ecx == ecl else 2))
                ty = int(ecy + 4.5 + ph * 7.0)
                if (tx, ty) in CELLS:
                    v = math.sin(math.pi * ph) * 0.95
                    main[(tx, ty)] = max(main.get((tx, ty), 0.0), v)
    elif state == 'think':                   # ... thought bubble
        n = int(anim * 1.8) % 4
        for k, (px_, py_) in enumerate(((5, -9), (7, -9), (9, -8))):
            if k < n and (int(HALF + px_), int(HALF + py_)) in CELLS:
                main[(int(HALF + px_), int(HALF + py_))] = 1.0
    elif state == 'hungry' and icon in _ICONS:
        v = 0.55 + 0.45 * math.sin(anim * 5.0)
        _blit_bitmap(main, _ICONS[icon], int(HALF + 3), int(HALF - 11), max(0.2, v))
    elif state == 'kiss':                    # floating heart above the head (not on the eyes)
        p = (anim * 0.9) % 1.0
        _blit_bitmap(main, _ICONS['heart'], int(HALF + 4), int(HALF - 10 - p * 1.5),
                     max(0.0, math.sin(math.pi * p)))
    return main, red, tuple(eye_centers)


# ----------------------------- clock ------------------------------------
FONT5 = {
    '0': ('01110', '10001', '10011', '10101', '11001', '10001', '01110'),
    '1': ('00100', '01100', '00100', '00100', '00100', '00100', '01110'),
    '2': ('01110', '10001', '00001', '00010', '00100', '01000', '11111'),
    '3': ('11110', '00001', '00001', '01110', '00001', '00001', '11110'),
    '4': ('00010', '00110', '01010', '10010', '11111', '00010', '00010'),
    '5': ('11111', '10000', '11110', '00001', '00001', '10001', '01110'),
    '6': ('00110', '01000', '10000', '11110', '10001', '10001', '01110'),
    '7': ('11111', '00001', '00010', '00100', '01000', '01000', '01000'),
    '8': ('01110', '10001', '10001', '01110', '10001', '10001', '01110'),
    '9': ('01110', '10001', '10001', '01111', '00001', '00010', '01100'),
    ':': ('0', '0', '1', '0', '1', '0', '0'),
    'A': ('01110', '10001', '10001', '11111', '10001', '10001', '10001'),
    'B': ('11110', '10001', '10001', '11110', '10001', '10001', '11110'),
    'C': ('01110', '10001', '10000', '10000', '10000', '10001', '01110'),
    'D': ('11110', '10001', '10001', '10001', '10001', '10001', '11110'),
    'E': ('11111', '10000', '10000', '11110', '10000', '10000', '11111'),
    'F': ('11111', '10000', '10000', '11110', '10000', '10000', '10000'),
    'G': ('01110', '10001', '10000', '10111', '10001', '10001', '01111'),
    'H': ('10001', '10001', '10001', '11111', '10001', '10001', '10001'),
    'I': ('01110', '00100', '00100', '00100', '00100', '00100', '01110'),
    'J': ('00111', '00010', '00010', '00010', '00010', '10010', '01100'),
    'K': ('10001', '10010', '10100', '11000', '10100', '10010', '10001'),
    'L': ('10000', '10000', '10000', '10000', '10000', '10000', '11111'),
    'M': ('10001', '11011', '10101', '10101', '10001', '10001', '10001'),
    'N': ('10001', '11001', '10101', '10011', '10001', '10001', '10001'),
    'O': ('01110', '10001', '10001', '10001', '10001', '10001', '01110'),
    'P': ('11110', '10001', '10001', '11110', '10000', '10000', '10000'),
    'Q': ('01110', '10001', '10001', '10001', '10101', '10010', '01101'),
    'R': ('11110', '10001', '10001', '11110', '10100', '10010', '10001'),
    'S': ('01111', '10000', '10000', '01110', '00001', '00001', '11110'),
    'T': ('11111', '00100', '00100', '00100', '00100', '00100', '00100'),
    'U': ('10001', '10001', '10001', '10001', '10001', '10001', '01110'),
    'V': ('10001', '10001', '10001', '10001', '10001', '01010', '00100'),
    'W': ('10001', '10001', '10001', '10101', '10101', '10101', '01010'),
    'X': ('10001', '10001', '01010', '00100', '01010', '10001', '10001'),
    'Y': ('10001', '10001', '01010', '00100', '00100', '00100', '00100'),
    'Z': ('11111', '00001', '00010', '00100', '01000', '10000', '11111'),
    ' ': ('000', '000', '000', '000', '000', '000', '000'),
    '.': ('0', '0', '0', '0', '0', '0', '1'),
    ',': ('0', '0', '0', '0', '0', '1', '1'),
    '!': ('1', '1', '1', '1', '1', '0', '1'),
    '?': ('01110', '10001', '00001', '00110', '00100', '00000', '00100'),
    "'": ('1', '1', '0', '0', '0', '0', '0'),
    '-': ('000', '000', '000', '111', '000', '000', '000'),
    '+': ('00000', '00100', '00100', '11111', '00100', '00100', '00000'),
    '/': ('00001', '00010', '00010', '00100', '01000', '01000', '10000'),
    '<': ('00010', '00100', '01000', '10000', '01000', '00100', '00010'),
    '>': ('01000', '00100', '00010', '00001', '00010', '00100', '01000'),
}

def clock_cells(hh, mm):
    """(set of lit cells, colon column)"""
    s = '%02d:%02d' % (hh, mm)
    cells, colx, colon_x = set(), 0, None
    for ch in s:
        rows = FONT5[ch]
        if ch == ':':
            colon_x = colx
        for r, row in enumerate(rows):
            for c, bit in enumerate(row):
                if bit == '1':
                    cells.add((colx + c, r))
        colx += len(rows[0]) + 1
    return cells, colon_x



CLOCK_COLS = 25


def clock_cells(text):
    """text like '13:06' or '13:06:45' -> (lit cells, colon columns, column count)"""
    cells, colx, colons = set(), 0, []
    for ch in text:
        rows = FONT5[ch]
        if ch == ':':
            colons.append(colx)
        for r, row in enumerate(rows):
            for c, bit in enumerate(row):
                if bit == '1':
                    cells.add((colx + c, r))
        colx += len(rows[0]) + 1
    return cells, colons, max(1, colx - 1)


def clock_width(text):
    return clock_cells(text)[2]


def label_xy(c, r, cols=CLOCK_COLS):
    x0 = (BW - cols * LABEL_PITCH) / 2.0 + LABEL_PITCH / 2.0
    return x0 + c * LABEL_PITCH, LABEL_Y + LABEL_PITCH / 2.0 + r * LABEL_PITCH


# ----------------------------- rays -------------------------------------
def ray_radii(maxdots=RAY_MAX_DOTS):
    out, r = [], RAY_R0
    for j in range(maxdots):
        out.append(r)
        r += 5.0 + 0.6 * j
    return out


RAY_RADII = ray_radii()


class RayGeom:
    """pre-computed geometry for n rays (no trig per frame)"""

    def __init__(self, n, starts=None):
        self.n = int(n)
        self.xy = []
        self.cs = []
        if starts is None or len(starts) != self.n:
            starts = [RAY_R0] * self.n
        mean_start = 0.0
        for i in range(self.n):
            ang = 2 * math.pi * i / self.n - math.pi / 2
            c, s = math.cos(ang), math.sin(ang)
            self.cs.append((c, s))
            r0 = starts[i]
            mean_start += r0
            self.xy.append([(CX + (r0 + (r - RAY_R0)) * c,
                             CY + (r0 + (r - RAY_R0)) * s) for r in RAY_RADII])
        sp = 2 * math.pi * (mean_start / self.n) / self.n
        self.r0 = max(1.1, min(2.15, 0.37 * sp))

    def tip(self, i, L):
        """tip coordinates of ray i with length L (a dot)"""
        j = max(0, min(RAY_MAX_DOTS - 1, int(L)))
        return self.xy[i][j]


def band_pos_arr(n, shift=0.0, layout='bottom'):
    """band position (0 bass .. 1 treble) per ray. mirrored; shift = rotation"""
    i = (np.arange(n, dtype=float) + shift) % n
    k = np.minimum(i, n - i)
    pos = 1.0 - k / (n / 2.0)            # top = treble, bottom = bass
    if layout == 'top':
        pos = 1.0 - pos
    return pos


# ------------------------------ color -----------------------------------
def hsv(h, s=1.0, v=1.0):
    # v18.3 (LEDPET_V18_PERF): the stdlib HSV->RGB conversion body is
    # inlined here verbatim (same clamp order, same float expression
    # order) so the results are bit-identical, without the extra Python
    # call per pixel.
    h = h % 1.0
    s = max(0.0, min(1.0, s))
    v = max(0.0, min(1.0, v))
    if s == 0.0:
        return (int(v * 255),) * 3
    i = int(h * 6.0)                     # int() truncates (like colorsys)
    f = (h * 6.0) - i
    p = v * (1.0 - s)
    q = v * (1.0 - s * f)
    t = v * (1.0 - s * (1.0 - f))
    i = i % 6
    if i == 0:
        r, g, b = v, t, p
    elif i == 1:
        r, g, b = q, v, p
    elif i == 2:
        r, g, b = p, v, t
    elif i == 3:
        r, g, b = p, q, v
    elif i == 4:
        r, g, b = t, p, v
    else:
        r, g, b = v, p, q
    return (int(r * 255), int(g * 255), int(b * 255))


def lerp_rgb(a, b, t):
    t = max(0.0, min(1.0, t))
    return (int(a[0] + (b[0] - a[0]) * t), int(a[1] + (b[1] - a[1]) * t),
            int(a[2] + (b[2] - a[2]) * t))


def ray_colors(mode, n, rgb1, rgb2, t=0.0, bass=0.0):
    if mode == 'rainbow':
        return [hsv(i / float(n) + t * 0.06, 0.82, 1.0) for i in range(n)]
    if mode == 'gradient':
        out = []
        for i in range(n):
            tri = 1.0 - abs(2.0 * i / n - 1.0)       # top=0, bottom=1
            out.append(lerp_rgb(rgb1, rgb2, tri))
        return out
    if mode == 'reactive':
        return [hsv(0.58 + 0.42 * bass + (min(i, n - i) / float(n)) * 0.25 + t * 0.02, 0.8, 1.0)
                for i in range(n)]
    return [tuple(rgb1)] * n


def accent_color(mode, rgb1, rgb2, t=0.0, bass=0.0):
    """face and clock color"""
    if mode == 'rainbow':
        return hsv(t * 0.06, 0.5, 1.0)
    if mode == 'reactive':
        return hsv(0.58 + 0.42 * bass, 0.55, 1.0)
    return tuple(rgb1)


# ----------------------------- settings ---------------------------------
DEFAULTS = {
    'x': -1, 'y': -1,
    'cidx': 0,
    'rgb1': list(PALETTE[0][1]), 'rgb2': [110, 220, 255], 'color_mode': 'solid',
    'scale': 0.80, 'glow': 1.0, 'rays': 96, 'ray_len': 1.0, 'rotate': 0.0,
    'layout': 'bottom', 'peaks': True, 'sparks': True, 'ripples': True,
    'clock': True, 'clock_secs': False, 'clock12': False,
    # v1.1 (LEDPET_V1_QUIET): the sound-reactive features now ship OFF.
    # The user report: after "Reset name" a pink circle kept appearing
    # around the pet - that was the mic 'surprised' reaction + its ripple
    # and the beat ripples, because the factory reset (and the old v12
    # migration inside sanitize_cfg) force-enabled audio + mic.  The most
    # default pet is the quiet happy circle that just follows the mouse;
    # the equalizer and the mic reactions are one click away in Settings.
    # (v1.1 LEDPET_V1_FINAL_QUIET, ver 5: the quarantine below is now the
    # FINAL one - see the full story inside sanitize_cfg.)
    'audio': False, 'sens': 1.0, 'smooth': 0.5, 'beat_fx': True,
    'mic': False, 'mic_sens': 1.0, 'eye_bounce': True, 'bounce_amt': 1.0, 'halo_gain': 1.35,
    # v1.1 (LEDPET_V1_QUARANTINE): stamped into a config the first time
    # THIS build loads it.  A config without the stamp that still wants
    # sound reactions gets them pulled ONCE (see sanitize_cfg) - after
    # that the stamp protects every choice the owner makes themselves.
    'quiet_lock': False,
    'track': 'eyes', 'topmost': True, 'autosleep': True, 'fps': 30, 'quality': 'auto',
    'click_through': False,
    # --- v13: home frame, food/water/games, expressions ---
    'home': True, 'follow_mode': 'chase_slow', 'idle_emotes': True,
    'n_food': 0.80, 'n_water': 0.80, 'n_fun': 0.70, 'n_ts': 0.0,
    # --- v17: body shape, bubble motion, eyes and pupils (LEDPET_V17_BODY) ---
    'shape': 'circle',
    'blob': True, 'blob_stretch': 1.0, 'blob_wobble': 1.0, 'blob_lean': 1.0,
    'eye_count': 2, 'eye_size': 1.0, 'eye_gap': 1.0,
    'eye_cmode': 'same', 'eye_rgb': [120, 220, 255],
    'pupil': 'none', 'pupil_size': 1.0, 'pupil_cmode': 'dark', 'pupil_rgb': [255, 90, 90],
    'pupil_follow': True, 'pupil_glint': False,
    # --- v17.3: face part toggles ---
    # v1.0 (THEGEM): the DEFAULT pet is now the minimal happy face - a
    # circle with two eyes only (no cheeks, no mouth) that just follows
    # the mouse; both toggles live in the Face tab as before.
    'show_mouth': False, 'show_cheeks': False,
    # --- v17.8: solid body fill (LEDPET_V17_FILL) ---
    'body_fill': False, 'body_fill_rgb': [0, 0, 0],   # v18.1: TRUE black
    # --- v18.1: full eye customization (LEDPET_V18_CUSTOM) ---
    # the eye is now three layers: cornea (the eye shape itself) -> iris
    # (NEW colored layer behind the pupil) -> pupil.  'iris' 'none' and
    # iris_size 1.0 keep the old look byte-identical.
    'iris': 'none', 'iris_size': 1.0, 'iris_rgb': [90, 170, 255],
    'fill_rgb2': [30, 34, 60],           # second body-fill color (gradient)
    'cheek_rgb': [255, 52, 52],          # the blush dots (was hardcoded C.RED)
    'clock_cmode': 'accent', 'clock_rgb': [255, 255, 255],
    'deep_dark': True,                   # v18.1: near-black unlit LED grid
    # --- v17.9: +10 options per area, dynamic-heavy (LEDPET_V17_9_OPTIONS) ---
    # every new switch defaults to OFF and every new slider to the exact
    # value that reproduces the old behaviour -> untouched pets render
    # byte-identical.
    'hue_speed': 1.0, 'ring_pulse': False, 'comet': False, 'scan_dot': False,
    'rain_fx': False, 'fireflies': False, 'heartbeat': False,
    'spark_density': 1.0, 'peak_hold_t': 0.28, 'eq_mirror': False,
    'dance_amt': 1.0, 'bass_zoom': False, 'beat_flash': False,
    'beat_blink': False, 'mic_react_eyes': False, 'eq_wave': False,
    'auto_dance': True, 'silence_pose': 'breathe', 'beat_min': 0.45,
    'eq_fall': 1.0,
    'blink_rate': 1.0, 'wink_chance': 0.14, 'eye_wander': True,
    'emote_rate': 1.0, 'zzz_fx': True, 'dizzy_amt': 1.0,
    'hover_react': False, 'click_hearts': False, 'drag_squish': False,
    'sleep_after': 0,
    'body_outline': False, 'outline_rgb': [90, 220, 255],
    'outline_cycle': False, 'body_pulse': False, 'fill_opacity': 100,
    'dot_size': 1.0, 'dot_style': 'circle', 'edge_fade': False,
    'wobble_speed': 1.0, 'fill_style': 'solid',
    # --- v18.0: global keyboard shortcuts for the face expressions ---
    # (LEDPET_V18_KEYS) 'hotkeys' is a JSON string {state: combo} so the
    # existing sanitizer (str branch) carries it untouched.
    'hotkeys_on': True, 'hotkeys': '',   # filled right below
    # --- v18.1: sticky shortcuts (LEDPET_V18_CUSTOM): a shortcut HOLDS the
    # expression until the next shortcut (instead of falling back to idle) ---
    'hk_pin': True,
    # --- v18.2: resizable settings window (LEDPET_V18_RESIZE) ---
    # the settings panel can be freely resized (min 460x560); the last
    # 'WxH+X+Y' geometry is stored here (str branch of the sanitizer
    # carries it untouched) so the panel reopens at the same size.
    'settings_geo': '',
    # --- v1.0 (LEDPET_V1_NAME): the pet's name, picked in the first-run
    # "give me a name" dialog (centered mini home frame).  Empty = the
    # unnamed pet (the home frame keeps the LED PET brand mark). ---
    'name': '',
    # v1.1 (LEDPET_V1_QUARANTINE): ver 5 = the FINAL quiet era
    # (LEDPET_V1_FINAL_QUIET).  Configs saved by THIS build (or stamped
    # once on the first load) carry ver 5 + quiet_lock:True and are never
    # re-processed - the owner's own Settings choices are permanent.
    'ver': 5,
}


# ----------------------- styles (shareable looks) -----------------------
# A "style" is a shareable snapshot of the pet's LOOK: colors, size,
# body shape, fill styles, dot shapes, eyes, effects and clock options.
# Styles live as small JSON files in the Styles folder; the Settings
# window lists them and applies one with a click.  Everything that is
# NOT the look (the name, the window position, the sound switches, the
# shortcuts, the needs...) never travels with a style file.
STYLE_EXCLUDE = frozenset((
    'x', 'y', 'name', 'ver', 'quiet_lock', 'hotkeys', 'hotkeys_on',
    'hk_pin', 'settings_geo', 'audio', 'mic', 'sens', 'smooth',
    'mic_sens', 'fps', 'quality', 'topmost', 'click_through', 'home',
    'follow_mode', 'idle_emotes', 'n_food', 'n_water', 'n_fun', 'n_ts',
    'track', 'autosleep', 'sleep_after',
))
STYLE_KEYS = tuple(k for k in DEFAULTS if k not in STYLE_EXCLUDE)


def sanitize_name(s, limit=12):
    """v1.0 (LEDPET_V1_NAME): keep a pet name clean - uppercase (the LED
    font has one case), only glyphs FONT5 can actually show, whitespace
    collapsed, max 12 characters."""
    s = str(s or '').upper()
    s = s.replace('\t', ' ').replace('\n', ' ').replace('\r', ' ')
    ok = set('0123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZ .,!?-+/<>')
    s = ''.join(ch for ch in s if ch in ok)
    s = ' '.join(s.split())
    return s[:limit].strip()

# v18.0: default expression shortcuts. Groups: Alt+digit = classic moods,
# Ctrl+Alt+digit = the v13 emotions, Shift+Alt+digit = needs/activities,
# Alt+0 = back to the normal face. All 21 are unique and are combos that
# almost no other program claims system-wide.
HOTKEY_STATES = [n for n, _ in OLD_STATES + NEW_STATES if n != 'dance']
HOTKEY_DEFAULTS = {
    'idle': 'Alt+0',
    'happy': 'Alt+1', 'wink': 'Alt+2', 'surprised': 'Alt+3',
    'love': 'Alt+4', 'frown': 'Alt+5', 'dizzy': 'Alt+6',
    'sad': 'Ctrl+Alt+1', 'cry': 'Ctrl+Alt+2', 'angry': 'Ctrl+Alt+3',
    'laugh': 'Ctrl+Alt+4', 'cool': 'Ctrl+Alt+5', 'star': 'Ctrl+Alt+6',
    'think': 'Ctrl+Alt+7', 'sleepy': 'Ctrl+Alt+8', 'shy': 'Ctrl+Alt+9',
    'kiss': 'Ctrl+Alt+0',
    'smirk': 'Shift+Alt+1', 'eat': 'Shift+Alt+2',
    'drink': 'Shift+Alt+3', 'hungry': 'Shift+Alt+4',
}
try:
    import json as _json_d
    DEFAULTS['hotkeys'] = _json_d.dumps(HOTKEY_DEFAULTS, ensure_ascii=False)
except Exception:                          # pragma: no cover
    DEFAULTS['hotkeys'] = '{"idle": "Alt+0"}'

CHOICES = {
    'rays': (48, 64, 96, 128, 160),
    'color_mode': ('solid', 'rainbow', 'gradient', 'reactive'),
    'track': ('off', 'eyes', 'chase_slow', 'chase_fast'),
    'fps': (20, 30, 45, 60),
    'quality': ('auto', 'high', 'low'),
    'layout': ('bottom', 'top'),
    'follow_mode': ('chase_slow', 'chase_fast'),
    'shape': ('circle', 'squircle', 'heart', 'star', 'cat', 'bear', 'ghost',
              'mug', 'cloud', 'drop'),
    'eye_count': (1, 2, 3),
    'eye_cmode': ('same', 'custom'),
    'pupil': ('none', 'dot', 'big', 'slit', 'hslit', 'ring', 'square', 'heart', 'spark',
              'cross', 'star5', 'diamond', 'crescent', 'flower', 'bars', 'target',
              'scan', 'pulse', 'wander'),
    'pupil_cmode': ('dark', 'custom'),
    # v17.9
    'dot_style': ('circle', 'square', 'diamond',          # v18.1: +8 shapes
                  'ring', 'hex', 'tri', 'star', 'plus', 'pixel', 'roundsq', 'heart'),
    'fill_style': ('solid', 'panel', 'scan',             # v18.1: +9 styles
                   'gradient', 'stripes', 'checker', 'rings', 'sparkle',
                   'waves', 'bricks', 'plasma', 'aurora'),
    'silence_pose': ('breathe', 'look', 'calm'),
    # v18.1 (LEDPET_V18_CUSTOM)
    'iris': ('none', 'circle', 'ring', 'square', 'diamond', 'heart', 'star5'),
    'clock_cmode': ('accent', 'custom'),
}
RANGES = {'scale': (0.40, 1.60), 'glow': (0.0, 2.0), 'ray_len': (0.5, 1.4), 'rotate': (-1.0, 1.0),
          'sens': (0.3, 3.0), 'smooth': (0.0, 1.0), 'mic_sens': (0.3, 3.0), 'bounce_amt': (0.3, 2.5), 'halo_gain': (0.5, 3.0),
          'n_food': (0.0, 1.0), 'n_water': (0.0, 1.0), 'n_fun': (0.0, 1.0),
          'blob_stretch': (0.0, 2.5), 'blob_wobble': (0.0, 2.5), 'blob_lean': (0.0, 2.0),
          'eye_size': (0.6, 1.6), 'eye_gap': (0.7, 1.4), 'pupil_size': (0.5, 1.6),
          # v17.9
          'hue_speed': (0.0, 3.0), 'spark_density': (0.0, 2.0), 'peak_hold_t': (0.0, 1.2),
          'dance_amt': (0.0, 2.0), 'beat_min': (0.1, 0.9), 'eq_fall': (0.4, 1.6),
          'blink_rate': (0.3, 2.5), 'wink_chance': (0.0, 1.0), 'emote_rate': (0.0, 2.0),
          'dizzy_amt': (0.5, 2.0), 'sleep_after': (0, 180), 'fill_opacity': (0, 100),
          'dot_size': (0.7, 1.3), 'wobble_speed': (0.3, 2.5),
          'iris_size': (0.5, 1.6)}      # v18.1 (LEDPET_V18_CUSTOM)

THEMES = [
    ('Classic (pure white)', dict(color_mode='solid', rgb1=[246, 246, 246], rotate=0.0, glow=1.0, rays=96)),
    ('Cyber neon', dict(color_mode='gradient', rgb1=[255, 90, 200], rgb2=[80, 220, 255], rotate=0.15, glow=1.4, rays=128)),
    ('Rainbow', dict(color_mode='rainbow', rotate=0.35, glow=1.3, rays=128)),
    ('Matrix', dict(color_mode='solid', rgb1=[70, 255, 110], rotate=0.0, glow=1.2, rays=160)),
    ('Sunset', dict(color_mode='gradient', rgb1=[255, 170, 60], rgb2=[190, 90, 255], rotate=0.0, glow=1.2, rays=96)),
    ('Polar ice', dict(color_mode='gradient', rgb1=[240, 250, 255], rgb2=[90, 190, 255], rotate=-0.1, glow=1.1, rays=128)),
    ('Bass reactive', dict(color_mode='reactive', rotate=0.2, glow=1.5, rays=96)),
    # v17.9: ten more presets (mostly living / dynamic looks)
    ('Aurora', dict(color_mode='gradient', rgb1=[80, 255, 170], rgb2=[120, 90, 255], rotate=0.08, glow=1.3, rays=128)),
    ('Lava', dict(color_mode='gradient', rgb1=[255, 60, 30], rgb2=[255, 190, 40], rotate=0.0, glow=1.5, rays=96)),
    ('Ocean', dict(color_mode='gradient', rgb1=[20, 90, 220], rgb2=[70, 230, 255], rotate=-0.06, glow=1.2, rays=128)),
    ('Fire', dict(color_mode='reactive', rotate=0.10, glow=1.5, rays=96)),
    ('Candy', dict(color_mode='gradient', rgb1=[255, 120, 190], rgb2=[120, 255, 210], rotate=0.12, glow=1.2, rays=128)),
    ('Emerald', dict(color_mode='solid', rgb1=[60, 230, 140], rotate=0.0, glow=1.2, rays=96)),
    ('Gold', dict(color_mode='gradient', rgb1=[255, 215, 80], rgb2=[255, 130, 30], rotate=0.0, glow=1.3, rays=96)),
    ('Vaporwave', dict(color_mode='gradient', rgb1=[255, 70, 160], rgb2=[60, 230, 255], rotate=0.20, glow=1.4, rays=128)),
    ('Toxic', dict(color_mode='solid', rgb1=[170, 255, 40], rotate=0.0, glow=1.6, rays=160)),
    ('Rose', dict(color_mode='solid', rgb1=[255, 105, 150], rotate=0.0, glow=1.1, rays=96)),
]


def sanitize_cfg(c):
    """merge with defaults + validation (a broken config never crashes)"""
    out = dict(DEFAULTS)
    if not isinstance(c, dict):
        # v1.1 (LEDPET_V1_QUARANTINE): even a garbage config is stamped,
        # so it can never be re-processed as an ancient one later.
        out['quiet_lock'] = True
        return out
    # migration from older versions
    if 'color' in c and 'rgb1' not in c:
        try:
            out['cidx'] = int(c['color']) % len(PALETTE)
            out['rgb1'] = list(PALETTE[out['cidx']][1])
        except Exception:
            pass
    for k, dv in DEFAULTS.items():
        if k not in c:
            continue
        v = c[k]
        try:
            if isinstance(dv, bool):
                out[k] = bool(v)
            elif isinstance(dv, int):
                out[k] = int(v)
            elif isinstance(dv, float):
                out[k] = float(v)
            elif isinstance(dv, list):
                out[k] = [max(0, min(255, int(x))) for x in v][:3]
                if len(out[k]) != 3:
                    out[k] = list(dv)
            else:
                out[k] = str(v)
        except Exception:
            out[k] = dv
    for k, ch in CHOICES.items():
        if out[k] not in ch:
            if k == 'rays':
                out[k] = min(ch, key=lambda z: abs(z - out[k]))
            else:
                out[k] = DEFAULTS[k]
    for k, (lo, hi) in RANGES.items():
        out[k] = max(lo, min(hi, float(out[k])))
    out['name'] = sanitize_name(out.get('name', ''))   # v1.0 (LEDPET_V1_NAME)
    # v1.1 (LEDPET_V1_FINAL_QUIET): ver 5 = the FINAL quiet era.  The pink
    # halo is dead for good.  The full story:
    #
    # The ancient v12 migration below ("old configs must not lose the
    # equalizer") force-enabled audio + mic, and the pre-V1.0 factory
    # resets re-ran it on every load - so config files ended up
    # PERMANENTLY POISONED (audio:True + mic:True): every system sound
    # made the pet gasp 'surprised' and throw the pink beat/mic ripple
    # rings plus the glowing beat ring around the body - the user's
    # "pink halo around everything" (three reports in a row).
    # UPDATE 3 fixed the empty-config path, UPDATE 4 quarantined configs
    # that were not stamped yet - but TWO holes let the poison survive:
    #   * a config whose 'ver' was missing hit the migration FIRST
    #     (old_ver 1 < 2), was forced audio+mic ON, and the quarantine's
    #     own old_ver >= 2 check then deliberately left it ON - stamped
    #     as if the owner had chosen it;
    #   * any config stamped by UPDATE 4 while still poisoned stayed
    #     poisoned forever ("stamped = the owner's choice").
    # ver 5 closes both:
    #   * the forced enable is RETIRED.  V1.0's shipped default is the
    #     quiet pet; the equalizer is one click away in Settings -> Audio,
    #     so no migration may ever switch sound reactions on by itself.
    #   * ONE last pull: every config below ver 5 that still asks for
    #     audio/mic gets them pulled exactly once and is re-stamped
    #     ver 5.  From then on the owner's own choices made in Settings
    #     are never touched again.
    try:
        old_ver = int(c.get('ver', 1))
    except Exception:
        old_ver = 1
    if not c:
        # an EMPTY config is a fresh install or a "Reset name" factory
        # reset - NOT an ancient one.  The shipped defaults must apply
        # verbatim and no migration may fire (LEDPET_V1_QUIET).
        old_ver = 5
    if old_ver < 5 and (out.get('audio') or out.get('mic')):
        out['audio'] = False
        out['mic'] = False
    out['quiet_lock'] = True
    out['ver'] = 5
    return out


# ------------------------- spectrum analysis (numpy) --------------------
class SpecAnalyzer:
    """FFT -> 32 log-spaced bands with auto dB normalization + beat detection.
    outputs: bands (0..1), level, bass, beat_count, beat_strength"""

    def __init__(self, sr=48000, nfft=2048, nb=NB):
        self.sr, self.nfft, self.nb = sr, nfft, nb
        self.win = np.hanning(nfft)
        binw = sr / float(nfft)
        edges = [38.0 * (16000.0 / 38.0) ** (i / float(nb)) for i in range(nb + 1)]
        self.idx, cen = [], []
        for i in range(nb):
            lo = int(edges[i] / binw)
            hi = max(lo + 1, int(edges[i + 1] / binw))
            hi = min(hi, nfft // 2)
            lo = min(lo, hi - 1)
            self.idx.append((lo, hi))
            cen.append(math.sqrt(edges[i] * edges[i + 1]))
        self.tilt = np.array([(c / 500.0) ** 0.6 for c in cen])
        self.sm = np.zeros(nb)
        self.ceil = -40.0
        self.bavg = 0.0
        self.last_beat = 0.0
        self.attack, self.release = 0.65, 0.20
        self.bands = [0.0] * nb
        self.level = 0.0
        self.bass = 0.0
        self.beat_count = 0
        self.beat_strength = 0.0

    def set_smooth(self, s):
        """s: 0 (sharp and fast) .. 1 (soft and slow)"""
        s = max(0.0, min(1.0, s))
        self.attack = 0.85 - 0.45 * s
        self.release = 0.40 - 0.31 * s

    def feed(self, x):
        n = self.nb
        rms = float(np.sqrt(np.mean(x * x)))
        if rms < 6e-4:                       # silence
            self.sm *= 0.84
            self.bavg *= 0.9
            self._publish(0.0)
            return
        X = np.abs(np.fft.rfft(x * self.win)) * (4.0 / self.nfft)
        vals = np.empty(n)
        for i, (lo, hi) in enumerate(self.idx):
            vals[i] = math.sqrt(float(np.mean(X[lo:hi] ** 2)))
        vals *= self.tilt
        db = 20.0 * np.log10(vals + 1e-7)
        m = float(db.max())
        self.ceil = max(m, self.ceil - 0.03, -70.0)
        norm = np.clip((db - (self.ceil - 46.0)) / 46.0, 0.0, 1.0) ** 1.25
        up = norm > self.sm
        self.sm = np.where(up, self.sm + (norm - self.sm) * self.attack,
                           self.sm + (norm - self.sm) * self.release)
        bass_raw = float(norm[:5].mean())
        now = time.time()
        self.bavg = 0.90 * self.bavg + 0.10 * bass_raw
        strength = 0.0
        if bass_raw > 0.40 and bass_raw > self.bavg * 1.22 + 0.05 and now - self.last_beat > 0.17:
            self.last_beat = now
            self.beat_count += 1
            strength = min(1.0, (bass_raw - self.bavg) * 2.5 + 0.4)
            self.beat_strength = strength
        self._publish(bass_raw)

    def _publish(self, bass_raw):
        self.bands = self.sm.tolist()
        self.level = float(self.sm.mean())
        self.bass = float(self.sm[:5].mean())


class MicAnalyzer:
    """Microphone -> mouth. Feed it mono blocks; read .open (0..1) and .wide (0..1).
    Self-calibrating: tracks the room noise floor, so it works with quiet and loud mics alike."""

    def __init__(self, sr=48000):
        self.sr = sr
        self.floor = -60.0        # noise floor (dB) - drops fast, rises slowly
        self.ceil = -30.0         # recent speech peak (dB) - rises fast, decays slowly
        self.open = 0.0           # smoothed mouth opening 0..1
        self.wide = 0.35          # smoothed mouth width 0..1 (spectral tilt)
        self.level_raw = 0.0      # un-smoothed 0..1 (for the settings meter)
        self.sens = 1.0
        self._win = None

    def feed(self, x, sens=1.0):
        n = len(x)
        if n < 64:
            return
        rms = float(np.sqrt(np.mean(x * x)))
        db = 20.0 * math.log10(rms + 1e-9)
        # --- adaptive floor / ceiling ---
        if db < self.floor:
            self.floor = db
        else:
            self.floor = min(-35.0, self.floor + 0.012)
        self.floor = max(-90.0, self.floor)
        if db > self.ceil:
            self.ceil = db
        else:
            self.ceil = max(self.floor + 16.0, self.ceil - 0.02)
        span = max(10.0, self.ceil - self.floor - 6.0)
        v = (db - self.floor - 6.0) / span
        v = max(0.0, min(1.0, v)) ** 0.85 * max(0.1, sens)
        v = max(0.0, min(1.0, v))
        if rms < 1.5e-4:                      # digital silence
            v = 0.0
        self.level_raw = v
        # fast attack, slower release -> natural lips
        k = 0.62 if v > self.open else 0.22
        self.open += (v - self.open) * k
        # --- width: high-frequency share (ee/ss -> wide, oo/aa -> narrow) ---
        if v > 0.12:
            if self._win is None or len(self._win) != n:
                self._win = np.hanning(n)
            X = np.abs(np.fft.rfft(x * self._win))
            fr = np.fft.rfftfreq(n, 1.0 / self.sr)
            lo = float(np.sum(X[(fr >= 150) & (fr < 1000)] ** 2)) + 1e-12
            hi = float(np.sum(X[(fr >= 1800) & (fr < 6000)] ** 2))
            tilt = max(0.0, min(1.0, 0.5 + 0.5 * math.log10(hi / lo + 1e-6) / 1.6))
            self.wide += (tilt - self.wide) * 0.25
        else:
            self.wide += (0.35 - self.wide) * 0.10


# --------------------- ripple wave on the LED matrix --------------------
if np is not None:
    _GX = np.array([c[0] for c in sorted(CELLS)], dtype=float)
    _GY = np.array([c[1] for c in sorted(CELLS)], dtype=float)
    _KEYS = sorted(CELLS)
else:
    _GX = _GY = _KEYS = None


def ripple_cells(ripples, now, speed=22.0, life=1.1):
    """ripples: [(gx, gy, t0, strength)] -> {(gx,gy): brightness}"""
    if np is None or not ripples:
        return {}
    acc = np.zeros(len(_KEYS))
    for (cx, cy, t0, st) in ripples:
        age = now - t0
        if age < 0 or age > life:
            continue
        d = np.hypot(_GX - cx, _GY - cy)
        fade = (1.0 - age / life) ** 1.4
        acc = np.maximum(acc, np.exp(-((d - speed * age) / 1.6) ** 2) * fade * st)
    idx = np.nonzero(acc > 0.05)[0]
    return {_KEYS[i]: float(acc[i]) for i in idx}


# ---------------- v17: body shapes + shape-hugging ring + pupils ----------------
# v17.5: the bunny is gone (user request) - 10 shapes remain.
SHAPES = [('circle', 'Circle'), ('squircle', 'Rounded square'), ('heart', 'Heart'),
          ('star', 'Star'), ('cat', 'Cat'), ('bear', 'Bear'),
          ('ghost', 'Ghost'), ('mug', 'Mug'), ('cloud', 'Cloud'), ('drop', 'Drop')]
PUPILS = [('none', 'None'), ('dot', 'Dot'), ('big', 'Big'), ('slit', 'Cat slit'),
          ('hslit', 'Goat bar'), ('ring', 'Ring'), ('square', 'Square'),
          ('heart', 'Heart'), ('spark', 'Sparkle'),
          # v17.9: ten more pupils (the last three are animated)
          ('cross', 'Cross'), ('star5', 'Star'), ('diamond', 'Diamond'),
          ('crescent', 'Moon'), ('flower', 'Flower'), ('bars', 'Anime bars'),
          ('target', 'Target'), ('scan', 'Scanning (live)'), ('pulse', 'Beating (live)'),
          ('wander', 'Wandering (live)')]

_CIRCLE_CELLS = CELLS          # the original round LED matrix
_CIRCLE_KEYS = _KEYS
_CIRCLE_GX = _GX
_CIRCLE_GY = _GY

SHAPE = 'circle'
EDGE = frozenset()
_SHAPE_NAMES = tuple(nm for nm, _lb in SHAPES)


def _ell(u, v, cx, cy, rx, ry):
    return ((u - cx) / rx) ** 2 + ((v - cy) / ry) ** 2 <= 1.0


def _tri(u, v, a, b, c):
    def s(p, q, r):
        return (p[0] - r[0]) * (q[1] - r[1]) - (q[0] - r[0]) * (p[1] - r[1])
    p = (u, v)
    d1, d2, d3 = s(p, a, b), s(p, b, c), s(p, c, a)
    return not (((d1 < 0) or (d2 < 0) or (d3 < 0)) and
                ((d1 > 0) or (d2 > 0) or (d3 > 0)))


def _ellr(u, v, cx, cy, rx, ry, ang):
    # tilted ellipse (ang > 0 = top leans right)
    ca, sa = math.cos(ang), math.sin(ang)
    x, y = u - cx, v - cy
    return ((x * ca + y * sa) / rx) ** 2 + ((y * ca - x * sa) / ry) ** 2 <= 1.0


def _rbox(u, v, cx, cy, hx, hy, r):
    qx = abs(u - cx) - hx + r
    qy = abs(v - cy) - hy + r
    return min(max(qx, qy), 0.0) + math.hypot(max(qx, 0.0), max(qy, 0.0)) - r <= 0.0


# ---------------- v17.1 shape polish (LEDPET_V17_1_SHAPES) ----------------
def _star_poly(T=(0.0, -13.35), R=(13.35, -2.3), BR=(8.1, 13.1),
               vTR=(5.8, -6.6), vRB=(8.2, 3.0), vB=(0.0, 8.9), bulge=1.6):
        # v17.6: MARIO-GALAXY star rebuilt from ABSOLUTE vertices - the user
        # said the v17.5 star still looked small, because its side tips were
        # clipped flat by the display edge (they read as a band, not points)
        # and its face filled the whole body.  The new polygon places every
        # tip by hand so all five points stay VISIBLE: the top tip starts at
        # row 0, the side tips poke out to the outermost columns as real
        # points, the legs reach the bottom edge - corner to corner.  The
        # arms are FAT (convex edges, two bulge points per edge) with deep,
        # rounded valleys so the five arms read separately.
    def mir(p):
        return (-p[0], p[1])
    L, BL, vTL, vLB = mir(R), mir(BR), mir(vTR), mir(vRB)
    cyc = [T, vTR, R, vRB, BR, vB, BL, vLB, L, vTL]   # tips at even indices
    pts = []
    n = len(cyc)

    def lerp(a, b, t):
        return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)

    def bulge_pts(a, b):
        out = []
        for t in (0.33, 0.67):               # two points = fat convex edge
            mx, my = a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t
            d = math.hypot(mx, my)
            out.append((mx + mx / d * bulge, my + my / d * bulge)
                       if d > 1e-6 else (mx, my))
        return out

    for i in range(n):
        p, q = cyc[i], cyc[(i + 1) % n]
        if i % 2 == 0:
            # p is a sharp TIP; edge p->q runs into the valley q
            pts.append(p)
            pts.extend(bulge_pts(p, q))
            for t in (0.80, 0.93):           # approach fillets near the valley
                pts.append(lerp(p, q, t))
            d = math.hypot(q[0], q[1])
            pts.append((q[0] + q[0] / d * 0.35, q[1] + q[1] / d * 0.35)
                       if d > 1e-6 else q)   # pushed (chubby) valley vertex
        else:
            # p is a VALLEY; edge p->q runs out to the tip q
            for t in (0.07, 0.20):           # leave fillets near the valley
                pts.append(lerp(p, q, t))
            pts.extend(bulge_pts(p, q))
    return pts


_STAR_PTS = _star_poly()


def _pip(pts, x, y):
        # exact even-odd point-in-polygon - mirror-symmetric for symmetric
        # polygons (the old ray/radius test rounded asymmetrically at the
        # near-horizontal leg edges)
    inside = False
    j = len(pts) - 1
    for i in range(len(pts)):
        xi, yi = pts[i]
        xj, yj = pts[j]
        if (yi > y) != (yj > y):
            if x < (xj - xi) * (y - yi) / (yj - yi) + xi:
                inside = not inside
        j = i
    return inside


def _star_r(a, _pts=None):
        # boundary radius of the fat five-point star at angle a (kept for the
        # boundary-table tooling; the mask itself uses _pip now)
    pts = _STAR_PTS if _pts is None else _pts
    dx, dy = math.cos(a), math.sin(a)
    best = 0.0
    for j in range(len(pts)):
        px, py = pts[j]
        qx, qy = pts[(j + 1) % len(pts)]
        den = dx * (qy - py) - dy * (qx - px)
        if abs(den) < 1e-12:
            continue
        s = (px * dy - py * dx) / den
        t = (px * qy - py * qx) / den
        if -1e-9 <= s <= 1.0 + 1e-9 and t > 0.0 and (best == 0.0 or t < best):
            best = t
    return best


# (v17.2: the old _MUG_HANDLE cell list is gone - the handle is a real
#  annulus with a hole now, see _inside('mug'))


def _inside(name, u, v):
        # is the point (u, v) inside the body?  u right, v DOWN, cell units (-13..13).
    # Every shape keeps the whole face zone (eyes, cheeks, mouth) inside.
    if name == 'squircle':
        return (abs(u / 12.7) ** 4 + abs(v / 13.05) ** 4) <= 1.0
    if name == 'heart':
        # v17.2: classic emoji heart - two round lobes, a SHORT WIDE cleft,
        # sides that curve smoothly inward and a soft bottom point
        if v <= -6.2 and abs(u) < 2.7 * ((-6.2 - v) / 7.3):
            return False                      # the cleft
        if _ell(u, v, -5.6, -7.2, 6.3, 6.3) or _ell(u, v, 5.6, -7.2, 6.3, 6.3):
            return True
        if -7.2 <= v <= 12.9:
            t = (v + 7.2) / 20.1
            return abs(u) <= 11.9 * (1.0 - 0.05 * t - 0.95 * t ** 4)
        return False
    if name == 'star':
        # v17.6: fat Mario-Galaxy star from absolute vertices (see _star_poly)
        # - exact point-in-polygon test, mirror-symmetric by construction.
        return _pip(_STAR_PTS, u, v)
    if name == 'cat':
        if _ell(u, v, 0, 1.6, 12.55, 11.6) or _ell(u, v, 0, 4.8, 11.8, 9.4):
            return True
        return (_tri(u, v, (-11.2, -3.4), (-2.4, -9.0), (-11.4, -12.9))
                or _tri(u, v, (11.2, -3.4), (2.4, -9.0), (11.4, -12.9)))
    if name == 'bear':
        if (_ell(u, v, 0, -1.0, 12.6, 11.9) or _ell(u, v, 0, 2.6, 12.3, 11.0)
                or _ell(u, v, 0, 4.6, 12.0, 9.5)):
            return True
        return _ell(u, v, -9.9, -9.5, 3.65, 3.65) or _ell(u, v, 9.9, -9.5, 3.65, 3.65)
    if name == 'ghost':
        if v <= -0.5:
            return _ell(u, v, 0, -0.5, 12.7, 12.2)
        if abs(u) > 12.7:
            return False
        return v <= 11.7 + 1.45 * math.cos(u * math.pi / 3.3)
    if name == 'mug':
        # v18.6 (user request): the ear handle now REACHES THE DISPLAY EDGE
        # (outer arc pushed out to u 13.7 around a wider 4-column see-through
        # opening) so it reads even more like a real handle, and the bottom
        # is ROUNDER + NARROWER: the straight sides end at v 7.0 and flow
        # into a big bottom ellipse (8.9 x 6.0) that tapers down to a small
        # 10-cell-wide foot on the display bottom (the v17.7 box ran almost
        # square all the way down).  Rim ellipse, dark coffee lens and the
        # whole face zone stay exactly as approved in v17.7.
        if (_ell(u, v, -1.5, -8.3, 8.9, 4.1)
                or _rbox(u, v, -1.5, -0.45, 8.9, 7.45, 2.6)
                or _ell(u, v, -1.5, 7.0, 8.9, 6.0)
                or _rbox(u, v, -1.5, 11.7, 4.9, 2.0, 1.5)):
            if _ell(u, v, -1.5, -9.7, 6.0, 1.5):           # the dark coffee
                return False
            return True
        if u >= 6.6:                                       # ear handle, right
            eo_ = ((u - 9.7) / 4.0) ** 2 + ((v - 1.0) / 7.6) ** 2 <= 1.0
            ei_ = ((u - 9.8) / 1.9) ** 2 + ((v - 1.0) / 4.6) ** 2 <= 1.0
            return eo_ and not ei_
        return False
    if name == 'cloud':
        # v17.5: kawaii cartoon cloud - one BIG centre dome and two fat side
        # puffs that melt into it (smooth lobed outline, no carved notches)
        # + a rounded flat base the puffs overhang.  The big dome leaves
        # room for three eyes at the classic spot.
        if _ell(u, v, 0, -4.9, 8.8, 8.3):                  # big centre dome
            return True
        if _ell(u, v, -8.8, -1.5, 5.4, 5.2):               # left fat puff
            return True
        if _ell(u, v, 8.8, -1.5, 5.4, 5.2):                # right fat puff
            return True
        return _rbox(u, v, 0, 6.2, 10.6, 3.8, 3.0)         # rounded flat base
    if name == 'drop':
        # teardrop: fat round bottom, a neck at the upper diagonal, soft point up
        a_ = math.atan2(v, u)
        return math.hypot(u, v) <= (12.55 + 0.45 * max(0.0, math.sin(a_)) ** 2
                                    + 0.90 * math.exp(-((a_ + 90.0) / 14.0) ** 2)
                                    - 2.30 * math.exp(-((a_ + 58.0) / 11.0) ** 2))
    return False


def _face_core(u, v):
        # the zone the face needs (eyes, mouth, cheeks) - always kept inside.
        # v17.2: tight per-shape cores for the rebuilt silhouettes (the wide
        # generic box inflated narrow shapes into blobs); the approved shapes
        # (cat/bear/ghost/drop/squircle) keep the original box core.
    if SHAPE == 'star':
        # v17.6: the face is drawn smaller on the Galaxy star (the LED margin
        # around it is what makes the star read BIG) - the guaranteed-fit
        # core shrinks with it
        return (_ell(u, v, -4.6, -1.0, 2.8, 3.0) or _ell(u, v, 4.6, -1.0, 2.8, 3.0)
                or _ell(u, v, 0.0, 6.2, 3.6, 1.5)
                or _ell(u, v, -4.6, 3.4, 2.0, 1.5) or _ell(u, v, 4.6, 3.4, 2.0, 1.5))
    if SHAPE == 'heart':
        return (_ell(u, v, -5.0, -1.0, 3.2, 3.4) or _ell(u, v, 5.0, -1.0, 3.2, 3.4)
                or _ell(u, v, 0.0, 7.4, 5.2, 2.0)
                or _ell(u, v, -6.5, 4.0, 3.0, 2.2) or _ell(u, v, 6.5, 4.0, 3.0, 2.2))
    if SHAPE == 'mug':
        # v17.6: tighter core on the narrower cup body (cheeks on the straight
        # body, right edge u = 7.4 since v17.7 - the ear needs the room)
        return (_ell(u, v, -4.6, -1.0, 2.9, 3.1) or _ell(u, v, 4.6, -1.0, 2.9, 3.1)
                or _ell(u, v, 0.0, 7.2, 4.4, 1.7)
                or _ell(u, v, -4.8, 4.8, 2.3, 1.6) or _ell(u, v, 4.8, 4.8, 2.3, 1.6))
    if SHAPE == 'cloud':
        # v17.5: cheeks follow the rounded flat base (|u| <= 10.6)
        return (_ell(u, v, -5.0, -1.0, 3.2, 3.4) or _ell(u, v, 5.0, -1.0, 3.2, 3.4)
                or _ell(u, v, 0.0, 7.4, 5.2, 2.0)
                or _ell(u, v, -5.6, 6.0, 2.8, 2.2) or _ell(u, v, 5.6, 6.0, 2.8, 2.2))
    return (_rbox(u, v, 0, -1.2, 9.9, 5.9, 1.8)
            or _ell(u, v, 0, 7.6, 5.4, 3.4)
            or _ell(u, v, -8.8, 6.0, 2.5, 2.9)
            or _ell(u, v, 8.8, 6.0, 2.5, 2.9))


def shape_cells(name):
        # the LED cells of a body shape (circle = the original matrix)
    if name not in _SHAPE_NAMES:
        return _CIRCLE_CELLS
    out = set()
    for gy in range(N):
        for gx in range(N):
            u, v = gx - HALF, gy - HALF
            if _face_core(u, v) or _inside(name, u, v):
                out.add((gx, gy))
    return frozenset(out)


def set_shape(name):
        # switch the LED matrix body shape (call BEFORE building a Renderer)
    global SHAPE, CELLS, EDGE, _GX, _GY, _KEYS
    if name not in _SHAPE_NAMES:
        name = 'circle'
    if name == SHAPE:
        return
    if name == 'circle':
        CELLS = _CIRCLE_CELLS
        EDGE = frozenset()
        SHAPE = name
        if np is not None:
            _KEYS = _CIRCLE_KEYS
            _GX = _CIRCLE_GX
            _GY = _CIRCLE_GY
        return
    SHAPE = name                  # v17.1: _face_core is shape-aware -> set FIRST
    cells = shape_cells(name)
    edge = set()
    for (gx, gy) in cells:
        if ((gx + 1, gy) not in cells or (gx - 1, gy) not in cells
                or (gx, gy + 1) not in cells or (gx, gy - 1) not in cells):
            edge.add((gx, gy))
    CELLS = frozenset(cells)
    EDGE = frozenset(edge)
    if np is not None:
        _KEYS = sorted(CELLS)
        _GX = np.array([c[0] for c in _KEYS], dtype=float)
        _GY = np.array([c[1] for c in _KEYS], dtype=float)


_BOUND_CACHE = {}


def _shape_boundary(name):
        # 144 samples of the body outline radius (logical px), angle k*2pi/144
    if name in _BOUND_CACHE:
        return _BOUND_CACHE[name]
    if name not in _SHAPE_NAMES:
        tab = [RMAX] * 144
    else:
        cells = shape_cells(name)
        tab = []
        for k in range(144):
            ang = 2.0 * math.pi * k / 144.0
            c, s = math.cos(ang), math.sin(ang)
            r_out = 0.0
            r = 0.4
            while r <= 18.0:
                gx = int(round(HALF + r * c))
                gy = int(round(HALF + r * s))
                if (gx, gy) in cells:
                    r_out = r
                r += 0.15
            tab.append(r_out * PITCH)
    _BOUND_CACHE[name] = tab
    return tab


def ray_starts(n):
        # per-ray equalizer bar start radius (px) - the bars hug the body
    if SHAPE not in _SHAPE_NAMES or SHAPE == 'circle':
        return [RAY_R0] * n
    tab = _shape_boundary(SHAPE)
    out = []
    for i in range(n):
        ang = 2.0 * math.pi * i / n - math.pi / 2.0
        k = (ang % (2.0 * math.pi)) / (2.0 * math.pi) * 144.0
        i0 = int(k) % 144
        i1 = (i0 + 1) % 144
        f = k - int(k)
        out.append(tab[i0] * (1.0 - f) + tab[i1] * f + 20.0)
    return out


def outline_radii():
        # outline ring radius (px) per 144 angles for the current shape
    if SHAPE not in _SHAPE_NAMES or SHAPE == 'circle':
        return [R + 7.0] * 144
    return [r + 8.0 for r in _shape_boundary(SHAPE)]


# ------------------------------- v17: pupils --------------------------------
_PHEART = ('01010', '11111', '11111', '01110', '00100')
_PSPARK = ('00100', '01110', '11111', '01110', '00100')
# v17.9: the ten new pupil bitmaps (3x/5x glyphs, scaled by k)
_PCROSS = ('00100', '00100', '11111', '00100', '00100')
_PSTAR5 = ('00100', '01110', '11111', '01110', '01010')
_PBARS = ('10101', '10101', '10101', '10101', '10101')
_PTGT = ('01110', '10001', '10101', '10001', '01110')


def pupil_fn(kind, k=1.0):
        # a pupil shape as a soft function (1 = full pupil)
    k = max(0.3, k)
    if kind in ('dot', 'big', 'scan', 'wander', 'pulse'):
        r = (1.15 if kind in ('dot', 'scan', 'wander', 'pulse') else 2.05) * k
        return lambda px, py: cov((math.hypot(px, py) - r) * 1.2)
    if kind in ('slit', 'hslit'):
        rx, ry = (0.75 * k, 3.4 * k) if kind == 'slit' else (2.8 * k, 0.75 * k)

        def f(px, py):
            return cov((math.hypot(px / rx, py / ry) - 1.0) * min(rx, ry) * 1.3)
        return f
    if kind == 'ring':
        r = 2.3 * k
        return lambda px, py: cov((abs(math.hypot(px, py) - r) - 0.45) * 1.25)
    if kind == 'square':
        h = 1.25 * k
        return lambda px, py: cov(sd_rbox(px, py, h, h, 0.35, 0.35, 0.35, 0.35) * 1.25)
    if kind == 'heart':
        return _scaled(bmp_fn(_PHEART), k, k)
    if kind == 'spark':
        return _scaled(bmp_fn(_PSPARK), k, k)
    # --- v17.9: the ten new pupils ---
    if kind == 'cross':
        return _scaled(bmp_fn(_PCROSS), k, k)
    if kind == 'star5':
        return _scaled(bmp_fn(_PSTAR5), k, k)
    if kind == 'bars':
        return _scaled(bmp_fn(_PBARS), k, k)
    if kind == 'target':
        return _scaled(bmp_fn(_PTGT), k, k)
    if kind == 'diamond':
        d = 1.85 * k
        return lambda px, py: cov((abs(px / d) + abs(py / d) - 1.0) * 1.5)
    if kind == 'crescent':
        r1, r2 = 2.05 * k, 1.75 * k

        def f(px, py):
            a = cov((math.hypot(px, py) - r1) * 1.3)
            b = cov((math.hypot(px + 0.85 * k, py - 0.45 * k) - r2) * 1.3)
            return max(0.0, a - b)
        return f
    if kind == 'flower':
        rb, rv = 0.95 * k, 0.85 * k

        def f(px, py):
            rr = math.hypot(px, py)
            if rr < 1e-4:
                return cov((rr - rb - rv) * 1.5)
            r_edge = rb + rv * math.cos(4.0 * math.atan2(py, px))
            return cov((rr - r_edge) * 1.5)
        return f
    return lambda px, py: 0.0


# v18.1 (LEDPET_V18_CUSTOM): the IRIS - the colored ring/disc behind the
# pupil.  r is the desired outer radius in cells; every style stays inside
# the eye because build_face carves it with the eye coverage.
def iris_fn(kind, r=2.6):
    r = max(0.6, r)
    if kind == 'circle':                    # full disc
        return lambda px, py: cov((math.hypot(px, py) - r) * 1.2)
    if kind == 'ring':                      # annulus (eye color stays inside)
        th = max(0.55, r * 0.34)
        rr = max(0.7, r - th)
        return lambda px, py: cov((abs(math.hypot(px, py) - rr) - th) * 1.25)
    if kind == 'square':
        h = r * 0.80
        return lambda px, py: cov(sd_rbox(px, py, h, h, 0.4, 0.4, 0.4, 0.4) * 1.25)
    if kind == 'diamond':
        d = r * 0.95
        return lambda px, py: cov((abs(px / d) + abs(py / d) - 1.0) * 1.5)
    if kind == 'heart':                     # the 5x5 pupil heart, scaled to r
        s = r / 2.9
        return _scaled(bmp_fn(_PHEART), s, s)
    if kind == 'star5':
        s = r / 2.9
        return _scaled(bmp_fn(_PSTAR5), s, s)
    return lambda px, py: 0.0


_SYM_EYE = {'sadL': 'sadC', 'sadR': 'sadC', 'angryL': 'angryC', 'angryR': 'angryC',
            'frownL': 'frownC', 'frownR': 'frownC'}
