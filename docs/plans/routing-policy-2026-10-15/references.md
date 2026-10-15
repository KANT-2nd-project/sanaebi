# 기업별 근거 검토

확인일 2026-10-15. 아래는 원문의 요약이며, 인용문이나 회사 전체의 운영 보증이 아니다. ‘확인’은 문서·코드에 나타난 내용, ‘적용 해석’은 사내비에 대한 연구자의 판단이다. 동적 문서는 이후 바뀔 수 있다.

## 1. Anthropic — 라우팅은 조건에 맞는 패턴

[Building effective agents](https://www.anthropic.com/engineering/building-effective-agents), 최초 게시 2024-12-19. 이후 도구 생태계 변화 안내가 있는 설계 글이다.

- 확인: 입력을 분류하여 별도 후속 작업으로 보낸다. 서로 다르게 처리할 범주가 있고 정확한 분류가 가능할 때 적합하다. 분류에는 LLM과 전통적 모델 모두 가능하다. 간단한 구조부터 시작하고 복잡성·비용·지연을 고려한다.
- 적용 해석: 분류기를 두는 것 자체는 정당한 설계다. 그러나 정상 질문을 반복 차단하는 모델이라면 적합 조건을 다시 검증해야 한다.
- 한계: SEARCH/CLARIFY/UNSUPPORTED, 한국어 KoELECTRA, 회사 무관 질문의 사전 거절을 정하지 않는다. Anthropic 내부 고객 지원 전체의 실제 구조를 공개한 문서도 아니다.

## 2. LangChain — 프레임워크 분기와 제품 정책은 다름

[Workflows and agents](https://docs.langchain.com/oss/python/langgraph/workflows-agents), [Thinking in LangGraph](https://docs.langchain.com/oss/javascript/langgraph/thinking-in-langgraph). 동적 공식 구현 가이드.

- 확인: 라우팅을 작업별 경로 선택으로 설명한다. 후자의 지원 에이전트 예시는 의도·긴급도 분류, 문서 검색, 필요한 정보 확인 등을 구분한다.
- 적용 해석: 분류 대상은 요구되는 후속 행동으로 정의해야 한다. ‘질문으로 충분한가’는 그 자체로 구체적인 작업 계약이 아니다.
- 한계: 프레임워크가 분기를 지원한다는 사실은 모든 지식 챗봇에 별도 학습 분류기가 필요하다는 근거가 아니다. 특정 회사의 운영 아키텍처도 아니다.

## 3. Microsoft — 근거 제한을 생성 단계에 둔 공개 샘플

기존 조사에서 사용한 revision `558ffd397eddcfe4da5c85ebc285796b367eb9b2`를 고정했다.

- [답변 시스템 프롬프트](https://github.com/Azure-Samples/azure-search-openai-demo/blob/558ffd397eddcfe4da5c85ebc285796b367eb9b2/app/backend/approaches/prompts/chat_answer.system.jinja2): 출처의 사실만 사용하고 부족하면 모른다고 답하도록 지시한다.
- [검색·생성 경로](https://github.com/Azure-Samples/azure-search-openai-demo/blob/558ffd397eddcfe4da5c85ebc285796b367eb9b2/app/backend/approaches/chatreadretrieveread.py): 검토한 일반 경로는 검색 질의를 만들고 검색 결과를 최종 답변 호출에 전달한다. 결과가 없다는 이유만으로 그 경로에서 생성 전 종료하는 분기는 확인되지 않았다.
- [질의 파서](https://github.com/Azure-Samples/azure-search-openai-demo/blob/558ffd397eddcfe4da5c85ebc285796b367eb9b2/app/backend/approaches/approach.py), [재작성 프롬프트](https://github.com/Azure-Samples/azure-search-openai-demo/blob/558ffd397eddcfe4da5c85ebc285796b367eb9b2/app/backend/approaches/prompts/query_rewrite.system.jinja2): 재작성 결과 `0`은 원문 질의로 대체된다. 이것을 범위 밖 질문의 사전 거절로 해석하면 안 된다.

적용 해석: 질문 전달과 일반 지식 답변 허용이 분리되는 구체적 구현이다. 한계: Azure 공식 샘플이며 Microsoft의 모든 운영 제품이 동일하게 처리한다는 뜻은 아니다. 옵션별 다른 경로까지 동일하다고 일반화하지 않는다.

## 4. AWS — 질의 변환·생성·주제 제한은 구별 가능

[Knowledge Bases 설정](https://docs.aws.amazon.com/bedrock/latest/userguide/kb-test-config.html)은 orchestration 프롬프트의 검색 질의 생성과 generation 프롬프트의 검색 결과 활용을 구분한다. 별도 Guardrails 설정도 제공한다.

기존 참조인 [S3 Vectors RAG 샘플 query.py](https://github.com/aws-samples/sample-s3-vectors-rag-pipeline/blob/decec6b9ab0a5965ae7ba2309c0783e5b72fe5b9/query.py), revision `decec6b9ab0a5965ae7ba2309c0783e5b72fe5b9`에서는 검색 결과가 0건이면 생성 전 종료한다. 결과가 있으면 context-only 지침으로 생성하고, 답이 없으면 그 사실을 알리도록 한다.

적용 해석: 검색 후 자료 부재와 질문만 보고 하는 주제 차단은 다르다. 검색 결과가 하나라도 있다는 사실이 충분한 근거를 보장하지도 않는다. 한계: AWS 샘플의 0건 처리를 모든 Bedrock 구성의 동작으로 확대하지 않는다. 별도 주제 가드레일의 존재도 사내비 3분류가 필수라는 근거가 아니다.

## 5. Google — 분류와 차단을 분리한 API

[AnswerGenerationSpec](https://docs.cloud.google.com/gemini/enterprise/docs/reference/rest/v1/AnswerGenerationSpec)은 `ignoreNonAnswerSeekingQuery`, `ignoreAdversarialQuery`, `ignoreJailBreakingQuery`, `ignoreLowRelevantContent`를 별도 옵션으로 둔다. 앞 세 항목은 기본 false이며, 낮은 관련성 처리는 false와 true/미설정의 의미가 다르다. ‘답을 구하는 질의 유형’과 ‘문서 관련성’은 별개다.

[Get answers and follow-ups](https://docs.cloud.google.com/gemini/enterprise/docs/answer)의 query classification 설명은 분류 결과를 반환하더라도 답변은 자동 변경하지 않으며, 답변 단계 설정으로 동작을 바꾼다고 명시한다. **이 페이지는 Legacy 안내이므로 신규 구현 권장 API로 제시하지 않는다.** 여기서는 분류와 차단 분리의 공개 사례로만 사용한다.

이전 조사 자료인 [피부 관리 질문 예제](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/prompt-gallery/samples/answer_question_skin_care_questions)는 제공 정보만 사용하게 한다. [답할 수 없는 질문 예제](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/prompt-gallery/samples/extract_hedge_unanswerable_question)는 대화에 없는 가격을 확정하지 않는 응답을 보여 준다. 프롬프트 예시이며 운영 품질 증거는 아니다.

적용 해석: 사용자 생각과 가까운 ‘답변 추구 여부’ 판단은 실제 공개 API에도 존재하지만, 사내비의 회사 범위 판단과 같은 개념이 아니다. 이 옵션들이 김치 질문을 어떤 값으로 예측하는지 직접 실행한 것은 아니다.

## 6. NVIDIA — 별도 주제 가드레일도 선택 가능

[Query-to-Answer Pipeline](https://docs.nvidia.com/rag/latest/query-to-answer-pipeline.html)의 기본 흐름은 선택적 재작성→검색→선택적 재순위화→생성이다. 활성화한 가드레일 등은 생성 단계에 적용된다.

[NeMo Guardrails](https://docs.nvidia.com/rag/latest/nemo-guardrails.html)는 내용 안전성, 주제 이탈 통제, jailbreak 대응을 설명하며 선택적으로 활성화한다. 모델과 구성의 제약도 명시한다. 이것은 주제 범위를 최종 답변 프롬프트 밖에서 통제하는 설계도 가능하다는 근거다. 해당 설명만으로 반드시 검색 이전에 차단한다고 표현하지 않는다.

[Prompt customization](https://docs.nvidia.com/rag/latest/prompt-customization.html)은 일반 채팅과 지식 기반 답변 템플릿을 구별한다. `use_knowledge_base` 설정을 입력 분류기가 자동으로 판정한다는 증거는 아니다. [Self-reflection](https://docs.nvidia.com/rag/latest/self-reflection.html)은 선택 기능이며 검색 문서 관련성과 생성 후 근거성을 별도로 평가한다.

적용 해석: 범위·안전·근거는 별도 책임이다. 모든 단계를 현재 사내비에 도입하라는 권고는 아니다. `latest` 문서이며 해당 Blueprint가 NVIDIA의 모든 내부 서비스 구조를 대표하지 않는다.

## 7. NAVER Cloud — 분기의 존재와 의미를 구별

[Create conversation API](https://api.ncloud-docs.com/docs/en/rag-create-chat)는 START, QUERY_REWRITE, RETRIEVAL, CONDITIONAL, GENERATOR 단계를 설명한다. 생성기의 `systemPrompt` 설정도 노출한다. **CONDITIONAL은 분기 선택이라고만 설명되며, 회사 범위 분류인지 검색 결과 판단인지 확정할 설명은 확인하지 못했다.**

기존 참고 자료는 [RAG 테스트 안내](https://guide.ncloud-docs.com/docs/rag-services-testmodel)와 [프롬프트 예제](https://guide.ncloud-docs.com/docs/clovastudio-promptsample)다. 이 자료를 회사 전체의 내부 프롬프트나 KoELECTRA 사전 거절 구조의 증거로 쓰지 않는다.

적용 해석: 검색과 생성, 분기를 나누는 구조는 확인 가능하다. 그러나 NAVER도 우리의 3분류를 한다거나 김치 질문을 생성 전에 거절한다는 주장은 근거 부족이다.

## 8. Snyk — 운영 평가 지표를 사전 라우터로 오독하지 않음

[LangChain의 Snyk 사례](https://www.langchain.com/blog/how-snyk-turned-an-internal-support-agent-into-a-customer-feature), 2026-10-08. 사용자 권한에 맞춰 도구를 등록하고, 가드레일·문맥·체크포인터를 갖춘 공통 실행기를 설명한다. 운영 평가에서 회사 관련 질문인지와 응답이 답했는지를 따로 측정한다.

적용 해석: 관련성은 측정해야 하지만 이 운영 평가가 요청 전 거절 분류기라는 뜻은 아니다. 권한별 도구 제한은 자연어 분류보다 실제 서버 권한 통제의 사례다. 한계: 공급사 고객 사례이며 독립 감사가 아니다. 모든 입력 경로·범위 밖 질문 처리·한국어 분류 정책은 공개하지 않는다.

보충: [Snyk Assist 제품 발표](https://updates.snyk.io/snyk-assist-in-ui/)는 지원·온보딩 용도를 설명한다. [생성형 AI 활용 문서](https://docs.snyk.io/snyk-data-and-governance/how-snyk-incorporates-generative-ai-into-the-platform)에서는 지원용 질문 조정과 생성을 구분한다. 전자의 초기 접근 시점과 후속 사례의 배포 시점을 같은 상태로 섞지 않는다.

## 근거의 종합과 남은 미확인

확인된 공통점은 모든 곳의 동일한 입력 분류기가 아니라 **작업·문서·권한·응답 품질을 각각 관리한다는 점**이다. ‘사전 분류를 공개하지 않았다’는 사실만으로 실제로 전혀 사용하지 않는다고 결론 내릴 수 없다. 또한 공개 예제에서 정상 동작하는 지침이 한국어 사내비에서 항상 지켜진다는 보장은 없다.

다음은 미확인이다: 각 회사의 비공개 운영 라우터 전체, 범위 밖 한국어 질문의 실제 응답, 사내비 Luna의 분류 우회 요청 품질과 증가 비용. 이를 이 보고서의 확인 결과로 표현하지 않는다.
