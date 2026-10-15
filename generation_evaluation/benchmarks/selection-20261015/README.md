# 2026-10-15 생성 답변 평가 세트

이 폴더는 프롬프트 개선용 개발 세트와 별도 최종 모델 비교 세트를 고정한다. 각 문항의 필수 주장, 금지 주장, 판정 근거와 답변 가능성은 모델 응답을 열기 전에 정의했다. GPT/Qwen 응답이나 튜닝 결과는 문항 구성에 사용하지 않았다.

## 파일과 판정

- `dev.json`: 회귀·개선 확인용 8문항. 기존 프롬프트 실험의 5개 회귀 문항과 정상·경계 확인 3문항이다.
- `final.json`: 최종 선택용 holdout 20문항. `normal` 8, `missing` 4, `boundary` 4, `authority` 2, `false_premise` 2개다. 18개는 `data/dataset.csv`의 기존 `SEARCH_KNOWLEDGE` 문항이며, 데이터에 부족한 잘못된 전제 유형 2개는 합성으로 보충하고 `source`에 표시했다.
- `rubric.json`: 두 세트에 공통으로 적용한다. 형식·근거·범위와 조건·완전성·유보 판단·행동 경계·말투·관련성을 평가한다. 차원별 판정은 `pass`/`fail`/`na`/`uncertain`이며 근거와 이유를 기록한다. 형식은 코드로 검증하고 의미 품질은 모델명을 가린 검토로 판정한다.

각 문항은 고유한 `group_id`를 가진다. 개발 세트와 최종 세트 사이 그룹 ID는 겹치지 않는다. 2개의 합성 문항은 기존 데이터 문항을 바꿔 쓰지 않았으며 별도 합성 출처와 그룹 ID를 갖는다. 모델 출력이 생긴 뒤 최종 문항이나 rubric을 수정하지 않는다. 수정이 불가피하면 새 버전으로 만들고 기존 hash·실험 기록을 보존한다.

## 고정 입력과 hash

| 입력 | SHA-256 |
|---|---|
| 71개 문서 snapshot (`generation-cli-documents.jsonl`) | `d58dc0ab1d40bdb9fff68362dc4f5a241fb34ac7fee92f551851d933c1adde74` |
| 원본 질문 (`data/dataset.csv`) | `a7d65d3556899a529278f69d5e4d177722fc73fa71c23bbfc006149b0c551c98` |
| `dev.json` | `519171f4cc554fc2866867479d919dfccd25f7db27ee56925f55630d22d56cb9` |
| `final.json` | `94e6a0fe13da9855001e127e335e685b44bfd77f22ca1f5279287659238f6e1b` |
| `rubric.json` | `7ad85447a6d41de5963090debdab4a6e60c0e63110acee1a7fd0cac65b7ba2aa` |

`evidence`의 인용은 고정 문서 `document` 필드의 원문 부분 문자열이어야 한다. 데이터·문서 snapshot hash가 다르면 이전 평가와 같은 평가로 취급하지 않는다. 이 세트는 회사 문서의 소규모 모델 선택 자료로, 전체 질문 정확도나 운영 환경의 품질을 입증하지 않는다.
