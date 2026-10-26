# -*- coding: utf-8 -*-
# =====================================================================
#  LEDPet - the 'home' window (v13)
#     a second layered window (below the pet) with a Nothing OS look:
#       - the pet 'lives' inside (docked); dragging the pet or the frame moves both
#       - FOLLOW button: the pet leaves the frame and follows the mouse; off = returns
#       - FOOD / WATER: drag the button onto the pet (or just click it)
#       - PLAY: three tiny games (CATCH / TAP / MEMORY) on the dot display
#     every error is guarded: if something breaks only the frame turns off and the pet stays fine.
# =====================================================================
import math
import random
import time

import tkinter as tk

from PIL import Image

import ledpet_core as C
import home_logic as HL
import home_render as HR


def _clamp(v, a, b):
    return a if v < a else (b if v > b else v)


class HomeFrame:
    TICK_ACTIVE = 1.0 / 20.0       # while animating / interacting
    TICK_IDLE = 1.0 / 4.0          # while resting

    @property
    def cfg(self):
        return self.pet.cfg

    def __init__(self, pet, veil=False, at=None):
        self.pet = pet
        self.root = pet.root
        self.closed = False
        self.top = None
        self.layer = None
        self.hwnd = None
        self.err = 0
        # LEDPET_V1_MORPH: veil=True -> the frame builds itself but stays
        # hidden while the naming dialog plays the grow animation; the
        # morph's last frame IS this frame's first one, so the hand-over
        # is pixel-seamless.  at=(x, y) places the frame exactly there
        # (the morph's final rect) instead of deriving it from the config.
        self.veiled = bool(veil)

        now = time.time()
        self.needs = HL.Needs(self.cfg.get('n_food', 0.8), self.cfg.get('n_water', 0.8),
                              self.cfg.get('n_fun', 0.7))
        ts = float(self.cfg.get('n_ts', 0.0) or 0.0)
        if ts > 0:
            self.needs.offline(now - ts)
        self.display = HL.Display()
        self.feeder = HL.Feeder()
        self.person = HL.Personality(now)
        self.game = None
        self.menu_mode = False
        self.menu_zones = []
        self.menu_idx = 0
        self.docked = True
        self.hover = None
        self.pressed = None
        self.cap = None
        self.hx, self.hy = 0.0, 0.0
        self._pos_sent = None
        self._last_render = 0.0
        self._last_place = 0.0
        self._last_persist = now
        self._dirty = True
        self._pm = None
        self._near_face = False
        self._next_ambient = now + 2.5
        self._prev_follow = self.following()
        self._intro_done = False
        _nm = (getattr(pet, 'name', '') or '').strip()
        # a personal welcome right after the naming (the morph's intro
        # bitmap shows exactly the same cells -> seamless hand-over)
        self.display.say(('HI ' + _nm) if _nm else 'HELLO!', now, 2.6)

        self._make_renderer()
        self._create_window()
        self.snap_initial(at=at)

    # ------------------------------ build ------------------------------
    def following(self):
        return self.cfg.get('track') in ('chase_slow', 'chase_fast')

    def _make_renderer(self):
        s = self.pet.ren.W / float(C.BW)
        ss = 1 if self.cfg.get('quality') == 'low' else 2
        self.ren = HR.HomeRenderer(s, ss=ss)

    def _create_window(self):
        pet = self.pet
        top = tk.Toplevel(self.root)
        top.title('LEDPET V1.0 - Home')
        top.overrideredirect(True)
        top.config(bg='black')
        top.geometry('%dx%d+%d+%d' % (self.ren.W, self.ren.H, 40, 40))
        try:
            top.attributes('-topmost', bool(self.cfg.get('topmost', True)))
        except Exception:
            pass
        top.update()
        self.top = top
        self.layer, self.hwnd = pet.make_layer_for(top, self.ren.W, self.ren.H)
        if self.veiled:
            # LEDPET_V1_MORPH: the window exists but must be INVISIBLE
            # until the unveil - push one fully transparent frame so the
            # plain black Tk surface never flashes over the morph
            try:
                self.layer.present(Image.new('RGBA', (self.ren.W, self.ren.H),
                                             (0, 0, 0, 0)), 0, 0)
            except Exception:
                pass

    def snap_initial(self, at=None):
        """first placement: frame positioned so the pet sits exactly in its
        slot; at=(x, y) forces the top-left corner (the v1.0 morph uses it
        to continue EXACTLY where the grow animation ended)"""
        pet = self.pet
        oy = int(round(HR.PET_OFF[1] * self.ren.kf))
        try:
            sw = self.root.winfo_screenwidth()
            sh = self.root.winfo_screenheight()
        except Exception:
            sw, sh = 1920, 1080
        if at is not None:
            hx, hy = int(at[0]), int(at[1])
        elif self.cfg.get('x', -1) < 0 or self.cfg.get('y', -1) < 0:
            hx = (sw - self.ren.W) // 2
            hy = (sh - self.ren.H) // 2
        else:
            hx, hy = pet.wx, pet.wy - oy
        hx = max(-self.ren.W + 80, min(sw - 80, hx))
        hy = max(0, min(sh - 120, hy))
        self.hx, self.hy = float(hx), float(hy)
        if not self.following():
            pet.wx, pet.wy = self.slot()
            pet.fx, pet.fy = float(pet.wx), float(pet.wy)
            self.docked = True
        else:
            self.docked = False
        self.place()

    # ----------------------------- geometry -----------------------------
    def slot(self):
        oy = int(round(HR.PET_OFF[1] * self.ren.kf))
        return int(round(self.hx)), int(round(self.hy)) + oy

    def to_units(self, sx, sy):
        k = self.ren.kf
        return (sx - self.hx) / k, (sy - self.hy) / k

    def face_center_u(self):
        pet = self.pet
        k = self.ren.kf
        cx, cy = C.cell_xy(C.HALF, C.HALF)
        return (pet.wx - self.hx) / k + cx, (pet.wy - self.hy) / k + cy

    def mouth_design(self):
        pet = self.pet
        return C.cell_xy(C.HALF + pet.lx * 0.45, C.HALF + C.MY + pet.ly * 0.35)

    def mouth_u(self):
        pet = self.pet
        k = self.ren.kf
        mx, my = self.mouth_design()
        return (pet.wx - self.hx) / k + mx, (pet.wy - self.hy) / k + my

    # ------------------------- syncing with the pet -------------------------
    def owns_event(self, e):
        try:
            return self.top is not None and e.widget.winfo_toplevel() is self.top
        except Exception:
            return False

    def capturing(self):
        return self.cap is not None

    def apply_topmost(self):
        on = bool(self.cfg.get('topmost', True))
        try:
            self.top.attributes('-topmost', on)
        except Exception:
            pass
        # Win32 fallback: Tk's -topmost alone is not always reliable for
        # layered windows (this is the "Always on top" menu switch)
        try:
            self.pet.win_set_topmost(self.hwnd, on)
        except Exception:
            pass
        self.place(force=True)

    def place(self, force=False):
        """keeps the frame right below the pet window"""
        now = time.time()
        if not force and now - self._last_place < 1.5:
            return
        self._last_place = now
        try:
            self.pet.place_below(self.hwnd)
        except Exception:
            pass

    def on_pet_resized(self):
        """the pet was resized -> rebuild the frame keeping its top-left corner"""
        self._make_renderer()
        W, H = self.ren.W, self.ren.H
        try:
            self.top.geometry('%dx%d+%d+%d' % (W, H, int(self.hx), int(self.hy)))
        except Exception:
            pass
        try:
            self.layer.resize(W, H)             # TkLayer only
        except Exception:
            pass
        pet = self.pet
        if self.docked:
            pet.wx, pet.wy = self.slot()
            pet.fx, pet.fy = float(pet.wx), float(pet.wy)
        self._dirty = True
        self._pos_sent = None

    def drive_pet(self, dt, have_ptr, mx, my, fcx, fcy, track):
        """pet position: docked in the frame / chasing the mouse / flying home"""
        pet = self.pet
        follow = track in ('chase_slow', 'chase_fast')
        if follow:
            if self.docked:
                self.docked = False
                self._dirty = True
            if have_ptr and not pet.press:
                pet.chase(dt, mx, my, fcx, fcy, 1.6 if track == 'chase_slow' else 4.8)
            return
        if self.docked:
            self.hx, self.hy = float(pet.wx), float(pet.wy - int(round(HR.PET_OFF[1] * self.ren.kf)))
            return
        if pet.press:                           # mid pet-drag: do not interfere
            return
        tx, ty = self.slot()
        k = 1.0 - math.exp(-7.0 * dt)
        pet.fx += (tx - pet.fx) * k
        pet.fy += (ty - pet.fy) * k
        pet.wx, pet.wy = int(round(pet.fx)), int(round(pet.fy))
        if math.hypot(tx - pet.fx, ty - pet.fy) < 2.0:
            pet.wx, pet.wy = tx, ty
            pet.fx, pet.fy = float(tx), float(ty)
            self.docked = True
            self._dirty = True

    # ---------------------------- mouse input ----------------------------
    def _blocked(self):
        """when must food/games be refused? (shows a message and returns True)"""
        now = time.time()
        if not self.docked:
            self.display.say('PET IS OUT', now, 2.0)
            return True
        if self.pet.mode == 'sleep':
            self.display.say('SHH... ZZZ', now, 2.0)
            return True
        return False

    def press(self, e):
        pet = self.pet
        if pet.menu_open:
            return
        now = time.time()
        ux, uy = self.to_units(e.x_root, e.y_root)
        name = HR.button_at(ux, uy)
        self._dirty = True
        if name:
            self.pressed = name
            self.cap = {'kind': 'btn', 'name': name, 'x0': e.x_root, 'y0': e.y_root, 'moved': False}
            if name in ('food', 'water') and not self.game and not self._blocked():
                bx, by = HR.button_center(name)
                self.feeder.start_drag(name, ux, uy)
                self.cap['item'] = True
            return
        if HR.in_display(ux, uy):
            c, r = HR.disp_cell_at(ux, uy)
            # the display area also DRAGS the frame; the tap (game click /
            # menu / prev-next) fires on release only if the mouse didn't move
            self.cap = {'kind': 'disp', 'c': c, 'r': r, 'now': now,
                        'x0': e.x_root, 'y0': e.y_root,
                        'hx0': self.hx, 'hy0': self.hy, 'moved': False}
            return
        self.cap = {'kind': 'drag', 'x0': e.x_root, 'y0': e.y_root,
                    'hx0': self.hx, 'hy0': self.hy, 'moved': False}

    def drag(self, e):
        cap = self.cap
        if cap is None:
            return
        self._dirty = True
        if cap['kind'] == 'btn':
            if math.hypot(e.x_root - cap['x0'], e.y_root - cap['y0']) > 10:
                cap['moved'] = True
            if cap.get('item'):
                ux, uy = self.to_units(e.x_root, e.y_root)
                self.feeder.drag_to(ux, uy)
        elif cap['kind'] == 'drag':
            dx, dy = e.x_root - cap['x0'], e.y_root - cap['y0']
            if not cap['moved'] and dx * dx + dy * dy > 16:
                cap['moved'] = True
            if cap['moved']:
                self.hx, self.hy = cap['hx0'] + dx, cap['hy0'] + dy
                if self.docked:
                    pet = self.pet
                    pet.wx, pet.wy = self.slot()
                    pet.fx, pet.fy = float(pet.wx), float(pet.wy)
        elif cap['kind'] == 'disp':
            # dragging on the display moves the frame too
            dx, dy = e.x_root - cap['x0'], e.y_root - cap['y0']
            if not cap['moved'] and dx * dx + dy * dy > 16:
                cap['moved'] = True
            if cap['moved']:
                self.hx, self.hy = cap['hx0'] + dx, cap['hy0'] + dy
                if self.docked:
                    pet = self.pet
                    pet.wx, pet.wy = self.slot()
                    pet.fx, pet.fy = float(pet.wx), float(pet.wy)

    def abort_drag(self):
        """force-finish an open drag without an event (stuck-drag watchdog).
        Clears the capture, cancels a dragged food/water item and saves the
        position if the frame was actually moved."""
        cap = self.cap
        self.cap = None
        self.pressed = None
        self._dirty = True
        if cap is None:
            return
        try:
            if cap.get('item'):
                self.feeder.cancel_drag()
            if cap.get('moved') and cap.get('kind') in ('drag', 'disp'):
                self.pet.save_now()
        except Exception:
            pass

    def release(self, e):
        cap, self.cap = self.cap, None
        self.pressed = None
        self._dirty = True
        if cap is None:
            return
        now = time.time()
        if cap['kind'] == 'drag':
            if cap['moved']:
                self.pet.save_now()
            return
        if cap['kind'] == 'disp':
            # tap (no drag) = game click / menu navigation, exactly as before
            if not cap['moved']:
                self._display_click(cap['c'], cap['r'], now)
            else:
                self.pet.save_now()
            return
        if cap['kind'] != 'btn':
            return
        name = cap['name']
        ux, uy = self.to_units(e.x_root, e.y_root)
        if cap.get('item'):
            kind = name
            refuse = self.needs.v[kind] > 0.92
            if not cap['moved']:
                self.feeder.cancel_drag()
                bx, by = HR.button_center(name)
                self.feeder.quick(kind, bx, by, refuse)
            else:
                fc = self.face_center_u()
                self.feeder.drop(self.mouth_u(), C.R + 45.0, refuse, center=fc)
            return
        if HR.button_at(ux, uy) == name:
            self._activate(name, now)

    def _activate(self, name, now):
        pet = self.pet
        if name == 'follow':
            pet.toggle_follow()
            self.display.say('FOLLOWING YOU' if self.following() else 'WELCOME HOME', now, 2.4)
        elif name == 'play':
            if self.game is not None:
                self.game = None
                self.display.say('BYE', now, 1.2)
            elif self.menu_mode:
                self.menu_mode = False
                self.display.say('', now, 0.1)
            elif not self._blocked():
                self.menu_mode = True
                self.display.say('', now, 0.1)
        elif name in ('food', 'water'):
            pass

    def _display_click(self, c, r, now):
        if self.game is not None:
            self.game.click(c, r)
            return
        if self.menu_mode:
            for (nm, x0, x1) in (self.menu_zones or HL.menu_cells()[1]):
                if x0 <= c < x1:
                    if nm == 'prev':
                        self.menu_idx = (self.menu_idx - 1) % len(HL.GAMES)
                    elif nm == 'next':
                        self.menu_idx = (self.menu_idx + 1) % len(HL.GAMES)
                    else:
                        self._start_game(self.menu_idx, now)
                    return

    def _start_game(self, idx, now):
        try:
            self.game = HL.GAMES[idx][1](random.Random())
        except Exception:
            self.game = None
            return
        self.menu_mode = False
        self.person.poke(now)
        self.pet.set_mode('star', 1.2)
        self.display.say('', now, 0.1)

    # ------------------------------ logic ------------------------------
    def _pointer_units(self):
        px, py = self.pet.last_ptr
        return self.to_units(px, py)

    def _react(self, now):
        """game and food events -> the pet's face reaction"""
        pet = self.pet
        if self.game is not None:
            for ev in self.game.pop_events():
                if ev == 'good':
                    self.needs.add('fun', 0.03)
                    pet.set_mode('happy', 0.45)
                    pet.kick(0.5)
                elif ev == 'bad':
                    pet.set_mode('sad', 0.8)
                elif ev == 'win':
                    pet.set_mode('laugh', 1.1)
                    pet.kick(1.0)
                elif ev == 'lose':
                    pet.set_mode('cry', 1.8)
            if self.game.over:
                sc = self.game.score
                self.needs.add('fun', 0.10 + 0.01 * min(sc, 20))
                self.display.say('SCORE %d' % sc, now, 3.2)
                self.game = None
        mx, my = self.mouth_design()
        for ev in self.feeder.pop_events():
            kind = ev[0]
            fk = ev[1]
            if kind == 'eat_start':
                pet.face_icon = None
                pet.set_mode('eat' if fk == 'food' else 'drink', 1.9)
                self.person.poke(now)
            elif kind == 'bite':
                self.needs.add(fk, HL.Feeder.PER_BITE[fk])
                pet.kick(0.7)
                col = HR.FOOD_RGB if fk == 'food' else HR.WATER_RGB
                try:
                    pet.spawn_sparks(5, origin=(mx, my), col=col)
                except Exception:
                    pass
            elif kind == 'eat_done':
                self.needs.add('fun', 0.03)
                pet.set_mode('kiss' if random.random() < 0.3 else 'happy', 1.6)
                self.display.say('YUM!' if fk == 'food' else 'AHH!', now, 1.8)
            elif kind == 'refuse':
                pet.set_mode('frown', 1.4)
                self.display.say('I AM FULL' if fk == 'food' else 'NO THANKS', now, 2.0)

    def _display_cells(self, now, pointer_u):
        if self.game is not None:
            return self.game.cells()
        if self.menu_mode:
            hov = None
            if HR.in_display(*pointer_u):
                c, r = HR.disp_cell_at(*pointer_u)
                zones = self.menu_zones or HL.menu_cells()[1]
                for (nm, x0, x1) in zones:
                    if x0 <= c < x1:
                        hov = nm
            cells, zones = HL.menu_cells(self.menu_idx, hov)
            self.menu_zones = zones
            return cells
        return self.display.cells(now)

    def _ambient(self, now):
        low = self.needs.lowest()
        if low == 'food':
            return 'FEED ME!'
        if low == 'water':
            return 'I AM THIRSTY'
        if low == 'fun':
            return 'PLAY WITH ME'
        return random.choice(('HI!', 'HELLO', 'LED PET', 'READY', 'NICE DAY', time.strftime('%H:%M')))

    def tick(self, now, dt):
        pet = self.pet
        cfg = self.cfg
        if self.closed:
            return
        self.needs.update(dt)
        if self.docked and self.cap is None:
            self.hx, self.hy = float(pet.wx), float(pet.wy - int(round(HR.PET_OFF[1] * self.ren.kf)))

        # --- mouse following toggled on/off ---
        fol = self.following()
        if fol != self._prev_follow:
            self._prev_follow = fol
            self._dirty = True
            if self.game is not None:
                self.game = None
            self.menu_mode = False

        pu = self._pointer_units()
        # --- hover ---
        hv = HR.button_at(*pu) if (self.cap is None and not pet.menu_open) else None
        if hv != self.hover:
            self.hover = hv
            self._dirty = True

        # --- mouse for the game (basket) ---
        mouse = None
        if self.game is not None:
            c, r = HR.disp_cell_at(_clamp(pu[0], HR.DP['x0'], HR.DP['x1']), _clamp(pu[1], HR.DP['y0'], HR.DP['y1']))
            mouse = (c, r)
            self.game.update(dt, mouse)

        # --- food ---
        self.feeder.update(dt, self.mouth_u(), HR.BTN_Y + HR.BTN_R + 24.0, 1.0)
        # the pet goes 'oh!' when an item is dragged near its face
        it = self.feeder.dragging()
        near = False
        if it is not None:
            fc = self.face_center_u()
            near = math.hypot(it.x - fc[0], it.y - fc[1]) <= C.R + 45.0
        if near and not self._near_face and pet.mode != 'sleep':
            pet.set_mode('surprised', 0.5)
        self._near_face = near

        self._react(now)

        # --- display messages ---
        if self.game is None and not self.menu_mode and self.display.idle(now) and now >= self._next_ambient:
            self._next_ambient = now + random.uniform(9.0, 15.0)
            self.display.say(self._ambient(now), now, 2.4)

        # --- personality: random emotes + hungry/thirsty ---
        idle = (pet.mode == 'idle' or now >= pet.mode_until) and pet.mode != 'sleep' \
            and self.game is None and not self.feeder.busy()
        if idle and self.docked and not self.feeder.dragging():
            res = self.person.tick(now, True, self.needs, bool(cfg.get('idle_emotes', True)))
            # v17.9: emote_rate scales how often the random emotes fire
            # (rescaled ONCE per newly scheduled interval, not every frame)
            _er = max(0.0, float(cfg.get('emote_rate', 1.0)))
            if _er > 0.01 and getattr(self, '_er_last', None) != self.person.next_emote:
                self._er_last = self.person.next_emote
                if _er != 1.0 and self.person.next_emote > now:
                    self.person.next_emote = now + (self.person.next_emote - now) / _er
            if res is not None:
                st, dur, icon = res
                pet.face_icon = icon
                pet.set_mode(st, dur)
                pet.kick(0.6)

        # --- saving the needs ---
        if now - self._last_persist > 20.0:
            self._last_persist = now
            self.persist()

        # --- render / present ---
        active = (self.game is not None or self.menu_mode or self.feeder.items or self.cap is not None
                  or (self.display.scroll and not self.display.idle(now)))
        interval = self.TICK_ACTIVE if active else self.TICK_IDLE
        if self._dirty or now - self._last_render >= interval:
            self._render(now, pu)
        pos = (int(round(self.hx)), int(round(self.hy)))
        if self._pm is not None and not self.veiled \
                and (pos != self._pos_sent or self._last_render == now):
            self._present(pos)
        self.place()

    def _render(self, now, pu):
        pet = self.pet
        self._last_render = now
        self._dirty = False
        cells = self._display_cells(now, pu)
        asleep = pet.mode == 'sleep'
        disabled = set()
        if not self.docked or asleep:
            disabled.update(('food', 'water', 'play'))
        elif self.game is not None:
            disabled.update(('food', 'water'))
        active = set()
        if self.following():
            active.add('follow')
        if self.game is not None or self.menu_mode:
            active.add('play')
        items = []
        for it in self.feeder.items:
            items.append((it.kind, it.x, it.y, it.size * (1.0 if it.state != 'drag' else 1.15), it.alpha))
        S = dict(t=now - pet.t0, accent=getattr(pet, '_accent_now', (246, 246, 246)),
                 brand=(getattr(pet, 'name', '') or 'LED PET').upper(),
                 needs=self.needs.v, cells=cells, items=items, away=not self.docked,
                 hover=self.hover, pressed=self.pressed, disabled=tuple(sorted(disabled)),
                 active=tuple(sorted(active)))
        self._pm = self.ren.frame(S)

    def _present(self, pos):
        ok = False
        try:
            ok = self.layer.present(self._pm, pos[0], pos[1])
        except Exception:
            ok = False
        self._pos_sent = pos if ok else None

    def unveil(self):
        """LEDPET_V1_MORPH: the grow animation is over - the frame takes
        over the screen exactly where the morph's last frame ended"""
        self.veiled = False
        self._pos_sent = None
        self._dirty = True

    # --------------------------- save / close ---------------------------
    def persist(self):
        try:
            self.cfg['n_food'] = float(self.needs.v['food'])
            self.cfg['n_water'] = float(self.needs.v['water'])
            self.cfg['n_fun'] = float(self.needs.v['fun'])
            self.cfg['n_ts'] = float(time.time())
        except Exception:
            pass

    def close(self):
        self.closed = True
        self.persist()
        try:
            self.layer.close()
        except Exception:
            pass
        try:
            self.top.destroy()
        except Exception:
            pass
        self.top = None
