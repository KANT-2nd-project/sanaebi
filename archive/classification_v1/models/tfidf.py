"""TF-IDF 전용 학습·선택과 직렬화. 다른 모델 구현을 import하지 않는다."""

from dataclasses import dataclass

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, confusion_matrix, f1_score
from sklearn.pipeline import make_pipeline

from contracts.classification import LABELS as ROUTING_LABELS

from ..types import DEFAULT_SEED, FittedModel, Prediction, Predictor, validate_label

LABELS = list(ROUTING_LABELS)


def texts_and_labels(rows):
    return [r["question"] for r in rows], [r["label"] for r in rows]


@dataclass(frozen=True)
class TfidfConfig:
    c_candidates: tuple[float, ...] = (0.1, 0.5, 1.0, 10.0)
    seed: int = DEFAULT_SEED


def select_tfidf(train_rows, validation_rows, config):
    """test를 받지 않는다. 어휘·IDF·가중치는 train에서만 학습한다."""
    train_texts, train_labels = texts_and_labels(train_rows)
    validation_texts, validation_labels = texts_and_labels(validation_rows)
    vectorizer = TfidfVectorizer(analyzer="char", ngram_range=(2, 5), min_df=1)
    train_vectors = vectorizer.fit_transform(train_texts)
    validation_vectors = vectorizer.transform(validation_texts)
    best_classifier = None
    best_c = None
    best_score = -1.0
    trials = []
    for c in config.c_candidates:
        candidate = LogisticRegression(
            C=c, max_iter=1000, class_weight="balanced", random_state=config.seed
        )
        candidate.fit(train_vectors, train_labels)
        predictions = candidate.predict(validation_vectors)
        accuracy = accuracy_score(validation_labels, predictions)
        score = f1_score(
            validation_labels,
            predictions,
            labels=LABELS,
            average="macro",
            zero_division=0,
        )
        trials.append(
            {"C": c, "validation_accuracy": accuracy, "validation_macro_f1": score}
        )
        print(f"C={c}: 검증 정확도={accuracy:.4f}, Macro F1={score:.4f}")
        matrix = confusion_matrix(validation_labels, predictions, labels=LABELS)
        for label, row in zip(LABELS, matrix):
            print(label, row.tolist())
        if score > best_score:  # 동점은 앞선 후보 유지
            best_classifier, best_c, best_score = candidate, c, score
    if best_classifier is None:
        raise ValueError("학습할 C 후보가 없습니다.")
    # 이미 학습한 객체를 묶는다. pipeline.fit을 다시 호출하지 않는다.
    return make_pipeline(vectorizer, best_classifier), best_c, best_score, trials


def sklearn_predictor(model) -> Predictor:
    def predict(text):
        return Prediction(validate_label(str(model.predict([text])[0])))

    return predict


def fit(train_rows, validation_rows, config):
    model, best_c, best_score, trials = select_tfidf(
        train_rows, validation_rows, config
    )
    settings = {
        "model_name": "TF-IDF + LogisticRegression",
        "labels": LABELS,
        "C": best_c,
        "analyzer": "char",
        "ngram_range": [2, 5],
        "min_df": 1,
        "class_weight": "balanced",
        "max_iter": 1000,
        "seed": config.seed,
        "input_condition": "question 열만 입력, 전체 질문 사용",
        "validation_macro_f1": best_score,
        "trials": trials,
    }

    def save(path):
        import joblib

        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(model, path)

    def predict_batch(texts):
        return [
            Prediction(validate_label(str(label))) for label in model.predict(texts)
        ]

    return FittedModel(sklearn_predictor(model), save, settings, predict_batch)


def load(path, settings=None) -> Predictor:
    import joblib

    return sklearn_predictor(joblib.load(path))
