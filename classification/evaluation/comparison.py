"""유효한 현재 모델의 validation 결과만 수집·그룹화·게시한다."""

from .. import artifacts
from . import reporting


def refresh_comparison(artifact_root):
    """유효 모델에 연결된 결과만 같은 평가 조건끼리 비교한다."""
    from .. import storage

    with storage.lock(artifact_root, "comparison"):
        groups = {}
        for directory in sorted((artifact_root / "results").glob("*")):
            if not directory.is_dir():
                continue
            path = directory / "validation/metrics.json"
            if not path.exists():
                path = directory / "metrics.json"  # 과거 형식: validation 부분만 사용

            try:
                report = artifacts.read_json(path)
                manifest = storage.validate_bundle(
                    artifact_root / "models" / directory.name, directory.name
                )
                if report.get("model_id") != manifest["model_id"]:
                    continue
                if (
                    report.get("evaluated_split", "validation") != "validation"
                    or "validation" not in report
                ):
                    continue
                if not artifacts.is_current_report(report):
                    continue
                key = storage.digest(
                    {
                        "labels": report["settings"]["labels"],
                        "schema_version": report.get("schema_version", 1),
                        "evaluated_split": report.get("evaluated_split", "legacy-both"),
                        "split": report["settings"]["data_split"],
                        **{
                            key: report.get(key)
                            for key in (
                                "data_hashes",
                                "counts",
                                "measurement_policy",
                                "evaluation_environment",
                            )
                        },
                    }
                )
                report = dict(
                    report,
                    report_href=f"{directory.name}/validation/report.html"
                    if path.parent.name == "validation"
                    else f"{directory.name}/report.html",
                )
                groups.setdefault(key, {})[directory.name] = report
            except (ValueError, OSError, KeyError):
                continue
        output = artifact_root / "results/comparison.html"
        # 각 그룹별 완전한 보고서를 별도 페이지로 만들고 인덱스에서 연결한다.
        from html import escape

        links = []
        active_pages = set()
        for key, reports in groups.items():
            name = f"comparison-{key}.html"
            active_pages.add(name)
            storage.atomic_text(
                output.parent / name, reporting.render_comparison(reports)
            )
            links.append(f'<li><a href="{name}">{escape(", ".join(reports))}</a></li>')
        storage.atomic_text(
            output,
            '<!doctype html><meta charset="utf-8"><h1>동일 조건 모델 비교</h1><p>모델과 불일치하거나 손상된 결과는 제외됩니다.</p><ul>'
            + "".join(links)
            + "</ul>",
        )

        # 이전 그룹 링크를 직접 열어도 현재 모델의 점수로 오해하지 않게 표시한다.
        for old in output.parent.glob("comparison-*.html"):
            if old.name not in active_pages:
                storage.atomic_text(
                    old,
                    '<!doctype html><meta charset="utf-8"><p>이 비교는 현재 모델·평가 조건과 달라 만료되었습니다. <a href="comparison.html">현재 비교</a></p>',
                )
