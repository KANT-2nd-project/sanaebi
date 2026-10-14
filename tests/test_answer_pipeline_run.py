"""평가 세트 대조와 main의 LangChain 실행기로 모델별 실행이 기록되는지 본다.

모델은 가짜 채팅 모델로 바꾼다 (비용·네트워크 없음).
"""

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

import sanaebi_assistant as assistant
from answer_pipeline.checks import answer_checks
from answer_pipeline.cli import DEFAULT_EVAL_SET_PATH, build_parser, main
from answer_pipeline.run import (
    ModelConfig,
    applied_conditions,
    check_eval_set,
    executor_settings,
    load_documents,
    load_eval_set,
    parse_model_configs,
    read_jsonl,
    record_key,
    run_case,
    run_comparison,
)
from tests.answer_pipeline_support import (
    DOCUMENTS,
    LEAVE_DOC,
    ROOM_DOC,
    case,
    unsupported_case,
)

LOCAL = ModelConfig(
    name="local-test", provider="ollama", model="test-local", num_ctx=8192
)
CLOUD = ModelConfig(name="cloud-test", provider="openai", model="test-cloud")


def answer(text):
    return json.dumps(
        {"answer": text, "referenced_documents": [], "note": "테스트 근거"},
        ensure_ascii=False,
    )


class StructuredFakeChatModel(GenericFakeChatModel):
    def with_structured_output(self, schema, **kwargs):
        from langchain_core.runnables import RunnableLambda

        return self | RunnableLambda(
            lambda message: schema.model_validate_json(message.content)
        )


def fake_model(text, finish_reason="stop", seen=None):
    """실행기가 만드는 채팅 모델 대신 쓰는 가짜 모델. 만들 때의 실행기 설정을 seen에 남긴다."""

    def create(provider):
        if seen is not None:
            seen.append((provider, assistant.OLLAMA_MODEL, assistant.OLLAMA_NUM_CTX))
        message = AIMessage(
            content=text,
            usage_metadata={
                "input_tokens": 1200,
                "output_tokens": 30,
                "total_tokens": 1230,
            },
            response_metadata={"done_reason": finish_reason, "model": "served-model"},
        )
        return StructuredFakeChatModel(messages=iter([message]))

    return create


class ExecutorPatch(unittest.TestCase):
    def use_model(self, text, finish_reason="stop", seen=None):
        patches = (
            patch.object(
                assistant, "create_chat_model", fake_model(text, finish_reason, seen)
            ),
            patch.object(assistant, "ensure_ollama_server", lambda: None),
        )
        for item in patches:
            item.start()
            self.addCleanup(item.stop)


class RunCaseTests(ExecutorPatch):
    def test_records_prompt_usage_and_raw_response_from_executor(self):
        seen = []
        self.use_model(answer("그룹웨어에서 신청하세요."), seen=seen)
        default_model = assistant.OLLAMA_MODEL
        documents_path = (
            Path(self.enterContext(tempfile.TemporaryDirectory())) / "docs.jsonl"
        )
        document = {"title": "실행 테스트 문서", "document": "실행 테스트 근거"}
        documents_path.write_text(
            json.dumps(document, ensure_ascii=False) + "\n", encoding="utf-8"
        )

        result = run_case(
            case(question="연차 신청은 어떻게 하나요?"),
            LOCAL,
            documents_path=documents_path,
        )

        self.assertIsNone(result["error"])
        self.assertTrue(result["llm_called"])
        self.assertEqual(seen, [("ollama", "test-local", 8192)])  # 설정이 적용됐다
        self.assertEqual(assistant.OLLAMA_MODEL, default_model)  # 끝나면 되돌린다
        self.assertIn("연차 신청은 어떻게 하나요?", result["prompt"])
        self.assertIn("실행 테스트 근거", result["prompt"])
        self.assertEqual(result["response_text"], answer("그룹웨어에서 신청하세요."))
        self.assertEqual(
            result["executor_output"]["answer"], "그룹웨어에서 신청하세요."
        )  # 실행기 출력도 남긴다
        self.assertEqual(result["usage"], {"input_tokens": 1200, "output_tokens": 30})
        self.assertEqual(result["finish_reason"], "stop")
        self.assertTrue(result["generation_complete"])
        self.assertEqual(result["served_model"], "served-model")

    def test_structured_tool_call_preserves_raw_text_and_payload(self):
        from langchain_core.outputs import ChatGeneration, LLMResult

        from answer_pipeline.checks import answer_text
        from answer_pipeline.run import CallCapture

        payload = {
            "answer": "그룹웨어에서 신청하세요.",
            "referenced_documents": ["연차"],
            "note": "정책 근거",
        }
        message = AIMessage(
            content="",
            tool_calls=[
                {"id": "call-test", "name": "AssistantResponse", "args": payload}
            ],
            response_metadata={"finish_reason": "tool_calls"},
        )
        capture = CallCapture()
        capture.on_llm_end(LLMResult(generations=[[ChatGeneration(message=message)]]))
        self.assertEqual(capture.raw_text, "")
        self.assertEqual(capture.structured_response, payload)
        record = {
            **case(),
            "llm_called": True,
            "error": None,
            "generation_complete": True,
            "response_text": "",
            "structured_response": capture.structured_response,
        }
        self.assertTrue(
            next(c["ok"] for c in answer_checks(record) if c["code"] == "A3")
        )
        self.assertEqual(answer_text(record), payload["answer"])
        record["structured_response"] = {"answer": "불완전"}
        self.assertFalse(
            next(c["ok"] for c in answer_checks(record) if c["code"] == "A3")
        )

    def test_length_stop_is_incomplete(self):
        self.use_model('{"text": "그룹웨어에서', finish_reason="length")
        result = run_case(case(), LOCAL)
        self.assertFalse(result["generation_complete"])

    def test_unparsable_reply_is_format_failure_not_call_error(self):
        # 모델은 답했는데 실행기가 평문을 풀지 못하면 A1(호출)은 통과하고 A3(형식)에서 실패한다
        self.use_model("그룹웨어에서 신청하세요.")
        result = run_case(case(), LOCAL)
        self.assertIsNone(result["error"])
        self.assertEqual(result["output_error"], "ValidationError")
        self.assertEqual(result["response_text"], "그룹웨어에서 신청하세요.")
        self.assertTrue(result["generation_complete"])
        checks = {c["code"]: c["ok"] for c in answer_checks({**case(), **result})}
        self.assertTrue(checks["A1"])
        self.assertFalse(checks["A3"])

    def test_non_answer_route_uses_no_documents(self):
        self.use_model(answer("지원 범위가 아닙니다."))
        result = run_case(unsupported_case(), LOCAL)
        self.assertIn("사용하지 않음", result["prompt"])

    def test_failure_is_recorded_with_type_only(self):
        def broken(provider):
            raise RuntimeError("secret-key-1234")

        with patch.object(assistant, "create_chat_model", broken):
            result = run_case(case(), LOCAL)
        self.assertEqual(result["error"], "RuntimeError")
        self.assertIsNone(result["output_error"])
        self.assertFalse(result["llm_called"])
        self.assertFalse(result["generation_complete"])
        self.assertNotIn("secret", json.dumps(result))


class RunComparisonTests(unittest.TestCase):
    def setUp(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self.run_dir = Path(temp_dir.name) / "run"

    def test_same_cases_go_to_every_model_and_are_saved(self):
        calls = []

        def run_fn(test_case, config):
            calls.append((test_case["id"], config.name))
            return {
                "llm_called": True,
                "prompt": "p",
                "response_text": answer("답"),
                "executor_output": None,
                "usage": {"input_tokens": 1, "output_tokens": 1},
                "generation_complete": True,
                "finish_reason": "stop",
                "served_model": None,
                "latency_seconds": 0.1,
                "error": None,
            }

        cases = [case("q1"), case("q2")]
        records = run_comparison(
            cases, self.run_dir, [LOCAL, CLOUD], 2, {}, run_fn, log=lambda _: None
        )
        self.assertEqual(len(records), 8)
        self.assertEqual(calls[:4], [("q1", "local-test"), ("q1", "cloud-test")] * 2)
        self.assertEqual([r["cold_start"] for r in records[:3]], [True, True, False])
        self.assertEqual(
            records[0]["limits"], {"num_ctx": 8192, "max_output_tokens": 512}
        )
        self.assertEqual(read_jsonl(self.run_dir / "results.jsonl"), records)
        with self.assertRaises(FileExistsError):
            run_comparison(cases, self.run_dir, [LOCAL], 1, {}, run_fn)


class ModelConfigTests(unittest.TestCase):
    def test_rejects_settings_the_executor_does_not_apply(self):
        for rows in (
            [{"name": "c", "provider": "openai", "temperature": 0.2}],
            [{"name": "c", "provider": "openai", "num_ctx": 4096}],
            [{"name": "c", "provider": "openai", "base_url": "http://x"}],
            [{"name": "l", "provider": "ollama", "api_key": "x"}],
            [{"name": "x", "provider": "anthropic"}],
            [{"name": "a b", "provider": "ollama"}],
            [{"name": "l", "provider": "ollama"}, {"name": "l", "provider": "openai"}],
            [],
        ):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                parse_model_configs(rows)

    def test_applied_conditions_fill_executor_defaults(self):
        conditions = applied_conditions(CLOUD)
        self.assertEqual(conditions["model"], "test-cloud")
        self.assertEqual(conditions["max_output_tokens"], assistant.OPENAI_MAX_TOKENS)
        self.assertEqual(conditions["max_retries"], assistant.MAX_RETRIES)
        self.assertIsNone(conditions["temperature"])  # OpenAI 모델 기본값을 쓴다
        self.assertEqual(
            applied_conditions(LOCAL)["temperature"], assistant.OLLAMA_TEMPERATURE
        )
        # 시간 제한은 두 모델이 같은 실행기 값을 쓴다
        for config in (CLOUD, LOCAL):
            self.assertEqual(
                applied_conditions(config)["timeout_seconds"], assistant.TIMEOUT
            )
        self.assertEqual(applied_conditions(LOCAL)["num_ctx"], 8192)
        self.assertNotEqual(assistant.OPENAI_MODEL, "test-cloud")

    def test_settings_are_restored_after_error(self):
        before = assistant.OLLAMA_NUM_CTX
        with self.assertRaises(KeyError), executor_settings(LOCAL):
            raise KeyError
        self.assertEqual(assistant.OLLAMA_NUM_CTX, before)


class CommandLineTests(ExecutorPatch):
    def setUp(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self.dir = Path(temp_dir.name)
        self.eval_set = self.dir / "eval.jsonl"
        self.eval_set.write_text(
            json.dumps(case("q1", expected_document_ids=None), ensure_ascii=False)
            + "\n"
            + json.dumps(unsupported_case("q2"), ensure_ascii=False)
            + "\n",
            encoding="utf-8",
        )
        self.documents = self.dir / "documents.jsonl"
        self.documents.write_text(
            json.dumps(
                {"title": "테스트 문서", "document": "테스트 정책 본문"},
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        self.models = self.dir / "models.json"

    def write_models(self, *configs):
        self.models.write_text(json.dumps(list(configs)), encoding="utf-8")

    def run_cli(self, *args):
        output = io.StringIO()
        with redirect_stdout(output):
            main(list(args))
        return output.getvalue()

    def test_openai_call_cap_blocks_run(self):
        self.write_models({"name": "cloud", "provider": "openai"})
        with self.assertRaises(SystemExit), redirect_stdout(io.StringIO()):
            main(
                [
                    "run",
                    "--eval-set",
                    str(self.eval_set),
                    "--documents",
                    str(self.documents),
                    "--models",
                    str(self.models),
                    "--run-dir",
                    str(self.dir / "run"),
                    "--max-openai-calls",
                    "3",
                ]
            )
        self.assertFalse((self.dir / "run").exists())

    def test_dry_run_checks_eval_set_without_calling(self):
        self.write_models({"name": "local", "provider": "ollama"})
        output = self.run_cli(
            "run",
            "--eval-set",
            str(self.eval_set),
            "--documents",
            str(self.documents),
            "--models",
            str(self.models),
            "--run-dir",
            str(self.dir / "run"),
            "--dry-run",
        )
        self.assertIn("오류 0건", output)
        self.assertIn("[dry-run]", output)
        self.assertFalse((self.dir / "run").exists())

    def test_run_then_report_writes_outputs(self):
        self.use_model(answer("그룹웨어에서 신청하세요."))
        self.write_models({"name": "local", "provider": "ollama", "num_ctx": 2048})
        run_dir = self.dir / "run"
        self.run_cli(
            "run",
            "--eval-set",
            str(self.eval_set),
            "--documents",
            str(self.documents),
            "--models",
            str(self.models),
            "--run-dir",
            str(run_dir),
            "--repeats",
            "1",
        )
        output = self.run_cli("report", "--run-dir", str(run_dir))
        self.assertIn("사용 가능 답변: 채점 대기 1건", output)
        meta = json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["models"][0]["num_ctx"], 2048)
        self.assertEqual(len(meta["executor"]["sha256"]), 64)
        self.assertEqual(meta["executor"]["documents_path"], str(self.documents))
        result = read_jsonl(run_dir / "results.jsonl")[0]
        self.assertIn("테스트 정책 본문", result["prompt"])
        report = (run_dir / "report.md").read_text(encoding="utf-8")
        self.assertIn("## 2. 요약 비교표", report)
        # 가짜 모델의 입력 1200토큰 + 출력 512 ≤ 2048 → P5 통과, q2는 LLM이 답해 P1 실패
        checks = read_jsonl(run_dir / "checks.jsonl")
        self.assertEqual([c["failed"] for c in checks], [[], ["P1"]])
        for name in ("results.jsonl", "human_scores_blind.csv", "comparison.json"):
            self.assertTrue((run_dir / name).exists(), name)

    def test_run_requires_explicit_documents_for_nondefault_eval_set(self):
        self.write_models({"name": "local", "provider": "ollama"})
        with self.assertRaisesRegex(SystemExit, "--documents"):
            main(
                [
                    "run",
                    "--eval-set",
                    str(self.eval_set),
                    "--models",
                    str(self.models),
                    "--run-dir",
                    str(self.dir / "run"),
                    "--dry-run",
                ]
            )

    def test_default_eval_set_is_archived_company_knowledge_set(self):
        args = build_parser().parse_args(
            ["run", "--models", "models.json", "--run-dir", "run"]
        )

        self.assertEqual(Path(args.eval_set), DEFAULT_EVAL_SET_PATH)
        self.assertIsNone(args.documents)

    def test_default_eval_and_document_pair_runs_without_overrides(self):
        self.write_models({"name": "local", "provider": "ollama"})
        with (
            patch("answer_pipeline.cli.DEFAULT_EVAL_SET_PATH", self.eval_set),
            patch(
                "answer_pipeline.cli.DEFAULT_EVALUATION_DOCUMENTS_PATH", self.documents
            ),
        ):
            output = self.run_cli(
                "run",
                "--models",
                str(self.models),
                "--run-dir",
                str(self.dir / "run"),
                "--dry-run",
            )

        self.assertIn("오류 0건", output)
        self.assertIn("[dry-run]", output)


def eval_row(**overrides):
    row = {
        "id": "q1",
        "question": "연차는 어디서 신청해요?",
        "split": "final",
        "expected_route": "SEARCH_KNOWLEDGE",
        "expected_document_ids": ["1"],
        "required_points": ["그루"],
        "forbidden_claims": [],
        "topic": "people",
        "question_type": "answerable",
        "evidence_position": "front",
        "note": "",
    }
    row.update(overrides)
    return row


class EvalSetFileTests(unittest.TestCase):
    def setUp(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self.dir = Path(temp_dir.name)

    def write_jsonl(self, name, *rows):
        path = self.dir / name
        path.write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in rows),
            encoding="utf-8",
        )
        return path

    def test_load_eval_set_round_trips_and_requires_split(self):
        path = self.write_jsonl("eval.jsonl", eval_row())
        self.assertEqual(load_eval_set(path), [eval_row()])
        bad = self.write_jsonl("bad.jsonl", eval_row(split=None))
        with self.assertRaises(ValueError):
            load_eval_set(bad)

    def test_load_eval_set_rejects_unknown_field_route_or_tag(self):
        for name, row in (
            ("typo.jsonl", {**eval_row(), "expected_documents": []}),
            ("old.jsonl", eval_row(expected_route="IN_SCOPE")),
            ("type.jsonl", eval_row(question_type="unknown")),
            ("position.jsonl", eval_row(evidence_position="앞")),
        ):
            path = self.write_jsonl(name, row)
            with self.subTest(name=name), self.assertRaises(ValueError):
                load_eval_set(path)

    def test_load_documents_reads_executor_format(self):
        path = self.write_jsonl(
            "ieum_works.jsonl",
            {"title": LEAVE_DOC["title"], "document": LEAVE_DOC["text"]},
            {"title": ROOM_DOC["title"], "document": f"  {ROOM_DOC['text']}  "},
        )
        self.assertEqual(load_documents(path), DOCUMENTS)  # 실행기처럼 공백 정리
        bad = self.write_jsonl("bad.jsonl", {"doc": "이전 형식"})
        with self.assertRaises(ValueError):
            load_documents(bad)

    def test_load_documents_preserves_explicit_stable_ids(self):
        path = self.write_jsonl(
            "stable.jsonl",
            {
                "document_id": "leave-policy-v1",
                "title": LEAVE_DOC["title"],
                "document": LEAVE_DOC["text"],
            },
            {
                "document_id": "room-policy-v1",
                "title": ROOM_DOC["title"],
                "document": ROOM_DOC["text"],
            },
        )

        self.assertEqual(
            load_documents(path),
            {
                "leave-policy-v1": DOCUMENTS["1"],
                "room-policy-v1": DOCUMENTS["2"],
            },
        )

    def test_load_documents_keeps_legacy_row_ids_and_skips_blank_lines(self):
        path = self.dir / "legacy.jsonl"
        path.write_text(
            "\n"
            + json.dumps(
                {"title": LEAVE_DOC["title"], "document": LEAVE_DOC["text"]},
                ensure_ascii=False,
            )
            + "\n  \n"
            + json.dumps(
                {"title": ROOM_DOC["title"], "document": ROOM_DOC["text"]},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        self.assertEqual(load_documents(path), DOCUMENTS)

    def test_load_documents_rejects_mixed_blank_and_duplicate_ids(self):
        legacy = {"title": "제목", "document": "본문"}
        stable = {"document_id": "policy-a", **legacy}
        invalid_rows = (
            ("mixed.jsonl", (stable, legacy)),
            ("blank.jsonl", ({"document_id": "  ", **legacy},)),
            ("wrong-type.jsonl", ({"document_id": None, **legacy},)),
            (
                "duplicate.jsonl",
                (
                    stable,
                    {
                        "document_id": "policy-a",
                        "title": "다른 제목",
                        "document": "다른 본문",
                    },
                ),
            ),
        )
        for name, rows in invalid_rows:
            with self.subTest(name=name):
                path = self.write_jsonl(name, *rows)
                with self.assertRaises(ValueError):
                    load_documents(path)

    def test_historical_eval_set_loads_with_its_archived_documents(self):
        root = Path(__file__).resolve().parents[1]
        archive = root / "data" / "archive" / "company-knowledge-v0"
        documents = load_documents(archive / "ieum_works.jsonl")
        rows = load_eval_set(archive / "eval_set_dev.jsonl")

        errors, _ = check_eval_set(rows, documents)
        self.assertEqual(errors, [])

        with tempfile.TemporaryDirectory() as directory:
            models = Path(directory) / "models.json"
            models.write_text(
                json.dumps([{"name": "local", "provider": "ollama"}]),
                encoding="utf-8",
            )
            output = io.StringIO()
            with redirect_stdout(output):
                main(
                    [
                        "run",
                        "--eval-set",
                        str(archive / "eval_set_dev.jsonl"),
                        "--documents",
                        str(archive / "ieum_works.jsonl"),
                        "--models",
                        str(models),
                        "--run-dir",
                        str(Path(directory) / "run"),
                        "--dry-run",
                    ]
                )
            self.assertIn("오류 0건", output.getvalue())
            self.assertIn("[dry-run]", output.getvalue())


class CheckEvalSetTests(unittest.TestCase):
    def test_complete_row_has_no_errors_or_warnings(self):
        self.assertEqual(check_eval_set([eval_row()], DOCUMENTS), ([], []))

    def test_missing_route_is_an_error(self):
        errors, _ = check_eval_set([eval_row(expected_route=None)], DOCUMENTS)
        self.assertEqual(len(errors), 1)

    def test_unknown_document_is_an_error(self):
        errors, _ = check_eval_set([eval_row(expected_document_ids=["9"])], DOCUMENTS)
        self.assertEqual(len(errors), 1)

    def test_required_point_missing_from_expected_document_is_an_error(self):
        errors, _ = check_eval_set([eval_row(required_points=["인사 포털"])], DOCUMENTS)
        self.assertIn("인사 포털", errors[0])

    def test_non_answer_route_with_expected_documents_is_an_error(self):
        errors, _ = check_eval_set([eval_row(expected_route="UNSUPPORTED")], DOCUMENTS)
        self.assertEqual(len(errors), 1)

    def test_blank_answer_key_gives_warnings(self):
        _, warnings = check_eval_set(
            [
                eval_row(
                    expected_document_ids=None, required_points=[], question_type=None
                )
            ],
            DOCUMENTS,
        )
        self.assertEqual(len(warnings), 3)


class RecordKeyTests(unittest.TestCase):
    def test_record_key_uses_model_name(self):
        record = {"case_id": "q1", "model_name": "local", "repeat": "2"}
        self.assertEqual(record_key(record), ("q1", "local", 2))


if __name__ == "__main__":
    unittest.main()
