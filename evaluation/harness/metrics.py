from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from harness.client import Answer, StudyCompanionClient
from harness.judge import GroqJudge
from harness.testset import TestCase

logger = logging.getLogger(__name__)

REFUSED = {"refused", "unsupported"}


@dataclass
class Prediction:
    case: TestCase
    answer: Answer
    contexts: list[str] = field(default_factory=list)

    @property
    def retrieved_ground_truth(self) -> bool:
        return bool(set(self.answer.retrieved_unit_ids) & set(self.case.ground_truth_unit_ids))


def collect(
    client: StudyCompanionClient,
    course_id: str,
    student_id: str,
    cases: list[TestCase],
    *,
    on_progress=None,
) -> list[Prediction]:
    session_id = client.create_session(course_id, student_id, title="Evaluation run")
    predictions: list[Prediction] = []

    for index, case in enumerate(cases):
        if on_progress:
            on_progress(index, len(cases), case.question)
        answer = client.ask(session_id, case.question)
        contexts = [citation.get("excerpt", "") for citation in answer.citations]
        predictions.append(Prediction(case=case, answer=answer, contexts=contexts))

    return predictions


def retrieval_metrics(predictions: list[Prediction]) -> dict[str, Any]:
    answerable = [p for p in predictions if p.case.expected_behavior == "answerable"]
    scored = [p for p in answerable if p.case.ground_truth_unit_ids]
    if not scored:
        return {}

    hits = 0
    reciprocal = []
    precisions = []
    recalls = []

    for prediction in scored:
        truth = set(prediction.case.ground_truth_unit_ids)
        retrieved = prediction.answer.retrieved_unit_ids
        matched = [i for i, unit_id in enumerate(retrieved) if unit_id in truth]
        if matched:
            hits += 1
            reciprocal.append(1.0 / (matched[0] + 1))
        else:
            reciprocal.append(0.0)
        if retrieved:
            precisions.append(len(set(retrieved) & truth) / len(retrieved))
        recalls.append(len(set(retrieved) & truth) / len(truth))

    return {
        "source_hit_rate": round(hits / len(scored), 4),
        "mean_reciprocal_rank": round(sum(reciprocal) / len(scored), 4),
        "source_precision_at_k": round(sum(precisions) / len(precisions), 4) if precisions else 0.0,
        "source_recall": round(sum(recalls) / len(recalls), 4) if recalls else 0.0,
        "answerable_cases": len(scored),
    }


def refusal_metrics(predictions: list[Prediction]) -> dict[str, Any]:
    off_material = [p for p in predictions if p.case.expected_behavior == "off_material"]
    answerable = [p for p in predictions if p.case.expected_behavior == "answerable"]

    correct = sum(1 for p in off_material if p.answer.grounding_status in REFUSED)
    false_refusals = sum(1 for p in answerable if p.answer.grounding_status in REFUSED)

    metrics: dict[str, Any] = {
        "off_material_cases": len(off_material),
        "correct_refusal_rate": round(correct / len(off_material), 4) if off_material else None,
        "false_refusal_rate": round(false_refusals / len(answerable), 4) if answerable else None,
    }

    if off_material and answerable:
        true_positive = correct
        false_positive = false_refusals
        false_negative = len(off_material) - correct
        precision = (
            true_positive / (true_positive + false_positive)
            if (true_positive + false_positive)
            else 0.0
        )
        recall = (
            true_positive / (true_positive + false_negative)
            if (true_positive + false_negative)
            else 0.0
        )
        metrics["refusal_f1"] = (
            round(2 * precision * recall / (precision + recall), 4) if (precision + recall) else 0.0
        )
    return metrics


def latency_metrics(predictions: list[Prediction]) -> dict[str, Any]:
    values = sorted(p.answer.latency_ms for p in predictions if p.answer.latency_ms)
    if not values:
        return {}
    return {
        "latency_median_ms": values[len(values) // 2],
        "latency_p90_ms": values[min(len(values) - 1, int(len(values) * 0.9))],
        "latency_max_ms": values[-1],
    }


def ragas_metrics(predictions: list[Prediction], judge: GroqJudge) -> dict[str, Any]:
    from langchain_openai import ChatOpenAI
    from ragas import EvaluationDataset, RunConfig, evaluate
    from ragas.dataset_schema import SingleTurnSample
    from ragas.embeddings import LangchainEmbeddingsWrapper
    from ragas.llms import LangchainLLMWrapper
    from ragas.metrics import (
        Faithfulness,
        LLMContextPrecisionWithReference,
        LLMContextRecall,
        ResponseRelevancy,
    )

    scored = [
        p
        for p in predictions
        if p.case.expected_behavior == "answerable"
        and p.contexts
        and p.answer.text
        and p.answer.grounding_status not in REFUSED
    ]
    if not scored:
        return {}

    samples = [
        SingleTurnSample(
            user_input=p.case.question,
            response=p.answer.text,
            retrieved_contexts=p.contexts,
            reference=p.case.reference_answer or "",
        )
        for p in scored
    ]

    llm = LangchainLLMWrapper(
        ChatOpenAI(
            model=judge.model,
            base_url=judge.base_url,
            api_key=judge.api_key,
            temperature=0.0,
            max_retries=8,
            timeout=180.0,
        )
    )
    embeddings = LangchainEmbeddingsWrapper(_local_embeddings())

    result = evaluate(
        dataset=EvaluationDataset(samples=samples),
        metrics=[
            Faithfulness(llm=llm),
            ResponseRelevancy(llm=llm, embeddings=embeddings, strictness=1),
            LLMContextPrecisionWithReference(llm=llm),
            LLMContextRecall(llm=llm),
        ],
        run_config=RunConfig(timeout=600, max_retries=10, max_wait=90, max_workers=1),
        show_progress=False,
        raise_exceptions=False,
    )

    frame = result.to_pandas()
    skip = {"user_input", "response", "retrieved_contexts", "reference"}
    aggregate: dict[str, Any] = {}
    for column in frame.columns:
        if column in skip:
            continue
        series = frame[column].dropna()
        if len(series):
            aggregate[column] = round(float(series.mean()), 4)

    for index, prediction in enumerate(scored):
        prediction.case_scores = {  # type: ignore[attr-defined]
            column: (
                None
                if frame[column].isna().iloc[index]
                else round(float(frame[column].iloc[index]), 4)
            )
            for column in frame.columns
            if column not in skip
        }

    return aggregate


def _local_embeddings():
    from langchain_core.embeddings import Embeddings
    from sentence_transformers import SentenceTransformer

    class LocalEmbeddings(Embeddings):
        def __init__(self, model_name: str = "BAAI/bge-small-en-v1.5"):
            self._model = SentenceTransformer(model_name)

        def embed_documents(self, texts: list[str]) -> list[list[float]]:
            vectors = self._model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
            return [vector.tolist() for vector in vectors]

        def embed_query(self, text: str) -> list[float]:
            return self._model.encode(
                text, normalize_embeddings=True, show_progress_bar=False
            ).tolist()

        async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
            return self.embed_documents(texts)

        async def aembed_query(self, text: str) -> list[float]:
            return self.embed_query(text)

    return LocalEmbeddings()
