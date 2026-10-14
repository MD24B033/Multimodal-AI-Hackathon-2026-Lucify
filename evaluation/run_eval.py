from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from harness import metrics as metric_module
from harness import personalization, testset
from harness.client import StudyCompanionClient
from harness.judge import GroqJudge

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s | %(message)s")

RESULTS_DIR = ROOT / "results"

METRIC_LABELS = {
    "faithfulness": "Faithfulness",
    "answer_relevancy": "Answer relevancy",
    "llm_context_precision_with_reference": "Context precision",
    "context_recall": "Context recall",
    "source_hit_rate": "Source hit rate",
    "mean_reciprocal_rank": "Mean reciprocal rank",
    "source_recall": "Source recall",
    "source_precision_at_k": "Source precision@k",
    "correct_refusal_rate": "Correct refusal rate",
    "false_refusal_rate": "False refusal rate",
    "refusal_f1": "Refusal F1",
}


def pct(value) -> str:
    if value is None:
        return "not measured"
    if isinstance(value, (int, float)) and 0 <= value <= 1:
        return f"{value * 100:.1f}%"
    return str(value)


def table(rows: list[tuple[str, str]], headers: tuple[str, str] = ("Metric", "Score")) -> str:
    lines = [f"| {headers[0]} | {headers[1]} |", "|---|---|"]
    lines += [f"| {name} | {value} |" for name, value in rows]
    return "\n".join(lines)


def section(title: str, metrics: dict, keys: list[str]) -> str:
    rows = [(METRIC_LABELS.get(k, k), pct(metrics[k])) for k in keys if k in metrics]
    return f"### {title}\n\n{table(rows)}\n" if rows else ""


def render_report(
    course: dict,
    config: dict,
    rag: dict | None,
    personal: dict | None,
    judge_model: str,
) -> str:
    parts = [
        "# Evaluation results",
        "",
        f"Course **{course['title']}** — {course['unit_count']} content units, "
        f"{course['topic_count']} topics, {course['source_count']} sources.",
        f"Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} by the standalone "
        "harness, driving the running app over its public HTTP API.",
        "",
        f"App models: generation `{config['models']['generation']}`, vision "
        f"`{config['models']['vision']}`, verifier `{config['models']['verifier']}`. "
        f"Harness judge: `{judge_model}`. Embeddings `{config['embedding_model']}` (local).",
        "",
        "Methodology is in [METHODOLOGY.md](METHODOLOGY.md).",
        "",
    ]

    if rag:
        m = rag["metrics"]
        parts += [
            "## Retrieval and generation",
            "",
            f"{m.get('total_cases', 0)} test cases: {m.get('answerable_cases', 0)} answerable with "
            f"known source locations, {m.get('off_material_cases', 0)} off-material.",
            "",
            section("RAGAS", m, ["faithfulness", "answer_relevancy",
                                 "llm_context_precision_with_reference", "context_recall"]),
            section("Source-location accuracy", m, ["source_hit_rate", "mean_reciprocal_rank",
                                                    "source_recall", "source_precision_at_k"]),
            section("Refusal behaviour", m, ["correct_refusal_rate", "false_refusal_rate",
                                             "refusal_f1"]),
        ]

        latency = {k: v for k, v in m.items() if k.startswith("latency_")}
        if latency:
            parts.append(
                "### Answer latency\n\n"
                + table([(k.replace("latency_", "").replace("_", " "), f"{v} ms")
                         for k, v in latency.items()])
                + "\n"
            )

        misses = [c for c in rag["cases"]
                  if c["expected_behavior"] == "answerable" and not c["retrieved_ground_truth"]]
        wrong_refusals = [c for c in rag["cases"]
                          if c["expected_behavior"] == "answerable" and c["refused"]]
        if misses or wrong_refusals:
            parts.append("### Cases the system got wrong\n")
            for case in (misses + wrong_refusals)[:6]:
                parts.append(
                    f"- **{case['question']}**\n"
                    f"  - expected source: {case['ground_truth_locator'] or 'unknown'}\n"
                    f"  - status: `{case['grounding_status']}`"
                )
            parts.append("")

    if personal:
        m = personal["metrics"]
        parts += ["## Personalization", ""]
        rows = []
        for arm in ("adaptive", "control"):
            data = m.get(arm)
            if not isinstance(data, dict):
                continue
            rows.append(
                f"| {arm} | {pct(data.get('mean_true_mastery_gain'))} | "
                f"{pct(data.get('mean_estimated_mastery_gain'))} | "
                f"{pct(data.get('mean_calibration_error'))} | "
                f"{pct(data.get('question_repetition_rate'))} | {data.get('total_questions')} |"
            )
        if rows:
            parts += [
                "| Arm | True mastery gain | Estimated gain | Calibration error | "
                "Question repetition | Questions |",
                "|---|---|---|---|---|---|",
                *rows,
                "",
            ]

        advantage = m.get("adaptive_advantage")
        if isinstance(advantage, dict):
            relative = advantage.get("relative")
            parts.append(
                f"**Adaptive advantage: {pct(advantage.get('absolute'))} additional true mastery "
                f"gain over the non-adaptive control arm"
                + (f", {relative * 100:.1f}% relative.**" if relative is not None else ".**")
            )
            parts.append("")

        adaptive = m.get("adaptive")
        if isinstance(adaptive, dict) and isinstance(adaptive.get("by_persona"), dict):
            parts.append("### True mastery gain by persona\n")
            parts.append(
                table([(p, pct(v)) for p, v in adaptive["by_persona"].items()], ("Persona", "Gain"))
            )
            parts.append("")

    return "\n".join(part for part in parts if part)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evaluate a running Study Companion instance over its HTTP API"
    )
    parser.add_argument("--app", default=os.environ.get("APP_URL", "http://localhost:8000"))
    parser.add_argument("--course", required=True, help="course title or id")
    parser.add_argument("--judge-model", default="openai/gpt-oss-120b")
    parser.add_argument("--tokens-per-minute", type=int, default=4000,
                        help="harness budget; keep below the app's so the app stays responsive")
    parser.add_argument("--answerable", type=int, default=10)
    parser.add_argument("--off-material", type=int, default=4)
    parser.add_argument("--sessions", type=int, default=3)
    parser.add_argument("--questions", type=int, default=3)
    parser.add_argument("--personas", nargs="*", default=["novice", "intermediate", "advanced"])
    parser.add_argument("--testset", type=Path, help="reuse a saved test set instead of building one")
    parser.add_argument("--skip-rag", action="store_true")
    parser.add_argument("--skip-personalization", action="store_true")
    parser.add_argument("--skip-ragas", action="store_true", help="retrieval and refusal metrics only")
    parser.add_argument("--out", type=Path, default=RESULTS_DIR)
    args = parser.parse_args()

    client = StudyCompanionClient(args.app)
    health = client.health()
    if health.get("status") != "ok":
        raise SystemExit(f"App is not healthy: {health}")
    print(f"App healthy at {args.app} (realtime: {health.get('realtime')})")

    config = client.config()
    course = client.find_course(args.course)
    print(f"Course: {course['title']} — {course['unit_count']} units\n")

    students = client.students()
    student = students[0] if students else client.create_student("Evaluation learner")

    judge = GroqJudge(args.judge_model, tokens_per_minute=args.tokens_per_minute)
    args.out.mkdir(parents=True, exist_ok=True)

    rag_payload = None
    personal_payload = None

    if not args.skip_rag:
        if args.testset and args.testset.exists():
            cases = testset.load(args.testset)
            print(f"Loaded {len(cases)} test cases from {args.testset}")
        else:
            print(f"Building test set ({args.answerable} answerable + {args.off_material} off-material)...")
            cases = testset.build(
                client, judge, course["id"],
                answerable=args.answerable, off_material=args.off_material,
            )
            testset.save(cases, args.out / "testset.json")
            print(f"  built {len(cases)} cases -> {args.out / 'testset.json'}")

        def on_progress(index: int, total: int, question: str) -> None:
            print(f"  [{index + 1}/{total}] {question[:68]}")

        print("\nAsking the app...")
        started = time.perf_counter()
        predictions = metric_module.collect(
            client, course["id"], student["id"], cases, on_progress=on_progress
        )
        print(f"  {len(predictions)} answers in {(time.perf_counter() - started) / 60:.1f} min")

        rag_metrics: dict = {}
        rag_metrics.update(metric_module.retrieval_metrics(predictions))
        rag_metrics.update(metric_module.refusal_metrics(predictions))
        rag_metrics.update(metric_module.latency_metrics(predictions))
        rag_metrics["total_cases"] = len(predictions)

        if not args.skip_ragas:
            print("\nScoring with RAGAS...")
            try:
                rag_metrics.update(metric_module.ragas_metrics(predictions, judge))
            except Exception as exc:
                print(f"  RAGAS failed: {str(exc)[:200]}")
                rag_metrics["ragas_error"] = str(exc)[:300]

        rag_payload = {
            "metrics": rag_metrics,
            "cases": [
                {
                    "question": p.case.question,
                    "expected_behavior": p.case.expected_behavior,
                    "reference_answer": p.case.reference_answer,
                    "ground_truth_locator": p.case.ground_truth_locator,
                    "modality": p.case.modality,
                    "answer": p.answer.text,
                    "grounding_status": p.answer.grounding_status,
                    "coverage": p.answer.coverage,
                    "refused": p.answer.refused,
                    "retrieved_ground_truth": p.retrieved_ground_truth,
                    "retrieved": [
                        f"{c.get('source_title')} {c.get('label')}" for c in p.answer.citations
                    ],
                    "latency_ms": p.answer.latency_ms,
                    "scores": getattr(p, "case_scores", {}),
                }
                for p in predictions
            ],
        }
        (args.out / "rag.json").write_text(json.dumps(rag_payload, indent=2), encoding="utf-8")
        print(f"\nRAG metrics: {json.dumps(rag_metrics, indent=2)}")

    if not args.skip_personalization:
        print("\nRunning simulated learners...")

        def on_session(arm: str, persona: str, index: int, total: int) -> None:
            print(f"  {arm:<9} {persona:<13} session {index}/{total}")

        personal_payload = personalization.run(
            client, course["id"],
            personas=args.personas,
            sessions_per_learner=args.sessions,
            questions_per_session=args.questions,
            compare_control=True,
            on_progress=on_session,
        )
        (args.out / "personalization.json").write_text(
            json.dumps(personal_payload, indent=2), encoding="utf-8"
        )
        print(f"\nPersonalization metrics: {json.dumps(personal_payload['metrics'], indent=2)}")

    report = render_report(course, config, rag_payload, personal_payload, args.judge_model)
    report_path = args.out / "RESULTS.md"
    report_path.write_text(report, encoding="utf-8")

    print(f"\nJudge used {judge.calls} calls, ~{judge.tokens_used:,} tokens")
    print(f"Report written to {report_path}")
    client.close()
    judge.close()


if __name__ == "__main__":
    main()
