import tempfile
from pathlib import Path

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline

from classification import persistence


def prepare_learning_evaluation(self):
    import csv

    from classification.persistence import file_sha, split_id

    self.temp = tempfile.TemporaryDirectory()
    self.addCleanup(self.temp.cleanup)
    self.root = Path(self.temp.name)
    self.dataset = self.root / "data.csv"
    self.rows = [
        {
            "question_id": f"Q{i}",
            "question": f"{label} 질문 {i}",
            "label": label,
            "group_id": f"G{i}",
        }
        for i, label in enumerate(["CLARIFY", "SEARCH_KNOWLEDGE", "UNSUPPORTED"] * 3)
    ]
    with self.dataset.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=self.rows[0])
        writer.writeheader()
        writer.writerows(self.rows)
    self.model = make_pipeline(TfidfVectorizer(analyzer="char"), LogisticRegression())
    self.model.fit(
        [r["question"] for r in self.rows[:3]], [r["label"] for r in self.rows[:3]]
    )
    ids = {
        name: [r["question_id"] for r in self.rows[start : start + 3]]
        for name, start in [("train", 0), ("validation", 3), ("test", 6)]
    }
    self.metadata = {
        "schema_version": 1,
        "model_name": "learning_tfidf",
        "model_id": "fixture",
        "labels": self.model.classes_.tolist(),
        "dataset_sha256": file_sha(self.dataset),
        "question_ids": ids,
        "split_id": split_id(ids),
    }
    self.bundle = self.root / "model"
    persistence.save_bundle(
        self.model, self.bundle, self.metadata, [self.rows[0]["question"]]
    )
