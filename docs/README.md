# 문서 찾아보기

[프로젝트 README](../README.md)는 서비스 목적·사용 모습·현재 구성과 공통 시작을 소개하는 진입점이다. 이 색인은 목적별 상세 문서를 안내한다. 서버 코드를 이해하려면 [서버 요청 흐름](../app/README.md)으로 바로 이동해도 된다.

```mermaid
flowchart TD
    R["프로젝트 README"] --> S["이해: 서버 요청·분류 추론"]
    R --> W["작업: 학습·문서 관리·배포"]
    R --> C["참조: 정책·설정·데이터 계약"]
    R --> H["근거: 실험 보고서·과거 기록"]
```

## 이해하기

| 문서 | 읽는 목적 |
|---|---|
| [서버 요청 흐름](../app/README.md) | 시작·의존성 조립·질문 한 건의 처리 |
| [서버 분류기 추론](../app/classification/README.md) | 토큰화·점수·라벨, 저장본 로딩과 재사용 |
| [서비스 아키텍처](service-architecture.md) | 현재 처리 정책과 후속 설계의 경계 |
| [프런트엔드 설계](frontend-architecture.md) | 화면·API 중계·정적 내보내기 |

## 작업하기

| 문서 | 작업 |
|---|---|
| [프로젝트 빠른 시작](../README.md#빠른-시작) | 설치·통합 실행 |
| [서버 준비·API 확인](../app/README.md#실행-준비와-api-확인) | 모델·문서·제공자 준비, HTTP 확인과 선택적 답변 요청 |
| [분류기 독립 확인](../app/classification/README.md#분류기만-직접-확인하기) | HTTP·문서 저장소 없이 로컬 저장본 추론 |
| [분류 학습](../classification/README.md) | 데이터·그룹 분할·TF-IDF·Transformer 학습과 명시적 평가 |
| [문서 관리](document-management.md) | 등록·개정·게시·사용 중단·이관·내보내기 |
| [생성 모듈](../generation/README.md) · [별도 평가 실행](../generation_evaluation/README.md) | 서버와 분리한 생성·평가 |
| [웹 개발](../web/README.md) · [배포](../deployment/README.md) | 프런트 개발·정적 빌드·nginx 구성 |

## 계약과 기준 찾기

| 문서 | 기준 위치 |
|---|---|
| [서버 규약](server-conventions.md) | 책임·내부 계약·설정·오류·회귀 검증 |
| [라벨 기준](label-taxonomy.md) | 세 처리 라벨의 의미와 경계 사례 |
| [데이터 안내](../data/README.md) | 분류 데이터와 답변용 회사 지식의 용도·검수·분할 |
| [생성 평가 기준](generation-evaluation.md) | 응답 검사와 품질 평가 기준 |
| [문서 관리 가이드](documentation-guide.md) | 사실의 기준 위치·Notion 대응·작성 절차 |

## 결과와 과거 기록

| 문서 | 시간·용도 구분 |
|---|---|
| [분류 보고서 목록](../classification/reports/README.md) | 현재 학습 코드의 비교·선정 판단과 근거 |
| [서버 연결 기록](worklogs/2026-10-15-server-classifier-integration.md) | 선정 checkpoint 연결·당시 검증 결과 |
| [서버 구조 정리 기록](worklogs/2026-10-15-server-feature-layout.md) | 기능별 재배치·호환·당시 검증 |
| [작업 기록 폴더](worklogs/) | 작업별 변경·실행·검증 경위. 현재 사용법은 해당 기준 문서 확인 |
| [기존 분류 구현](../archive/classification_v1/README.md) · [과거 실험 보고서](../archive/classification_v1/reports/README.md) | 보존된 sanaebi CLI·MLflow·과거 저장 형식과 결과 |
| [과거 문서 주제 분류](../data/archive/document-topics-v0.2/README.md) · [과거 질문 주제 분류](../data/archive/question-topics/README.md) | 현재 처리 라벨과 구별되는 이전 자료 |

과거 결과를 현재 실행 결과로 옮겨 쓰지 않는다. 학습·모델 선정·서버 연결·실서비스 품질은 별도로 확인한다. 실행 원자료와 가중치의 로컬 위치는 각 보고서에 있으며 공개 다운로드 링크가 아니다.
