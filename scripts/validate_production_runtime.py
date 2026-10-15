#!/usr/bin/env python3
"""Validate the mounted CPU classifier and public ask admission without provider calls."""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import platform
import resource
import statistics
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

LABELS = frozenset({"SEARCH_KNOWLEDGE", "CLARIFY", "UNSUPPORTED"})


class ValidationInputError(ValueError):
    """A fixture does not have the expected, privacy-safe validation shape."""


def _load_validation_cases(predictions_path: Path, dataset_path: Path):
    try:
        saved = json.loads(predictions_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValidationInputError("invalid_predictions_fixture") from exc
    if not isinstance(saved, list) or not saved:
        raise ValidationInputError("predictions_must_be_nonempty_list")

    try:
        with dataset_path.open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            required_columns = {"question_id", "question", "label"}
            if not reader.fieldnames or not required_columns.issubset(
                set(reader.fieldnames)
            ):
                raise ValidationInputError("dataset_columns_missing")
            source_rows = list(reader)
    except (OSError, UnicodeError, csv.Error) as exc:
        raise ValidationInputError("invalid_dataset_fixture") from exc

    by_id = {}
    for row in source_rows:
        question_id = (row.get("question_id") or "").strip()
        question = row.get("question") or ""
        label = (row.get("label") or "").strip()
        if not question_id or not question.strip() or label not in LABELS:
            raise ValidationInputError("invalid_dataset_row")
        if question_id in by_id:
            raise ValidationInputError("duplicate_dataset_id")
        by_id[question_id] = (question, label)

    cases = []
    seen_ids = set()
    dataset_actual_mismatches = 0
    for item in saved:
        if not isinstance(item, dict):
            raise ValidationInputError("invalid_prediction_row")
        question_id = item.get("question_id")
        question = item.get("question")
        actual = item.get("actual")
        expected = item.get("predicted")
        if (
            not isinstance(question_id, str)
            or not question_id.strip()
            or not isinstance(question, str)
            or not question.strip()
            or actual not in LABELS
            or expected not in LABELS
        ):
            raise ValidationInputError("invalid_prediction_row")
        if question_id in seen_ids:
            raise ValidationInputError("duplicate_prediction_id")
        seen_ids.add(question_id)
        source = by_id.get(question_id)
        if source is None:
            raise ValidationInputError("prediction_id_missing_from_dataset")
        source_question, source_label = source
        if question != source_question or actual != source_label:
            dataset_actual_mismatches += 1
        cases.append(
            {
                "question": source_question,
                "expected": expected,
            }
        )

    return cases, len(source_rows), dataset_actual_mismatches


def _latency_summary_ms(samples: list[float]) -> dict:
    if not samples:
        return {"count": 0, "mean": None, "median": None, "p95": None, "max": None}
    ordered = sorted(samples)
    p95_index = max(0, math.ceil(0.95 * len(ordered)) - 1)
    return {
        "count": len(samples),
        "mean": round(statistics.fmean(samples) * 1000, 3),
        "median": round(statistics.median(samples) * 1000, 3),
        "p95": round(ordered[p95_index] * 1000, 3),
        "max": round(ordered[-1] * 1000, 3),
    }


def _peak_rss_bytes() -> int:
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # Linux reports KiB; macOS reports bytes. The production validator runs Linux.
    return int(peak if sys.platform == "darwin" else peak * 1024)


def _validate_classifier(model_path: Path, cases: list[dict], expected_count: int):
    import torch

    from app.classification.predictor import TransformerClassifier

    classifier = TransformerClassifier(model_path)
    cold_started = time.perf_counter()
    first_label = classifier.predict(cases[0]["question"])
    cold_seconds = time.perf_counter() - cold_started
    prediction_matches = int(first_label == cases[0]["expected"])
    warm_latencies = []

    for case in cases[1:]:
        started = time.perf_counter()
        label = classifier.predict(case["question"])
        warm_latencies.append(time.perf_counter() - started)
        prediction_matches += int(label == case["expected"])

    try:
        cpu_capability = torch.backends.cpu.get_cpu_capability()
    except (AttributeError, RuntimeError):
        cpu_capability = "unavailable"

    runtime = {
        "device": "cpu",
        "platform_machine": platform.machine(),
        "torch_version": torch.__version__,
        "torch_cpu_capability": cpu_capability,
        "torch_threads": torch.get_num_threads(),
        "peak_rss_bytes": _peak_rss_bytes(),
    }
    validation = {
        "saved_prediction_count": len(cases),
        "expected_prediction_count": expected_count,
        "count_matches_expected": len(cases) == expected_count,
        "prediction_matches": prediction_matches,
        "prediction_mismatches": len(cases) - prediction_matches,
        "all_saved_labels_match": prediction_matches == len(cases),
        "cold_latency_ms": round(cold_seconds * 1000, 3),
        "warm_latency_ms": _latency_summary_ms(warm_latencies),
    }
    return classifier, runtime, validation


def _make_delayed_answer(capacity: int, timeout_seconds: float):
    entered_capacity = threading.Event()
    release_handlers = threading.Event()
    state_lock = threading.Lock()
    state = {"active": 0, "maximum_active": 0}

    def delayed_answer(_question, _documents):
        with state_lock:
            state["active"] += 1
            state["maximum_active"] = max(state["maximum_active"], state["active"])
            if state["active"] == capacity:
                entered_capacity.set()
        try:
            if not release_handlers.wait(timeout_seconds):
                raise TimeoutError("runtime probe timed out")
            return "테스트 답변"
        finally:
            with state_lock:
                state["active"] -= 1

    return delayed_answer, entered_capacity, release_handlers, state


def _validate_ask_slots(
    timeout_seconds: float, overload_timeout_seconds: float
) -> list[dict]:
    """Exercise /ask admission with a fake answerer and no model-provider calls."""
    from fastapi.testclient import TestClient

    from app import fastapi_main
    from app.dependencies import get_classifier
    from app.documents.context import DocumentContext, DocumentContextSnapshot

    snapshot = DocumentContextSnapshot(
        (
            DocumentContext(
                document_id="runtime-probe-document",
                knowledge_id="runtime-probe-knowledge",
                revision_id="runtime-probe-revision",
                revision=1,
                title="Runtime probe",
                body="Private fixture content is not emitted.",
                source_reference="runtime-probe",
                content_hash="runtime-probe",
                metadata={},
            ),
        )
    )

    class SearchClassifier:
        def predict(self, _question: str) -> str:
            return "SEARCH_KNOWLEDGE"

    original_overrides = fastapi_main.app.dependency_overrides.copy()
    outcomes = []
    try:
        fastapi_main.app.dependency_overrides.clear()
        classifier = SearchClassifier()
        fastapi_main.app.dependency_overrides[get_classifier] = lambda: classifier
        for capacity, client_ip in ((1, "198.51.100.81"), (2, "198.51.100.82")):
            with tempfile.TemporaryDirectory() as temp_dir:
                directory = Path(temp_dir)
                env = {
                    "SANAEBI_PUBLIC_DEMO": "1",
                    "SANAEBI_MAX_INFLIGHT_ASKS": str(capacity),
                    "SANAEBI_DAILY_GENERATION_LIMIT": "1000",
                    "SANAEBI_GENERATION_BUDGET_DB": str(
                        directory / "generation-budget.sqlite3"
                    ),
                    "SANAEBI_DOCUMENT_DB": str(directory / "documents.sqlite3"),
                    "SANAEBI_ANSWER_PROVIDER": "openai",
                }
                with patch.dict(os.environ, env):
                    os.environ.pop("OPENAI_API_KEY", None)
                    os.environ.pop("TRACE_DIR", None)
                    (
                        delayed_answer,
                        entered_capacity,
                        release_handlers,
                        load_state,
                    ) = _make_delayed_answer(capacity, timeout_seconds)

                    with TestClient(
                        fastapi_main.app,
                        raise_server_exceptions=False,
                        client=(client_ip, 41000),
                    ) as client:
                        fastapi_main.app.state.document_provider.snapshot = lambda: (
                            snapshot
                        )
                        fastapi_main.app.state.answerer.answer = delayed_answer
                        with ThreadPoolExecutor(max_workers=capacity + 1) as workers:
                            pending = [
                                workers.submit(
                                    client.post,
                                    "/ask",
                                    json={"question": "비밀 없는 부하 시험"},
                                )
                                for _ in range(capacity)
                            ]
                            try:
                                if not entered_capacity.wait(timeout_seconds):
                                    raise TimeoutError(
                                        "configured ask capacity was not reached"
                                    )
                                rejected_started = time.perf_counter()
                                rejected_future = workers.submit(
                                    client.post,
                                    "/ask",
                                    json={"question": "추가 시험 요청"},
                                )
                                try:
                                    rejected = rejected_future.result(
                                        overload_timeout_seconds
                                    )
                                except TimeoutError as exc:
                                    release_handlers.set()
                                    rejected_future.result(timeout_seconds)
                                    raise RuntimeError(
                                        "ask overload rejection was not immediate"
                                    ) from exc
                                rejected_seconds = (
                                    time.perf_counter() - rejected_started
                                )
                            finally:
                                release_handlers.set()
                            accepted = [
                                response.result(timeout=timeout_seconds)
                                for response in pending
                            ]

                    statuses = [response.status_code for response in accepted]
                    if statuses != [200] * capacity or rejected.status_code != 429:
                        raise RuntimeError("ask_slot_probe_status_mismatch")
                    maximum_active = load_state["maximum_active"]
                    if maximum_active != capacity:
                        raise RuntimeError("ask_slot_probe_capacity_mismatch")
                    outcomes.append(
                        {
                            "configured_slots": capacity,
                            "accepted_inflight": sum(
                                response.status_code == 200 for response in accepted
                            ),
                            "overload_status": rejected.status_code,
                            "overload_response_ms": round(rejected_seconds * 1000, 3),
                            "overload_threshold_ms": round(
                                overload_timeout_seconds * 1000, 3
                            ),
                            "maximum_active_handlers": maximum_active,
                            "immediate_overload_rejection": True,
                        }
                    )
    finally:
        fastapi_main.app.dependency_overrides.clear()
        fastapi_main.app.dependency_overrides.update(original_overrides)

    return outcomes


def _arguments():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-path", type=Path, required=True)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--expected-predictions", type=int, default=133)
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    parser.add_argument("--overload-timeout-seconds", type=float, default=2.0)
    return parser.parse_args()


def main() -> int:
    args = _arguments()
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["CUDA_VISIBLE_DEVICES"] = ""

    report = {"ok": False}
    stage = "load_fixtures"
    try:
        cases, dataset_count, dataset_actual_mismatches = _load_validation_cases(
            args.predictions, args.dataset
        )
        stage = "cpu_classifier"
        _, runtime, validation = _validate_classifier(
            args.model_path, cases, args.expected_predictions
        )
        validation.update(
            {
                "dataset_row_count": dataset_count,
                "dataset_alignment_mismatches": dataset_actual_mismatches,
                "dataset_alignment_ok": dataset_actual_mismatches == 0,
            }
        )
        stage = "ask_slot_load"
        try:
            ask_slots = _validate_ask_slots(
                args.timeout_seconds, args.overload_timeout_seconds
            )
            ask_slot_ok = True
        except Exception as exc:  # noqa: BLE001 - report type only, never details
            ask_slots = [{"error_type": type(exc).__name__}]
            ask_slot_ok = False

        validation_ok = (
            validation["count_matches_expected"]
            and validation["all_saved_labels_match"]
            and validation["dataset_alignment_ok"]
        )
        report = {
            "ok": validation_ok and ask_slot_ok,
            "runtime": runtime,
            "classifier_validation": validation,
            "ask_slot_load": {"ok": ask_slot_ok, "runs": ask_slots},
        }
        if not report["ok"]:
            report["stage"] = stage
    except Exception as exc:  # noqa: BLE001 - do not print paths or exception text
        report.update({"stage": stage, "error_type": type(exc).__name__})

    print(json.dumps(report, ensure_ascii=False, separators=(",", ":")))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
