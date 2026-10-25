"""Popups the game shows the human player, which Lua can't read: screenshot, read, decide.

The bridge writes `popup-<id>.req` in the turn root when a message popup opens and holds the
popup until `popup-<id>.done` appears. This module, polled by the turn loop:
- screenshots the game window (X11: xdotool + ImageMagick `import`);
- has the screenshot read by a vision model (Claude Haiku, which transcribed a marriage offer
  live in about 20 s: title, text, stats counted from the stars, traits, the question);
- for a plain message, releases the popup straight after the screenshot and keeps the reading
  for the ruler's next report;
- for a decision, asks the ruler, clicks accept or decline in the window, and keeps the answer
  for the report. A decision is a marriage or adoption offer (with the man's real age, stats
  and traits from the game event), or any popup whose screenshot shows a green check with a red
  X beside it: the ruler decides from the reading alone, whatever the game is asking.
"""

import json
import logging
import re
import shutil
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image

from parley import pause
from parley.bridge import atomic_write
from parley.seats.base import SeatError, SeatLimit, empty_workdir, safe_env

log = logging.getLogger("parley.popups")

WINDOW_NAME = "^Medieval 2$"
ORPHAN_AFTER = 240  # seconds: past the bridge's longest wait (DECIDE_WAIT, 180)
PAUSED = object()  # _ask's answer when the ruler's seat hit a usage limit
OFFER_LOOKS = 25  # an offer whose scroll is hidden: looks, 5 s apart, before giving up
# accept and decline on the marriage scroll, as fractions of the game window (measured live on a
# 1600x900 window: 761,612 and 839,612); the game's UI scales with the window
BUTTONS = {"accept": (761 / 1600, 612 / 900), "decline": (839 / 1600, 612 / 900)}
READ_PROMPT = ("Read popup.png. It is a screenshot of Medieval II: Total War. Transcribe the popup "
               "scroll in the middle exactly: its title, every line of text, any stats (count the "
               "filled stars or icons out of 10 for each) and traits. Then say in one line what "
               "decision it asks for, if any. Plain text only. Ignore the dark \"Parley\" window at "
               "the top: it is our own overlay, not the game's. If no game scroll is open, answer "
               "only: NO SCROLL.")


def _window() -> str:
    out = subprocess.run(["xdotool", "search", "--name", WINDOW_NAME], capture_output=True, text=True, timeout=10)
    ids = out.stdout.split()
    if not ids:
        raise RuntimeError("game window not found")
    return ids[0]


def _clear_pointer(wid: str) -> None:
    """Move the pointer off the scroll before a screenshot: a hovered button changes colour and
    isn't found (live: the cursor rested on a guild offer's check, ten looks found no buttons, and
    the turn stalled five minutes). Moved only when it sits over the scroll band."""
    try:
        geo = dict(line.split("=", 1) for line in _xdo("getwindowgeometry", "--shell", wid).split())
        mouse = dict(line.split("=", 1) for line in _xdo("getmouselocation", "--shell").split())
        x0, y0, w, h = (int(geo[k]) for k in ("X", "Y", "WIDTH", "HEIGHT"))
        fx, fy = (int(mouse["X"]) - x0) / w, (int(mouse["Y"]) - y0) / h
        if .25 <= fx <= .75 and .25 <= fy <= .8:
            _xdo("mousemove", "--window", wid, str(int(w * .9)), str(int(h * .2)))
            time.sleep(.2)
    except Exception as e:  # no pointer move is no worse than before
        log.warning("moving the pointer off the scroll failed: %s", e)


def screenshot(path: Path) -> None:
    wid = _window()
    _clear_pointer(wid)
    subprocess.run(["import", "-window", wid, str(path)], check=True, capture_output=True, timeout=20)


def read(path: Path, model: str = "haiku", timeout: float = 120) -> str:
    workdir = empty_workdir()
    try:
        shutil.copy(path, Path(workdir) / "popup.png")
        proc = subprocess.run(["claude", "-p", READ_PROMPT, "--model", model, "--tools", "Read",
                               "--strict-mcp-config", "--no-session-persistence", "--output-format", "text"],
                              capture_output=True, text=True, timeout=timeout, env=safe_env(), cwd=workdir)
        return proc.stdout.strip()
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


# where scroll buttons are looked for, top to bottom: the HUD's top edge (the Army, Town and
# Agents tabs, y ~680+) has green of its own, and live it outweighed an adoption's check, so the
# offer went undecided and blocked End Turn; every button measured sat at y 617-628 of 900
BAND_BOTTOM = .75


def _green(p) -> bool:
    return p[1] > 140 and p[1] > p[0] + 50 and p[1] > p[2] + 50


def _red(p) -> bool:
    # the X under the mouse turns pale pink (live: about 200,140,140); parchment is R-G ~20
    return p[0] > 140 and p[0] >= p[1] + 40 and p[0] >= p[2] + 40


def _blob(points, w: int) -> list | None:
    """The button-sized blob around the densest spot (live: a mark is about 30 px on a 1600-wide
    window), if it holds most of the points: a few strays are dropped, a spread (grass, banners,
    heraldry) is no button."""
    if len(points) < 20:
        return None
    cell = max(1, int(w * 20 / 1600))
    counts: dict = {}
    for x, y in points:
        counts[(x // cell, y // cell)] = counts.get((x // cell, y // cell), 0) + 1
    cx, cy = max(counts, key=counts.get)
    reach = w * 30 / 1600
    blob = [(x, y) for x, y in points
            if abs(x - (cx + .5) * cell) <= reach and abs(y - (cy + .5) * cell) <= reach]
    return blob if len(blob) >= 20 and len(blob) >= .8 * len(points) else None


def find_vote_buttons(png: Path) -> list[tuple[float, float]]:
    """The papal election's Vote buttons, top to bottom (one per candidate), as fractions of the
    window. Live (1600x900): green-arrowed buttons at x ~1080, y ~345/455/565; the green
    shields among the undecided votes sit further left, outside the band searched."""
    im = Image.open(png).convert("RGB")
    w, h = im.size
    px = im.load()
    pts = sorted((y, x) for y in range(int(h * .2), int(h * .75)) for x in range(int(w * .62), int(w * .72))
                 if _green(px[x, y]))
    groups, gap = [], 30 * h / 900
    for y, x in pts:
        if groups and y - groups[-1][-1][0] <= gap:
            groups[-1].append((y, x))
        else:
            groups.append([(y, x)])
    return [(sum(x for _, x in g) / len(g) / w, sum(y for y, _ in g) / len(g) / h)
            for g in groups if len(g) >= 20]


def vote_prompt(persona: str, faction: str, n: int, reading: str) -> str:
    return f"""{persona.strip()}

You rule {faction}. The Pope is dead, and the College of Cardinals is electing his successor NOW. Your cardinals vote as you direct.

WHAT THE GAME SHOWS (read from the screen; candidates top to bottom)
{reading or "(the screen could not be read)"}

WEIGH IT
- A Pope friendly to your realm, or from a faction you favour, spares you excommunication and may bless your wars; one from a rival's lands may turn Rome against you.
- The frontrunner already has the most supporters; backing him wins favour if he wins, backing another may still decide a close vote.

Answer with one line starting with the number of your candidate (1 to {n}, top to bottom), then your reason in one or two plain sentences.
"""


def find_tick(png: Path) -> tuple[float, float] | None:
    """A message scroll's lone acknowledging check (no X beside it), as fractions of the window.
    Clearing such a scroll only minimizes it, and some (the papal election's notice) must be
    acknowledged for the game to go on: seen live, reopened and minimized again in a loop."""
    im = Image.open(png).convert("RGB")
    w, h = im.size
    px = im.load()
    x0, y0 = int(w * .25), int(h * .3)
    green = _blob([(x, y) for y in range(y0, int(h * BAND_BOTTOM)) for x in range(x0, int(w * .75))
                   if _green(px[x, y])], w)
    if not green:
        return None
    gx, gy = sum(x for x, _ in green) // len(green), sum(y for _, y in green) // len(green)
    return (gx / w, gy / h)


def same_scroll(a: Path, b: Path) -> bool:
    """True when two screenshots show the same scroll: the bridge hasn't cleared the last one read.
    The band leaves out the Parley overlay at the top, whose text changes (live: up to 13%)."""
    im_a, im_b = Image.open(a), Image.open(b)
    if im_a.size != im_b.size:
        return False
    w, h = im_a.size
    box = (int(w * .3), int(h * .15), int(w * .7), int(h * .85))
    ca = im_a.crop(box).convert("L").resize((64, 64))
    cb = im_b.crop(box).convert("L").resize((64, 64))
    pa, pb = list(ca.getdata()), list(cb.getdata())
    return sum(abs(x - y) for x, y in zip(pa, pb)) / len(pa) < 1.5  # two scrolls alike but for a name differ by more


def find_choice(png: Path) -> dict[str, tuple[float, float]] | None:
    """The accept check and the decline X of a decision scroll, as fractions of the window, or
    None. Live (1600x900): the check at 760,628 on an adoption, 757,617 on a marriage, with the X
    78 px to its right; a scroll's single close tick has no X beside it, so it isn't a decision.
    The search keeps to the middle of the window, where scrolls open; each mark must be one
    button-sized blob, so scattered green (grass, banners) or red (heraldry) doesn't count."""
    im = Image.open(png).convert("RGB")
    w, h = im.size
    px = im.load()
    x0, y0 = int(w * .25), int(h * .3)
    green = [(x, y) for y in range(y0, int(h * BAND_BOTTOM)) for x in range(x0, int(w * .75)) if _green(px[x, y])]
    green = _blob(green, w)
    if not green:
        return None
    gx, gy = sum(x for x, _ in green) // len(green), sum(y for _, y in green) // len(green)
    near, far, tall = int(w * 40 / 1600), int(w * 120 / 1600), int(h * 20 / 900)
    red = [(x, y) for y in range(max(0, gy - tall), min(h, gy + tall))
           for x in range(gx + near, min(w, gx + far)) if _red(px[x, y])]
    red = _blob(red, w)
    if not red:
        return None
    rx, ry = sum(x for x, _ in red) // len(red), sum(y for _, y in red) // len(red)
    return {"accept": (gx / w, gy / h), "decline": (rx / w, ry / h)}


# Minimized messages: icons stacked up the left edge, above the radar's zoom buttons. A
# minimized decision blocks End Turn unseen, so a stuck turn looks here and reopens what it
# finds. Measured live (1600x900): an icon is 73x55 from x 0, its frame's top edge a row of
# light grey (R=G=B, 100 and up) across x 8-66 with a near-black line 2-4 rows below; the picture
# inside may be grey or in colour, the frame is the same.
ICON_X = (8 / 1600, 66 / 1600)
ICON_HEIGHT = 55 / 900
ICON_ZONE = (250 / 900, 700 / 900)  # where the stack can reach, top to bottom


def find_minimized(png: Path) -> list[tuple[float, float]]:
    """Centres (fractions of the window) of the minimized-message icons, bottom first."""
    im = Image.open(png).convert("RGB")
    w, h = im.size
    px = im.load()
    xs = range(int(ICON_X[0] * w), int(ICON_X[1] * w))
    tops, y = [], int(ICON_ZONE[1] * h)
    while y > int(ICON_ZONE[0] * h):
        row = [px[x, y] for x in xs]
        dark_below = any(sum(1 for x in xs if max(px[x, y + d]) < 40) > 0.7 * len(xs) for d in (2, 3, 4))
        # (the frame's light grey dims with the scene: 109-144 seen live, 144-190 another time)
        if all(abs(r - g) <= 3 and abs(g - b) <= 3 and r >= 100 for r, g, b in row) and dark_below:
            tops.append(y)
            y -= int(ICON_HEIGHT * h) - 4  # the next icon up starts a frame above
        else:
            y -= 1
    cx = (ICON_X[0] + ICON_X[1]) / 2
    return [(cx, (t + ICON_HEIGHT * h / 2) / h) for t in tops]


# the stack's slots, bottom first: the bottom icon's centre, then one icon height up each
# (live: up to eight stacked, about 56 px apart on 900)
ICON_BOTTOM_Y = 667 / 900
ICON_PITCH = 56 / 900


def minimized_slots(png: Path) -> list[tuple[float, float]]:
    """Every slot of the minimized-message stack, bottom first ([] when there is none): the
    frame detector reliably finds the stack's top, and the stack always grows up from the
    bottom slot."""
    found = find_minimized(png)
    if not found:
        return []
    top = min(y for _, y in found)
    n = max(1, round((ICON_BOTTOM_Y - top) / ICON_PITCH) + 1)
    cx = (ICON_X[0] + ICON_X[1]) / 2
    return [(cx, ICON_BOTTOM_Y - k * ICON_PITCH) for k in range(n)]


def _xdo(*args) -> str:
    return subprocess.run(["xdotool", *args], capture_output=True, text=True, timeout=10).stdout


def click(which: str, at: tuple[float, float] | None = None) -> None:
    """Click accept or decline in the game window, at `at` (fractions of the window, found in the
    screenshot) or else where the marriage scroll has it; then the mouse and the focused window
    go back to where they were. Live: a click without focus does nothing, so the game window is
    activated first and the button gets a real press and release."""
    wid = _window()
    geo = dict(line.split("=", 1) for line in _xdo("getwindowgeometry", "--shell", wid).split())
    fx, fy = at or BUTTONS[which]
    x, y = int(int(geo["WIDTH"]) * fx), int(int(geo["HEIGHT"]) * fy)
    mouse = dict(line.split("=", 1) for line in _xdo("getmouselocation", "--shell").split())
    previous = _xdo("getactivewindow").strip()
    _xdo("windowactivate", "--sync", wid)
    time.sleep(0.3)
    _xdo("mousemove", "--window", wid, str(x), str(y))
    time.sleep(0.3)
    _xdo("mousedown", "1")
    time.sleep(0.15)
    _xdo("mouseup", "1")
    time.sleep(0.5)
    _xdo("mousemove", mouse["X"], mouse["Y"])
    if previous and previous != wid:
        _xdo("windowactivate", previous)


def parse_decision(answer: str) -> str | None:
    first = answer.strip().split(None, 1)[0].strip(".:,-!").lower() if answer.strip() else ""
    return first if first in ("accept", "decline") else None


def _names(name: str | None, reading: str) -> bool:
    """Whether the screen reading is about this man: his first name in it (live names carry
    underscores and " (null)"; a reading that failed can't tell, so it counts as a match)."""
    if not name or not reading:
        return True
    first = name.replace("_", " ").split()[0]
    if first.lower() == "captain" and len(name.split()) > 1:
        first = name.split()[1]
    return first.lower() in reading.lower()


def parse_choice(answer: str, options: list[str]) -> str | None:
    first = answer.strip().split(None, 1)[0].strip(".:,-!").lower() if answer.strip() else ""
    return first if first in options else None


# what each option on a named decision scroll leads to in Medieval II, for the ruler to weigh
CHOICE_NOTES = {
    "occupy": "occupy: keep the population and its goodwill; no loot",
    "sack": "sack: a large gold haul now, some townsfolk killed, unrest and a reputation for dread",
    "exterminate": "exterminate: the most gold, most of the population killed, order easy to keep, "
                   "a dark reputation, and the Pope and neighbours take note",
    "ransom": "ransom: offer the prisoners back to their faction for gold (it may refuse to pay)",
    "release": "release: let them go freely; chivalry and goodwill, no gold",
    "execute": "execute: kill them all; the enemy loses those men for good, you gain dread and infamy",
    "pay": "pay: pay the ransom asked and get your men back",
    "refuse": "refuse: keep your gold; your captured men stay with the enemy, who may execute them",
    "accept": "accept: agree to the AI's offer exactly as shown on screen",
    "decline": "decline: turn the offer down",
}


def choice_prompt(persona: str, faction: str, what: str, options: list[str], reading: str) -> str:
    listed = "\n".join(f"- {CHOICE_NOTES.get(o, o)}" for o in options)
    return f"""{persona.strip()}

You rule {faction}. The game asks you to decide {what or "a matter"} NOW, while it waits.

WHAT THE GAME SHOWS (read from the screen)
{reading or "(the screen could not be read)"}

YOUR OPTIONS
{listed}

Weigh gold, your armies, public order, your reputation, and relations with the other rulers and the Pope. Decide as yourself; nobody else answers it for you.

Answer with one line starting with one option word ({", ".join(o.upper() for o in options)}), then your reason in one or two plain sentences.
"""


def _stars(n) -> str:
    return f"{n} of 10" if isinstance(n, int) else "unknown"


# EOP gives a man's base attributes, before his traits; the scroll's stars include them (live: a
# 4-star Proven Commander read "command 0", and the ruler declined him as worthless)
BASE_NOTE = ("These are base values, before his traits add to them. The stars on the scroll above "
             "are the real ones: where they differ, trust the scroll.")


OFFER = re.compile(r"(Marriage|Adoption) offer: (.+?) \(age (\d+)\).*?You (accepted|declined) it\. "
                   r"Your reason: (.*)", re.S)


def offer_history(texts: list[str], n: int = 8) -> str:
    """The ruler's own past family offers, newest last, with a count: each offer is judged alone
    otherwise (live: every suitor declined for 25 turns, holding a princess for a royal match
    that never came, until she died unmarried)."""
    rows = [m.groups() for m in map(OFFER.match, texts) if m]
    if not rows:
        return ""
    suitors = [r for r in rows if r[0] == "Marriage"]
    lines = [f"- {kind.lower()}: {name} (age {age}), you {done} it: {' '.join(reason.split())[:110]}"
             for kind, name, age, done, reason in rows[-n:]]
    count = (f"Marriage offers so far: {len(suitors)}, {sum(r[3] == 'accepted' for r in suitors)} accepted, "
             f"{sum(r[3] == 'declined' for r in suitors)} declined.")
    return count + "\n" + "\n".join(lines)


def _past(history: str) -> str:
    return f"\nYOUR PAST FAMILY OFFERS (your own decisions, newest last)\n{history}\n" if history else ""


def marriage_prompt(persona: str, faction: str, suitor: dict, reading: str, history: str = "") -> str:
    traits = ", ".join(suitor.get("traits") or []) or "none known"
    return f"""{persona.strip()}

You rule {faction}. The game asks you to decide a marriage NOW, while it waits.

WHAT THE GAME SHOWS (read from the screen)
{reading or "(the screen could not be read)"}

THE SUITOR, FROM THE GAME'S RECORDS
{suitor.get("name")}, age {suitor.get("age")}. Command {_stars(suitor.get("command"))}, loyalty {_stars(suitor.get("loyalty"))}, piety {_stars(suitor.get("piety"))}, chivalry or dread {_stars(suitor.get("chivalry_or_dread"))}. Traits: {traits}.
{BASE_NOTE}
{_past(history)}
WEIGH IT
- Accepting adopts him into your family as a general. His command, loyalty and traits matter: low loyalty risks a disloyal or rebel general, a good commander is worth a lot.
- His age matters: an old man serves and lives only a few years more.
- Your princess stops being a diplomat. She can no longer marry into another royal house for an alliance, as you may have planned. An unmarried princess also ages, and can die, without ever making a match: see your past offers.
- A family with few generals or no clear heir gains more from a match than a large one.

Answer with one line starting ACCEPT or DECLINE, then your reason in one or two plain sentences.
"""


def adoption_prompt(persona: str, faction: str, candidate: dict, reading: str, history: str = "") -> str:
    traits = ", ".join(candidate.get("traits") or []) or "none known"
    return f"""{persona.strip()}

You rule {faction}. The game asks you to decide an adoption NOW, while it waits.

WHAT THE GAME SHOWS (read from the screen)
{reading or "(the screen could not be read)"}

THE CANDIDATE, FROM THE GAME'S RECORDS
{candidate.get("name")}, age {candidate.get("age")}. Command {_stars(candidate.get("command"))}, loyalty {_stars(candidate.get("loyalty"))}, piety {_stars(candidate.get("piety"))}, chivalry or dread {_stars(candidate.get("chivalry_or_dread"))}. Traits: {traits}.
{BASE_NOTE}
{_past(history)}
WEIGH IT
- Accepting adopts him into your family as a general and a possible claimant to the throne. A good young commander is worth a lot; low loyalty risks a disloyal or rebel general.
- Every family member costs upkeep and wants a command. A family short of generals or heirs gains more than a large one.
- He becomes a rival claimant: an ambitious adoptee can trouble a weak succession.

Answer with one line starting ACCEPT or DECLINE, then your reason in one or two plain sentences.
"""


def decision_prompt(persona: str, faction: str, reading: str) -> str:
    """Any other popup with a check and an X: the ruler decides from what the screen shows."""
    return f"""{persona.strip()}

You rule {faction}. The game asks you a question NOW, while it waits, with two buttons: a green check (accept, yes) and a red X (decline, no).

WHAT THE GAME SHOWS (read from the screen)
{reading or "(the screen could not be read)"}

WEIGH IT
- Work out exactly what accepting and declining each lead to in Medieval II: gold, armies, relations with other factions and the Pope, your family and your lands.
- Decide as yourself, for your realm's good. Nobody else answers it for you.

Answer with one line starting ACCEPT or DECLINE, then your reason in one or two plain sentences.
"""


class Popups:
    def __init__(self, turn_root: Path, game_id: str, seats: dict, personas: dict[str, str],
                 screenshot=screenshot, read=read, click=click, find=find_choice,
                 find_slots=minimized_slots, same=same_scroll, background: bool = True,
                 decide_timeout: float = 120):
        self.root, self.game_id, self.seats, self.personas = Path(turn_root), game_id, seats, personas
        self.screenshot, self.read, self.click, self.find = screenshot, read, click, find
        self.find_slots = find_slots
        self.same = same
        self._find_tick = find_tick
        self.find_votes = find_vote_buttons
        self.reopened = 0  # minimized messages opened so far: each stuck look tries the next slot
        self.decide_timeout = decide_timeout
        self.captures = self.root / game_id / "captures"
        self.store_path = self.root / game_id / "game_messages.json"
        self.lock = threading.Lock()
        self.seen: set[str] = set()
        self.last_read: Path | None = None
        self.read_tries: dict[str, int] = {}
        self.pool = ThreadPoolExecutor(max_workers=2) if background else None
        # decisions one at a time: popups stack, and each screenshot shows only the top one
        # (live: five requests at once all showed the same scroll, and two clicks answered it)
        self.decider = ThreadPoolExecutor(max_workers=1) if background else None
        self.later: list = []  # requeued decisions, without a background decider (tests)

    # --- what the ruler hears --------------------------------------------------------------

    def _load(self) -> list:
        try:
            return json.loads(self.store_path.read_text())
        except (OSError, ValueError):
            return []

    def _add(self, faction: str, turn: int, text: str) -> None:
        with self.lock:
            items = self._load()
            items.append({"faction": faction, "turn": turn, "text": text, "delivered": False})
            atomic_write(self.store_path, json.dumps(items, indent=2))

    def _history(self, faction: str) -> str:
        try:
            with self.lock:
                texts = [i["text"] for i in self._load() if i["faction"] == faction]
            return offer_history(texts)
        except Exception as e:  # a missing history never blocks the decision
            log.error("offer history for %s failed: %s", faction, e)
            return ""

    def messages_for(self, faction: str) -> list[str]:
        """Readings not yet given to this ruler; marked delivered."""
        with self.lock:
            items = self._load()
            out = [i["text"] for i in items if i["faction"] == faction and not i["delivered"]]
            for i in items:
                if i["faction"] == faction:
                    i["delivered"] = True
            if out:
                atomic_write(self.store_path, json.dumps(items, indent=2))
        return out

    # --- the work ------------------------------------------------------------------------------

    def poll(self) -> None:
        if pause.paused(self.root):  # nothing is decided while the rulers can't answer
            return
        for req_path in sorted(self.root.glob("popup-*.req")):
            if req_path.name in self.seen:
                continue
            self.seen.add(req_path.name)
            if self._orphan(req_path):
                continue
            try:
                req = json.loads(req_path.read_text())
            except (OSError, ValueError):
                continue
            self.captures.mkdir(parents=True, exist_ok=True)
            png = self.captures / f"{req['id']}.png"
            try:
                self.screenshot(png)
            except Exception as e:  # no window, no X: the bridge times out and clears it
                log.error("popup %s: screenshot failed: %s", req["id"], e)
                continue
            if req.get("kind") == "vote":  # a papal election: the ruler's cardinals vote
                if self.decider:
                    self.decider.submit(self._vote, req, png, req_path)
                else:
                    self._vote(req, png, req_path)
                continue
            if req.get("kind") == "minimized":  # a stuck turn: reopen a minimized message
                self._reopen(req, png, req_path)
                continue
            if req.get("kind") == "clicks":  # a screen job from the bridge (retraining): click, then close
                if self.decider:  # on the decider's one worker: never between a decision's look and click
                    self.decider.submit(self._clicks, req, req_path)
                else:
                    self._clicks(req, req_path)
                continue
            if req.get("kind") == "choice":  # a named scroll: the bridge presses the ruler's pick
                if self.decider:
                    self.decider.submit(self._choose, req, png, req_path)
                else:
                    self._choose(req, png, req_path)
                continue
            try:  # a named scroll being chosen on is on top: its buttons aren't this message's
                choice = None if self._choice_open() else self.find(png)
            except Exception as e:  # an unreadable screenshot: no buttons found
                log.error("popup %s: looking for buttons failed: %s", req["id"], e)
                choice = None
            if req.get("kind") in ("marriage", "adoption") or choice:
                # the bridge waits a decision's full time, not a reading's (see captured())
                atomic_write(req_path.with_suffix(".hold"), "")
                log.info("popup %s: a decision (%s), buttons at %s", req["id"], req.get("kind"), choice)
                if self.decider:
                    self.decider.submit(self._decide, req, png, req_path)
                else:
                    self._decide(req, png, req_path)
            else:
                try:
                    is_same = bool(self.last_read and self.same(png, self.last_read))
                except Exception:
                    is_same = False
                if is_same:
                    tries = self.read_tries.get(req["id"], 0) + 1
                    self.read_tries[req["id"]] = tries
                    if tries < 5:
                        self.seen.discard(req_path.name)
                        log.info("popup %s: same scroll as the last reading; looking again", req["id"])
                        break
                    atomic_write(req_path.with_suffix(".done"), "")
                    log.info("popup %s: same scroll after 5 looks; not read again", req["id"])
                    continue
                # a lone check acknowledges the scroll; clearing it would only minimize it
                try:
                    tick = None if self._choice_open() else self._find_tick(png)
                except Exception as e:  # an unreadable screenshot: read it the usual way
                    log.error("popup %s: looking for its check failed: %s", req["id"], e)
                    tick = None
                if tick:
                    self._run(self._read, req, png)  # read from this screenshot, then press
                    try:
                        self.click("accept", tick)
                        log.info("popup %s: acknowledged with its check", req["id"])
                        atomic_write(req_path.with_suffix(".done"), "acked")
                        self.last_read = png
                        break
                    except Exception as e:
                        log.error("popup %s: pressing its check failed: %s", req["id"], e)
                atomic_write(req_path.with_suffix(".done"), "")  # the popup can go; reading continues
                self._run(self._read, req, png)
                self.last_read = png
                break
        while self.later:  # decisions put back behind the others (no background decider: tests)
            self._decide(*self.later.pop(0))

    def _vote(self, req: dict, png: Path, req_path: Path) -> None:
        """The papal election: find the Vote buttons, ask the ruler which candidate, click it."""
        faction = req.get("faction")
        try:
            buttons = self.find_votes(png)
        except Exception as e:
            log.error("popup %s: looking for vote buttons failed: %s", req["id"], e)
            buttons = []
        if not buttons:
            log.warning("popup %s: no vote buttons on screen", req["id"])
            return
        reading = self._reading(req, png)
        answer = self._ask(req, faction, lambda persona: vote_prompt(persona, faction, len(buttons), reading))
        if answer is PAUSED:
            return
        m = re.match(r"\s*(\d+)", answer or "")
        pick = int(m.group(1)) if m and 1 <= int(m.group(1)) <= len(buttons) else 1
        reason = answer.strip().split(None, 1)[1] if answer and len(answer.split()) > 1 else "no clear answer; the first was chosen"
        if not req_path.exists():
            return
        try:
            self.click("vote", buttons[pick - 1])
        except Exception as e:
            log.error("popup %s: vote click failed: %s", req["id"], e)
            return
        atomic_write(req_path.with_suffix(".done"), "")
        self._add(faction, req.get("turn", 0), f"A papal election:\n{reading}\nYour cardinals voted for "
                  f"candidate {pick} of {len(buttons)}. Your reason: {reason}")
        log.info("popup %s: %s voted for candidate %d of %d", req["id"], faction, pick, len(buttons))

    # the settlement scroll's closing seal, bottom right (live, 1600x900: London's scroll)
    SEAL = (1550 / 1600, 652 / 900)

    def _clicks(self, req: dict, req_path: Path) -> None:
        """A screen job: click each card the bridge found (positions in the UI's 1024x768 space,
        which scales to the window), then close the settlement scroll."""
        cards = req.get("cards") or []
        # what the clicks met (live: eight clicks on Nottingham's cards queued nothing)
        self.captures.mkdir(parents=True, exist_ok=True)
        try:
            self.screenshot(self.captures / f"{req['id']}-before.png")
        except Exception as e:
            log.error("popup %s: screenshot before the clicks failed: %s", req["id"], e)
        # last card first: a clicked card leaves the row and the ones after it shift left (live:
        # clicking left to right hit the wrong cards and skipped the worst-hurt unit)
        for i, (fx, fy) in reversed(list(enumerate(cards))):
            try:
                self.click("open", (fx, fy))
            except Exception as e:
                log.error("popup %s: clicking card %d failed: %s", req["id"], i + 1, e)
        try:
            self.screenshot(self.captures / f"{req['id']}-after.png")
        except Exception as e:
            log.error("popup %s: screenshot after the clicks failed: %s", req["id"], e)
        try:
            self.click("open", self.SEAL)
        except Exception as e:
            log.error("popup %s: closing the scroll failed: %s", req["id"], e)
        atomic_write(req_path.with_suffix(".done"), "")
        log.info("popup %s: %s: clicked %d cards", req["id"], req.get("what"), len(cards))

    def _reopen(self, req: dict, png: Path, req_path: Path) -> None:
        """A stuck turn (the bridge asks): open one minimized message, the next slot up each
        time, so a decision buried in the stack is reached and a plain notice reopened and
        minimized again can't hold the turn forever. Reopening fires the game's onMessageOpen,
        and the scroll goes the usual way (read, or decided by the ruler)."""
        try:  # a decision open on screen that no request tracks: the ruler decides it now
            choice = None if self._choice_open() or not req.get("faction") else self.find(png)
        except Exception as e:
            log.error("popup %s: looking for buttons failed: %s", req["id"], e)
            choice = None
        if choice:  # live: a marriage offer missed its window and sat on screen all night
            log.info("popup %s: a decision is open on screen; the ruler decides it", req["id"])
            decision = dict(req, kind="decision")
            if self.decider:
                self.decider.submit(self._decide, decision, png, req_path)
            else:
                self._decide(decision, png, req_path)
            return
        try:
            slots = self.find_slots(png)
        except Exception as e:
            log.error("popup %s: looking for minimized messages failed: %s", req["id"], e)
            slots = []
        if slots:
            k = self.reopened % len(slots)
            self.reopened += 1
            try:
                self.click("open", slots[k])
                log.info("popup %s: reopened minimized message %d of %d", req["id"], k + 1, len(slots))
            except Exception as e:
                log.error("popup %s: reopening failed: %s", req["id"], e)
        for p in (req_path, req_path.with_suffix(".done")):  # the bridge doesn't wait on these
            p.unlink(missing_ok=True)

    def _orphan(self, req_path: Path) -> bool:
        """A request older than any wait the bridge keeps (it gives up after 180 s and removes
        its own) was forgotten by a bridge reload. Seen live: a restarted turn loop took eight
        such leftovers for new popups. Removed with its sibling files."""
        try:
            age = time.time() - req_path.stat().st_mtime
        except OSError:
            return True
        if age <= ORPHAN_AFTER:
            return False
        for sibling in req_path.parent.glob(req_path.stem + ".*"):
            sibling.unlink(missing_ok=True)
        log.info("popup %s: a leftover from before a reload (%ds old); removed", req_path.stem, age)
        return True

    def _choice_open(self) -> bool:
        """A named-scroll choice still waiting (the bridge removes its .req once pressed)."""
        for path in self.root.glob("popup-*.req"):
            try:
                if json.loads(path.read_text()).get("kind") == "choice":
                    return True
            except (OSError, ValueError):
                continue
        return False

    def _run(self, fn, *args) -> None:
        if self.pool:
            self.pool.submit(fn, *args)
        else:
            fn(*args)

    def _read(self, req: dict, png: Path) -> None:
        try:
            text = self.read(png)
        except Exception as e:
            log.error("popup %s: reading failed: %s", req["id"], e)
            return
        if text and text.strip().upper().startswith("NO SCROLL"):  # live: our overlay, read as news
            log.info("popup %s: no game scroll on screen", req["id"])
            return
        if text and req.get("faction"):
            self._add(req["faction"], req.get("turn", 0), text)
            log.info("popup %s read for %s", req["id"], req["faction"])

    def _choose(self, req: dict, png: Path, req_path: Path) -> None:
        """A named decision scroll (a captured city, prisoners, a ransom, an AI's offer): the
        ruler picks one of its options; the bridge presses that button by name."""
        faction, options = req.get("faction"), req.get("options") or []
        if not req_path.exists():  # the bridge gave up, or the scroll went
            return
        reading = self._reading(req, png)
        answer = self._ask(req, faction, lambda persona: choice_prompt(
            persona, faction, req.get("what", ""), options, reading)) if options else None
        if answer is PAUSED:
            return
        pick = parse_choice(answer, options) if answer else None
        if not req_path.exists():
            log.warning("popup %s: answered too late; the bridge already pressed its default", req["id"])
            return
        if pick is None:  # "none": the bridge presses its default now, not after its full wait
            log.warning("popup %s: no clear choice %r; the bridge presses its default", req["id"], (answer or "")[:120])
            atomic_write(req_path.with_suffix(".answer"), "none")
            return
        atomic_write(req_path.with_suffix(".answer"), pick)
        reason = answer.strip().split(None, 1)[1] if len(answer.split()) > 1 else ""
        self._add(faction, req.get("turn", 0), f"{req.get('what', 'A choice').capitalize()}: you chose to "
                  f"{pick}. Your reason: {reason}")
        log.info("popup %s: %s chose %s (%s)", req["id"], faction, pick, req.get("what"))

    def _requeue(self, req: dict, png: Path, req_path: Path) -> None:
        if self.decider:
            self.decider.submit(self._decide, req, png, req_path)
        else:
            self.later.append((req, png, req_path))

    def _reading(self, req: dict, png: Path) -> str:
        try:
            return self.read(png)
        except Exception as e:
            log.error("popup %s: reading failed: %s", req["id"], e)
            return ""

    def _ask(self, req: dict, faction: str, prompt_for) -> str | None:
        """The ruler's answer to prompt_for(persona), or None when there's no ruler or he fails;
        PAUSED when his seat hit a usage limit (the request is tried again after the pause)."""
        seat = self.seats.get(faction)
        if seat is None:
            log.warning("popup %s: no ruler for %s", req["id"], faction)
            return None
        try:
            return seat.chat(prompt_for(self.personas.get(faction, "")), timeout=self.decide_timeout)
        except SeatLimit as e:
            log.error("popup %s: %s; pausing the game", req["id"], e)
            pause.pause(self.root, str(e))
            self.seen.discard(f"{req['id']}.req")
            return PAUSED
        except SeatError as e:
            log.error("popup %s: %s couldn't decide: %s", req["id"], faction, e)
            return None

    def _decide(self, req: dict, png: Path, req_path: Path) -> None:
        faction, suitor, kind = req.get("faction"), req.get("suitor") or {}, req.get("kind")
        if not req_path.exists():  # the bridge gave up, or the scroll went
            return
        try:  # a fresh look: an earlier decision may have closed the scroll this request saw
            self.screenshot(png)
            choice = self.find(png)
        except Exception as e:
            log.error("popup %s: second look failed: %s", req["id"], e)
            choice = None
        if not choice and kind not in ("marriage", "adoption"):
            log.info("popup %s: no decision on screen any more; reading it instead", req["id"])
            atomic_write(req_path.with_suffix(".done"), "")
            self._read(req, png)
            return
        if not choice:  # an offer whose scroll isn't up (yet, or any more): never click blind
            tries = req.get("_tries", 0)
            # keep looking about as long as the bridge waits (180 s): live, a marriage offer sat
            # under a battle result for longer than three looks
            if tries < OFFER_LOOKS:
                log.info("popup %s: no buttons on screen yet; trying again later", req["id"])
                # the game may have minimized the offer at once (live: an offer's icon sat in
                # the stack while this waited two minutes): reopen one, the next slot each look
                try:
                    slots = self.find_slots(png)
                    if slots:
                        self.click("open", slots[self.reopened % len(slots)])
                        self.reopened += 1
                        log.info("popup %s: reopened a minimized message to find it", req["id"])
                except Exception as e:
                    log.error("popup %s: reopening failed: %s", req["id"], e)
                time.sleep(0 if not self.decider else 5)
                self._requeue({**req, "_tries": tries + 1}, png, req_path)
            else:
                log.warning("popup %s: the offer never showed its buttons; not clicking", req["id"])
            return
        reading = self._reading(req, png)
        if kind in ("marriage", "adoption") and not _names(suitor.get("name"), reading):
            # another offer's scroll is on top (seen live: Humphrey's adoption over Godwine's,
            # and Godwine's answer went to Humphrey). Let it be answered by its own request,
            # then look again; after a few tries, decide whatever is shown.
            tries = req.get("_tries", 0)
            if tries < 3:
                log.info("popup %s: the screen shows someone else's offer; trying again later", req["id"])
                time.sleep(0 if not self.decider else 5)
                self._requeue({**req, "_tries": tries + 1}, png, req_path)
                return
        def prompt_for(persona: str) -> str:
            if kind == "marriage":
                return marriage_prompt(persona, faction, suitor, reading, self._history(faction))
            if kind == "adoption":
                return adoption_prompt(persona, faction, suitor, reading, self._history(faction))
            return decision_prompt(persona, faction, reading)

        answer = self._ask(req, faction, prompt_for)
        if answer is PAUSED:
            return
        decision = parse_decision(answer) if answer else None
        if decision is None:  # no ruler, a failure or an unclear answer: no is the safe answer,
            # and nobody at the keyboard would answer otherwise (autoplay would stall)
            log.warning("popup %s: no clear answer %r; declining", req["id"], (answer or "")[:120])
            decision, answer = "decline", "DECLINE Nobody answered in time, so it was declined."
        if not req_path.exists():
            log.warning("popup %s: decided too late; the bridge already gave up on it", req["id"])
            return
        try:  # the ruler took a while: is the scroll still up? (live: minimized mid-answer,
            self.screenshot(png)  # then "accepted" with a click on the map)
            choice = self.find(png)
        except Exception as e:
            log.error("popup %s: last look failed: %s", req["id"], e)
            choice = None
        if not choice:
            log.warning("popup %s: the scroll is gone from the screen; not clicking", req["id"])
            return
        try:
            self.click(decision, choice[decision] if choice else None)
        except Exception as e:
            log.error("popup %s: click failed: %s", req["id"], e)
            return
        atomic_write(req_path.with_suffix(".done"), "")
        reason = answer.strip().split(None, 1)[1] if len(answer.split()) > 1 else ""
        if kind == "marriage":
            what = f"Marriage offer: {suitor.get('name')} (age {suitor.get('age')}) for your princess."
        elif kind == "adoption":
            what = f"Adoption offer: {suitor.get('name')} (age {suitor.get('age')}) into your family."
        else:
            what = "A decision the game asked of you:\n" + (reading or "(unread)") + "\n"
        done = "accepted" if decision == "accept" else "declined"
        self._add(faction, req.get("turn", 0), f"{what} You {done} it. Your reason: {reason}")
        log.info("popup %s: %s %s (%s)", req["id"], faction, done, kind)
