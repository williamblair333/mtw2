"""Play reviewer: watches an LLM ruler play and explains its mistakes.

Usage: python -m parley.play_review <game.toml> <faction> [--every 5] [--model agy:gemini-3.8-flash-low] [--out _review] [--once]
"""

import argparse
from datetime import datetime
import logging
from pathlib import Path
import sys
import time

from parley.config import load_config
from parley.seats import make_seat

# not answer.txt: the seat's raw answer (live: 57 KB from agy) is orders.json again, unparsed
FILES = ("prompt.txt", "orders.json", "results.json", "rejected.json")


def _prompt_part(text: str, start: str, limit: int) -> str:
    """The prompt from the `start` heading to OUTPUT RULES, at most `limit` characters: the
    persona and the rules are the same every turn, and agy takes its prompt as one argument,
    which Linux caps at 128 KB (live: five whole 60 KB prompts failed with E2BIG)."""
    i = text.find("\n" + start)
    j = text.find("\nOUTPUT RULES")
    part = text[i + 1 if i >= 0 else 0: j if j > i else len(text)]
    return part[:limit]


def turn_digest(turn_dir: Path, faction: str, max_prompt_chars: int = 30000,
                start: str = "YOUR SETTLEMENTS") -> str:
    """Join existing turn files for a faction under markdown headings."""
    turn_dir = Path(turn_dir)
    if (turn_dir / faction).is_dir():
        folder = turn_dir / faction
    elif turn_dir.name == faction or any((turn_dir / f).exists() for f in FILES):
        folder = turn_dir
    else:
        folder = turn_dir / faction

    blocks = []
    for name in FILES:
        p = folder / name
        if not p.is_file():
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except OSError:
            continue
        if name == "prompt.txt":
            text = _prompt_part(text, start, max_prompt_chars)
        blocks.append(f"### {name}\n{text.strip()}")
    return "\n\n".join(blocks)


def review_prompt(faction: str, digests: list[tuple[int, str]]) -> str:
    """Instructions to a reviewer model examining an AI ruler's play."""
    turn_blocks = []
    for turn, digest in digests:
        turn_blocks.append(f"## Turn {turn}\n\n{digest.strip()}")
    body = "\n\n".join(turn_blocks) if turn_blocks else "(no turns found)"

    return (
        f"You are reviewing an AI ruler's last few turns of Medieval II: Total War, played through Parley, as the faction {faction}.\n\n"
        "For each turn, here is what the ruler saw (prompt), what it ordered (orders/answer), and what the game did (results/rejections):\n\n"
        f"{body}\n\n"
        "---\n\n"
        "Please provide a review covering:\n"
        "1. Concrete mistakes (orders refused for avoidable reasons, the same refused order repeated, "
        "contradictions with its own plan or notes, ignoring threats or money in the report, wasted moves).\n"
        "2. For each mistake, the most likely CAUSE, classified as one of:\n"
        "   - ruler judgement\n"
        "   - missing or wrong data in the report/prompt\n"
        "   - unclear rules in the prompt\n"
        "   - a bridge or game bug\n"
        "3. A short suggested fix for each non-judgement cause, citing the prompt text or result line.\n"
        "4. 1-3 things the ruler did well.\n\n"
        "Format as plain markdown, under 600 words. Say plainly when unsure."
    )


def _turn_folder(turn_root: Path, game_id: str, turn: int, faction: str) -> Path | None:
    game_dir = Path(turn_root) / game_id
    candidates = [
        game_dir / f"turn-{turn:04d}" / faction,
        game_dir / f"turn-{turn:04d}",
        game_dir / f"turn-{turn}" / faction,
        game_dir / f"turn-{turn}",
    ]
    for c in candidates:
        if c.is_dir():
            return c
    return None


def review(turn_root: Path, game_id: str, faction: str, last_turn: int, span: int, seat) -> str:
    """Collect digests for turns in window, build prompt, and ask seat for review."""
    digests = []
    start = max(0, last_turn - span + 1)
    for t in range(start, last_turn + 1):
        folder = _turn_folder(turn_root, game_id, t, faction)
        if folder is None:
            continue
        # the newest turn in full (its state is what the next moves face); earlier turns from
        # their order results on, so the whole review stays well under agy's 128 KB argument
        d = (turn_digest(folder, faction, 28000) if t == last_turn
             else turn_digest(folder, faction, 8000, start="LAST TURN'S ORDER RESULTS"))
        if d:
            digests.append((t, d))
    prompt = review_prompt(faction, digests)
    return seat.chat(prompt, timeout=600)


def newest_turn(turn_root: Path, game_id: str, faction: str) -> int | None:
    """The latest turn number whose <faction>/results.json exists."""
    game_dir = Path(turn_root) / game_id
    if not game_dir.is_dir():
        return None
    turns = []
    for p in game_dir.glob("turn-*"):
        if (p / faction / "results.json").is_file():
            try:
                turns.append(int(p.name.removeprefix("turn-")))
            except ValueError:
                continue
    return max(turns) if turns else None


def find_last_reviewed(out_dir: Path, game_id: str, faction: str) -> int:
    """Latest turn reviewed based on existing markdown files in out_dir."""
    turns = []
    if out_dir.is_dir():
        for p in out_dir.glob(f"*-play-review-{game_id}-{faction}-t*.md"):
            try:
                t_str = p.stem.split("-t")[-1]
                turns.append(int(t_str))
            except ValueError:
                continue
    return max(turns) if turns else 0


def write_review_file(out_dir: Path, game_id: str, faction: str, last_turn: int, span: int, model: str, text: str) -> Path:
    """Write review to <out>/<YYYY-MM-DD>-play-review-<game_id>-<faction>-t<NNNN>.md."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    filename = f"{today}-play-review-{game_id}-{faction}-t{last_turn:04d}.md"
    path = out_dir / filename
    start_turn = max(0, last_turn - span + 1)
    header = f"# Play review: {model} (turns {start_turn}..{last_turn})\n\n"
    path.write_text(header + text + "\n", encoding="utf-8")
    return path


def main(argv=None):
    parser = argparse.ArgumentParser(description="Watch an LLM ruler play and explain mistakes.")
    parser.add_argument("config", help="Path to game TOML config file")
    parser.add_argument("faction", help="Faction name to review")
    parser.add_argument("--every", type=int, default=5, help="Review every N turns (default: 5)")
    parser.add_argument("--model", default="agy:gemini-3.8-flash-low", help="Seat spec for the reviewer model")
    parser.add_argument("--out", default="_review", help="Output directory for reviews (default: _review)")
    parser.add_argument("--once", action="store_true", help="Review newest turns once and exit")

    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    if not logging.getLogger().handlers:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    cfg = load_config(Path(args.config))
    turn_root = cfg.turn_root
    game_id = cfg.game_id
    out_dir = Path(args.out)
    seat = make_seat(args.model)

    if args.once:
        turn = newest_turn(turn_root, game_id, args.faction)
        if turn is None:
            logging.warning("No turns with results found for %s in %s", args.faction, game_id)
            return 0
        try:
            text = review(turn_root, game_id, args.faction, turn, args.every, seat)
            written = write_review_file(out_dir, game_id, args.faction, turn, args.every, args.model, text)
            logging.info("Wrote review to %s", written)
        except Exception as e:
            logging.error("Failed to review turn %d: %s", turn, e)
            return 1
        return 0

    last_reviewed = find_last_reviewed(out_dir, game_id, args.faction)
    logging.info("Starting play review loop for %s in %s (every %d turns, last reviewed: %d)",
                 args.faction, game_id, args.every, last_reviewed)
    while True:
        try:
            current = newest_turn(turn_root, game_id, args.faction)
            if current is not None:
                while last_reviewed + args.every <= current:
                    target = last_reviewed + args.every
                    try:
                        text = review(turn_root, game_id, args.faction, target, args.every, seat)
                        written = write_review_file(out_dir, game_id, args.faction, target, args.every, args.model, text)
                        logging.info("Wrote review for turn %d to %s", target, written)
                    except Exception as e:
                        logging.error("Failed to review turn %d: %s", target, e)
                    last_reviewed = target
        except Exception as e:
            logging.error("Error in play review loop: %s", e)
        time.sleep(30)


if __name__ == "__main__":
    main()
