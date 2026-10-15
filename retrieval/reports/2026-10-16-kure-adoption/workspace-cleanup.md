# 임시 작업 폴더 보존·정리

로컬 main과 원격의 시작 SHA는 `68b47f37d9ac12ad75bb832339fe842a577b184b`였다. 초기 목록에 있던 모든 작업 HEAD가 main에 포함돼 있는지 확인했다. Git 브랜치·커밋과 정식 보고서는 보존한다.

## 원자료 접근

아래 경로는 현재 개발 환경의 Git 제외 자료다. 팀원이 다운로드할 수 있는 공개 링크가 아니다. 기존 보고서의 과거 절대 경로는 당시 기록으로 유지하고, 재현할 때 아래 대응을 사용한다.

| 과거 위치 | 현재 위치 |
|---|---|
| `.sanaebi-rag-answer-evaluation-20261015/tmp/answer-evaluation/` | `artifacts/retrieval-reference/answer-evaluation/` |
| 같은 작업 폴더의 `tmp/tiny-model` 외부 cache 링크 | `artifacts/retrieval-reference/tiny-model/`의 검증한 실제 파일 |
| `tmp/kure-v3-pilot-2026-10-16/` | `artifacts/retrieval-reference/pilot/` |
| 옛 작업 폴더의 나머지 고유 원자료·로그·미게시 변경 | `artifacts/local-archive/2026-10-16-workspaces/` |
| 새 KURE 모델 및 분할 tokenizer | `artifacts/embeddings/nlpai-lab--KURE-v1/8b418a58414668e75532ed045c22d9ca018ae2b2/` |
| 새 KURE 기본 복원 묶음 | `artifacts/retrieval-baselines/schema-v1/bca3b6b3fc1fb803856881d853a8e7f12fa922310761cd6cb1dc52f862bdfc87/` |
| 새 KURE 격리 색인·검증 DB | `artifacts/kure-runtime-verification-20261016/` |

아카이브 `manifest.json`의 `archived_files`는 출처·상대 경로·크기·SHA256·보존 object 경로를 제공한다. 같은 내용은 `objects/sha256/`의 한 사본에 대응한다. 복구할 파일의 `object`를 별도 목적지에 복사한 뒤 기록 SHA256과 비교한다. `main_diffs`는 당시 main과의 diff다. 이 파일들은 현재 구현을 덮어쓰기 위한 자동 병합 입력이 아니다. 비공개 환경 자료가 포함될 수 있어 아카이브 전체를 Git에 게시하지 않는다.

## 검증 범위

2,211개 출처 항목(파일2,202·링크9), main 대비 diff15개, 재현용 파일45개를 검증했다. 내용 기반 아카이브의 고유 파일은3,443,130,417바이트이며 재현용 별도 자료170,805,091바이트를 준비했다. 파일 수·크기·해시 및 pilot DB/색인 identity를 확인했다. 링크 자체와 필요한 대상 사본을 구분하고 외부 링크 대상은 삭제하지 않는다.

옛 RAG 평가 폴더에서 현재 main과 다른 다음7개는 원본과 diff만 보존하고 자동 반영하지 않았다.

- `retrieval/experiments/calibration_search.py`
- `retrieval/experiments/score_only.py`
- `retrieval/experiments/thresholds.py`
- `retrieval/reports/2026-10-15-context-limits/README.md`
- `retrieval/reports/2026-10-15-context-limits/artifact-manifest.json`
- `retrieval/reports/2026-10-15-context-limits/resumed-results.md`
- `tests/retrieval/test_calibration_search.py`

## 정리 대상

- `.sanaebi-chat-input-publish-20261015`
- `.sanaebi-doc-editor-publish-20261015`
- `.sanaebi-doc-sync-20261015`
- `.sanaebi-document-rag-sync-20261016`
- `.sanaebi-kure-gate-20261016`
- `.sanaebi-prompt-v7-recovery-20261015`
- `.sanaebi-public-demo-20261015`
- `.sanaebi-rag-answer-evaluation-20261015`
- `.sanaebi-rag-c-publication-20261015`
- `.sanaebi-rag-v3-20261015`
- `.sanaebi-readme-reader-20261015`
- `sanaebi-classification-advisory-20261015`
- `sanaebi-company-knowledge`
- `sanaebi-deployment`
- `sanaebi-routing-shadow`
- `sanaebi/tmp/chat-markdown-publication`

가상환경·의존성·빌드·캐시는 재생성 가능한 자료로 분류했다. 삭제 직전 현재 프로세스의 cwd/fd 참조를 확인한다. 새로 발견된 `sanaebi-rag-label-minimal-20261016`은 다른 진행 작업이므로 보존한다. main의 가상환경·모델·DB와 원본 회사 문서는 유지한다.

초기16개 작업 폴더를 제거하고 이미 사라진 `/tmp` worktree12개의 등록을 정리했다. 마지막 등록은 main과 다른 진행 작업 label-minimal 두 개다. 브랜치 삭제0, 외부 심볼릭 링크 대상 삭제0이며 정리 직전 보이는 프로세스 cwd/fd 참조는0이었다.

하드링크를 고려한 회수 가능 블록은7,977,070,592바이트(약7.43GiB)였고,16개 제거 직후 파일시스템 가용량은8,158,793,728바이트(약7.60GiB) 증가했다. 새 아카이브·재현 자료 공간을 빼면 사전 추정 순감소는 약4.06GiB다. 별도로 이번 모델 준비의 불완전 중복 사본2,291,085,628바이트도 완성본과 모든 파일 해시를 대조한 뒤 제거했다. 최종 전체 가용량 변화는 동시 작업의 I/O도 포함하므로 모두16개 폴더 정리 효과라고 주장하지 않는다.

삭제 후 재현 자료·아카이브를 다시 확인하고 새 경로만으로 모델 준비 검증, 색인 status/once, restore-baseline, reset --check 명령이 모두 종료0이었다. 자세한 삭제·prune·검증 로그는 로컬 아카이브의 `removal-log.json`에 보존한다. 하드링크로 외부 캐시가 보유하는 블록은 회수량으로 세지 않는다.
