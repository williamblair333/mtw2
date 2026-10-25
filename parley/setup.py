"""Make a game from the template: who plays, which personalities, which brains.

The same engine serves the template file, the command-line options and the ask-me setup.
"""

import random
import re
import tomllib
from pathlib import Path

from parley.control import PRESETS, resolve
from parley.personas import load_personas

BRAIN_SHORTHANDS = {
    "sonnet": "claude:sonnet", "opus": "claude:opus", "haiku": "claude:haiku",
    "flash": "agy:gemini-3.8-flash-low", "gemini": "agy:gemini-3.8-flash-low",
    "local": "ollama:qwen3.5:9b",
}
PERSONA_MODES = ("template", "historic", "archetypes", "random")
SCRATCH_BRAIN = "claude:opus"

HELP_EXAMPLES = """\
examples:
  just new-game game3
      Use your template as it stands (games/local/template.toml): its play line,
      personas and brains.

  just new-game game3 --rivals 6
      6 random rivals, each with its faction's personality from the template.

  just new-game game3 --play france hre papal_states
      Exactly these three rivals.

  just new-game game3 --play all
      Every faction is an LLM ruler (you can just watch: spectator mode).

  just new-game game3 --rivals 5 --personas historic
      5 random rivals played as their 1080 rulers (William, Philip I, Gregory VII...).

  just new-game game3 --rivals 4 --personas archetypes
      4 random rivals, each a different permanent archetype (rules lawyer, zealot,
      faithless charmer...). Old Scratch is never picked this way.

  just new-game game3 --rivals 6 --personas random
      A random mix of historic rulers and archetypes.

  just new-game game3 --rivals 6 --scratch
      As above, but one rival is secretly Old Scratch, masked under his faction's normal
      ruler's name. Only games/local/game3.hidden.toml says which (don't peek).

  just new-game game3 --play france venice --seat france=@rules-lawyer:opus
      France is the Rules Lawyer on Claude Opus; Venice as in the template.

  just new-game game3 --rivals 3 --seat sicily=@scratch:opus
      Old Scratch in the open as Sicily, plus 3 random rivals (a --seat adds its faction).

  just new-game game3 --rivals 6 --brain flash
      Every rival on Gemini Flash (fast, uses your Gemini subscription).

  just new-game game3 --play france hre --brain opus --seat hre=@henry-iv-hre:sonnet
      Opus for everyone except the HRE, which keeps its 1080 ruler on Sonnet.

  just new-game game3 --ask
      Answer a few questions instead of typing options.

  just new-game game3 --from game2
      Copy the seats of an existing game (games/local/game2.toml) under a new game id.

  just new-game soak --play all --personas random --autoplay --until 30
      Unattended test: every faction an LLM, and the game ends your turn itself once
      every ruler has answered, up to turn 30. No humans. Watch, then: just report soak

  just new-game soak --play all --autoplay --until 30 --wait 120 \\
                     --seat venice=@rules-lawyer:script:games/soak-test.json
      As above, giving late rulers 2 minutes (default 5), and Venice plays a fixed plan
      that tries every order type, so each one gets exercised.

  just new-game watch --play all --autoplay --control england=full --adviser england \\
                      --seat england=@william-the-conqueror:opus
      Observer game: start the campaign as England and watch Opus play it alone: every
      army, agent, building and tax rate; its governors recruit. You advise it in
      Discord (!adviser opens the thread); it may overrule you.

  just new-game watch2 --play all --autoplay --control england=diplomacy,armies,agents
      As above, but England's governors handle building, recruiting and taxes.

control:  diplomat | ruler (default: diplomacy, armies, agents) | full (all but recruit) |
          your own list of diplomacy, armies, agents, build, recruit, taxes. Areas left out
          are the game's. "recruit" works only in settlements with no units inside (EOP bug).
brains:   sonnet, opus, haiku (Claude) | flash (Gemini via agy) | local (Ollama) | or a full
          spec like claude:sonnet, agy:gemini-3.8-flash-low, ollama:qwen3.5:9b
personas: any @id in personas/*.toml, e.g. @philip-i-of-france, @rules-lawyer, @scratch,
          @honest-merchant, @faithless-charmer, @grudge-holder, @zealot, @coward
"""


class SetupError(ValueError):
    pass


def brain_spec(text: str) -> str:
    return BRAIN_SHORTHANDS.get(text, text) if ":" not in text else text


def _parse_seat(spec: str) -> tuple[str, dict]:
    m = re.fullmatch(r"([a-z_]+)=(@[\w-]+)(?::(.+))?", spec)
    if not m:
        raise SetupError(f"--seat must look like faction=@persona or faction=@persona:brain, got '{spec}'")
    faction, persona, brain = m.groups()
    seat = {"persona": persona}
    if brain:
        seat["brain"] = brain_spec(brain)
    return faction, seat


def _pick(template: dict, play, rng: random.Random) -> list[str]:
    factions = list(template["factions"])
    humans = set(template.get("humans", {}))
    pool = [f for f in factions if f not in humans]
    if play is None or play == []:
        play = template.get("play", "random 6")
    if isinstance(play, list):
        for f in play:
            if f not in template["factions"]:
                raise SetupError(f"unknown faction '{f}'. Factions: {', '.join(factions)}")
            if f in humans:
                raise SetupError(f"'{f}' is a human player, not an LLM rival")
        return list(dict.fromkeys(play))
    if play == "all":
        return pool
    m = re.fullmatch(r"random (\d+)", str(play))
    if m:
        n = int(m.group(1))
        if n > len(pool):
            raise SetupError(f"asked for {n} random rivals, but only {len(pool)} factions are free")
        return sorted(rng.sample(pool, n))
    raise SetupError(f'play must be a list of factions, "all" or "random N", got {play!r}')


def build_game(template: dict, name: str, *, personas_dir: Path, play=None, personas=None,
               scratch=None, seats: list[str] | None = None, brain: str | None = None,
               rng: random.Random | None = None, autoplay: dict | None = None,
               control: list[str] | None = None, adviser: list[str] | None = None) -> tuple[dict, dict]:
    """Returns (game, hidden): the game config dict and the hidden seats (secret Scratch).

    autoplay ({"wait": s, "until_turn": n}) makes an unattended game: no humans.
    control: "faction=preset" or "faction=area,area"; adviser: "faction" or "faction=username"
    (a bare faction takes the template's human username)."""
    rng = rng or random.Random()
    template_humans = list(template.get("humans", {}).values())
    if not re.fullmatch(r"[A-Za-z0-9_-]+", name):
        raise SetupError(f"game name must be letters, digits, dashes or underscores: '{name}'")
    mode = personas or template.get("personas", "template")
    if mode not in PERSONA_MODES:
        raise SetupError(f"personas must be one of {', '.join(PERSONA_MODES)}, got '{mode}'")
    if autoplay is not None:  # unattended: nobody is human, so every faction is free to seat
        template = {**template, "humans": {}}
    overrides = dict(_parse_seat(s) for s in (seats or []))
    for f in overrides:
        if f not in template["factions"]:
            raise SetupError(f"unknown faction '{f}' in --seat")
    chosen = _pick(template, play, rng)
    chosen += [f for f in overrides if f not in chosen]

    library = load_personas(personas_dir)
    historic = {p.faction: f"@{p.id}" for p in library.values() if p.kind == "historic" and p.faction}
    archetypes = sorted(f"@{p.id}" for p in library.values() if p.kind == "archetype" and p.id != "scratch")
    rng.shuffle(archetypes)
    default_brain = template.get("defaults", {}).get("brain", "claude:sonnet")

    game_seats = {}
    for i, f in enumerate(chosen):
        base = dict(template["factions"][f])
        persona = base.get("persona", historic.get(f, ""))
        if mode == "historic":
            persona = historic.get(f, persona)
        elif mode == "archetypes":
            persona = archetypes[i % len(archetypes)]
        elif mode == "random":
            persona = rng.choice([historic.get(f, persona), archetypes[i % len(archetypes)]])
        seat = {"brain": brain_spec(brain) if brain else base.get("brain", default_brain),
                "persona": persona}
        if base.get("name"):
            seat["name"] = base["name"]
        seat.update(overrides.get(f, {}))
        game_seats[f] = seat

    for spec in control or []:
        f, _, value = spec.partition("=")
        if f not in game_seats:
            raise SetupError(f"--control: '{f}' is not seated in this game")
        value = value if value in PRESETS else [a for a in value.split(",") if a]
        try:
            resolve(value)
        except ValueError as e:
            raise SetupError(f"--control {spec}: {e}") from None
        game_seats[f]["control"] = value
    for spec in adviser or []:
        f, _, user = spec.partition("=")
        if f not in game_seats:
            raise SetupError(f"--adviser: '{f}' is not seated in this game")
        user = user or (template_humans[0] if template_humans else "")
        if not user:
            raise SetupError(f"--adviser {f}: give a Discord username (--adviser {f}=NAME); the "
                             "template's [humans] has none")
        plays = next((h for h, u in template.get("humans", {}).items() if u == user), None)
        if plays:  # an adviser has no throne: they'd read one realm's counsel while playing another
            raise SetupError(f"--adviser {f}: {user} plays {plays} in this game; an adviser can't "
                             "also be a player (name another user, or use --autoplay)")
        game_seats[f]["adviser"] = user

    hidden = {}
    if scratch if scratch is not None else template.get("secret_scratch", False):
        candidates = [f for f in chosen if f not in overrides]
        if not candidates:
            raise SetupError("no rival left to hide Old Scratch behind (every seat was set with --seat)")
        f = rng.choice(candidates)
        mask = game_seats[f].get("name") or _persona_name(game_seats[f]["persona"], library) or f.title()
        # the game file keeps the seat exactly as it would be; only the .hidden.toml changes it
        hidden = {"seats": {f: {"persona": "@scratch", "brain": SCRATCH_BRAIN, "name": mask}}}

    game = {k: template[k] for k in ("turn_root", "save_dir", "seat_timeout") if k in template}
    game = {"game_id": name, **game, "humans": dict(template.get("humans", {})),
            "seats": game_seats}
    if "discord" in template:
        game["discord"] = dict(template["discord"])
    if autoplay is not None:
        game["humans"] = {}
        game["autoplay"] = {k: v for k, v in autoplay.items() if v is not None}
    return game, hidden


def _persona_name(ref: str, library) -> str:
    p = library.get(ref.lstrip("@")) if ref.startswith("@") else None
    return p.name if p else ""


# --- writing TOML (just the shapes we produce) ----------------------------------------------

def _value(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, list):
        return "[" + ", ".join(_value(x) for x in v) + "]"
    s = str(v)
    if "\n" in s:
        return '"""' + s.replace("\\", "\\\\").replace('"""', '\\"""') + '"""'
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def to_toml(data: dict, header: str = "") -> str:
    lines = [header] if header else []
    for k, v in data.items():
        if not isinstance(v, dict):
            lines.append(f"{k} = {_value(v)}")
    for k, v in data.items():
        if isinstance(v, dict) and k != "seats":
            lines += ["", f"[{k}]"] + [f"{kk} = {_value(vv)}" for kk, vv in v.items()]
    for f, seat in data.get("seats", {}).items():
        lines += ["", f"[seats.{f}]"] + [f"{kk} = {_value(vv)}" for kk, vv in seat.items()]
    return "\n".join(lines) + "\n"


def write_game(game: dict, hidden: dict, path: Path) -> Path:
    path = Path(path)
    if path.exists():
        raise SetupError(f"{path} already exists (pick another name, or 'just play {path.stem}')")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(to_toml(game, f"# Game '{game['game_id']}', made by `just new-game`. Edit freely."))
    if hidden:
        path.with_name(f"{path.stem}.hidden.toml").write_text(
            to_toml(hidden, "# SPOILER: the hidden rulers of this game. Don't read it if you're playing."))
    tomllib.loads(path.read_text())  # never leave an unreadable game file behind
    return path


def summary(game: dict, hidden: dict) -> str:
    lines = [f"game '{game['game_id']}': {len(game['seats'])} LLM rivals"]
    for f, s in game["seats"].items():  # from the game file only: identical with or without a secret
        lines.append(f"  {f:<13} {s.get('name') or s['persona']:<32} {s['brain']}")
    if hidden:
        lines.append("  (one of them is not who they seem)")
    return "\n".join(lines)


# --- ask-me setup ---------------------------------------------------------------------------

def ask(template: dict, prompt=None) -> dict:
    """Interactive answers -> keyword arguments for build_game."""
    prompt = prompt or input
    factions = [f for f in template["factions"] if f not in template.get("humans", {})]
    print(f"Factions: {', '.join(factions)}")
    how = prompt("Rivals: a number for random, 'all', or faction names [6]: ").strip() or "6"
    play = f"random {how}" if how.isdigit() else ("all" if how == "all" else how.replace(",", " ").split())
    personas = prompt(f"Personalities ({'/'.join(PERSONA_MODES)}) [template]: ").strip() or None
    brain = prompt("One brain for everyone? (sonnet/opus/flash/local, blank = per template): ").strip() or None
    scratch = prompt("Hide Old Scratch among them? (y/N): ").strip().lower().startswith("y")
    return {"play": play, "personas": personas, "brain": brain, "scratch": scratch}
