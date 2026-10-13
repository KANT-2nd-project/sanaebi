# Jev API로 질문 분류 및 CSV 평가 (별도 학습 없음)

import argparse
import hashlib
import json
import os
import statistics
from datetime import datetime, timedelta, timezone
from time import perf_counter
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import numpy as np

if __package__:
    from .model_report import (
        DATA_DIR,
        evaluate,
        read_rows,
        report_dir,
        write_comparison,
        write_report,
    )
else:
    from model_report import (
        DATA_DIR,
        evaluate,
        read_rows,
        report_dir,
        write_comparison,
        write_report,
    )

##### 설정 #####

MODEL_NAME = "jev-latest"
MODEL_FOLDER = "jev"
API_URL = "https://api.typesafe.ai/v1/systemone"
QUESTION = "VPN 접속 방법을 알려줘"  # 테스트할 질문
INSTRUCTIONS = "이 회사 질문의 담당 영역을 하나 선택하세요."

# 반환할 카테고리와 각 카테고리의 의미
CATEGORIES = {
    "it": "IT: 계정, VPN, 소프트웨어, 시스템 장애, 정보 보안",
    "hr": "인사: 연차, 근태, 채용, 인사 기록, 직원 복지",
    "finance": "재무: 경비 정산, 급여 지급, 세금, 매출과 입금",
    "general_affairs": "총무: 비품, 회의실, 사무실 시설, 회사 자산 관리",
    "other": "기타: 위 네 영역에 해당하지 않거나 회사와 무관한 질문",
}

##### 질문 분류 #####


def request_classification(question: str) -> dict:
    api_key = os.environ.get("TYPESAFE_API_KEY")  # 키는 환경변수에서 읽기
    if not api_key:
        raise SystemExit("TYPESAFE_API_KEY 환경변수에 API 키를 설정해 주세요.")

    # Jev에게 질문 내용과 선택할 카테고리를 전달
    payload = {
        "model": MODEL_NAME,
        "state": question,
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


def classify_question(question: str) -> str:
    return request_classification(question)["answers"]["category"]["choice"]


##### 검증·테스트 CSV 평가 #####


def evaluate_csv():
    if not os.environ.get("TYPESAFE_API_KEY"):
        raise SystemExit("TYPESAFE_API_KEY 환경변수에 API 키를 설정해 주세요.")

    rows = {split: read_rows(split) for split in ["validation", "test"]}
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
            started = perf_counter()
            result = request_classification(row["text"])
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
                    "id": row["id"],
                    "question": row["text"],
                    "actual": row["label"],
                    "predicted": answer["choice"],
                    "confidence": answer.get("confidence"),
                    "model": result.get("model"),
                    "elapsed_ms": elapsed_ms,
                }
            )
            print(f"{split}: {step}/{len(data)}")

        scores[split] = evaluate(data, predictions)
        print(f"{split} 정확도: {scores[split]['accuracy']:.4f}")
        print(f"{split} Macro F1: {scores[split]['macro_f1']:.4f}")
        print("혼동행렬: 행은 정답, 열은 예측 / 순서:", list(CATEGORIES))
        for label, matrix_row in zip(CATEGORIES, scores[split]["confusion_matrix"]):
            print(label, matrix_row)

    report = {
        "title": "JEV · API 질문 분류",
        "created_at": datetime.now(timezone(timedelta(hours=9))).strftime(
            "%Y-%m-%d %H:%M KST"
        ),
        "counts": {"train": 0, **{split: len(data) for split, data in rows.items()}},
        # 같은 CSV를 사용하는 로컬 모델 보고서와 데이터 식별자를 맞추기
        "data_hashes": {
            split: hashlib.sha256((DATA_DIR / f"{split}.csv").read_bytes()).hexdigest()
            for split in ["train", "validation", "test"]
        },
        "settings": {
            "requested_model": MODEL_NAME,
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
    write_comparison()
    print("HTML 보고서:", output)


##### 실행 #####

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Jev 질문 분류 및 평가")
    parser.add_argument(
        "--evaluate", action="store_true", help="검증·테스트 CSV 전체를 API로 평가"
    )
    args = parser.parse_args()
    if args.evaluate:
        evaluate_csv()
    else:
        category = classify_question(QUESTION)
        print("질문:", QUESTION)
        print("분류:", category)
