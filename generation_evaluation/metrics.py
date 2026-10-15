from collections import Counter

from generation.config import GenerationConfig
from generation.types import GenerationStatus
from generation_evaluation.types import GenerationRun, GenerationSummary


def count_outcomes(runs: list[GenerationRun]) -> dict[str, int]:
    counts = {
        "total": len(runs),
        "completed": 0,
        "parse_error": 0,
        "empty_answer": 0,
        "timeout": 0,
        "execution_error": 0,
        "truncated": 0,
        "refusal": 0,
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


def summarize_runs(
    runs: list[GenerationRun],
) -> list[GenerationSummary]:
    groups = _group_by_profile(runs)
    summaries = []

    for (config, profile), config_runs in groups.items():
        summary = GenerationSummary(
            config=config,
            prompt_profile=profile,
            counts=count_outcomes(config_runs),
            completion_rate=completion_rate(config_runs),
            mean_attempt_seconds=mean_attempt_seconds(config_runs),
            mean_completed_seconds=mean_completed_seconds(config_runs),
        )
        summaries.append(summary)

    return summaries


def summarize_comparable_runs(runs: list[GenerationRun]) -> list[GenerationSummary]:
    """Summarize observed runs only after common-input comparison checks."""
    if not runs:
        return []

    corpus = (runs[0].documents_sha256, runs[0].document_count)
    prompts_by_case = {}
    for run in runs:
        if not isinstance(run.case_id, str) or not run.case_id.strip():
            raise ValueError("비교에는 비어 있지 않은 case_id가 필요합니다.")
        if any(
            value is None
            for value in (run.documents_sha256, run.document_count, run.prompt_sha256)
        ):
            raise ValueError("입력 식별 정보가 없는 기록은 비교할 수 없습니다.")
        if (run.documents_sha256, run.document_count) != corpus:
            raise ValueError("서로 다른 문서 입력을 비교 집계할 수 없습니다.")
        if run.case_id in prompts_by_case:
            if prompts_by_case[run.case_id] != run.prompt_sha256:
                raise ValueError(f"동일 문항의 프롬프트가 다릅니다: {run.case_id}")
        else:
            prompts_by_case[run.case_id] = run.prompt_sha256

    expected_counts = None
    for config_runs in _group_by_profile(runs).values():
        counts = Counter(run.case_id for run in config_runs)
        if expected_counts is None:
            expected_counts = counts
        elif counts != expected_counts:
            raise ValueError("설정별 문항 목록 또는 문항별 시도 수가 다릅니다.")

    return summarize_runs(runs)


def _group_by_profile(
    runs: list[GenerationRun],
) -> dict[tuple[GenerationConfig, str | None], list[GenerationRun]]:
    groups = {}
    for run in runs:
        groups.setdefault((run.config, run.prompt_profile), []).append(run)
    return groups
