"""Retrieval and refusal-gate benchmark that costs no model tokens.

Everything here runs against the app's own retrieval path through its HTTP API:
local embeddings, pgvector and Postgres full-text search. No generation, no judge,
so it can be run as often as you like on a free tier -- which is what makes it
usable for tuning, while the generation benchmark stays held out.

It reports retrieval at two levels, because chunking makes them different questions:

  unit     the exact chunk a question was written from reached the context
  locator  some chunk from the right page, slide or timestamp reached the context

and it scores the refusal gate by how well the retrieved set's shape separates
answerable questions from off-material ones.

    python run_retrieval_eval.py --course "Deep Learning Foundations"
    python run_retrieval_eval.py --dataset datasets/dev.json --top-k 8
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

from harness.client import StudyCompanionClient

ROOT = Path(__file__).parent


def locator_of(unit: dict) -> tuple:
    return (
        unit.get("source_id"),
        unit.get("page_no"),
        unit.get("slide_no"),
        unit.get("start_time_s"),
    )


def auc(positives: list[float], negatives: list[float]) -> float | None:
    """Probability that a random answerable question scores above a random
    off-material one. 0.5 is a coin toss; 1.0 is perfect separation."""
    if not positives or not negatives:
        return None
    wins = sum(1.0 if p > n else 0.5 if p == n else 0.0 for p in positives for n in negatives)
    return round(wins / (len(positives) * len(negatives)), 4)


def margin_of(scores: list[float]) -> float:
    usable = sorted([s for s in scores if s], reverse=True)
    if len(usable) < 2:
        return 0.0
    rest = usable[1:]
    return usable[0] - sum(rest) / len(rest)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", default="http://localhost:8000")
    parser.add_argument("--course", default="Deep Learning Foundations")
    parser.add_argument("--dataset", type=Path, default=ROOT / "datasets" / "dev.json")
    parser.add_argument("--top-k", type=int, default=8)
    parser.add_argument("--out", type=Path, default=ROOT / "results" / "retrieval.json")
    args = parser.parse_args()

    client = StudyCompanionClient(args.app)
    course = client.find_course(args.course)
    units = {unit["id"]: unit for unit in client.all_units(course["id"])}
    cases = json.loads(args.dataset.read_text(encoding="utf-8"))
    print(f"{course['title']}: {len(units)} units, {len(cases)} cases, k={args.top_k}\n")

    rows = []
    for case in cases:
        found = client.search(course["id"], case["question"], top_k=args.top_k)
        results = found["results"]
        retrieved = [r.get("unit_id") or r.get("id") for r in results]

        truth = set(case.get("ground_truth_unit_ids") or [])
        ranks = [i for i, unit_id in enumerate(retrieved, 1) if unit_id in truth]
        truth_places = {locator_of(units[u]) for u in truth if u in units}
        got_places = {locator_of(units[u]) for u in retrieved if u in units}

        rows.append(
            {
                "question": case["question"],
                "behavior": case["expected_behavior"],
                "category": case.get("category", "unspecified"),
                "rank": ranks[0] if ranks else None,
                "unit_hit": bool(ranks),
                "locator_hit": bool(truth_places & got_places),
                "margin": float(found.get("margin") or 0.0),
                "best_score": float(found.get("best_score") or 0.0),
            }
        )

    answerable = [r for r in rows if r["behavior"] == "answerable"]
    off = [r for r in rows if r["behavior"] == "off_material"]

    if answerable:
        unit_hit = sum(r["unit_hit"] for r in answerable) / len(answerable)
        locator_hit = sum(r["locator_hit"] for r in answerable) / len(answerable)
        mrr = sum(1 / r["rank"] for r in answerable if r["rank"]) / len(answerable)
        print(f"retrieval over {len(answerable)} answerable cases")
        print(f"  unit hit rate    {unit_hit:.3f}")
        print(f"  locator hit rate {locator_hit:.3f}")
        print(f"  MRR              {mrr:.3f}")

        by_category: dict[str, list[bool]] = {}
        for row in answerable:
            by_category.setdefault(row["category"], []).append(row["unit_hit"])
        print("  by category:")
        for category, hits in sorted(by_category.items()):
            print(f"    {category:12} {sum(hits)}/{len(hits)}")

    if answerable and off:
        print(f"\nrefusal signal, {len(answerable)} answerable vs {len(off)} off-material")
        for name in ("margin", "best_score"):
            pos = [r[name] for r in answerable]
            neg = [r[name] for r in off]
            print(
                f"  {name:11} AUC {auc(pos, neg)}  "
                f"answerable {min(pos):.3f}-{max(pos):.3f} (mu={statistics.fmean(pos):.3f})  "
                f"off {min(neg):.3f}-{max(neg):.3f} (mu={statistics.fmean(neg):.3f})"
            )

    misses = [r for r in answerable if not r["unit_hit"]]
    if misses:
        print("\nunit-level misses:")
        for row in misses:
            where = "right page retrieved" if row["locator_hit"] else "page missed too"
            print(f"  [{row['category']}] {row['question'][:66]} ({where})")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nwrote {args.out}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
