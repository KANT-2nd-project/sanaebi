"""TF-IDF 후보 선택. 저장은 --output으로 명시한다."""

import argparse
import math
import platform
import subprocess
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from uuid import uuid4

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import classification_report, f1_score
from sklearn.pipeline import make_pipeline

from classification.dataset import DATASET_PATH, prepare_data, texts_and_labels
from classification.persistence import file_sha, save_bundle, split_id
from contracts.classification import LABELS


def select_model(train_rows, validation_rows, c_candidates):
    """test를 받지 않고 validation Macro-F1으로 후보를 선택한다."""
    splits = {"train": train_rows, "validation": validation_rows}
    train_texts, train_labels = texts_and_labels(splits["train"])

    vectorizer = TfidfVectorizer(analyzer="char", ngram_range=(2, 5))
    train_vectors = vectorizer.fit_transform(train_texts)

    validation_texts, validation_labels = texts_and_labels(splits["validation"])
    validation_vectors = vectorizer.transform(validation_texts)

    trials = []
    best_score = -1.0
    best_classifier = None
    best_c = None

    for c in c_candidates:
        classifier = LogisticRegression(C=c, max_iter=1000, class_weight="balanced")
        classifier.fit(train_vectors, train_labels)
        predictions = classifier.predict(validation_vectors)
        score = f1_score(
            validation_labels,
            predictions,
            labels=LABELS,
            average="macro",
            zero_division=0,
        )
        trials.append({"C": c, "validation_macro_f1": float(score)})
        print(f"C={c}, validation Macro-F1={score:.6f}")

        if score > best_score:
            best_score = score
            best_classifier = classifier
            best_c = c

    if best_classifier is None:
        raise ValueError("선택된 모델이 없습니다.")

    model = make_pipeline(vectorizer, best_classifier)
    predictions = model.predict(validation_texts)
    print("선택한 C:", best_c)
    print("선택한 Macro-F1:", best_score)

    correct = 0

    for actual, predicted in zip(validation_labels, predictions):
        if actual == predicted:
            correct += 1

    accuracy = correct / len(validation_labels)

    print("정답 수:", correct)
    print("전체 수:", len(validation_labels))
    print("정확도:", accuracy)

    for question, actual, predicted in zip(
        validation_texts, validation_labels, predictions
    ):
        if actual != predicted:
            print("질문:", question)
            print("정답:", actual, "/ 예측:", predicted)
            print()

    macro_f1 = f1_score(
        validation_labels, predictions, labels=LABELS, average="macro", zero_division=0
    )

    print("Validation Macro-F1:", macro_f1)
    print(
        classification_report(
            validation_labels,
            predictions,
            labels=LABELS,
            digits=4,
            zero_division=0,
        )
    )

    return model, {
        "selected_C": best_c,
        "validation_macro_f1": best_score,
        "trials": trials,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="train/validation으로 TF-IDF 선택. test 예측 없음."
    )
    parser.add_argument("--dataset", type=Path, default=DATASET_PATH)
    parser.add_argument("--seed", type=int, default=20261013)
    parser.add_argument(
        "--candidates", type=float, nargs="+", default=[0.1, 0.5, 1.0, 10.0]
    )
    parser.add_argument(
        "--output", type=Path, help="새 모델 폴더. 생략하면 저장하지 않음"
    )
    args = parser.parse_args(argv)
    if any(not math.isfinite(c) or c <= 0 for c in args.candidates):
        parser.error("C는 유한한 양수여야 합니다.")
    if args.output is not None and args.output.exists():
        parser.error(f"기존 경로를 보존합니다: {args.output}")
    sha = file_sha(args.dataset)
    splits = prepare_data(args.dataset, args.seed)
    model, selection = select_model(
        splits["train"], splits["validation"], args.candidates
    )
    if file_sha(args.dataset) != sha:
        raise ValueError("실행 중 데이터 파일이 변경되었습니다. 저장하지 않습니다.")
    if args.output is not None:
        question_ids = {
            name: [row["question_id"] for row in rows] for name, rows in splits.items()
        }
        root = Path(__file__).resolve().parents[1]
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
        metadata = {
            "schema_version": 1,
            "model_name": "learning_tfidf",
            "model_id": uuid4().hex,
            "created_at": datetime.now(UTC).isoformat(),
            "labels": list(model.classes_),
            "dataset_sha256": sha,
            "question_ids": question_ids,
            "split_id": split_id(question_ids),
            "seed": args.seed,
            "splitter": "StratifiedGroupKFold(20), fold counts 14/3/3",
            "config": {
                "analyzer": "char",
                "ngram_range": [2, 5],
                "min_df": 1,
                "class_weight": "balanced",
                "max_iter": 1000,
                "solver": "lbfgs",
                "c_candidates": args.candidates,
            },
            "selection": selection,
            "code_commit": commit.stdout.strip() if commit.returncode == 0 else None,
            "code_dirty": bool(status.stdout) if status.returncode == 0 else None,
            "environment": {
                "python": platform.python_version(),
                "scikit-learn": version("scikit-learn"),
                "joblib": version("joblib"),
            },
            "test_exposure": "이미 열람한 합성 개발 평가 자료",
        }
        save_bundle(
            model, args.output, metadata, texts_and_labels(splits["validation"])[0]
        )
        print("모델 저장:", args.output)
        print("model_id:", metadata["model_id"])


if __name__ == "__main__":
    main()
