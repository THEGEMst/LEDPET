# -*- coding: utf-8 -*-
# =====================================================================
#  LEDPet - 'home' logic (v13)          no Tk, no Pillow -> easily testable
#     - Needs       : hunger / thirst / fun (slow decay over time)
#     - Display     : scrolling dot-matrix text on the frame display
#     - Feeder      : food and water (drag & drop onto the pet, or click)
#     - CatchGame / TapGame / MemoryGame : three tiny games
#     - Personality : random idle emotes + hungry/thirsty faces
# =====================================================================
import math
import random

import ledpet_core as C

DW, DH = 60, 11            # dot display size (columns x rows)


def clamp(v, a, b):
    return a if v < a else (b if v > b else v)


# ============================== needs ================================
class Needs:
    RATES = {'food': 1.0 / (4 * 3600.0), 'water': 1.0 / (3 * 3600.0), 'fun': 1.0 / (2 * 3600.0)}
    LOW = 0.25

    def __init__(self, food=0.8, water=0.8, fun=0.7):
        self.v = {'food': clamp(float(food), 0.0, 1.0),
                  'water': clamp(float(water), 0.0, 1.0),
                  'fun': clamp(float(fun), 0.0, 1.0)}

    def update(self, dt):
        for k, r in self.RATES.items():
            self.v[k] = max(0.0, self.v[k] - r * dt)

    def offline(self, secs):
        """while the app was closed: half speed, capped at 3 hours"""
        secs = clamp(float(secs), 0.0, 3 * 3600.0)
        self.update(secs * 0.5)

    def add(self, key, amount):
        self.v[key] = clamp(self.v[key] + amount, 0.0, 1.0)

    def lowest(self):
        k = min(self.v, key=lambda z: self.v[z])
        return k if self.v[k] < self.LOW else None

    def mood(self):
        return sum(self.v.values()) / 3.0


# ============================ dot display ==============================
def text_width(text):
    w = 0
    for ch in text:
        rows = C.FONT5.get(ch)
        if rows:
            w += len(rows[0]) + 1
    return max(0, w - 1)


def text_cells(text, x0, y0=2):
    """text -> {(col, row): 1.0}; core 5x7 font"""
    out = {}
    x = x0
    for ch in text:
        rows = C.FONT5.get(ch)
        if not rows:
            continue
        for r, row in enumerate(rows):
            for c, bit in enumerate(row):
                if bit == '1' and 0 <= x + c < DW and 0 <= y0 + r < DH:
                    out[(int(x + c), y0 + r)] = 1.0
        x += len(rows[0]) + 1
    return out


class Display:
    """show a message; if longer than the display it scrolls as a marquee"""
    SPEED = 20.0       # columns per second

    def __init__(self):
        self.text = ''
        self.t0 = 0.0
        self.until = 0.0
        self.scroll = False
        self.sticky = False

    def say(self, text, now, secs=2.6, sticky=False):
        text = (text or '').upper()
        self.text = text
        self.t0 = now
        w = text_width(text)
        self.scroll = w > DW - 4
        if self.scroll:
            secs = max(secs, (DW + w) / self.SPEED + 0.3)
        self.until = now + secs
        self.sticky = sticky

    def idle(self, now):
        return (not self.sticky) and now >= self.until

    def cells(self, now):
        if not self.text:
            return {}
        w = text_width(self.text)
        if self.scroll:
            x0 = DW - (now - self.t0) * self.SPEED
        else:
            x0 = (DW - w) // 2
        if x0 > DW or x0 + w < 0:
            return {}
        return text_cells(self.text, int(round(x0)))


# ============================== food / water ============================
class FeedItem:
    __slots__ = ('kind', 'x', 'y', 'sx', 'sy', 'state', 't', 'vy', 'bites', 'alpha', 'bounced', 'size')

    def __init__(self, kind, x, y, state):
        self.kind = kind
        self.x, self.y = float(x), float(y)
        self.sx, self.sy = float(x), float(y)
        self.state = state
        self.t = 0.0
        self.vy = 0.0
        self.bites = 0
        self.alpha = 1.0
        self.bounced = False
        self.size = 1.0


class Feeder:
    FLY_T = 0.55
    EAT_T = (0.30, 0.85, 1.40)          # bite moments
    EAT_END = 1.75
    PER_BITE = {'food': 0.12, 'water': 0.12}

    def __init__(self):
        self.items = []
        self.events = []                # ('eat_start'|'bite'|'eat_done'|'refuse', kind, x, y)

    def busy(self):
        return any(it.state in ('fly', 'eat') for it in self.items)

    def dragging(self):
        for it in self.items:
            if it.state == 'drag':
                return it
        return None

    def start_drag(self, kind, x, y):
        self.cancel_drag()
        it = FeedItem(kind, x, y, 'drag')
        self.items.append(it)
        return it

    def cancel_drag(self):
        self.items = [i for i in self.items if i.state != 'drag']

    def drag_to(self, x, y):
        it = self.dragging()
        if it is not None:
            it.x, it.y = float(x), float(y)

    def drop(self, mouth, radius, refuse, center=None):
        """drop an item; eaten if close to the pet (face center). Returns True if accepted"""
        it = self.dragging()
        if it is None:
            return False
        ref = center if center is not None else mouth
        near = math.hypot(it.x - ref[0], it.y - ref[1]) <= radius
        it.sx, it.sy, it.t = it.x, it.y, 0.0
        if near and not refuse:
            it.state = 'fly'
            return True
        it.state = 'fall'
        it.vy = -120.0
        if near and refuse:
            self.events.append(('refuse', it.kind, it.x, it.y))
        return False

    def quick(self, kind, sx, sy, refuse):
        """simple button click: the item jumps to the pet's mouth by itself"""
        if refuse:
            it = FeedItem(kind, sx, sy, 'fall')
            it.vy = -260.0
            self.items.append(it)
            self.events.append(('refuse', kind, sx, sy))
            return False
        it = FeedItem(kind, sx, sy, 'fly')
        self.items.append(it)
        return True

    def update(self, dt, mouth, ground_y, unit=1.0):
        keep = []
        for it in self.items:
            if it.state == 'drag':
                keep.append(it)
                continue
            it.t += dt
            if it.state == 'fly':
                u = clamp(it.t / self.FLY_T, 0.0, 1.0)
                e = 1.0 - (1.0 - u) ** 3
                it.x = it.sx + (mouth[0] - it.sx) * e
                it.y = it.sy + (mouth[1] - it.sy) * e - math.sin(math.pi * u) * 70.0 * unit
                if u >= 1.0:
                    it.state, it.t = 'eat', 0.0
                    self.events.append(('eat_start', it.kind, mouth[0], mouth[1]))
            elif it.state == 'eat':
                it.x, it.y = mouth[0], mouth[1]
                while it.bites < len(self.EAT_T) and it.t >= self.EAT_T[it.bites]:
                    it.bites += 1
                    it.size = 1.0 - it.bites / 3.0
                    self.events.append(('bite', it.kind, it.x, it.y))
                if it.t >= self.EAT_END:
                    self.events.append(('eat_done', it.kind, it.x, it.y))
                    continue
            elif it.state == 'fall':
                it.vy += 1500.0 * unit * dt
                it.y += it.vy * dt
                if it.y >= ground_y:
                    it.y = ground_y
                    if not it.bounced:
                        it.bounced = True
                        it.vy = -it.vy * 0.35
                    else:
                        it.vy = 0.0
                if it.bounced and it.y >= ground_y - 0.5:
                    it.alpha -= dt * 1.8
                    if it.alpha <= 0.0:
                        continue
            keep.append(it)
        self.items = keep

    def pop_events(self):
        ev, self.events = self.events, []
        return ev


# ================================ games =================================
class BaseGame:
    name = 'GAME'

    def __init__(self, rng=None):
        self.rng = rng or random.Random()
        self.score = 0
        self.lives = 3
        self.over = False
        self.t = 0.0
        self.events = []            # 'good' | 'bad' | 'win' | 'lose'

    def pop_events(self):
        ev, self.events = self.events, []
        return ev

    def _lose_life(self):
        self.lives -= 1
        self.events.append('bad')
        if self.lives <= 0:
            self.finish()

    def finish(self):
        if not self.over:
            self.over = True
            self.events.append('lose')

    def hud(self):
        out = {}
        for i in range(max(0, self.lives)):
            out[(1 + 2 * i, 0)] = 0.8
        return out

    def update(self, dt, mouse):
        self.t += dt

    def click(self, c, r):
        pass

    def cells(self):
        return {}


class CatchGame(BaseGame):
    """move the basket with the mouse (left/right on the display); catch food, avoid bombs"""
    name = 'CATCH'
    PADDLE_HALF = 4.6

    def __init__(self, rng=None):
        BaseGame.__init__(self, rng)
        self.px = DW / 2.0
        self.target = DW / 2.0
        self.items = []
        self.spawn_in = 0.7

    def update(self, dt, mouse):
        BaseGame.update(self, dt, mouse)
        if self.over:
            return
        if mouse is not None:
            self.target = clamp(mouse[0], 5.0, DW - 6.0)
        self.px += (self.target - self.px) * min(1.0, dt * 14.0)
        speed = min(9.5, 3.6 + 0.22 * self.score)
        self.spawn_in -= dt
        if self.spawn_in <= 0.0:
            bomb = self.score >= 5 and self.rng.random() < 0.20
            self.items.append({'x': self.rng.uniform(3.0, DW - 4.0), 'y': -1.5, 'bomb': bomb})
            self.spawn_in = max(0.42, 1.0 - 0.03 * self.score) * self.rng.uniform(0.8, 1.2)
        keep = []
        for it in self.items:
            it['y'] += speed * dt
            if it['y'] >= DH - 2.2:
                if abs(it['x'] + 0.5 - self.px) <= self.PADDLE_HALF + 0.8:
                    if it['bomb']:
                        self._lose_life()
                    else:
                        self.score += 1
                        self.events.append('good')
                    continue
                if it['y'] >= DH:
                    if not it['bomb']:
                        self._lose_life()
                    continue
            keep.append(it)
        self.items = keep

    def cells(self):
        out = dict(self.hud())
        for dx in range(-4, 5):
            c = int(round(self.px)) + dx
            if 0 <= c < DW:
                out[(c, DH - 1)] = 1.0 if abs(dx) < 4 else 0.55
        for it in self.items:
            x, y = int(it['x']), int(math.floor(it['y']))
            if it['bomb']:
                pat = ((1, 0), (0, 1), (1, 1), (2, 1), (1, 2))
                b = 0.45 + 0.4 * (int(self.t * 8) % 2)
            else:
                pat = ((0, 0), (1, 0), (0, 1), (1, 1))
                b = 1.0
            for ox, oy in pat:
                cc, rr = x + ox, y + oy
                if 0 <= cc < DW and 0 <= rr < DH - 1:
                    out[(cc, rr)] = b
        return out


class TapGame(BaseGame):
    """click the blinking target quickly; it gets faster every round"""
    name = 'TAP'

    def __init__(self, rng=None):
        BaseGame.__init__(self, rng)
        self.tgt = None
        self.next_in = 0.6

    def _life(self):
        return max(0.60, 1.55 - 0.06 * self.score)

    def update(self, dt, mouse):
        BaseGame.update(self, dt, mouse)
        if self.over:
            return
        if self.tgt is not None:
            if self.t - self.tgt['t0'] > self.tgt['life']:
                self.tgt = None
                self.next_in = 0.45
                self._lose_life()
        elif self.next_in > 0.0:
            self.next_in -= dt
        else:
            self.tgt = {'c': self.rng.uniform(5.0, DW - 6.0), 'r': self.rng.uniform(3.0, DH - 4.0),
                        't0': self.t, 'life': self._life()}

    def click(self, c, r):
        if self.over or self.tgt is None:
            return
        if math.hypot(c - self.tgt['c'], r - self.tgt['r']) <= 3.8:
            self.score += 1
            self.events.append('good')
            self.tgt = None
            self.next_in = 0.30

    def cells(self):
        out = dict(self.hud())
        if self.tgt is not None:
            left = 1.0 - (self.t - self.tgt['t0']) / self.tgt['life']
            if left > 0.35 or int(self.t * 12) % 2 == 0:
                cc, rr = self.tgt['c'], self.tgt['r']
                for gy in range(int(rr) - 2, int(rr) + 3):
                    for gx in range(int(cc) - 2, int(cc) + 3):
                        d = math.hypot(gx + 0.5 - cc, gy + 0.5 - rr)
                        if d <= 1.9 and 0 <= gx < DW and 0 <= gy < DH:
                            out[(gx, gy)] = 1.0
        return out


class MemoryGame(BaseGame):
    """four pads; memorize the blink order and repeat it"""
    name = 'MEMORY'
    PAD_W, PAD_X = 13, (1, 16, 31, 46)

    def __init__(self, rng=None):
        BaseGame.__init__(self, rng)
        self.seq = [self.rng.randrange(4) for _ in range(2)]
        self.phase = 'pause'
        self.ph_t = 0.0
        self.pos = 0
        self.lit = None
        self.lit_until = 0.0
        self.lives = 1

    def hud(self):
        return {}

    def _next_phase(self, name):
        self.phase, self.ph_t, self.pos = name, 0.0, 0

    def update(self, dt, mouse):
        BaseGame.update(self, dt, mouse)
        if self.over:
            return
        self.ph_t += dt
        if self.lit is not None and self.t > self.lit_until:
            self.lit = None
        if self.phase == 'pause' and self.ph_t > 0.8:
            self._next_phase('show')
        elif self.phase == 'show':
            slot = 0.65
            i = int(self.ph_t / slot)
            if i >= len(self.seq):
                self._next_phase('input')
                self.lit = None
            else:
                self.lit = self.seq[i] if (self.ph_t % slot) < 0.45 else None
                self.lit_until = self.t + 0.05

    def _pad_at(self, c, r):
        if not (1 <= r <= 9):
            return None
        for i, x0 in enumerate(self.PAD_X):
            if x0 <= c < x0 + self.PAD_W:
                return i
        return None

    def click(self, c, r):
        if self.over or self.phase != 'input':
            return
        p = self._pad_at(c, r)
        if p is None:
            return
        self.lit, self.lit_until = p, self.t + 0.25
        if p == self.seq[self.pos]:
            self.pos += 1
            self.events.append('good')
            if self.pos >= len(self.seq):
                self.score += 1
                self.events.append('win')
                self.seq.append(self.rng.randrange(4))
                self._next_phase('pause')
        else:
            self.finish()

    def cells(self):
        out = {}
        for i, x0 in enumerate(self.PAD_X):
            lit = (self.lit == i)
            for gy in range(1, 10):
                for gx in range(x0, x0 + self.PAD_W):
                    edge = gx in (x0, x0 + self.PAD_W - 1) or gy in (1, 9)
                    if lit:
                        pat = [True, (gx + gy) % 2 == 0, gy % 2 == 1, gx % 2 == 0][i]
                        if edge or pat:
                            out[(gx, gy)] = 1.0
                    elif edge:
                        out[(gx, gy)] = 0.32
        return out


GAMES = (('CATCH', CatchGame), ('TAP', TapGame), ('MEMORY', MemoryGame))


_TRI_L = ('0001', '0011', '0111', '1111', '0111', '0011', '0001')
_TRI_R = ('1000', '1100', '1110', '1111', '1110', '1100', '1000')


def menu_cells(idx=0, hover=None):
    """game menu: < game name >  ->  (cells, zones=[(name, col_start, col_end)])"""
    out = {}
    name = GAMES[idx % len(GAMES)][0]
    w = text_width(name)
    for k in text_cells(name, (DW - w) // 2, 2):
        out[k] = 1.0 if hover == 'go' else 0.9
    for rows, x0, key in ((_TRI_L, 3, 'prev'), (_TRI_R, DW - 7, 'next')):
        for r, row in enumerate(rows):
            for c, bit in enumerate(row):
                if bit == '1':
                    out[(x0 + c, 2 + r)] = 1.0 if hover == key else 0.5
    for i in range(len(GAMES)):                       # page dots
        out[(DW // 2 - len(GAMES) + 2 * i, DH - 1)] = 1.0 if i == idx % len(GAMES) else 0.25
    zones = [('prev', 0, 14), ('go', 14, DW - 14), ('next', DW - 14, DW)]
    return out, zones


# ============================ personality ===============================
class Personality:
    EMOTES = (('think', 3.4), ('smirk', 2.4), ('shy', 2.4), ('cool', 2.8),
              ('star', 2.2), ('kiss', 2.6), ('sleepy', 3.6), ('laugh', 2.2), ('wink', 0.9))

    def __init__(self, now, rng=None):
        self.rng = rng or random.Random()
        self.next_emote = now + self.rng.uniform(18.0, 40.0)
        self.next_need = now + 45.0
        self.last = None

    def poke(self, now, secs=40.0):
        """after an interaction (food, game, ...) pause random emotes for a while"""
        self.next_emote = max(self.next_emote, now + secs * 0.5)

    def tick(self, now, idle, needs, emotes=True):
        """idle: the pet is in its normal state. Returns (state, secs, icon) or None"""
        if not idle:
            return None
        low = needs.lowest()
        if low and now >= self.next_need:
            self.next_need = now + self.rng.uniform(70.0, 120.0)
            if low == 'food':
                return ('hungry', 3.8, 'food')
            if low == 'water':
                return ('hungry', 3.8, 'drop')
            return ('sad', 3.0, None)
        if emotes and now >= self.next_emote:
            self.next_emote = now + self.rng.uniform(22.0, 55.0)
            choices = [e for e in self.EMOTES if e[0] != self.last]
            st, dur = self.rng.choice(choices)
            self.last = st
            return (st, dur, None)
        return None
