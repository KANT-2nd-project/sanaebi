"""요청 처리 라벨의 타입과 순서. 의미는 docs/label-taxonomy.md 참고.

과거 문서 주제 라벨과는 별개다. 저장된 모델의 출력 번호는 모델 자체의
id2label/classes_로 해석하며 이 순서로 덮어쓰지 않는다.
"""

from typing import Literal, get_args

ClassificationLabel = Literal["SEARCH_KNOWLEDGE", "CLARIFY", "UNSUPPORTED"]
LABELS: tuple[ClassificationLabel, ...] = get_args(ClassificationLabel)
SEARCH_KNOWLEDGE, CLARIFY, UNSUPPORTED = LABELS
