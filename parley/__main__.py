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
    args = ap.parse_args(argv)
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


if __name__ == "__main__":
    sys.exit(main())
