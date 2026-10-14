from __future__ import annotations

import math
from dataclasses import dataclass

DIFFICULTY_VALUES = {"easy": -1.0, "medium": 0.0, "hard": 1.0}


@dataclass
class Response:
    difficulty: float
    discrimination: float
    correct: bool


def difficulty_to_value(label: str | None) -> float:
    return DIFFICULTY_VALUES.get((label or "medium").lower(), 0.0)


def probability(theta: float, difficulty: float, discrimination: float = 1.0, guess: float = 0.0) -> float:
    exponent = -discrimination * (theta - difficulty)
    logistic = 1.0 / (1.0 + math.exp(max(-30.0, min(30.0, exponent))))
    return guess + (1.0 - guess) * logistic


def estimate_theta(
    responses: list[Response],
    *,
    prior_mean: float = 0.0,
    prior_sd: float = 1.0,
    iterations: int = 40,
) -> tuple[float, float]:
    if not responses:
        return prior_mean, prior_sd

    theta = prior_mean
    for _ in range(iterations):
        gradient = (prior_mean - theta) / (prior_sd**2)
        information = 1.0 / (prior_sd**2)

        for response in responses:
            expected = probability(theta, response.difficulty, response.discrimination)
            gradient += response.discrimination * ((1.0 if response.correct else 0.0) - expected)
            information += (response.discrimination**2) * expected * (1.0 - expected)

        if information <= 1e-9:
            break
        step = gradient / information
        theta += max(-1.0, min(1.0, step))
        if abs(step) < 1e-5:
            break

    standard_error = 1.0 / math.sqrt(max(information, 1e-6))
    return max(-4.0, min(4.0, theta)), standard_error


def target_difficulty(theta: float) -> str:
    if theta < -0.5:
        return "easy"
    if theta > 0.6:
        return "hard"
    return "medium"


def information_at(theta: float, difficulty: float, discrimination: float = 1.0) -> float:
    expected = probability(theta, difficulty, discrimination)
    return (discrimination**2) * expected * (1.0 - expected)
