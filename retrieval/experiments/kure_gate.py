"""Offline-only KURE question gate selection and frozen adoption criteria."""

import itertools
import math


def gate_hits(hits, threshold, *, maximum=20):
    """Gate once by the best cosine, then keep even low-scoring top-k members."""
    if not math.isfinite(threshold) or type(maximum) is not int or maximum < 1:
        raise ValueError("finite threshold and positive maximum required")
    hits = list(hits)
    if len({item[0] for item in hits}) != len(hits):
        raise ValueError("duplicate chunk ID")
    if any(not math.isfinite(score) for _, score in hits):
        raise ValueError("nonfinite cosine score")
    ranked = sorted(hits, key=lambda item: (-item[1], item[0]))
    if not ranked or ranked[0][1] < threshold:
        return []
    return ranked[:maximum]


def choose_threshold(rows, *, required_negative_count=10, minimum_rejections=5):
    """Freeze the lowest tied midpoint without rejecting any related question."""
    if not rows or len({row["case_id"] for row in rows}) != len(rows):
        raise ValueError("nonempty unique cases required")
    for row in rows:
        if (
            type(row["related"]) is not bool
            or type(row["gate_negative"]) is not bool
            or not math.isfinite(row["maximum"])
        ):
            raise ValueError("finite scores and explicit Boolean relevance required")
        if row["related"] and row["gate_negative"]:
            raise ValueError("related case cannot be a gate-negative case")
    if not any(row["related"] for row in rows):
        raise ValueError("related questions required")
    if sum(row["gate_negative"] for row in rows) != required_negative_count:
        raise ValueError("frozen negative denominator mismatch")
    if not 0 < minimum_rejections <= required_negative_count:
        raise ValueError("invalid rejection acceptance count")
    values = sorted({row["maximum"] for row in rows})
    thresholds = [math.nextafter(values[0], -math.inf)]
    thresholds.extend(a + (b - a) / 2 for a, b in itertools.pairwise(values))
    thresholds.append(math.nextafter(values[-1], math.inf))
    trials = []
    for threshold in thresholds:
        rejected = [row for row in rows if row["maximum"] < threshold]
        trials.append(
            {
                "threshold": threshold,
                "related_rejected": sorted(
                    row["case_id"] for row in rejected if row["related"]
                ),
                "negative_rejected": sorted(
                    row["case_id"] for row in rejected if row["gate_negative"]
                ),
            }
        )
    safe = [row for row in trials if not row["related_rejected"]]
    best = min(safe, key=lambda row: (-len(row["negative_rejected"]), row["threshold"]))
    return {
        **best,
        "eligible": len(best["negative_rejected"]) >= minimum_rejections,
        "minimum_rejections": minimum_rejections,
        "negative_count": required_negative_count,
        "trials": trials,
    }


def decide_adoption(
    *,
    development_eligible,
    baseline_success,
    candidate_success,
    related_rejected,
    unrelated_rejected,
    resource_passed,
):
    """No holdout regression or related-question rejection may be averaged away."""
    lost = sorted(set(baseline_success) - set(candidate_success))
    adopted = (
        development_eligible is True
        and not lost
        and not related_rejected
        and unrelated_rejected >= 5
        and resource_passed is True
    )
    return {
        "adopted": bool(adopted),
        "lost_success_ids": lost,
        "related_rejected": sorted(related_rejected),
        "unrelated_rejected": unrelated_rejected,
        "resource_passed": resource_passed,
        "development_eligible": development_eligible,
    }


def validate_confirmation(cases, baseline_rows, candidate_rows):
    """Require every frozen confirmation result before comparing model outcomes."""
    ids = {case["case_id"] for case in cases}
    if len(cases) != 40 or len(ids) != 40:
        raise ValueError("confirmation must contain exactly 40 unique cases")
    kinds = [case["answerability"] for case in cases]
    if any(
        kinds.count(kind) != count
        for kind, count in [("answerable", 20), ("partial", 5), ("unanswerable", 15)]
    ):
        raise ValueError("confirmation answerability counts differ from protocol")
    if any(
        type(case["related"]) is not bool or type(case["gate_negative"]) is not bool
        for case in cases
    ):
        raise ValueError("explicit relatedness required")
    if (
        sum(case["related"] for case in cases) != 30
        or sum(case["gate_negative"] for case in cases) != 10
    ):
        raise ValueError("confirmation relevance denominators differ from protocol")
    if any(case["related"] == case["gate_negative"] for case in cases):
        raise ValueError(
            "related and unrelated confirmation groups must partition cases"
        )
    by_id = {case["case_id"]: case for case in cases}
    for rows in (baseline_rows, candidate_rows):
        if len(rows) != 40 or {row["case_id"] for row in rows} != ids:
            raise ValueError("missing or duplicate confirmation outcome")
        for row in rows:
            if type(row["gate_rejected"]) is not bool:
                raise ValueError("explicit gate outcome required")
            answerable = by_id[row["case_id"]]["answerability"] != "unanswerable"
            if (answerable and type(row["complete"]) is not bool) or (
                not answerable and row["complete"] is not None
            ):
                raise ValueError("missing or inconsistent coverage outcome")
    return True


def resource_passes(benchmark):
    """Partial runs and missing measurements cannot certify the resource gate."""
    runs = benchmark.get("runs", [])
    if len(runs) != 2 or {run.get("concurrency") for run in runs} != {1, 2}:
        return False
    for run in runs:
        if run.get("requested") != 144 or run.get("completed") != 144:
            return False
        for field, maximum in [("p95_ms", 3000), ("max_rss_mib", 6144)]:
            value = run.get(field)
            if (
                not isinstance(value, (int, float))
                or not math.isfinite(value)
                or not 0 <= value <= maximum
            ):
                return False
    return True
