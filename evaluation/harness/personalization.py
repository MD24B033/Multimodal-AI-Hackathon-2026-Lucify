from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Any

from harness.client import StudyCompanionClient

PERSONAS = {
    "novice": {"mean": -1.0, "spread": 0.5, "learning_rate": 0.42},
    "intermediate": {"mean": 0.0, "spread": 0.7, "learning_rate": 0.32},
    "advanced": {"mean": 1.0, "spread": 0.5, "learning_rate": 0.22},
}

DIFFICULTY_B = {"easy": -1.0, "medium": 0.0, "hard": 1.0}


def irt_probability(theta: float, difficulty: float, discrimination: float = 1.2) -> float:
    exponent = -discrimination * (theta - difficulty)
    return 1.0 / (1.0 + math.exp(max(-30.0, min(30.0, exponent))))


@dataclass
class SimulatedLearner:
    name: str
    persona: str
    arm: str
    ability: dict[str, float]
    learning_rate: float
    student_id: str = ""
    seen: set[str] = field(default_factory=set)
    repeats: int = 0
    total_questions: int = 0

    def answers_correctly(self, topic_id: str | None, difficulty: str, rng: random.Random) -> bool:
        theta = self.ability.get(topic_id or "", 0.0)
        return rng.random() < irt_probability(theta, DIFFICULTY_B.get(difficulty, 0.0))

    def study(self, topic_ids: list[str]) -> None:
        for topic_id in topic_ids:
            self.ability[topic_id] = min(3.0, self.ability.get(topic_id, 0.0) + self.learning_rate)

    def true_mastery(self, topic_ids: list[str]) -> float:
        if not topic_ids:
            return 0.0
        return sum(irt_probability(self.ability.get(t, 0.0), 0.0) for t in topic_ids) / len(topic_ids)


def _make_learner(persona: str, arm: str, topic_ids: list[str], rng: random.Random, index: int):
    template = PERSONAS[persona]
    return SimulatedLearner(
        name=f"{persona.title()} learner {index + 1}",
        persona=persona,
        arm=arm,
        ability={t: rng.gauss(template["mean"], template["spread"]) for t in topic_ids},
        learning_rate=template["learning_rate"],
    )


def _simulate_response(question: dict[str, Any], correct: bool, rng: random.Random) -> str:
    options = question.get("options") or []
    key = question.get("answer_key") or ""
    if options:
        if correct and key:
            return key
        wrong = [option for option in options if option != key]
        return rng.choice(wrong) if wrong else (key or options[0])
    return key if correct else "I am not sure how to approach this."


def run_session(
    client: StudyCompanionClient,
    course_id: str,
    learner: SimulatedLearner,
    rng: random.Random,
    *,
    questions_per_session: int,
) -> dict[str, Any]:
    assessment = client.create_assessment(
        course_id,
        learner.student_id,
        num_questions=questions_per_session,
        qtypes=["mcq"],
        adaptive=(learner.arm == "adaptive"),
        verify=False,
    )

    items = assessment.get("items") or []
    if not items:
        return {"questions": 0, "accuracy": None}

    responses: dict[str, str] = {}
    studied: list[str] = []
    correct_count = 0

    for item in items:
        question = item["question"]
        learner.total_questions += 1
        fingerprint = question["stem"].strip().lower()
        if fingerprint in learner.seen:
            learner.repeats += 1
        else:
            learner.seen.add(fingerprint)

        correct = learner.answers_correctly(
            question.get("topic_id"), question.get("difficulty", "medium"), rng
        )
        correct_count += int(correct)
        responses[question["id"]] = _simulate_response(question, correct, rng)
        if question.get("topic_id"):
            studied.append(question["topic_id"])

    result = client.submit_assessment(assessment["id"], responses)
    learner.study(sorted(set(studied)))

    return {
        "questions": len(responses),
        "accuracy": round(correct_count / len(responses), 4),
        "score_percent": result["report"]["score_percent"],
        "topics": sorted(set(studied)),
    }


def _mean(values: list[float]) -> float | None:
    clean = [v for v in values if v is not None]
    return round(sum(clean) / len(clean), 4) if clean else None


def run(
    client: StudyCompanionClient,
    course_id: str,
    *,
    personas: list[str] | None = None,
    learners_per_persona: int = 1,
    sessions_per_learner: int = 3,
    questions_per_session: int = 3,
    compare_control: bool = True,
    seed: int = 11,
    on_progress=None,
) -> dict[str, Any]:
    personas = personas or ["novice", "intermediate", "advanced"]
    rng = random.Random(seed)

    topics = [t for t in client.topics(course_id) if t["kind"] == "subtopic"]
    topic_ids = [t["id"] for t in topics]
    if not topic_ids:
        raise RuntimeError("Course has no subtopics; ingest material first")

    arms = ["adaptive"] + (["control"] if compare_control else [])
    results: dict[str, list[dict[str, Any]]] = {arm: [] for arm in arms}

    for arm in arms:
        for persona in personas:
            for index in range(learners_per_persona):
                learner = _make_learner(
                    persona, arm, topic_ids, random.Random(rng.randint(0, 10**6)), index
                )
                student = client.create_student(f"{learner.name} [{arm}] {rng.randint(1000,9999)}")
                learner.student_id = student["id"]

                initial_true = learner.true_mastery(topic_ids)
                initial_estimate = client.dashboard(learner.student_id, course_id)["overall_mastery"]

                sessions = []
                learner_rng = random.Random(rng.randint(0, 10**6))
                for session_index in range(sessions_per_learner):
                    if on_progress:
                        on_progress(arm, persona, session_index + 1, sessions_per_learner)
                    outcome = run_session(
                        client,
                        course_id,
                        learner,
                        learner_rng,
                        questions_per_session=questions_per_session,
                    )
                    outcome["session"] = session_index + 1
                    outcome["estimated_mastery"] = client.dashboard(
                        learner.student_id, course_id
                    )["overall_mastery"]
                    outcome["true_mastery"] = round(learner.true_mastery(topic_ids), 4)
                    sessions.append(outcome)

                final_true = learner.true_mastery(topic_ids)
                final_estimate = client.dashboard(learner.student_id, course_id)["overall_mastery"]

                results[arm].append(
                    {
                        "student_id": learner.student_id,
                        "name": learner.name,
                        "persona": persona,
                        "arm": arm,
                        "initial_true_mastery": round(initial_true, 4),
                        "final_true_mastery": round(final_true, 4),
                        "true_mastery_gain": round(final_true - initial_true, 4),
                        "initial_estimated_mastery": round(initial_estimate, 4),
                        "final_estimated_mastery": round(final_estimate, 4),
                        "estimated_mastery_gain": round(final_estimate - initial_estimate, 4),
                        "calibration_error": round(abs(final_estimate - final_true), 4),
                        "questions_asked": learner.total_questions,
                        "repeated_questions": learner.repeats,
                        "repetition_rate": round(learner.repeats / learner.total_questions, 4)
                        if learner.total_questions
                        else 0.0,
                        "sessions": sessions,
                    }
                )

    metrics: dict[str, Any] = {}
    for arm, learners in results.items():
        if not learners:
            continue
        metrics[arm] = {
            "learners": len(learners),
            "mean_true_mastery_gain": _mean([x["true_mastery_gain"] for x in learners]),
            "mean_estimated_mastery_gain": _mean([x["estimated_mastery_gain"] for x in learners]),
            "mean_calibration_error": _mean([x["calibration_error"] for x in learners]),
            "question_repetition_rate": _mean([x["repetition_rate"] for x in learners]),
            "total_questions": sum(x["questions_asked"] for x in learners),
            "by_persona": {
                persona: _mean(
                    [x["true_mastery_gain"] for x in learners if x["persona"] == persona]
                )
                for persona in {x["persona"] for x in learners}
            },
        }

    if "adaptive" in metrics and "control" in metrics:
        adaptive_gain = metrics["adaptive"]["mean_true_mastery_gain"] or 0.0
        control_gain = metrics["control"]["mean_true_mastery_gain"] or 0.0
        metrics["adaptive_advantage"] = {
            "absolute": round(adaptive_gain - control_gain, 4),
            "relative": round((adaptive_gain - control_gain) / control_gain, 4)
            if control_gain
            else None,
        }

    return {"metrics": metrics, "learners": results}
