"""명령에서 공유하는 모델 설정표. 모델 구현은 이 모듈을 참조하지 않는다."""

from . import tfidf, transformer

CONFIGS = {
    "bert_base": transformer.TransformerConfig("klue/bert-base", "bert_base"),
    "koelectra_base": transformer.TransformerConfig(
        "monologg/koelectra-base-v3-discriminator", "koelectra_base"
    ),
    "koelectra_small": transformer.TransformerConfig(
        "monologg/koelectra-small-v3-discriminator", "koelectra_small"
    ),
    "roberta_base": transformer.TransformerConfig("klue/roberta-base", "roberta_base"),
    "roberta_small": transformer.TransformerConfig(
        "klue/roberta-small", "roberta_small"
    ),
    "tfidf": tfidf.TfidfConfig(),
}


def load_bundle(name, bundle, summary):
    return (
        tfidf.load(bundle / "model.joblib", summary)
        if name == "tfidf"
        else transformer.load(bundle, summary)
    )
