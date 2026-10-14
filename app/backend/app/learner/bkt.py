from __future__ import annotations

from dataclasses import dataclass

DIFFICULTY_SLIP = {"easy": 0.06, "medium": 0.10, "hard": 0.18}
DIFFICULTY_GUESS = {"easy": 0.25, "medium": 0.18, "hard": 0.12}


@dataclass(frozen=True)
class BKTParameters:
    prior: float = 0.25
    learn: float = 0.18
    slip: float = 0.10
    guess: float = 0.20
    forget: float = 0.02

    def for_difficulty(self, difficulty: str | None) -> "BKTParameters":
        key = (difficulty or "medium").lower()
        return BKTParameters(
            prior=self.prior,
            learn=self.learn,
            slip=DIFFICULTY_SLIP.get(key, self.slip),
            guess=DIFFICULTY_GUESS.get(key, self.guess),
            forget=self.forget,
        )


DEFAULT_PARAMETERS = BKTParameters()


def posterior_given_observation(p_known: float, correct: bool, params: BKTParameters) -> float:
    if correct:
        numerator = p_known * (1 - params.slip)
        denominator = numerator + (1 - p_known) * params.guess
    else:
        numerator = p_known * params.slip
        denominator = numerator + (1 - p_known) * (1 - params.guess)
    if denominator <= 0:
        return p_known
    return numerator / denominator


def update(p_known: float, correct: bool, difficulty: str | None = None, params: BKTParameters | None = None) -> float:
    params = (params or DEFAULT_PARAMETERS).for_difficulty(difficulty)
    posterior = posterior_given_observation(_clamp(p_known), correct, params)
    transitioned = posterior + (1 - posterior) * params.learn
    return _clamp(transitioned)


def update_partial(p_known: float, score: float, difficulty: str | None = None, params: BKTParameters | None = None) -> float:
    score = max(0.0, min(1.0, score))
    as_correct = update(p_known, True, difficulty, params)
    as_incorrect = update(p_known, False, difficulty, params)
    return _clamp(as_incorrect + (as_correct - as_incorrect) * score)


def apply_forgetting(p_known: float, days_elapsed: float, params: BKTParameters | None = None) -> float:
    params = params or DEFAULT_PARAMETERS
    if days_elapsed <= 0:
        return _clamp(p_known)
    retention = (1 - params.forget) ** days_elapsed
    return _clamp(p_known * retention)


def probability_correct(p_known: float, difficulty: str | None = None, params: BKTParameters | None = None) -> float:
    params = (params or DEFAULT_PARAMETERS).for_difficulty(difficulty)
    return _clamp(p_known * (1 - params.slip) + (1 - p_known) * params.guess)


def _clamp(value: float, low: float = 0.01, high: float = 0.99) -> float:
    return max(low, min(high, value))
