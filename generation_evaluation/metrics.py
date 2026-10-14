from generation.config import GenerationConfig
from generation.types import GenerationStatus
from generation_evaluation.types import GenerationRun


def count_outcomes(runs: list[GenerationRun]) -> dict[str, int]:
    counts = {
        "total": len(runs),
        "completed": 0,
        "parse_error": 0,
        "empty_answer": 0,
        "timeout": 0,
        "execution_error": 0,
    }

    for run in runs:
        if run.error_type:
            counts["execution_error"] += 1
            continue

        if run.result is None:
            raise ValueError("모순된 기록(에러 없고 결과 없음)")

        counts[run.result.status] += 1

    return counts


def completion_rate(runs: list[GenerationRun]) -> float | None:
    counts = count_outcomes(runs)
    if counts["total"] == 0:
        return None

    return counts["completed"] / counts["total"]


def mean_attempt_seconds(runs: list[GenerationRun]) -> float | None:
    if not runs:
        return None

    total_run_elapsed_seconds = sum(run.elapsed_seconds for run in runs)
    return total_run_elapsed_seconds / len(runs)


def mean_completed_seconds(runs: list[GenerationRun]) -> float | None:
    completed_runs = []

    for run in runs:
        if (
            run.error_type is None
            and run.result is not None
            and run.result.status == GenerationStatus.COMPLETED
        ):
            completed_runs.append(run)

    return mean_attempt_seconds(completed_runs)


def group_by_config(
    runs: list[GenerationRun],
) -> dict[GenerationConfig, list[GenerationRun]]:
    groups = {}

    for run in runs:
        if run.config not in groups:
            groups[run.config] = []

        groups[run.config].append(run)

    return groups
