# Jev API로 문서 분류 및 공통 분할 평가 (별도 학습 없음)

import argparse
import csv
import json
import os
import statistics
from datetime import datetime, timedelta, timezone
from pathlib import Path
from time import perf_counter
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import numpy as np

if __package__:
    from .document_split import (
        LABELS,
        RANDOM_SEED,
        document_input,
        make_split_record,
        split_documents,
        split_input_hashes,
    )
    from .model_report import (
        evaluate,
        report_dir,
        write_comparison,
        write_report,
    )
else:
    from document_split import (
        LABELS,
        RANDOM_SEED,
        document_input,
        make_split_record,
        split_documents,
        split_input_hashes,
    )
    from model_report import (
        evaluate,
        report_dir,
        write_comparison,
        write_report,
    )

##### 설정 #####

MODEL_NAME = "jev-latest"
MODEL_FOLDER = "jev"
API_URL = "https://api.typesafe.ai/v1/systemone"
DATASET_PATH = (
    Path(__file__).resolve().parent.parent
    / "data"
    / "archive"
    / "document-topics-v0.2"
    / "dataset.csv"
)
DOCUMENT_TITLE = "VPN 연결 절차"  # 문서 하나를 분류할 때 사용하는 예시
DOCUMENT_TEXT = "업무용 VPN에 접속하려면 승인된 클라이언트를 설치하고 회사 계정으로 로그인한다. 접속 오류가 발생하면 오류 메시지를 IT 지원 담당자에게 전달한다."
INSTRUCTIONS = "문서의 제목과 본문을 읽고 대표 업무 주제를 하나 선택하세요. 작성 부서나 단순 언급보다 문서의 주요 목적과 핵심 행동을 기준으로 판단하세요."

# 반환할 카테고리와 각 카테고리의 의미
CATEGORIES = {
    "HR": "인사·근무·복지: 휴가, 근태, 근무 제도, 복지, 직원 급여, 입사·퇴사 절차, 인사 서류. 계정 설정과 직원 경비 정산은 제외.",
    "IT": "계정·업무도구·IT 지원: 계정 생성·로그인·권한 요청, 협업 도구, VPN, 업무 기기 설정·장애 해결. 구매 승인과 정보 취급·외부 공유 규칙은 제외.",
    "FINANCE_PROCUREMENT": "비용·구매·정산: 직원 경비, 출장비, 법인카드, 구매 요청·승인, 세금계산서, 협력사 대금 지급. 직원 급여·복지는 HR, 기술 설정은 IT.",
    "WORKPLACE": "총무·시설·사무환경: 사무실 출입, 출입증 이용, 좌석, 회의실, 주차, 사무용품 비치, 우편물, 시설 이용. 구매 예산·승인은 재무·구매, 보안 사고 대응은 보안·법무.",
    "SECURITY_LEGAL": "보안·개인정보·법무: 정보 취급·보관·외부 공유, 개인정보 보호, 접근 통제 원칙, 보안 사고 대응, 계약 검토, 윤리·준법. 일반 계정 사용법이나 사무실 운영은 제외.",
    "COMPANY": "회사·조직 안내: 회사 소개, 조직도, 부서·팀의 역할과 업무 분장, 전사 목표·조직 운영 안내. 구체적인 인사·IT·정산·시설·보안 절차가 핵심이면 해당 주제로 분류.",
}

##### 문서 데이터 준비 #####


def prepare_document_data():
    with DATASET_PATH.open("r", encoding="utf-8-sig", newline="") as file:
        document_rows = list(csv.DictReader(file))
    splits = split_documents(document_rows, seed=RANDOM_SEED)
    record = make_split_record(splits, DATASET_PATH, seed=RANDOM_SEED)
    if list(CATEGORIES) != LABELS:
        raise ValueError("Jev 카테고리 순서가 공통 문서 라벨과 다릅니다.")
    return splits, record


##### 문서 분류 #####


def request_classification(document: str) -> dict:
    api_key = os.environ.get("TYPESAFE_API_KEY")  # 키는 환경변수에서 읽기
    if not api_key:
        raise SystemExit("TYPESAFE_API_KEY 환경변수에 API 키를 설정해 주세요.")

    # 제목+본문과 6개 문서 카테고리의 의미를 전달
    payload = {
        "model": MODEL_NAME,
        "state": document,
        "questions": {
            "category": {
                "type": "choice",
                "instructions": INSTRUCTIONS,
                "criteria": CATEGORIES,
            }
        },
    }
    request = Request(
        API_URL,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urlopen(request, timeout=30) as response:
            result = json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        raise SystemExit(
            f"Jev API 요청 실패 (HTTP {error.code}). API 키·사용 권한·크레딧을 확인해 주세요."
        ) from None
    except (URLError, TimeoutError):
        raise SystemExit(
            "Jev API 연결에 실패했습니다. 네트워크를 확인해 주세요."
        ) from None

    category = result["answers"]["category"]["choice"]
    if category not in CATEGORIES:
        raise ValueError("API가 반환한 카테고리가 현재 목록에 없습니다.")
    return result  # 평가에서는 실제 모델 버전과 토큰 사용량도 기록


def classify_document(document: str) -> str:
    return request_classification(document)["answers"]["category"]["choice"]


def save_probability_csv(output_dir, predictions):
    # 원본 확률은 JSON에 유지하고, CSV에서는 퍼센트로 표시
    fields = [
        "split",
        "document_id",
        "title",
        "input_text",
        "actual",
        "predicted",
        "confidence",
    ]
    base_fields = fields.copy()
    fields += [f"{label}_percent" for label in CATEGORIES]
    with (output_dir / "prediction_probabilities.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        for prediction in predictions:
            row = {field: prediction.get(field, "") for field in base_fields}
            probabilities = prediction.get("probabilities") or {}
            for label in CATEGORIES:
                probability = probabilities.get(label)
                # API에서 확률을 주지 않았다면 빈 칸으로 남기기
                row[f"{label}_percent"] = (
                    round(probability * 100, 2) if probability is not None else ""
                )
            writer.writerow(row)


##### 검증·테스트 CSV 평가 #####


def evaluate_csv():
    if not os.environ.get("TYPESAFE_API_KEY"):
        raise SystemExit("TYPESAFE_API_KEY 환경변수에 API 키를 설정해 주세요.")

    splits, split_record = prepare_document_data()
    rows = {split: splits[split] for split in ["validation", "test"]}
    if any(not data for data in rows.values()):
        raise ValueError("검증·테스트 CSV는 비어 있을 수 없습니다.")
    print("Jev 평가 요청 수:", sum(len(data) for data in rows.values()))
    print("가중치 학습 없이 고정된 모델·카테고리 기준으로 평가합니다.")

    scores = {}
    durations = []
    resolved_models = set()
    input_tokens = []
    predictions_log = []
    for split, data in rows.items():
        predictions = []
        for step, row in enumerate(data, start=1):
            input_text = document_input(row)
            started = perf_counter()
            result = request_classification(input_text)
            elapsed_ms = (perf_counter() - started) * 1000
            answer = result["answers"]["category"]
            predictions.append(answer["choice"])
            if split == "test":
                durations.append(elapsed_ms)  # 테스트 요청의 실제 API 응답 시간
            if result.get("model"):
                resolved_models.add(result["model"])
            input_tokens.append(result.get("usage", {}).get("input_tokens"))
            predictions_log.append(
                {
                    "split": split,
                    "document_id": row["document_id"],
                    "title": row["title"],
                    "input_text": input_text,
                    "actual": row["label"],
                    "predicted": answer["choice"],
                    "confidence": answer.get("confidence"),
                    "probabilities": answer.get(
                        "probabilities"
                    ),  # 카테고리별 확률 (0~1)
                    "model": result.get("model"),
                    "elapsed_ms": elapsed_ms,
                }
            )
            print(f"{split}: {step}/{len(data)}")

        evaluation_rows = [dict(row, text=document_input(row)) for row in data]
        scores[split] = evaluate(evaluation_rows, predictions, labels=LABELS)
        print(f"{split} 정확도: {scores[split]['accuracy']:.4f}")
        print(f"{split} Macro F1: {scores[split]['macro_f1']:.4f}")
        print("혼동행렬: 행은 정답, 열은 예측 / 순서:", list(CATEGORIES))
        for label, matrix_row in zip(CATEGORIES, scores[split]["confusion_matrix"]):
            print(label, matrix_row)

    report = {
        "title": "JEV · API 문서 분류",
        "created_at": datetime.now(timezone(timedelta(hours=9))).strftime(
            "%Y-%m-%d %H:%M KST"
        ),
        "counts": {"train": 0, **{split: len(data) for split, data in rows.items()}},
        "data_hashes": split_input_hashes(splits),
        "settings": {
            "requested_model": MODEL_NAME,
            "labels": LABELS,
            "seed": RANDOM_SEED,
            "data_split": split_record,
            "resolved_models": sorted(resolved_models),
            "evaluation_calls": len(predictions_log),
            "input_tokens": sum(input_tokens)
            if all(isinstance(value, int) for value in input_tokens)
            else None,
            "instructions": INSTRUCTIONS,
            "criteria": CATEGORIES,
        },
        "validation": scores["validation"],
        "test": scores["test"],
        "model_size_mib": None,  # API 모델의 가중치는 로컬에 저장하지 않음
        "benchmark": {
            "mode": "api",
            "load_seconds": None,
            "mean_ms": statistics.mean(durations),
            "median_ms": statistics.median(durations),
            "p95_ms": float(np.percentile(durations, 95)),
            "samples": len(durations),
            "process_rss_mib": None,  # 서비스 측의 메모리 사용량은 측정할 수 없음
        },
    }
    output_dir = report_dir(MODEL_FOLDER)
    output_dir.mkdir(parents=True, exist_ok=True)
    for filename, content in [
        ("metrics.json", report),
        ("predictions.json", predictions_log),
    ]:
        (output_dir / filename).write_text(
            json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    output = write_report(MODEL_FOLDER, report)
    save_probability_csv(output_dir, predictions_log)
    write_comparison()
    print("HTML 보고서:", output)


##### 실행 #####

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Jev 문서 분류 및 평가")
    parser.add_argument(
        "--evaluate",
        action="store_true",
        help="공통 분할의 검증·테스트 문서를 API로 평가",
    )
    parser.add_argument(
        "--preview-documents",
        action="store_true",
        help="API 호출 없이 공통 분할과 입력 확인",
    )
    args = parser.parse_args()
    if args.preview_documents:
        splits, record = prepare_document_data()
        print("분할 시드:", RANDOM_SEED)
        for name, data in record["splits"].items():
            print(name, data["count"], "개", data["label_counts"])
        print("Jev 평가 요청 수:", len(splits["validation"]) + len(splits["test"]))
        print("첫 번째 검증 입력:\n", document_input(splits["validation"][0]), sep="")
        print("첫 번째 정답:", splits["validation"][0]["label"])
    elif args.evaluate:
        evaluate_csv()
    else:
        document = document_input({"title": DOCUMENT_TITLE, "text": DOCUMENT_TEXT})
        result = request_classification(document)
        answer = result["answers"]["category"]
        # 문서 하나만 실행해도 원본 확률을 저장
        prediction = {
            "title": DOCUMENT_TITLE,
            "input_text": document,
            "predicted": answer["choice"],
            "confidence": answer.get("confidence"),
            "probabilities": answer.get("probabilities"),
            "model": result.get("model"),
        }
        output_dir = report_dir(MODEL_FOLDER)
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "single_prediction.json").write_text(
            json.dumps(prediction, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print("문서 입력:", document)
        print("분류:", answer["choice"])
        for label, probability in (answer.get("probabilities") or {}).items():
            print(f"{label}: {probability:.2%}")
        print("저장 위치:", output_dir / "single_prediction.json")
