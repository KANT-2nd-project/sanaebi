"""저장된 분류 모델을 재학습하지 않고 평가해 HTML 보고서 만들기."""

import argparse
import csv
import ctypes
import hashlib
import json
import os
import statistics
import sys
from datetime import datetime, timedelta, timezone
from html import escape
from pathlib import Path
from time import perf_counter

import numpy as np
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix
from threadpoolctl import threadpool_limits

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT.parent / "data" / "questions"
RESULT_DIR = ROOT / "result"
LABELS = ["it", "hr", "finance", "general_affairs", "other"]
LABEL_NAMES = ["IT", "인사", "재무", "총무", "기타"]
CPU_THREADS = 4


def report_dir(kind):
    return RESULT_DIR / ("bert" if kind == "bert" else "tf-idf")


def memory_mib():
    """현재 프로세스의 RAM 사용량(RSS). 모델만의 메모리가 아님."""
    if sys.platform == "win32":
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        get_process = ctypes.windll.kernel32.GetCurrentProcess
        get_process.restype = wintypes.HANDLE
        query = ctypes.windll.psapi.GetProcessMemoryInfo
        query.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
        if query(get_process(), ctypes.byref(counters), counters.cb):
            return counters.WorkingSetSize / 1024**2
    elif sys.platform == "linux":
        resident_pages = int(Path("/proc/self/statm").read_text().split()[1])
        return resident_pages * os.sysconf("SC_PAGE_SIZE") / 1024**2
    return None


def read_rows(split):
    with (DATA_DIR / f"{split}.csv").open(
        "r", encoding="utf-8-sig", newline=""
    ) as file:
        return list(csv.DictReader(file))


def table(headers, rows):
    head = "".join(f"<th>{escape(str(value))}</th>" for value in headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{escape(str(value))}</td>" for value in row) + "</tr>"
        for row in rows
    )
    return f'<div class="scroll"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


def page(title, subtitle, body, root_prefix=""):
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
<nav><a href="{root_prefix}comparison.html">모델 비교</a><a href="{root_prefix}bert/report.html">BERT</a>
<a href="{root_prefix}tf-idf/report.html">TF-IDF + 로지스틱 회귀</a></nav></header>
{body}<footer>학습 손실 대신 검증 결과로 모델을 선택하고, 테스트 결과는 최종 성능 확인에 사용합니다.</footer>
</main></body></html>"""


def evaluate(rows, predictions):
    actual = [row["label"] for row in rows]
    if len(predictions) != len(rows) or set(predictions) - set(LABELS):
        raise ValueError("예측 개수 또는 라벨이 현재 데이터와 맞지 않습니다.")
    scores = classification_report(
        actual, predictions, labels=LABELS, output_dict=True, zero_division=0
    )
    errors = [
        [row["id"], row["text"], row["label"], prediction]
        for row, prediction in zip(rows, predictions)
        if row["label"] != prediction
    ]
    return {
        "accuracy": accuracy_score(actual, predictions),
        "macro_f1": scores["macro avg"]["f1-score"],
        "per_class": {label: scores[label] for label in LABELS},
        "confusion_matrix": confusion_matrix(
            actual, predictions, labels=LABELS
        ).tolist(),
        "errors": errors,
    }


def write_report(kind, report):
    test = report["test"]
    timing = report["benchmark"]
    memory = timing["process_rss_mib"]
    cards = [
        ("테스트 Macro F1", f"{test['macro_f1']:.4f}"),
        ("테스트 정확도", f"{test['accuracy']:.2%}"),
        ("질문 1개 평균 시간 · CPU", f"{timing['mean_ms']:.2f} ms"),
        ("모델 파일 크기", f"{report['model_size_mib']:.2f} MiB"),
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
                    "검증 Macro F1 최대 · 동점이면 먼저 선택한 결과 유지",
                ],
                [
                    "학습 / 검증 / 테스트 문장 수",
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
                    report["settings"].get("validation_macro_f1", "미기록"),
                ],
                ["데이터 식별자 · test SHA-256", report["data_hashes"]["test"]],
            ],
        )
        + "</section>"
    )
    per_class = test["per_class"]
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
                for label, name in zip(LABELS, LABEL_NAMES)
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
        for i, (name, row) in enumerate(zip(LABEL_NAMES, matrix))
    )
    body += '<section><h2>테스트 · 혼동행렬</h2><p class="muted">행은 실제 정답, 열은 예측입니다. 대각선은 정답, 붉은 칸은 오분류입니다.</p>'
    body += (
        '<div class="scroll"><table class="matrix"><thead><tr><th>정답 ↓ / 예측 →</th>'
        + "".join(f"<th>{name}</th>" for name in LABEL_NAMES)
        + f"</tr></thead><tbody>{matrix_rows}</tbody></table></div></section>"
    )
    body += (
        "<section><h2>속도와 자원 · 동일한 CPU 조건</h2>"
        + table(
            ["항목", "측정값"],
            [
                ["측정 장치 / 스레드 제한", f"CPU / {CPU_THREADS}"],
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
            ],
        )
        + '<p class="note">질문 한 개의 변환과 예측을 함께 측정합니다. 3회 준비 실행 후 로딩 시간을 제외하고 측정했으며, HTTP 통신 시간은 포함하지 않습니다. RAM은 라이브러리와 모델을 포함한 프로세스 전체 사용량이고, 모델만의 사용량이나 순간 최대값이 아닙니다. 컴퓨터 부하에 따라 시간이 달라집니다.</p></section>'
    )
    body += (
        "<section><h2>선택한 모델의 학습 설정</h2>"
        + table(
            ["설정", "값"],
            [
                [key, json.dumps(value, ensure_ascii=False)]
                for key, value in report["settings"].items()
                if key not in {"trials", "test_confusion_matrix"}
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
    else:
        body += "<section><h2>후보별 학습·검증 기록</h2><p>이 저장 모델에는 전체 후보 기록이 없습니다. 변경된 학습 스크립트로 다음 학습을 완료하면 함께 기록됩니다.</p></section>"
    errors = test["errors"]
    body += f"<section><h2>테스트 오답 · {len(errors)}개</h2>"
    body += (
        table(["ID", "질문", "실제 정답", "예측"], errors)
        if errors
        else "<p>현재 테스트 데이터에서 오답이 없습니다.</p>"
    )
    body += "</section>"
    output = report_dir(kind) / "report.html"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        page(
            report["title"],
            f"저장 모델 재평가 · {report['created_at']} · 학습 코드와 분리된 CPU 프로세스",
            body,
            root_prefix="../",
        ),
        encoding="utf-8",
    )
    return output


def write_comparison():
    reports = []
    for kind in ["tfidf_lr", "bert"]:
        path = report_dir(kind) / "metrics.json"
        if path.is_file():
            reports.append(json.loads(path.read_text(encoding="utf-8")))
    rows = [
        [
            r["title"],
            f"{r['validation']['macro_f1']:.4f}",
            f"{r['test']['macro_f1']:.4f}",
            f"{r['test']['accuracy']:.2%}",
            f"{r['benchmark']['mean_ms']:.2f}",
            f"{r['benchmark']['process_rss_mib']:.1f}"
            if r["benchmark"]["process_rss_mib"] is not None
            else "미측정",
            f"{r['model_size_mib']:.2f}",
        ]
        for r in reports
    ]
    body = (
        "<section><h2>저장된 모델 비교</h2>"
        + table(
            [
                "모델",
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
    if len(reports) == 2 and reports[0]["data_hashes"] != reports[1]["data_hashes"]:
        body += '<p class="note">두 보고서의 평가 데이터가 다릅니다. 동일한 CSV로 보고서를 다시 생성한 후 비교하세요.</p>'
    body += "<section><h2>비교할 때 확인할 점</h2><p>모델·설정 선택에는 검증 F1을 사용하고 테스트 점수는 최종 평가로 남깁니다. 비슷한 점수라면 오답 유형, 응답 시간과 자원 사용량을 함께 확인하세요.</p><p>두 모델 모두 CPU·스레드 제한 4·질문 1개 단위로 측정합니다. 각 측정은 별도 프로세스이며 RAM에는 라이브러리 메모리도 포함됩니다.</p></section>"
    (RESULT_DIR / "comparison.html").write_text(
        page(
            "질문 분류 모델 비교",
            "같은 질문 · 같은 카테고리 · 같은 CPU 측정 조건",
            body,
        ),
        encoding="utf-8",
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=["bert", "tfidf_lr"])
    args = parser.parse_args()
    rows = {split: read_rows(split) for split in ["train", "validation", "test"]}
    if not rows["test"] or not rows["validation"]:
        raise ValueError("검증·테스트 CSV는 비어 있을 수 없습니다.")
    model_path = (
        ROOT
        / "model"
        / ("bert" if args.kind == "bert" else "tf-idf/tfidf_logistic_regression.joblib")
    )
    if not model_path.exists():
        raise FileNotFoundError(f"저장된 모델이 없습니다: {model_path}")
    summary_path = (
        model_path / "training_summary.json"
        if args.kind == "bert"
        else model_path.with_suffix(".json")
    )
    settings = (
        json.loads(summary_path.read_text(encoding="utf-8"))
        if summary_path.is_file()
        else {}
    )
    started = perf_counter()
    if args.kind == "bert":
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        torch.set_num_threads(CPU_THREADS)
        tokenizer = AutoTokenizer.from_pretrained(model_path, local_files_only=True)
        model = AutoModelForSequenceClassification.from_pretrained(
            model_path, local_files_only=True
        ).to("cpu")
        model.eval()

        def predict(text):
            encoded = tokenizer(
                text,
                padding="max_length",
                truncation=True,
                max_length=settings.get("max_length", 192),
                return_tensors="pt",
            )
            with torch.inference_mode():
                output = model(
                    input_ids=encoded["input_ids"],
                    attention_mask=encoded["attention_mask"],
                )
            return model.config.id2label[output.logits.argmax(dim=1).item()]

        title = "BERT · 질문 분류"
    else:
        import joblib

        model = joblib.load(model_path)

        def predict(text):
            return str(model.predict([text])[0])

        title = "TF-IDF + 로지스틱 회귀 · 질문 분류"
    load_seconds = perf_counter() - started
    with threadpool_limits(limits=CPU_THREADS):
        validation_predictions = [predict(row["text"]) for row in rows["validation"]]
        test_predictions = [predict(row["text"]) for row in rows["test"]]
        for _ in range(3):
            predict(rows["test"][0]["text"])
        durations = []
        for _ in range(3):
            for row in rows["test"]:
                started = perf_counter()
                predict(row["text"])
                durations.append((perf_counter() - started) * 1000)
    files = list(model_path.rglob("*")) if model_path.is_dir() else [model_path]
    report = {
        "title": title,
        "created_at": datetime.now(timezone(timedelta(hours=9))).strftime(
            "%Y-%m-%d %H:%M KST"
        ),
        "counts": {split: len(data) for split, data in rows.items()},
        "data_hashes": {
            split: hashlib.sha256((DATA_DIR / f"{split}.csv").read_bytes()).hexdigest()
            for split in rows
        },
        "settings": settings,
        "validation": evaluate(rows["validation"], validation_predictions),
        "test": evaluate(rows["test"], test_predictions),
        "model_size_mib": sum(
            p.stat().st_size
            for p in files
            if p.is_file() and p.name != "training_summary.json"
        )
        / 1024**2,
        "benchmark": {
            "load_seconds": load_seconds,
            "mean_ms": statistics.mean(durations),
            "median_ms": statistics.median(durations),
            "p95_ms": float(np.percentile(durations, 95)),
            "samples": len(durations),
            "process_rss_mib": memory_mib(),
        },
    }
    report_dir(args.kind).mkdir(parents=True, exist_ok=True)
    (report_dir(args.kind) / "metrics.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    output = write_report(args.kind, report)
    write_comparison()
    print("HTML 보고서:", output)


if __name__ == "__main__":
    main()
