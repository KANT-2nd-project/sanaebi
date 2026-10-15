"""Read-only completeness audit before accepting blinded judgment summaries."""

import argparse
import json
from collections import Counter
from pathlib import Path


def audit(responses, mapping, judgments, cases, profiles, repetitions):
    rows = [json.loads(line) for line in responses.read_text().splitlines()]
    links = json.loads(mapping.read_text())
    document = json.loads(judgments.read_text())
    scored = document["responses"] if isinstance(document, dict) else document
    fixture = {case["id"]: case for case in json.loads(cases.read_text())["cases"]}
    expected = Counter(
        (case_id, profile, repeat)
        for case_id in fixture
        for profile in profiles
        for repeat in range(1, repetitions + 1)
    )
    actual = Counter(
        (row["case_id"], row["prompt_profile"], row["repetition"]) for row in rows
    )
    assert actual == expected, "response coverage or duplication"
    slots = {row["slot"]: row for row in rows}
    assert len(slots) == len(rows), "duplicate response slot"
    assert Counter(link["slot"] for link in links.values()) == Counter(slots.keys()), (
        "mapping coverage"
    )
    assert Counter(row["anonymous_id"] for row in scored) == Counter(links.keys()), (
        "judgment coverage"
    )
    for anonymous_id, link in links.items():
        row = slots[link["slot"]]
        assert (link["case_id"], link["profile"], link["repetition"]) == (
            row["case_id"],
            row["prompt_profile"],
            row["repetition"],
        ), anonymous_id
    for row in scored:
        link = links[row["anonymous_id"]]
        checks = row["required_checks"]
        assert [check["index"] for check in checks] == list(
            range(len(fixture[link["case_id"]]["required"]))
        ), row["anonymous_id"]
        assert all(
            check["status"] in {"met", "missing", "uncertain"} for check in checks
        )
        if row["content"] == "pass":
            assert all(check["status"] == "met" for check in checks), row[
                "anonymous_id"
            ]
        assert row["content"] in {"pass", "partial", "fail", "uncertain"}
    return {"responses": len(rows), "judgments": len(scored), "exact_coverage": True}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("responses", "mapping", "judgments", "cases"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--profiles", nargs="+", required=True)
    parser.add_argument("--repetitions", type=int, required=True)
    args = vars(parser.parse_args())
    print(json.dumps(audit(**args)))
