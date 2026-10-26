======================================================================
  LEDPET V1.0  -  made by THEGEM
  a desktop pet widget for Windows - round LED display + dot-matrix
  clock + Nothing OS style home frame
======================================================================

WHAT IT IS
----------
  LEDPET is a little desktop pet for Windows: a round LED panel with
  a living dot-matrix face that sits on your screen, follows your
  mouse with its eyes and reacts to your keyboard shortcuts.  It
  lives inside a Nothing OS style home frame with a real dot-matrix
  clock, a brand header with the pet's name and small status cells.

  - 21 face expressions, each with its own system-wide shortcut
  - 11 body shapes, 12 fill styles, 11 dot shapes, 7 ready themes
  - solid / rainbow / gradient / bass-reactive light modes
  - full eye studio (cornea + iris + pupil, each its own shape/color)
  - a style library: save your look as a style file, share it, and
    apply any style with one click (20 ready-made styles included)
  - built-in WASAPI audio engine (equalizer ring, bass reactions) -
    nothing to install, the mic reactions are OFF by default
  - a birth animation: the pet hatches out of the happy dot
  - light on the PC: the heavy glow work runs in an optimized small
    buffer, the frame rate eases down before the machine feels it,
    and quality auto-drops a step on slower systems


REQUIREMENTS
------------
  - Windows 10 / 11
  - Python 3.8 or newer  (https://www.python.org/downloads/)
    During the Python setup, tick "Add python.exe to PATH".
  - Pillow + numpy (installed automatically on the first start)


QUICK START
-----------
  1. Unzip everything into one folder (keep all files together).
  2. Double-click  run.bat.
     The launcher finds Python, installs the missing libraries with
     live progress and starts the pet - all details land in
     launcher_log.txt next to run.bat.
  3. Only one LEDPET may run at a time.  Starting a second copy
     shows a message and exits - close the first one instead.
  4. To quit: right-click the pet -> Quit.


FIRST RUN - THE NAME AND THE BIRTH
----------------------------------
  The very first time LEDPET starts, a small frame appears exactly
  in the middle of the screen - a mini version of the pet's own home
  frame (same dark glass, same rim, same LED dot font).  A happy LED
  dot wiggles above the words GIVE ME A NAME.

  Type a name (up to 12 letters - only glyphs the LED font can show)
  and press DONE (the round button, or just Enter).  Then the pet is
  BORN, not just spawned:

  - the happy dot freezes at its centre and becomes the egg - its
    heartbeat accelerates, it squints and shivers, LED rings ripple
    out of it and a white core charges up inside it;
  - at the burst a short white flash and an LED shockwave break the
    shell, and the newborn pops out with a springy jelly grow;
  - the naming frame blooms into the real home frame, the pet docks
    in its slot with a little spark kiss and a happy hop.

  The name replaces the LED PET brand mark in the home header.  The
  pet starts in its most default state: a happy circle with two eyes
  that follows your mouse (cheeks / mouth can be switched on any
  time in Settings -> Face; they are OFF by default).

  Changed your mind?  Settings -> Behavior -> "Reset name" is a FULL
  FACTORY RESET: everything goes back to the shipped defaults (the
  name AND all settings), the pet hides and the naming frame appears
  again - with the birth animation.


THE PET
-------
  - It blinks, looks at your mouse and hops in place.
  - LEFT-click it: the light color cycles (palette -> rainbow ->
    bass reactive).  A little ripple + sparkles celebrate the click.
  - RIGHT-click it: the menu - light color, size, body shape,
    expressions, home frame on/off, follow mode, settings, quit.
  - DRAG it anywhere; "Follow me / Go home" toggles mouse-following.
  - Ctrl+right-drag the home frame to move it; it can also dock to
    a screen edge.


THE HOME FRAME
--------------
  - A real dot-matrix clock (12/24 h, optional seconds).
  - The header shows the pet's name (or LED PET when unnamed).
  - Small status cells: needs (food / water / fun), away state,
    sound test, greeting texts.


SETTINGS
--------
  Right-click the pet -> "Advanced settings..." (or the menu's
  shortcuts entry).  The window is freely resizable and remembers
  its last size and position.  Seven tabs:

  - Colors:    7 ready themes, LED color, all body panel colors,
               outline, cheek + clock colors, true-black body fill.
  - Effects:   glow, equalizer ring, matrix rain, ripples, sparks,
               fireflies, heartbeat, clock options, quality.
  - Audio:     system-audio equalizer + microphone reactions
               (BOTH OFF by default - switch on what you want),
               sensitivity, smoothing, EQ strength.
  - Behavior:  following, auto-dance, idle timing, needs decay,
               "Reset name" (full factory reset).
  - Body:      11 shapes, 12 fill styles, 11 dot shapes, deep-dark
               unlit grid, bubble motion.
  - Face:      the eye studio (cornea / iris / pupil: counts, sizes,
               shapes, colors), mouth, cheeks, pupil glint.
  - Shortcuts: one row per expression - record any key combination
               (or click a single F1-F12 / Num0-Num9 button), clear,
               reset all, master switch, live engine status.
  - Styles:    the style library (see the next section).


KEYBOARD SHORTCUTS
------------------
  Every one of the 21 expressions has a global, system-wide shortcut
  that works while you are inside any program.  Defaults:

  - Alt+0            = back to the normal face (instant reset)
  - Alt+1 .. Alt+6   = Happy, Wink, Surprised, Love, Pout, Dizzy
  - Ctrl+Alt+1 .. 0  = Sad, Cry, Angry, Laugh, Cool, Star eyes,
                       Thinking, Sleepy, Shy, Kiss
  - Shift+Alt+1 .. 4 = Smirk, Eating, Drinking, Hungry

  "Sticky" mode (Shortcuts tab, on by default): a shortcut HOLDS its
  expression until the next shortcut - even with music playing.
  If another program owns a combination, the engine's passive
  fallback hook still fires the pet (without blocking the other
  program); the Shortcuts tab shows the live engine status.


STYLES - SAVE, SHARE AND SWITCH LOOKS
-------------------------------------
  A style is a small file that holds a complete look of the pet: the
  LED colors, the size, the body shape, the fill style, the dot
  shape, the eyes, the effects and the clock options.  Styles live
  in one folder and the Styles tab of the settings lists them all:

  - CLICK a style in the list and it is applied immediately.
  - "Save current look..." stores everything you see right now as a
    new style file (you pick the name).
  - "Import a file..." copies any LEDPet style file from anywhere
    into the library and applies it.
  - "Open styles folder" shows the folder itself - you can copy,
    share or back up the .json files freely.  Any style files found
    in a Styles folder next to the app files are picked up too.
  - "Delete selected" removes a style from the library.

  A style NEVER touches your pet's identity: the name, the window
  position, the sound switches, the keyboard shortcuts and the needs
  stay exactly as they are.  20 ready-made styles ship with the app
  (Lava, Ocean, Vaporwave, Matrix, Bubblegum, Retro Panel...).


AUDIO REACTIONS
---------------
  The built-in WASAPI engine captures the system audio directly -
  no extra libraries, no admin rights.  If it is unavailable the
  launcher falls back to the SoundCard library automatically.
  Out of the box the equalizer and the microphone are OFF: the pet
  is a calm LED circle that just follows your mouse.  Switch them
  on in Settings -> Audio whenever you want the reactive modes.


FILES
-----
  run.bat           the start script (double-click this)
  launcher.py       checks + auto-installs libraries + starts the pet
  pet_windows.py    the pet: window, states, audio, birth morph
  name_window.py    the naming frame + the hatching scene
  ledpet_core.py    config, face engine, shapes, effects
  ledpet_render.py  the LED renderer (styles, dots, glow)
  home_window.py    the home frame window
  home_render.py    the home frame renderer
  home_logic.py     clock, needs, greetings
  settings_ui.py    the settings window (8 tabs)
  hotkeys_win.py    the global shortcut engine (Windows API)
  wasapi_audio.py   the built-in WASAPI loopback/mic engine
  Styles\           ready-made style files (the look library seeds)
  palette.png       theme palette
  preview.png       preview image

  Config and logs live OUTSIDE the program folder:
  - %APPDATA%\LEDPet\config.json   (name, colors, size, shortcuts...)
  - %APPDATA%\LEDPet\error.log     (runtime errors)


TROUBLESHOOTING
---------------
  - Nothing starts / "Python was not found":
    install Python, tick "Add python.exe to PATH", run run.bat again.
  - A library failed to install:
    details are in launcher_log.txt (next to run.bat).
  - The pet behaves strangely or a window is missing:
    details are in %APPDATA%\LEDPet\error.log.
  - Shortcuts do not fire:
    open Settings -> Shortcuts and check the engine status line;
    another copy of LEDPET must not be running.
  - Reset name (Settings -> Behavior) is the full factory reset -
    it brings back the naming frame and the birth animation.

  When reporting a problem, please attach:
  launcher_log.txt  and  %APPDATA%\LEDPet\error.log

  LEDPET V1.0 - made by THEGEM. Thank you for running the pet!
