"""저장된 지표를 HTML로 표현한다. 모델 실행·점수 계산은 하지 않는다."""

import json
from html import escape

from contracts.classification import LABELS

from ..artifacts import is_current_report

LABEL_NAMES = {
    "SEARCH_KNOWLEDGE": "회사 지식 안내",
    "CLARIFY": "추가 확인 필요",
    "UNSUPPORTED": "지원 범위 밖",
}


def table(headers, rows):
    head = "".join(f"<th>{escape(str(value))}</th>" for value in headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{escape(str(value))}</td>" for value in row) + "</tr>"
        for row in rows
    )
    return f'<div class="scroll"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


def page(title, subtitle, body, root_prefix="", reports=None):
    # 비교 페이지에는 모든 모델 메뉴, 상세 페이지에는 비교 메뉴만 표시
    links = [("comparison.html", "모델 비교")]
    if not root_prefix:
        for folder, report in sorted((reports or {}).items()):
            if not is_current_report(report):
                continue
            name = "TF-IDF + 로지스틱 회귀" if folder == "tf-idf" else folder.upper()
            links.append((report.get("report_href", f"{folder}/report.html"), name))
    navigation = "".join(
        f'<a href="{escape(root_prefix + href, quote=True)}">{escape(name)}</a>'
        for href, name in links
    )
    return f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)} · 사내비</title>
<style>
*{{box-sizing:border-box}}body{{margin:0;background:#f3f6fb;color:#18263a;
font:15px/1.65 'Segoe UI','Malgun Gothic',sans-serif}}main{{max-width:1100px;margin:auto;padding:40px 24px}}
header{{margin-bottom:28px}}.eyebrow{{color:#3263ca;font-weight:700;letter-spacing:.12em;font-size:12px}}
h1{{font-size:32px;margin:8px 0}}h2{{font-size:20px;margin:0 0 12px}}p{{margin:6px 0 16px}}
.muted{{color:#657389}}nav{{display:flex;flex-wrap:wrap;gap:10px;margin-top:18px}}
a{{color:#2455b8}}nav a{{background:white;padding:7px 14px;border:1px solid #dae3f1;border-radius:8px;text-decoration:none}}
section{{background:white;border:1px solid #e0e7f1;border-radius:14px;padding:24px;margin:18px 0}}
.cards{{display:grid;grid-template-columns:repeat(4,1fr);gap:14px}}.card{{background:white;border:1px solid #e0e7f1;border-radius:12px;padding:20px}}
.card span{{display:block;color:#657389;font-size:13px}}.card strong{{font-size:27px;display:block;margin-top:5px}}
.scroll{{overflow:auto}}table{{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}}
th,td{{padding:11px 14px;border-bottom:1px solid #e7edf5;text-align:left;vertical-align:top}}
th{{background:#f5f8fd;font-weight:600;white-space:nowrap}}td:first-child{{min-width:90px}}
.matrix td{{text-align:center}}.correct{{background:#edf7f1;color:#236143;font-weight:700}}
.mistake{{background:#fff0ed;color:#ad4531;font-weight:700}}details summary{{cursor:pointer;font-weight:600}}
.note{{padding:14px 18px;border-left:3px solid #5680d5;background:#edf3ff;border-radius:4px}}
footer{{color:#657389;font-size:13px;margin-top:24px}}
@media(max-width:700px){{main{{padding:24px 14px}}.cards{{grid-template-columns:repeat(2,1fr)}}h1{{font-size:25px}}section{{padding:18px}}}}
@media print{{body{{background:white}}nav{{display:none}}section,.card{{break-inside:avoid}}main{{max-width:none;padding:0}}}}
</style></head><body><main><header><div class="eyebrow">SANAEBI · MODEL EVALUATION</div>
<h1>{escape(title)}</h1><p class="muted">{escape(subtitle)}</p>
<nav>{navigation}</nav></header>
{body}<footer>모델 선택에는 validation을 사용합니다. test 실행만으로 미열람 최종 평가가 보장되지는 않습니다.</footer>
</main></body></html>"""


def _render_legacy_report(report, *, cpu_threads=4):
    if not is_current_report(report):
        raise ValueError("현재 질문 3분류 모델로 학습·평가한 결과가 필요합니다.")
    labels = LABELS
    label_names = [LABEL_NAMES[label] for label in labels]
    split_record = report["settings"]["data_split"]
    test = report["test"]
    timing = report["benchmark"]
    memory = timing["process_rss_mib"]
    is_api = timing.get("mode") == "api"
    example_count = report["settings"].get("prompt_examples_count", 0)
    model_size = report["model_size_mib"]
    cards = [
        ("테스트 Macro F1", f"{test['macro_f1']:.4f}"),
        ("테스트 정확도", f"{test['accuracy']:.2%}"),
        (
            "질문 1개 평균 시간 · API" if is_api else "질문 1개 평균 시간 · CPU",
            f"{timing['mean_ms']:.2f} ms",
        ),
        (
            "모델 파일 크기",
            f"{model_size:.2f} MiB" if model_size is not None else "원격 모델",
        ),
    ]
    body = (
        '<div class="cards">'
        + "".join(
            f'<div class="card"><span>{escape(name)}</span><strong>{value}</strong></div>'
            for name, value in cards
        )
        + "</div>"
    )
    body += "<section><h2>평가 데이터와 선택 기준</h2>"
    body += (
        table(
            ["항목", "내용"],
            [
                [
                    "모델 선택 기준",
                    "고정된 API 모델·카테고리 기준으로 평가 (가중치 학습 없음)"
                    if is_api
                    else "검증 Macro F1 최대 · 동점이면 먼저 선택한 결과 유지",
                ],
                [
                    "사용한 학습 / 검증 / 테스트 문장 수"
                    if is_api
                    else "학습 / 검증 / 테스트 문장 수",
                    " / ".join(
                        str(report["counts"][s])
                        for s in ["train", "validation", "test"]
                    ),
                ],
                [
                    "현재 CSV 재평가 · 검증 Macro F1",
                    f"{report['validation']['macro_f1']:.4f}",
                ],
                [
                    "학습 당시 기록 · 최고 검증 Macro F1",
                    "해당 없음 (학습하지 않음)"
                    if is_api
                    else report["settings"].get("validation_macro_f1", "미기록"),
                ],
                ["데이터 식별자 · test SHA-256", report["data_hashes"]["test"]],
            ],
        )
        + "</section>"
    )
    per_class = test["per_class"]
    if split_record:
        body += (
            "<section><h2>질문 분할 기록</h2>"
            + f"<p>시드: {split_record['seed']} · 입력: question 열만 사용</p>"
            + (
                (
                    f"<p>아래는 비교용 공통 분할 수량입니다. API 모델에는 train 중 {example_count}개 질문을 대표 예시로 제공했으며, 가중치를 학습하지 않습니다.</p>"
                    if example_count
                    else "<p>아래는 비교용 공통 분할 수량입니다. API 모델은 train 질문을 학습하거나 API에 전달하지 않습니다.</p>"
                )
                if is_api
                else ""
            )
            + table(
                ["라벨", "학습", "검증", "테스트"],
                [
                    [
                        label,
                        *[
                            split_record["splits"][name]["label_counts"][label]
                            for name in ["train", "validation", "test"]
                        ],
                    ]
                    for label in labels
                ],
            )
            + table(
                ["분할", "질문 수", "source별 수량"],
                [
                    [
                        name,
                        data["count"],
                        json.dumps(
                            data["source_counts"],
                            ensure_ascii=False,
                        ),
                    ]
                    for name, data in split_record["splits"].items()
                ],
            )
        )
        body += "</section>"
    body += (
        "<section><h2>테스트 · 카테고리별 성능</h2>"
        + table(
            ["카테고리", "Precision", "Recall", "F1", "정답 문장 수"],
            [
                [
                    f"{name} ({label})",
                    f"{per_class[label]['precision']:.4f}",
                    f"{per_class[label]['recall']:.4f}",
                    f"{per_class[label]['f1-score']:.4f}",
                    int(per_class[label]["support"]),
                ]
                for label, name in zip(labels, label_names)
            ],
        )
        + '<p class="muted">Precision: 해당 분류로 예측한 것 중 맞은 비율 · Recall: 실제 해당 분류 중 찾아낸 비율</p></section>'
    )
    matrix = test["confusion_matrix"]
    matrix_rows = "".join(
        f"<tr><th>{escape(name)}</th>"
        + "".join(
            f'<td class="{"correct" if i == j else "mistake" if count else ""}">{count}</td>'
            for j, count in enumerate(row)
        )
        + "</tr>"
        for i, (name, row) in enumerate(zip(label_names, matrix))
    )
    body += '<section><h2>테스트 · 혼동행렬</h2><p class="muted">행은 실제 정답, 열은 예측입니다. 대각선은 정답, 붉은 칸은 오분류입니다.</p>'
    body += (
        '<div class="scroll"><table class="matrix"><thead><tr><th>정답 ↓ / 예측 →</th>'
        + "".join(f"<th>{escape(name)}</th>" for name in label_names)
        + f"</tr></thead><tbody>{matrix_rows}</tbody></table></div></section>"
    )
    if is_api:
        resource_rows = [
            ["측정 방식", "원격 API · 네트워크와 서비스 처리 시간 포함"],
            [
                "질문 1개 평균 / 중앙값 / P95",
                f"{timing['mean_ms']:.2f} / {timing['median_ms']:.2f} / {timing['p95_ms']:.2f} ms",
            ],
            [
                "측정 횟수",
                f"실제 테스트 요청 {timing['samples']}회 (추가 속도 측정 요청 없음)",
            ],
            ["서버 RAM / 모델 파일 크기", "측정 불가 (원격 서비스)"],
        ]
        resource_note = "API 시간에는 네트워크와 서비스 처리가 포함됩니다. 로컬 모델의 CPU 예측 시간과 조건이 다르므로, 서비스 응답 시간 관점에서 구분해서 비교하세요. 원격 모델의 크기와 메모리는 측정하지 않았습니다."
    else:
        resource_rows = [
            ["측정 장치 / 스레드 제한", f"CPU / {cpu_threads}"],
            ["모델 로딩 시간", f"{timing['load_seconds']:.3f} 초"],
            [
                "질문 1개 평균 / 중앙값 / P95",
                f"{timing['mean_ms']:.2f} / {timing['median_ms']:.2f} / {timing['p95_ms']:.2f} ms",
            ],
            [
                "측정 횟수",
                f"테스트 질문 {report['counts']['test']}개 × 3회 = {timing['samples']}회",
            ],
            [
                "추론 후 별도 프로세스 RAM · RSS",
                f"{memory:.1f} MiB"
                if memory is not None
                else "현재 OS에서는 측정하지 못함",
            ],
        ]
        resource_note = "질문 한 개의 변환과 예측을 함께 측정합니다. 3회 준비 실행 후 로딩 시간을 제외하고 측정했으며, HTTP 통신 시간은 포함하지 않습니다. RAM은 라이브러리와 모델을 포함한 프로세스 전체 사용량이고, 모델만의 사용량이나 순간 최대값이 아닙니다. 컴퓨터 부하에 따라 시간이 달라집니다."
    body += (
        (
            "<section><h2>속도와 자원 · API</h2>"
            if is_api
            else "<section><h2>속도와 자원 · 동일한 CPU 조건</h2>"
        )
        + table(
            ["항목", "측정값"],
            resource_rows,
        )
        + f'<p class="note">{escape(resource_note)}</p></section>'
    )
    body += (
        (
            "<section><h2>API 모델과 분류 기준</h2>"
            if is_api
            else "<section><h2>선택한 모델의 학습 설정</h2>"
        )
        + table(
            ["설정", "값"],
            [
                [key, json.dumps(value, ensure_ascii=False)]
                for key, value in report["settings"].items()
                if key not in {"trials", "test_confusion_matrix", "data_split"}
            ],
        )
        + "</section>"
    )
    trials = report["settings"].get("trials", [])
    if trials:
        columns = list(trials[0])
        body += (
            "<section><details><summary>후보별 학습·검증 기록</summary>"
            + table(
                columns,
                [
                    [
                        f"{trial[key]:.6g}"
                        if isinstance(trial[key], float)
                        else trial[key]
                        for key in columns
                    ]
                    for trial in trials
                ],
            )
            + "</details></section>"
        )
    elif not is_api:
        body += "<section><h2>후보별 학습·검증 기록</h2><p>이 저장 모델에는 전체 후보 기록이 없습니다. 변경된 학습 스크립트로 다음 학습을 완료하면 함께 기록됩니다.</p></section>"
    errors = test["errors"]
    body += f"<section><h2>테스트 오답 · {len(errors)}개</h2>"
    body += (
        table(
            [
                "ID",
                "질문",
                "실제 정답",
                "예측",
            ],
            errors,
        )
        if errors
        else "<p>현재 테스트 데이터에서 오답이 없습니다.</p>"
    )
    body += "</section>"
    return page(
        report["title"],
        f"{report['created_at']} · "
        + (
            "고정된 API 모델·프롬프트 평가"
            if is_api
            else "저장 모델 재평가 · 학습 코드와 분리된 CPU 프로세스"
        ),
        body,
        root_prefix="../",
    )


def render_comparison(reports_by_folder):
    """기본 모델 비교에는 validation만 표시한다. 과거 test는 숨긴다."""
    reports = {
        name: report
        for name, report in reports_by_folder.items()
        if is_current_report(report)
        and "validation" in report
        and report.get("evaluated_split", "validation") == "validation"
    }
    rows = [
        [
            r["title"],
            r.get("model_id", "미기록"),
            f"{r['validation']['macro_f1']:.4f}",
            f"{r['validation']['accuracy']:.2%}",
            r.get("data_review", "미기록"),
            "validation 단일 평가"
            if r.get("schema_version") == 2
            else "과거 형식 (속도는 test 측정)",
        ]
        for r in reports.values()
    ]
    body = (
        "<section><h2>Validation 기준 모델 비교</h2>"
        + table(
            ["모델", "model_id", "검증 F1", "검증 정확도", "자료 한계", "측정 범위"],
            rows,
        )
        + "</section>"
    )
    if reports:
        first = next(iter(reports.values()))
        if any(r["data_hashes"] != first["data_hashes"] for r in reports.values()):
            body += '<p class="note">평가 데이터가 서로 다릅니다. 동일 조건끼리 비교하세요.</p>'
    body += '<p class="note">기본 비교는 validation 기준입니다. test는 명시적으로 평가하며 이미 열람한 자료는 최종 미열람 평가로 취급하지 않습니다. API 시간과 로컬 CPU 시간은 직접 비교하지 않습니다.</p>'
    return page(
        "질문 분류 모델 비교",
        "Validation 기준 · 모델과 데이터 식별값 확인",
        body,
        reports=reports,
    )


def report_identity(report):
    record = report["settings"].get("data_split", {})
    split = report.get("evaluated_split", "validation/test (과거 형식)")
    return (
        "<section><h2>모델과 평가의 정체</h2>"
        + table(
            ["항목", "값"],
            [
                ["모델", report["title"]],
                ["model_id", report.get("model_id", "미기록")],
                ["데이터 SHA", record.get("dataset_sha256", "미기록")],
                [
                    "분할 식별값",
                    json.dumps(report.get("data_hashes", {}), ensure_ascii=False),
                ],
                ["입력", ", ".join(record.get("input_fields", [])) or "미기록"],
                ["평가 분할", split],
                ["용도", report.get("evaluation_purpose", "과거 평가 기록")],
                ["데이터 검수", report.get("data_review", "미기록")],
                [
                    "test 열람 상태",
                    report.get(
                        "test_exposure",
                        report["settings"].get("test_interpretation", "미기록"),
                    ),
                ],
            ],
        )
        + '<p class="note">manifest는 파일 무결성 확인이며 성능 승인이나 미열람 평가의 증명이 아닙니다.</p></section>'
    )


def render_report(report, *, cpu_threads=4):
    if not is_current_report(report):
        raise ValueError("현재 질문 3분류 모델로 학습·평가한 결과가 필요합니다.")
    if "evaluated_split" not in report:
        html = _render_legacy_report(report, cpu_threads=cpu_threads)
        return html.replace("</header>", "</header>" + report_identity(report), 1)
    split = report["evaluated_split"]
    scores = report[split]
    body = report_identity(report)
    body += (
        "<section><h2>선택 기준과 평가 점수</h2><p>모델 선택: validation Macro F1 최대, 동점은 먼저 선택한 후보 유지.</p>"
        + table(
            ["분할", "Macro F1", "정확도", "문항 수"],
            [
                [
                    split,
                    f"{scores['macro_f1']:.4f}",
                    f"{scores['accuracy']:.2%}",
                    report["counts"][split],
                ]
            ],
        )
        + "</section>"
    )
    body += (
        "<section><h2>라벨별 성능</h2>"
        + table(
            ["라벨", "Precision", "Recall", "F1", "문항 수"],
            [
                [
                    label,
                    *[
                        f"{scores['per_class'][label][k]:.4f}"
                        for k in ("precision", "recall", "f1-score")
                    ],
                    int(scores["per_class"][label]["support"]),
                ]
                for label in LABELS
            ],
        )
        + "</section>"
    )
    matrix = scores["confusion_matrix"]
    body += (
        "<section><h2>혼동행렬</h2><p>행: 정답, 열: 예측</p>"
        + table(
            ["정답 / 예측", *LABELS],
            [[label, *row] for label, row in zip(LABELS, matrix)],
        )
        + "</section>"
    )
    body += (
        "<section><h2>오류 방향</h2>"
        + table(
            ["정답", "예측", "건수"],
            [
                [a, b, matrix[i][j]]
                for i, a in enumerate(LABELS)
                for j, b in enumerate(LABELS)
                if i != j and matrix[i][j]
            ],
        )
        + "</section>"
    )
    body += (
        "<section><h2>오분류 질문</h2>"
        + table(["ID", "질문", "정답", "예측"], scores["errors"])
        + "</section>"
    )
    body += "<section><h2>속도·측정 조건</h2>" + table(
        ["항목", "값"],
        [
            [k, json.dumps(v, ensure_ascii=False)]
            for k, v in report["benchmark"].items()
        ],
    )
    body += "<p>선택한 분할에서 측정합니다. 로딩·HTTP 시간은 추론 시간에 포함하지 않으며 RSS는 프로세스 전체 메모리입니다.</p>"
    body += (
        table(
            ["측정 정책", "값"],
            [[k, v] for k, v in report.get("measurement_policy", {}).items()],
        )
        + "</section>"
    )
    details = {
        k: v
        for k, v in report["settings"].items()
        if k not in {"data_split", "trials"} and not k.startswith("test_")
    }
    body += "<section><details><summary>선택 설정·후보별 학습 기록</summary>" + table(
        ["설정", "값"],
        [[k, json.dumps(v, ensure_ascii=False)] for k, v in details.items()],
    )
    trials = report["settings"].get("trials", [])
    if trials:
        columns = list(trials[0])
        body += table(columns, [[trial.get(k) for k in columns] for trial in trials])
    body += "</details></section>"
    return page(
        report["title"],
        report["created_at"] + " · " + split,
        body,
        root_prefix="../../",
    )
