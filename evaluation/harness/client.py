from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any

import httpx


class AppError(RuntimeError):
    pass


@dataclass
class Answer:
    question: str
    text: str
    grounding_status: str
    coverage: float
    citations: list[dict[str, Any]]
    # What retrieval put in front of the generator, and what the generator chose to
    # cite from it. These are different things: scoring retrieval from the citations
    # counts a correct passage as a miss whenever the model cited a neighbour.
    retrieved_unit_ids: list[str]
    cited_unit_ids: list[str]
    retrieved_labels: list[str]
    margin: float
    latency_ms: int

    @property
    def refused(self) -> bool:
        return self.grounding_status in {"refused", "unsupported"}


class StudyCompanionClient:
    def __init__(self, base_url: str, timeout: float = 300.0, access_key: str | None = None):
        self.base_url = base_url.rstrip("/")
        # The app requires a pre-shared key whenever ACCESS_KEYS is configured, so the
        # harness has to present one too. Without it every call comes back 401.
        key = access_key or os.environ.get("ACCESS_KEY") or os.environ.get("LUCIFY_ACCESS_KEY", "")
        headers = {"X-Access-Key": key.strip()} if key.strip() else {}
        self._client = httpx.Client(timeout=timeout, headers=headers)

    def close(self) -> None:
        self._client.close()

    def _request(self, method: str, path: str, **kwargs) -> Any:
        response = self._client.request(method, f"{self.base_url}{path}", **kwargs)
        if response.status_code >= 400:
            raise AppError(f"{method} {path} -> {response.status_code}: {response.text[:300]}")
        if response.status_code == 204:
            return None
        return response.json()

    def health(self) -> dict[str, Any]:
        return self._request("GET", "/health")

    def config(self) -> dict[str, Any]:
        return self._request("GET", "/api/config")

    def courses(self) -> list[dict[str, Any]]:
        return self._request("GET", "/api/courses")

    def find_course(self, title_or_id: str) -> dict[str, Any]:
        courses = self.courses()
        for course in courses:
            if course["id"] == title_or_id or course["title"] == title_or_id:
                return course
        raise AppError(f"No course matching {title_or_id!r}. Available: {[c['title'] for c in courses]}")

    def units(
        self,
        course_id: str,
        *,
        modality: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if modality:
            params["modality"] = modality
        return self._request("GET", f"/api/courses/{course_id}/units", params=params)

    def all_units(self, course_id: str) -> list[dict[str, Any]]:
        """Every unit, paginated. The endpoint caps a page at 200, so a single call
        silently truncated a 327-unit course: test cases could only ever be drawn
        from the first 200 units."""
        collected: list[dict[str, Any]] = []
        offset = 0
        while True:
            page = self.units(course_id, limit=200, offset=offset)
            collected.extend(page)
            if len(page) < 200:
                return collected
            offset += len(page)

    def sources(self, course_id: str) -> list[dict[str, Any]]:
        return self._request("GET", f"/api/courses/{course_id}/sources")

    def topics(self, course_id: str) -> list[dict[str, Any]]:
        return self._request("GET", f"/api/courses/{course_id}/topics")

    def create_student(self, name: str) -> dict[str, Any]:
        return self._request("POST", "/api/learner/students", json={"name": name})

    def students(self, include_simulated: bool = False) -> list[dict[str, Any]]:
        return self._request(
            "GET", "/api/learner/students", params={"include_simulated": include_simulated}
        )

    def create_session(self, course_id: str, student_id: str, title: str | None = None) -> str:
        payload = self._request(
            "POST",
            "/api/chat/sessions",
            json={"course_id": course_id, "student_id": student_id, "title": title},
        )
        return payload["id"]

    def ask(
        self,
        session_id: str,
        question: str,
        *,
        source_ids: list[str] | None = None,
        language: str = "en",
    ) -> Answer:
        started = time.perf_counter()
        payload = self._request(
            "POST",
            f"/api/chat/sessions/{session_id}/ask",
            json={
                "message": question,
                "language": language,
                "speak": False,
                "source_ids": source_ids,
            },
        )
        message = payload["message"]
        retrieval = payload.get("retrieval") or {}
        cited = [citation["unit_id"] for citation in (message.get("citations") or [])]
        # Older builds did not report the retrieval set; fall back to the citations so
        # the harness still runs, and say so in the results rather than silently
        # measuring the wrong thing.
        retrieved = message.get("retrieved_unit_ids") or retrieval.get("unit_ids") or cited
        return Answer(
            question=question,
            text=message.get("content", ""),
            grounding_status=message.get("grounding_status") or "unknown",
            coverage=float(message.get("coverage") or 0.0),
            citations=message.get("citations") or [],
            retrieved_unit_ids=list(retrieved),
            cited_unit_ids=cited,
            retrieved_labels=list(retrieval.get("labels") or []),
            margin=float(retrieval.get("margin") or 0.0),
            latency_ms=message.get("latency_ms") or int((time.perf_counter() - started) * 1000),
        )

    def search(self, course_id: str, query: str, top_k: int = 8) -> dict[str, Any]:
        payload = self._request(
            "POST",
            "/api/chat/search",
            json={"course_id": course_id, "query": query, "top_k": top_k},
        )
        return payload

    def create_assessment(
        self,
        course_id: str,
        student_id: str,
        *,
        num_questions: int = 4,
        qtypes: list[str] | None = None,
        adaptive: bool = True,
        verify: bool = False,
        kind: str = "quiz",
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/api/assessments",
            json={
                "course_id": course_id,
                "student_id": student_id,
                "kind": kind,
                "num_questions": num_questions,
                "qtypes": qtypes or ["mcq"],
                "adaptive": adaptive,
                "verify": verify,
            },
        )

    def submit_assessment(self, assessment_id: str, responses: dict[str, str]) -> dict[str, Any]:
        return self._request(
            "POST", f"/api/assessments/{assessment_id}/submit", json={"responses": responses}
        )

    def dashboard(self, student_id: str, course_id: str) -> dict[str, Any]:
        return self._request(
            "GET",
            f"/api/learner/students/{student_id}/dashboard",
            params={"course_id": course_id},
        )

    def mastery(self, student_id: str, course_id: str) -> list[dict[str, Any]]:
        return self._request(
            "GET",
            f"/api/learner/students/{student_id}/mastery",
            params={"course_id": course_id},
        )

    def notes(
        self,
        course_id: str,
        student_id: str,
        *,
        note_format: str,
        topic_id: str | None = None,
        free_text: str | None = None,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/api/notes",
            json={
                "course_id": course_id,
                "student_id": student_id,
                "note_format": note_format,
                "topic_id": topic_id,
                "free_text": free_text,
            },
        )
