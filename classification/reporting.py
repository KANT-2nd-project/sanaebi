"""저장된 지표를 HTML로 표현한다. 모델 실행·점수 계산은 하지 않는다."""

import json
from html import escape

from contracts.classification import LABELS

from .artifacts import is_current_report

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
            links.append((f"{folder}/report.html", name))
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
{body}<footer>학습 손실 대신 검증 결과로 모델을 선택하고, 테스트 결과는 최종 성능 확인에 사용합니다.</footer>
</main></body></html>"""


def render_report(report, *, cpu_threads=4):
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
            "<section><h2>후보별 학습·검증 기록</h2>"
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
            + "</section>"
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
    reports = [
        report
        for _, report in sorted(reports_by_folder.items())
        if is_current_report(report)
    ]
    rows = [
        [
            r["title"],
            "API · 네트워크 포함"
            if r["benchmark"].get("mode") == "api"
            else "로컬 CPU",
            f"{r['validation']['macro_f1']:.4f}",
            f"{r['test']['macro_f1']:.4f}",
            f"{r['test']['accuracy']:.2%}",
            f"{r['benchmark']['mean_ms']:.2f}",
            f"{r['benchmark']['process_rss_mib']:.1f}"
            if r["benchmark"]["process_rss_mib"] is not None
            else "미측정",
            f"{r['model_size_mib']:.2f}"
            if r["model_size_mib"] is not None
            else "미공개",
        ]
        for r in reports
    ]
    body = (
        "<section><h2>저장된 모델 비교</h2>"
        + table(
            [
                "모델",
                "측정 방식",
                "검증 F1",
                "테스트 F1",
                "정확도",
                "평균 ms",
                "프로세스 RAM MiB",
                "모델 MiB",
            ],
            rows,
        )
        + "</section>"
    )
    if reports and any(r["data_hashes"] != reports[0]["data_hashes"] for r in reports):
        body += '<p class="note">보고서의 평가 데이터가 서로 다릅니다. 동일한 CSV로 보고서를 다시 생성한 후 비교하세요.</p>'
    body += "<section><h2>비교할 때 확인할 점</h2><p>모델·설정 선택에는 검증 F1을 사용하고 테스트 점수는 최종 평가로 남깁니다. 비슷한 점수라면 오답 유형, 응답 시간과 자원 사용량을 함께 확인하세요.</p><p>로컬 모델은 CPU·스레드 제한 4·질문 1개 단위로 측정하며, RAM에는 라이브러리 메모리도 포함됩니다. API 모델의 응답 시간은 네트워크를 포함하고 서버 RAM·모델 크기는 측정할 수 없어 같은 장치의 속도 비교로 해석하면 안 됩니다.</p></section>"
    return page(
        "질문 분류 모델 비교",
        "같은 질문 · 같은 카테고리 · 로컬 CPU와 원격 API 구분",
        body,
        reports=reports_by_folder,
    )
