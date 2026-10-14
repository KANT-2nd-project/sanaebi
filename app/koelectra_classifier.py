"""과거 단독 호출용 호환 함수. HTTP는 앱별 의존성 주입을 사용한다."""

from functools import lru_cache

from app.infrastructure.classifier import TransformerClassifier
from app.model_settings import get_classifier_path
from contracts.classification import ClassificationLabel


@lru_cache(maxsize=1)
def load_model() -> TransformerClassifier:
    return TransformerClassifier(get_classifier_path())


def classify_question(question: str) -> ClassificationLabel:
    return load_model().predict(question)
