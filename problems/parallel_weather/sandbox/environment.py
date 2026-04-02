"""Parallel Weather judge-side environment.

Tracks timing from get_questions -> final submission and checks correctness.
"""

from __future__ import annotations

import json
import random
import time

TOLERANCE = 0.01

# ---------------------------------------------------------------------------
# Randomized NL response templates — prevents regex / pattern-matching.
# ---------------------------------------------------------------------------

_TEMP_TEMPLATES = [
    "The current temperature in {city} is {val}°C.",
    "Right now it is {val} degrees Celsius in {city}.",
    "{city} weather station (ID: WS-{noise}) reports a temperature of {val}°C.",
    "Temperature data for {city}: {val}°C (updated {noise} seconds ago).",
    "At monitoring point #{noise}, {city} temperature reads {val} degrees Celsius.",
    "Recorded at {city}: {val}°C. Sensor batch #{noise}.",
    "In {city}, the base temperature is {a}°C with a {b}°C adjustment, yielding {val}°C.",
    "{city} temperature: {a} + {b} = {val} degrees Celsius.",
    "After applying {a}°C ground measurement and {b}°C altitude correction, {city} is at {val}°C.",
    "Station #{noise} calibration for {city}: base {a}°C, offset {b}°C, result {val}°C.",
]

_HUMID_TEMPLATES = [
    "The current humidity in {city} is {val}%.",
    "Relative humidity in {city} is {val} percent right now.",
    "{city} humidity sensor (ID: HS-{noise}) reads {val}%.",
    "Humidity data for {city}: {val}% (measured {noise} seconds ago).",
    "At station #{noise}, {city} humidity is {val}% RH.",
    "Recorded at {city}: {val}% humidity. Probe #{noise}.",
    "In {city}, ground humidity is {a}% plus {b}% atmospheric moisture, totaling {val}%.",
    "{city} humidity: {a} + {b} = {val} percent.",
    "Combining {a}% surface reading with {b}% upper-air data, {city} humidity is {val}%.",
    "Sensor #{noise} for {city}: base {a}%, correction {b}%, final humidity {val}%.",
]


def _format_response(city: str, val: float, templates: list[str]) -> str:
    tpl = random.choice(templates)
    noise = random.randint(100, 999)
    a = round(random.uniform(val - 20, val + 20), 1)
    b = round(val - a, 1)
    return tpl.format(city=city, val=val, noise=noise, a=a, b=b)


def _generate_nl_texts(weather_data: dict[str, dict[str, float]]) -> dict[str, dict[str, str]]:
    """Pre-generate NL response text for every city's temperature and humidity."""
    texts: dict[str, dict[str, str]] = {}
    for city, metrics in weather_data.items():
        texts[city] = {
            "temperature_text": _format_response(city, metrics["temperature"], _TEMP_TEMPLATES),
            "humidity_text": _format_response(city, metrics["humidity"], _HUMID_TEMPLATES),
        }
    return texts


class ParallelWeatherEnvironment:

    def __init__(self, case_data: dict, max_allowed_time: float = 27.0) -> None:
        self._weather_data: dict[str, dict[str, float]] = case_data["weather_data"]
        self._questions: list[dict] = case_data["questions"]
        self._max_allowed_time = max_allowed_time

        self._start_time: float | None = None
        self._end_time: float | None = None
        self._submitted = False
        self._success = False
        self._error_detail: str = ""
        self._partial_answers: dict[int, dict[str, float]] = {}
        self._question_by_index: dict[int, dict] = {
            int(q["q_index"]): q for q in self._questions
        }

    @property
    def done(self) -> bool:
        return self._submitted

    @property
    def success(self) -> bool:
        return self._success

    @property
    def elapsed_time(self) -> float:
        if self._start_time is None:
            return 0.0
        end = self._end_time if self._end_time is not None else time.time()
        return end - self._start_time

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def get_questions(self) -> str:
        self._start_time = time.time()
        nl_texts = _generate_nl_texts(self._weather_data)
        payload = {
            "questions": self._questions,
            "nl_texts": nl_texts,
        }
        return json.dumps(payload, ensure_ascii=False)

    def submit_answer(
        self,
        q_index: int | str,
        city_a_temperature: float | str,
        city_a_humidity: float | str,
        city_b_temperature: float | str,
        city_b_humidity: float | str,
    ) -> str:
        """Submit one answer. Auto-finalizes when all questions are submitted."""
        if self._submitted:
            return "wrong: already finalized"
        if self._start_time is None:
            return "wrong: call get_questions() first"

        try:
            idx = int(q_index)
            normalized = {
                "city_a_temperature": float(city_a_temperature),
                "city_a_humidity": float(city_a_humidity),
                "city_b_temperature": float(city_b_temperature),
                "city_b_humidity": float(city_b_humidity),
            }
        except (TypeError, ValueError):
            return "wrong: submit_answer requires numeric q_index + 4 numeric values"

        if idx not in self._question_by_index:
            return f"wrong: invalid q_index={idx}"

        self._partial_answers[idx] = normalized

        if len(self._partial_answers) < len(self._questions):
            return f"accepted: {len(self._partial_answers)}/{len(self._questions)}"

        return self._finalize()

    def submit_answers(self, answers_json: str) -> str:
        """Legacy bulk submit: accepts JSON array, delegates to submit_answer."""
        if self._submitted:
            return "wrong: already finalized"
        if self._start_time is None:
            return "wrong: call get_questions() first"

        try:
            answers = json.loads(answers_json)
        except (json.JSONDecodeError, TypeError) as e:
            return self._fail(f"invalid JSON: {e}")

        if not isinstance(answers, list) or len(answers) != len(self._questions):
            return self._fail(
                f"expected list of {len(self._questions)} answers, "
                f"got {type(answers).__name__} len={len(answers) if isinstance(answers, list) else '?'}"
            )

        for item in answers:
            if not isinstance(item, dict):
                return self._fail("each answer must be an object")
            try:
                resp = self.submit_answer(
                    item["q_index"],
                    item["city_a_temperature"],
                    item["city_a_humidity"],
                    item["city_b_temperature"],
                    item["city_b_humidity"],
                )
            except KeyError as e:
                return self._fail(f"missing field {e}")
            if resp.startswith("wrong:"):
                return resp

        return resp  # last submit_answer returns "correct" or "wrong: ..."

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    def compute_score(self) -> int:
        if not self._success:
            return 0
        return 100 if self.elapsed_time <= self._max_allowed_time else 30

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _fail(self, detail: str) -> str:
        self._success = False
        self._error_detail = detail
        self._submitted = True
        self._end_time = time.time()
        return f"wrong: {detail}"

    def _finalize(self) -> str:
        self._end_time = time.time()
        self._submitted = True

        for q in self._questions:
            q_idx = int(q["q_index"])
            ans = self._partial_answers.get(q_idx)
            if not isinstance(ans, dict):
                self._success = False
                self._error_detail = f"missing answer for q_index={q_idx}"
                return f"wrong: {self._error_detail}"

            expected_a = self._weather_data[q["city_a"]]
            expected_b = self._weather_data[q["city_b"]]

            for field, expected_val in [
                ("city_a_temperature", expected_a["temperature"]),
                ("city_a_humidity", expected_a["humidity"]),
                ("city_b_temperature", expected_b["temperature"]),
                ("city_b_humidity", expected_b["humidity"]),
            ]:
                try:
                    actual_val = float(ans[field])
                except (KeyError, TypeError, ValueError):
                    self._success = False
                    self._error_detail = f"q_index={q_idx}: invalid '{field}'"
                    return f"wrong: {self._error_detail}"

                if abs(actual_val - expected_val) > TOLERANCE:
                    self._success = False
                    self._error_detail = (
                        f"q_index={q_idx}: {field} expected {expected_val}, got {actual_val}"
                    )
                    return f"wrong: {self._error_detail}"

        self._success = True
        return "correct"
