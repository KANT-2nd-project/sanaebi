# Jev API로 요청 처리 질문 분류 및 공통 분할 평가 (별도 학습 없음)

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
    from .model_report import (
        evaluate,
        report_dir,
        write_comparison,
        write_report,
    )
    from .question_split import (
        LABELS,
        RANDOM_SEED,
        make_split_record,
        question_input,
        split_input_hashes,
        split_questions,
    )
else:
    from model_report import (
        evaluate,
        report_dir,
        write_comparison,
        write_report,
    )
    from question_split import (
        LABELS,
        RANDOM_SEED,
        make_split_record,
        question_input,
        split_input_hashes,
        split_questions,
    )

##### 설정 #####

MODEL_NAME = "jev-latest"
MODEL_FOLDER = "jev"
API_URL = "https://api.typesafe.ai/v1/systemone"
DATASET_PATH = Path(__file__).resolve().parent.parent / "data" / "dataset.csv"
QUESTION = "출장비 정산 절차 알려줘"  # 기본 실행에서 분류할 질문 하나

# 공식 Choice API는 instructions와 criteria에 구조화한 사전도 허용
# 입력 질문은 state, 판단 기준과 train 대표 예시는 questions에 각각 전달
INSTRUCTIONS = {
    "task": "현재 질문을 업무 주제가 아닌 다음 처리 경로로 분류하세요. 세 라벨 중 하나만 선택하세요.",
    "input": "현재 사용자 질문 하나만 제공됩니다. 이전 대화·화면·첨부 자료는 제공되지 않습니다.",
    "service_scope": (
        "서비스는 회사 문서로 규정·절차·조직·업무도구 정보를 안내합니다. "
        "직원의 실시간 기록 조회나 실제 업무 실행·변경은 지원하지 않습니다."
    ),
    "decision_rules": [
        "회사 정보 안내 요청 없이 실제 실행·기록 조회만 요구하거나 회사 업무와 무관하면 UNSUPPORTED입니다. 실행 의도가 명확하면 세부 정보가 빠져도 동일합니다.",
        "업무 주제가 보여도 질문의 대상·원하는 도움을 특정할 수 없으면 CLARIFY입니다. 제공되지 않은 표시·항목·지난 대화를 추측하지 마세요.",
        "무엇을 묻는지 특정할 수 있고 회사 정보를 설명하는 일반 안내가 가능하면 SEARCH_KNOWLEDGE입니다. 정보 안내와 실제 실행·조회가 섞여도 이 경로입니다.",
    ],
    "avoid": [
        "문의가 있습니다처럼 주제만 말하고 실질 질문을 하지 않은 문장은 CLARIFY입니다.",
        "신청 방법 안내와 신청 대행 중 무엇을 원하는지 불명확한 경우는 CLARIFY입니다.",
        "일반 안내 요청에 날짜·개인 상세 정보가 부족하다는 이유만으로 CLARIFY로 바꾸지 마세요.",
        "낯선 제도명·회사 문서 미등록·모델의 낮은 확신은 CLARIFY나 UNSUPPORTED의 판단 근거가 아닙니다.",
    ],
}

# 예시는 train에서만 고름. ID는 출처 기록용이며 API의 판단 기준에는 넣지 않음
EXAMPLE_QUESTION_IDS = {
    "SEARCH_KNOWLEDGE": ["RQ0014", "RQ0084", "RQ0162", "RQ0560"],
    "CLARIFY": ["RQ0003", "RQ0110", "RQ0121", "RQ0079"],
    "UNSUPPORTED": ["RQ0026", "RQ0163", "RQ0408", "RQ0451"],
}

# 라벨마다 설명·포함 조건·다른 라벨로 보낼 조건·대표 질문과 이유를 구분
CATEGORIES = {
    "SEARCH_KNOWLEDGE": {
        "description": "회사 문서로 정보를 찾아 설명하는 경로. 무엇을 묻는지 특정할 수 있습니다.",
        "includes": [
            "회사 규정·절차·조직·공통 업무도구의 일반 안내",
            "사용자가 제공한 상황에 회사 규정을 적용하는 질문",
            "명시적인 정보 안내와 지원하지 않는 실행·조회가 함께 있는 요청",
        ],
        "not_for": [
            "표시한 부분·지난 대화 등 제공되지 않은 대상이 핵심이면 CLARIFY",
            "실질 질문 없이 업무 주제만 말하거나 안내와 대행 중 의도가 불명확하면 CLARIFY",
            "명확한 실제 실행·실시간 기록 조회만 요구하면 UNSUPPORTED",
        ],
        "examples": [
            {
                "question": "신규 입사자가 사원증과 사무실 출입 권한을 받으려면 어떤 신청 절차가 필요한가요?",
                "reason": "실제 신청 대행이 아니라 신청 절차 안내를 묻습니다.",
            },
            {
                "question": "휴가 신청 화면에 항목이 몇 개 있는데, 선택 전에 각 항목의 적용 조건부터 확인할 수 있을까요?",
                "reason": "개인이 표시한 특정 항목이 아니라 휴가 항목별 일반 조건 안내를 요청합니다.",
            },
            {
                "question": "은행 제출용 재직증명서가 급합니다. 발급 방법을 알려주시고 신청도 대신 해주세요.",
                "reason": "실제 신청 요청과 함께 발급 방법을 명시적으로 묻기 때문에 안내 경로로 분류합니다.",
            },
            {
                "question": "가족 사정으로 근무를 잠시 쉬어야 할 때 어떤 휴직 제도가 있는지 사내 기준이 있나요?",
                "reason": "개인 상황을 제시했지만 회사 제도의 일반 안내가 가능합니다.",
            },
        ],
    },
    "CLARIFY": {
        "description": "현재 질문만으로 대상이나 원하는 도움을 특정할 수 없어 필요한 정보를 먼저 묻는 경로.",
        "includes": [
            "이것·그 항목·표시한 칸·지난번처럼 제공되지 않은 대상을 가리킴",
            "여러 대상·행동 중 어느 것을 원하는지 질문에서 결정할 수 없음",
            "업무 주제만 말하고 실질 질문을 하지 않음",
            "정보 안내인지 실제 대행인지 원하는 도움이 불명확함",
        ],
        "not_for": [
            "일반 규정·절차를 설명할 수 있는 짧거나 포괄적인 질문은 SEARCH_KNOWLEDGE",
            "실제 실행·기록 조회만 요구하는 의도가 명확하면 세부 정보가 없어도 UNSUPPORTED",
            "모델의 지식 부족·낮은 확신·문서 미등록 자체는 추가 확인 사유가 아님",
        ],
        "examples": [
            {
                "question": "업체 계좌 변경 안내를 받았어요. 첨부 양식에 제가 동그라미 친 칸은 꼭 채워야 하나요?",
                "reason": "첨부 양식과 표시한 칸이 입력에 없어 어떤 항목인지 특정할 수 없습니다.",
            },
            {
                "question": "지난번에 말한 퇴사 서류는 날짜를 정한 뒤에 내는 그거였나요?",
                "reason": "지난 대화가 없어 어떤 퇴사 서류와 날짜를 말하는지 특정할 수 없습니다.",
            },
            {
                "question": "인사 변경 뒤 “계정 이름 수정” 문의가 왔습니다. 프로필 표시명, 메일 주소, 로그인 ID 가운데 어떤 값을 바꾸길 원하는지 적혀 있지 않아 요청 범위를 알 수 없어요.",
                "reason": "업무 주제는 계정이지만 요청 대상이 여러 가지라 먼저 확인해야 합니다.",
            },
            {
                "question": "회의실 화면이 안 나와 장비를 확인 중이에요. 문의 하나 드릴게요.",
                "reason": "상황만 설명하고 무엇을 물어보려는지 아직 제시하지 않았습니다.",
            },
        ],
    },
    "UNSUPPORTED": {
        "description": "현재 서비스가 제공하지 않는 기록 조회·실제 실행 또는 회사 업무와 무관한 요청을 안내하는 경로.",
        "includes": [
            "개인·조직의 실시간 기록이나 처리 상태를 직접 조회하라는 요청",
            "신청·취소·등록·생성·변경 등 실제 업무를 대신 실행하라는 명확한 요청",
            "회사 업무와 명확히 무관한 요청",
        ],
        "not_for": [
            "조회하는 방법이나 신청 절차를 설명해 달라는 요청은 SEARCH_KNOWLEDGE",
            "회사 정보 안내와 실제 조회·실행이 함께 있으면 SEARCH_KNOWLEDGE",
            "안내와 대행 중 원하는 도움이 불명확하면 CLARIFY",
        ],
        "examples": [
            {
                "question": "급여 시스템에서 이번 달 제 급여가 지급 완료로 처리됐는지 조회해 주세요.",
                "reason": "조회 방법이 아니라 개인 기록의 현재 상태를 직접 조회하라고 요청합니다.",
            },
            {
                "question": "경조휴가와 지원금 신청을 제 이름으로 넣어 주세요.",
                "reason": "신청 방법 안내 없이 실제 신청 대행을 명확히 요청합니다.",
            },
            {
                "question": "결제 모듈 프로젝트용 GitLab 저장소를 지금 만들어 주세요.",
                "reason": "회사 업무이지만 실제 저장소 생성 기능은 지원하지 않습니다.",
            },
            {
                "question": "친구 결혼식 축의금 봉투에 쓸 짧은 축하 문구 만들어 주세요.",
                "reason": "회사 규정이나 업무 안내와 무관한 개인적인 문구 작성 요청입니다.",
            },
        ],
    },
}

##### 질문 데이터 준비 #####


def prepare_question_data():
    with DATASET_PATH.open("r", encoding="utf-8-sig", newline="") as file:
        question_rows = list(csv.DictReader(file))
    splits = split_questions(question_rows, seed=RANDOM_SEED)
    record = make_split_record(splits, DATASET_PATH, seed=RANDOM_SEED)
    if list(CATEGORIES) != LABELS:
        raise ValueError("Jev 카테고리 순서가 공통 질문 라벨과 다릅니다.")
    # 분할·데이터가 바뀌어 예시가 평가에 섞이면 실행 전에 오류로 알림
    train_by_id = {row["question_id"]: row for row in splits["train"]}
    for label, ids in EXAMPLE_QUESTION_IDS.items():
        examples = CATEGORIES[label]["examples"]
        if len(ids) != len(examples):
            raise ValueError("대표 예시 ID와 질문의 개수가 다릅니다.")
        for question_id, example in zip(ids, examples):
            row = train_by_id.get(question_id)
            if (
                row is None
                or row["label"] != label
                or question_input(row) != example["question"]
            ):
                raise ValueError(
                    f"대표 예시 {question_id}가 현재 train 질문·정답과 맞지 않습니다."
                )
    return splits, record


##### 질문 분류 #####


def request_classification(question: str) -> dict:
    api_key = os.environ.get("TYPESAFE_API_KEY")  # 키는 환경변수에서 읽기
    if not api_key:
        raise SystemExit("TYPESAFE_API_KEY 환경변수에 API 키를 설정해 주세요.")

    # 현재 질문의 정답은 보내지 않으며, 판단 기준에는 train 대표 예시를 포함
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


def save_probability_csv(output_dir, predictions):
    # 원본 확률은 JSON에 유지하고, CSV에서는 퍼센트로 표시
    fields = [
        "split",
        "question_id",
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

    splits, split_record = prepare_question_data()
    # 로컬 모델과 같은 분할로 평가; train 중 대표 12건만 기준의 예시로 전달
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
            input_text = question_input(row)
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
                    "question_id": row["question_id"],
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

        evaluation_rows = [dict(row, text=question_input(row)) for row in data]
        scores[split] = evaluate(evaluation_rows, predictions, labels=LABELS)
        print(f"{split} 정확도: {scores[split]['accuracy']:.4f}")
        print(f"{split} Macro F1: {scores[split]['macro_f1']:.4f}")
        print("혼동행렬: 행은 정답, 열은 예측 / 순서:", list(CATEGORIES))
        for label, matrix_row in zip(CATEGORIES, scores[split]["confusion_matrix"]):
            print(label, matrix_row)

    report = {
        "title": "JEV · API 요청 처리 분류",
        "created_at": datetime.now(timezone(timedelta(hours=9))).strftime(
            "%Y-%m-%d %H:%M KST"
        ),
        "counts": {
            "train": sum(len(ids) for ids in EXAMPLE_QUESTION_IDS.values()),
            **{split: len(data) for split, data in rows.items()},
        },
        "data_hashes": split_input_hashes(splits),
        "settings": {
            "requested_model": MODEL_NAME,
            "training_mode": "가중치 학습 없이 train 대표 예시를 프롬프트에 제공",
            "prompt_examples_count": sum(
                len(ids) for ids in EXAMPLE_QUESTION_IDS.values()
            ),
            "prompt_example_ids": EXAMPLE_QUESTION_IDS,
            "prompt_example_source": "train",
            "labels": LABELS,
            "seed": RANDOM_SEED,
            "data_split": split_record,
            "input_condition": "question 열만 입력, 전체 질문 사용 (이전 대화 없음)",
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
    parser = argparse.ArgumentParser(description="Jev 요청 처리 질문 분류 및 평가")
    parser.add_argument(
        "--evaluate",
        action="store_true",
        help="공통 분할의 검증·테스트 질문을 API로 평가",
    )
    parser.add_argument(
        "--preview-questions",
        "--preview-documents",
        dest="preview_questions",
        action="store_true",
        help="API 호출 없이 공통 분할과 입력 확인",
    )
    args = parser.parse_args()
    if args.preview_questions:
        splits, record = prepare_question_data()
        print("분할 시드:", RANDOM_SEED)
        for name, data in record["splits"].items():
            print(name, data["count"], "개", data["label_counts"])
        print("Jev 평가 요청 수:", len(splits["validation"]) + len(splits["test"]))
        print("첫 번째 검증 입력:\n", question_input(splits["validation"][0]), sep="")
        print("첫 번째 정답:", splits["validation"][0]["label"])
        print("train에서 고른 대표 예시:")
        for label, criteria in CATEGORIES.items():
            for example in criteria["examples"]:
                print(label, ":", example["question"])
                print("이유:", example["reason"])
    elif args.evaluate:
        evaluate_csv()
    else:
        question = QUESTION
        result = request_classification(question)
        answer = result["answers"]["category"]
        # 질문 하나만 실행해도 원본 확률을 저장
        prediction = {
            "input_text": question,
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
        print("질문 입력:", question)
        print("분류:", answer["choice"])
        for label, probability in (answer.get("probabilities") or {}).items():
            print(f"{label}: {probability:.2%}")
        print("저장 위치:", output_dir / "single_prediction.json")
