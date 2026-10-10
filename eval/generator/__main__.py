"""CLI: uv run python -m eval.generator [synth|heroes|portfolio|samples|hard|all] ..."""
from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def split_for(i: int) -> str:
    return "train" if i < 120 else ("dev" if i < 160 else "test")


def _one(args):
    seed, out = args
    from .bundle import make_bundle
    t = make_bundle(seed, Path(out), split_for(seed))
    return seed, len(t["documents"]), [p["rule"] for p in t["planted"]]


def synth(n: int, seed: int, out: Path, workers: int) -> None:
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    jobs = [(seed + i, str(out)) for i in range(n)]
    planted = {}
    with ProcessPoolExecutor(max_workers=workers) as ex:
        for s, nd, pl in ex.map(_one, jobs):
            for r in pl:
                planted[r] = planted.get(r, 0) + 1
    manifest = {"n": n, "seed": seed, "splits": {"train": [0, 119], "dev": [120, 159], "test": [160, 199]},
                "planted_counts": planted, "seconds": round(time.time() - t0, 1)}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1))
    print(json.dumps(manifest))


def main() -> None:
    ap = argparse.ArgumentParser(prog="eval.generator")
    ap.add_argument("cmd", nargs="?", default="synth", choices=["synth", "heroes", "portfolio", "samples", "hard", "all"])
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "synth")
    ap.add_argument("--workers", type=int, default=6)
    a = ap.parse_args()
    if a.cmd in ("synth", "all"):
        synth(a.n, a.seed, a.out, a.workers)
    if a.cmd in ("heroes", "all"):
        from .heroes import build_heroes
        build_heroes(ROOT / "data" / "seed")
    if a.cmd in ("portfolio", "all"):
        from .portfolio import build_portfolio
        build_portfolio(ROOT / "data" / "seed", workers=a.workers)
    if a.cmd in ("samples", "all"):
        from .samples import build_samples
        build_samples(ROOT / "data" / "seed", ROOT / "web" / "public" / "samples")
    if a.cmd in ("hard", "all"):
        from .hard import build_hard
        build_hard(ROOT / "data" / "hard")


if __name__ == "__main__":
    main()
