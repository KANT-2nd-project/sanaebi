# 과거 문서 주제 분류 코드

`document_split.py`는 과거 6개 문서 주제 라벨의 분할·기록 복원을 보존한다. 현재 요청 처리 3분류 학습에서는 사용하지 않는다.

데이터·출처·분할 기준은 [문서 주제 아카이브](../../../data/archive/document-topics-v0.2/README.md)를 따른다. 기본 시드 42와 기존 알고리즘을 유지하며, 기본 CSV 경로는 저장소의 `data/archive/document-topics-v0.2/dataset.csv`다. [회귀 테스트](../../../tests/test_document_split.py)로 동작을 확인한다.
