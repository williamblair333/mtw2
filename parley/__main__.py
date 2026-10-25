"""python -m parley run <game.toml>"""

import argparse
import logging
import sys
from pathlib import Path

from parley.config import load_config
from parley.orchestrator import Orchestrator
from parley.seats import make_seat


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="parley")
    sub = ap.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run", help="answer LLM-faction turns as the game writes them")
    run.add_argument("config", type=Path)
    disc = sub.add_parser("discord", help="run the Discord table bot for a game")
    disc.add_argument("config", type=Path)
    notes = sub.add_parser("notes", help="god view: rulers' private notes, orders and messages")
    notes.add_argument("config", type=Path)
    notes.add_argument("--faction")
    notes.add_argument("--last", type=int)
    tel = sub.add_parser("tell", help="post a game note to a ruler (its adviser thread and next prompt)")
    tel.add_argument("config", type=Path)
    tel.add_argument("faction")
    tel.add_argument("text")
    fol = sub.add_parser("follow", help="follow one ruler live: its messages and turn notes")
    fol.add_argument("config", type=Path)
    fol.add_argument("faction")
    fol.add_argument("--once", action="store_true", help="wait for the next new item, print it, exit")
    fol.add_argument("--state", type=Path, help="remember what was already shown in this file")
    rep = sub.add_parser("report", help="campaign report: what every ruler did, order coverage, failures")
    rep.add_argument("config", type=Path)
    from parley.setup import HELP_EXAMPLES
    ng = sub.add_parser("new-game", help="make a new game from your template",
                        description="Make games/local/<name>.toml: who plays, which personalities, "
                                    "which brains. Options override the template's settings.",
                        epilog=HELP_EXAMPLES, formatter_class=argparse.RawDescriptionHelpFormatter)
    ng.add_argument("name", help="game name: letters, digits, dashes, underscores")
    pick = ng.add_mutually_exclusive_group()
    pick.add_argument("--rivals", type=int, metavar="N", help="N random LLM rivals")
    pick.add_argument("--play", nargs="+", metavar="FACTION", help='these factions, or "all"')
    ng.add_argument("--personas", choices=["template", "historic", "archetypes", "random"])
    ng.add_argument("--scratch", action="store_true", help="hide Old Scratch among the rivals")
    ng.add_argument("--seat", action="append", default=[], metavar="FACTION=@PERSONA[:BRAIN]")
    ng.add_argument("--brain", help="one brain for every rival (sonnet, opus, flash, local, ...)")
    ng.add_argument("--ask", action="store_true", help="answer questions instead of options")
    ng.add_argument("--control", action="append", default=[], metavar="FACTION=CONTROL",
                    help="what that ruler commands: diplomat, ruler (default), full, or areas "
                         "like diplomacy,armies,build (areas: diplomacy armies agents build recruit taxes)")
    ng.add_argument("--adviser", action="append", default=[], metavar="FACTION[=USER]",
                    help="you (or USER) advise that ruler in a private Discord thread")
    ng.add_argument("--autoplay", action="store_true",
                    help="unattended: the game ends your turn once every ruler has answered; no humans")
    ng.add_argument("--until", type=int, metavar="TURN", help="with --autoplay: stop at this game turn")
    ng.add_argument("--wait", type=int, metavar="SECONDS", help="with --autoplay: wait this long for late "
                                                                "rulers (default 300)")
    ng.add_argument("--from", dest="from_game", metavar="GAME", help="copy an existing game's seats")
    ng.add_argument("--template", type=Path, help="template file (default: games/local/template.toml, "
                                                   "else games/template.toml)")
    ng.add_argument("--dir", type=Path, default=Path("games/local"), help=argparse.SUPPRESS)
    args = ap.parse_args(argv)
    if args.cmd == "new-game":
        return new_game(args)
    if args.cmd == "tell":
        from parley.store import Store
        from parley.tell import tell
        cfg = load_config(args.config)
        if args.faction not in cfg.seats:
            print(f"no ruler '{args.faction}' in {args.config}", file=sys.stderr)
            return 1
        tell(Store(cfg.turn_root / f"{cfg.game_id}.db"), cfg.turn_root, cfg.game_id, args.faction, args.text)
        print(f"note queued for {args.faction}; the bot posts it, and the next turn prompt includes it")
        return 0
    if args.cmd == "follow":
        from parley.follow import follow
        from parley.store import Store
        cfg = load_config(args.config)
        try:
            follow(Store(cfg.turn_root / f"{cfg.game_id}.db"), cfg.turn_root, cfg.game_id,
                   args.faction, args.state, args.once)
        except KeyboardInterrupt:
            pass
        return 0
    if args.cmd == "report":
        from parley.report import campaign_report
        cfg = load_config(args.config)
        print(campaign_report(cfg.turn_root, cfg.game_id), end="")
        return 0
    if args.cmd == "notes":
        from parley.notes import format_notes
        cfg = load_config(args.config)
        print(format_notes(cfg.turn_root, cfg.game_id, args.faction, args.last), end="")
        return 0

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    config = load_config(args.config)
    if args.cmd == "discord":
        from parley.discord_bot import run_bot
        run_bot(config)
        return 0
    seats = {faction: make_seat(s.brain) for faction, s in config.seats.items()}
    orch = Orchestrator(config, seats)
    try:
        orch.acquire()
    except RuntimeError as e:
        print(e, file=sys.stderr)
        return 1
    try:
        orch.run_forever()
    except KeyboardInterrupt:
        pass
    finally:
        orch.release()
    return 0


def new_game(args) -> int:
    import tomllib

    from parley.setup import SetupError, ask, build_game, summary, to_toml, write_game
    out_dir = args.dir
    repo = Path(__file__).resolve().parent.parent
    try:
        if args.from_game:
            src = out_dir / f"{args.from_game}.toml"
            if not src.exists():
                raise SetupError(f"no such game: {src}")
            game = tomllib.loads(src.read_text())
            game["game_id"] = args.name
            hidden_src = src.with_name(f"{src.stem}.hidden.toml")
            hidden = tomllib.loads(hidden_src.read_text()) if hidden_src.exists() else {}
        else:
            template_path = args.template or next(
                (p for p in (out_dir / "template.toml", repo / "games" / "template.toml") if p.exists()))
            template = tomllib.loads(template_path.read_text())
            if "your_discord_name" in template.get("humans", {}).values():
                print(f"note: {template_path} still has the placeholder Discord name; copy it to "
                      f"games/local/template.toml and set yours", file=sys.stderr)
            if args.ask:
                options = ask(template)
            else:
                play = ("all" if args.play == ["all"] else args.play) if args.play else (
                    f"random {args.rivals}" if args.rivals is not None else None)
                options = {"play": play, "personas": args.personas, "brain": args.brain,
                           "scratch": True if args.scratch else None}
            if (args.until or args.wait) and not args.autoplay:
                raise SetupError("--until and --wait go with --autoplay")
            autoplay = {"wait": args.wait, "until_turn": args.until} if args.autoplay else None
            game, hidden = build_game(template, args.name, personas_dir=repo / "personas",
                                      seats=args.seat, autoplay=autoplay, control=args.control,
                                      adviser=args.adviser, **options)
        path = write_game(game, hidden, out_dir / f"{args.name}.toml")
    except SetupError as e:
        print(e, file=sys.stderr)
        return 1
    print(summary(game, hidden))
    print(f"\nwrote {path}\nnext: just play {args.name}   then start a NEW Grand Campaign in the game")
    return 0


if __name__ == "__main__":
    sys.exit(main())
