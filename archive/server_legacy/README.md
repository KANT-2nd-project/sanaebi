# 과거 서버 JSONL 처리

`document_store.py`는 기존 JSONL append·reader를 보존한 코드다. 현재 서버는 SQLite를 사용하며 이 모듈을 import하지 않는다. reader 회귀 테스트는 보관본을 계속 확인한다. 실행 명령이나 활성 저장소로 안내하지 않는다.

과거 단독 KoELECTRA 호환 래퍼와 echo 답변 함수는 호출자가 없어 제거했으며 이전 Git 커밋에서 확인할 수 있다. 현재 구조는 [서버 규약](../../docs/server-conventions.md)을 따른다.
