"""Production flow assembly preserves request isolation and early exits."""

import unittest
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import Mock

from app.answering.input import AnswerInput
from app.documents.context import DocumentContextSnapshot
from app.questions.pipeline import build_full_flow, build_rag_flow
from app.questions.service import handle_question
from app.retrieval.types import RetrievalNotReady
from generation.advisory import ClassificationContext
from tests.runtime.test_langchain_adapter import snapshot


class QuestionPipelineTests(unittest.TestCase):
    def test_full_flow_reads_once_and_renders_exact_common_input(self):
        documents = snapshot()
        read = Mock(return_value=documents)
        answer = Mock(return_value="답변")
        flow = build_full_flow(read, answer)
        result = handle_question(
            "질문",
            classify=lambda _: "CLARIFY",
            document_flow=flow,
            routing_mode="advisory",
        )
        self.assertEqual(result.text, "답변")
        read.assert_called_once_with()
        answer.assert_called_once_with(
            AnswerInput.from_snapshot(
                "질문",
                documents,
                classification_context=ClassificationContext("CLARIFY"),
            )
        )

    def test_rag_only_renders_selected_evidence_and_keeps_request_context(self):
        documents = snapshot()
        read = Mock(return_value=documents)

        def retrieve(question, current):
            self.assertIs(current, documents)
            return SimpleNamespace(
                snapshot_fingerprint=current.fingerprint,
                evidence=(
                    SimpleNamespace(
                        knowledge_id="selected", title="제목", text=question, revision=1
                    ),
                ),
                source_document_count=1,
            )

        seen = []

        def answer(value):
            seen.append(value)
            return value.question

        flow = build_rag_flow(read, retrieve, answer)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(
                pool.map(
                    lambda q: (
                        handle_question(
                            q,
                            classify=lambda _: "SEARCH_KNOWLEDGE",
                            document_flow=flow,
                            routing_mode="advisory",
                        ).text
                    ),
                    ["질문-A", "질문-B"],
                )
            )
        self.assertEqual(results, ["질문-A", "질문-B"])
        self.assertEqual(read.call_count, 2)
        for value in seen:
            self.assertEqual(len(value.documents), 1)
            self.assertIn(value.question, value.documents[0])
            self.assertIn("[현재 게시 문서의 발췌 근거]", value.documents[0])

    def test_gate_empty_and_index_failure_never_generate(self):
        for scenario in ("gate", "empty_documents", "empty_retrieval", "unready"):
            with self.subTest(scenario=scenario):
                read = Mock(
                    return_value=DocumentContextSnapshot(())
                    if scenario == "empty_documents"
                    else snapshot()
                )
                retrieve = Mock(return_value=SimpleNamespace(evidence=()))
                answer = Mock()
                if scenario == "unready":
                    retrieve.side_effect = RetrievalNotReady("not ready")
                flow = build_rag_flow(read, retrieve, answer)

                def call(flow=flow, scenario=scenario):
                    return handle_question(
                        "질문",
                        classify=lambda _: "UNSUPPORTED",
                        document_flow=flow,
                        routing_mode="gate" if scenario == "gate" else "advisory",
                    )

                if scenario == "unready":
                    with self.assertRaises(RetrievalNotReady):
                        call()
                else:
                    call()
                answer.assert_not_called()
                if scenario in {"gate", "empty_documents"}:
                    retrieve.assert_not_called()
                if scenario == "gate":
                    read.assert_not_called()
