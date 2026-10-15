import unittest

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.prompt_values import PromptValue
from langchain_core.runnables import RunnableLambda

from generation.profiles import DEFAULT_PROMPT_PROFILE, build_profile_prompt
from generation.service import build_generation_pipeline
from generation.types import GenerationResult, GenerationStatus


class _MetadataCapture(BaseCallbackHandler):
    def __init__(self):
        self.metadata = []

    def on_chain_start(
        self,
        serialized,
        inputs,
        *,
        run_id,
        parent_run_id=None,
        tags=None,
        metadata=None,
        **kwargs,
    ):
        self.metadata.append(metadata or {})


class GenerationPipelineTests(unittest.TestCase):
    def test_named_pipeline_preserves_prompt_messages_and_validates_result(self):
        question = "연차 신청은 어디에서 하나요?"
        documents = ["인사 시스템에서 신청합니다."]
        expected = build_profile_prompt(question, documents, DEFAULT_PROMPT_PROFILE)
        received = []

        def invoke(prompt_value: PromptValue) -> AIMessage:
            messages = prompt_value.to_messages()
            received.extend(messages)
            return AIMessage(
                content='{"answer":"인사 시스템에서 신청하세요."}',
                usage_metadata={
                    "input_tokens": 11,
                    "output_tokens": 7,
                    "total_tokens": 18,
                },
                response_metadata={"finish_reason": "stop"},
            )

        result = build_generation_pipeline(RunnableLambda(invoke)).invoke(
            {
                "question": question,
                "documents": documents,
                "prompt_profile": DEFAULT_PROMPT_PROFILE,
                "classification_context": None,
            }
        )

        self.assertEqual(
            received,
            [
                SystemMessage(content=expected.system),
                HumanMessage(content=expected.user),
            ],
        )
        self.assertEqual(
            result,
            GenerationResult(
                GenerationStatus.COMPLETED,
                '{"answer":"인사 시스템에서 신청하세요."}',
                "인사 시스템에서 신청하세요.",
                11,
                7,
                "stop",
            ),
        )

    def test_named_pipeline_keeps_finish_reason_length_over_valid_json(self):
        pipeline = build_generation_pipeline(
            RunnableLambda(
                lambda _prompt: AIMessage(
                    content='{"answer":"안내"}',
                    usage_metadata={
                        "input_tokens": 10,
                        "output_tokens": 5,
                        "total_tokens": 15,
                    },
                    response_metadata={"finish_reason": "length"},
                )
            )
        )

        result = pipeline.invoke(
            {
                "question": "질문",
                "documents": ["문서"],
                "prompt_profile": DEFAULT_PROMPT_PROFILE,
                "classification_context": None,
            }
        )

        self.assertEqual(result.status, GenerationStatus.TRUNCATED)
        self.assertEqual(result.raw_text, '{"answer":"안내"}')
        self.assertEqual((result.input_tokens, result.output_tokens), (10, 5))

    def test_named_stages_include_trace_callback_metadata(self):
        capture = _MetadataCapture()
        pipeline = build_generation_pipeline(
            RunnableLambda(lambda _prompt: AIMessage(content='{"answer":"안내"}'))
        )

        pipeline.invoke(
            {
                "question": "질문",
                "documents": ["문서"],
                "prompt_profile": DEFAULT_PROMPT_PROFILE,
                "classification_context": None,
            },
            config={"callbacks": [capture]},
        )

        labels = {
            metadata["sanaebi_trace_stage"]: (
                metadata["sanaebi_trace_run_name"],
                metadata["sanaebi_trace_role"],
            )
            for metadata in capture.metadata
            if "sanaebi_trace_stage" in metadata
        }
        self.assertEqual(
            labels["generation_profile"], ("generation_profile", "transform")
        )
        self.assertEqual(labels["generation_model"], ("generation_model", "model"))


if __name__ == "__main__":
    unittest.main()
