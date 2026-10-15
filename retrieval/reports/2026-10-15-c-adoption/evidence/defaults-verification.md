# RAG 기본값·배포 호환 검증 기록

검증일: 2026-10-15 (Asia/Seoul)

## RED: 기본값·배포 호환 회귀 추가 직후

명령:

```text
uv run --locked python -m unittest tests.runtime.test_retrieval_mode_settings tests.runtime.test_deployment_embedding tests.runtime.test_deploy_release.HostPathTests tests.runtime.test_production_maintenance.RagHostMaintenanceTests
```

결과: 32개 중 실패 3건, 오류 2건. 실패는 의도한 동작 차이를 확인했다.

- `get_retrieval_mode()`가 미설정 시 `full`을 반환하여 새 계약 `rag` 기본값 assertion 실패.
- 정적 retrieval descriptor가 아직 `full`이라 신규 descriptor 기대값 assertion 실패.
- 후보 descriptor의 `rag` 기본값을 parser가 거부해 후보 fallback 테스트 2건 오류.
- 자정/유지보수 helper가 미설정 시 descriptor 기본값 대신 `full`을 선택해 기대값 assertion 실패.

## GREEN: 배포 기본값 및 호환 테스트

명령:

```text
uv run --locked python -m unittest tests.runtime.test_retrieval_mode_settings tests.runtime.test_deployment_embedding tests.runtime.test_deploy_release tests.runtime.test_production_maintenance tests.runtime.test_rag_http
```

결과:

```text
Ran 59 tests in 0.081s
OK
```

포함 확인: 미설정 앱 기본 `rag`, 명시적 `full` 우선, 신규 descriptor `rag`, 구형 descriptor `full`, descriptor 없는 릴리스 `full`, Compose API/indexer 기본값, 실제 실행 컨테이너의 환경변수 부재 시 구형 `full` 판정, 기존 배포·복구 및 RAG HTTP 테스트.

## 정적 검사

- `uv run --locked ruff check app/settings.py scripts/deployment_embedding.py scripts/deploy_release.py scripts/production_maintenance.py tests/runtime/test_retrieval_mode_settings.py tests/runtime/test_deployment_embedding.py tests/runtime/test_deploy_release.py tests/runtime/test_production_maintenance.py` — 통과.
- 동일 파일 대상 `uv run --locked ruff format --check ...` — 8개 파일 모두 이미 포맷됨.
- 해당 변경 파일 대상 `git diff --check` — 통과.

## 별도 readiness 테스트 결과

명령:

```text
uv run --locked python -m unittest tests.runtime.test_retrieval_mode_settings tests.runtime.test_deployment_embedding tests.runtime.test_deploy_release tests.runtime.test_production_maintenance tests.runtime.test_rag_http tests.runtime.test_rag_followup_readiness
```

배포 담당 59개는 통과했으나, 추가된 `tests.runtime.test_rag_followup_readiness`에서 5건이 실패했다. 동시 mock generation 1·2·4건은 기대 HTTP 200 대신 500을 받았고, worker 변경 중 요청 및 복원 후 검색 결과에서 evidence가 비었다. 이는 배포 기본값 테스트 밖의 검색 품질 fixture/런타임 경계로 분리해 상위 작업에서 확인할 필요가 있다.

## 수정 파일

- `app/settings.py`
- `deployment/retrieval-release.json`
- `deployment/compose.production.yaml`
- `scripts/deployment_embedding.py`
- `scripts/deploy_release.py`
- `scripts/production_maintenance.py`
- `tests/runtime/test_retrieval_mode_settings.py`
- `tests/runtime/test_deployment_embedding.py`
- `tests/runtime/test_deploy_release.py`
- `tests/runtime/test_production_maintenance.py`

이 기록은 작업 공간의 `tmp/` 아래 임시 검증 자료이며, 제품 문서나 배포 산출물이 아니다.
