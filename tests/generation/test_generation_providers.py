import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import httpx
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from openai import APIConnectionError, APITimeoutError, OpenAI

from generation.config import (
    GenerationConfig,
    GenerationOutputMode,
    GenerationProvider,
)
from generation.output_schema import OPENAI_ANSWER_RESPONSE_FORMAT
from generation.providers import (
    StrictOpenAIChatModel,
    build_model_call,
    build_ollama_call,
    build_ollama_model,
    build_openai_call,
    build_openai_model,
    extract_text,
    invoke_model,
    invoke_openai_message,
    make_model_call,
    to_messages,
)
from generation.service import generate
from generation.types import (
    GenerationPrompt,
    GenerationResult,
    GenerationStatus,
    ModelResponse,
)


class GenerationProviderTests(unittest.TestCase):
    def test_usage_and_provider_finish_reason_are_preserved(self):
        prompt = GenerationPrompt("규칙", "질문")
        for metadata in ({"done_reason": "stop"}, {"finish_reason": "length"}, {}):
            for usage in (
                None,
                {"input_tokens": 12, "output_tokens": 0, "total_tokens": 12},
            ):
                with self.subTest(metadata=metadata, usage=usage):
                    message = AIMessage(
                        content="raw", usage_metadata=usage, response_metadata=metadata
                    )
                    result = invoke_model(prompt, Mock(return_value=message))
                    self.assertEqual(result.raw_text, "raw")
                    self.assertEqual(result.input_tokens, 12 if usage else None)
                    self.assertEqual(result.output_tokens, 0 if usage else None)
                    self.assertEqual(
                        result.finish_reason,
                        metadata.get("done_reason") or metadata.get("finish_reason"),
                    )

    def test_openai_refusal_metadata_and_raw_content_are_preserved(self):
        message = AIMessage(
            content="거절 원문",
            additional_kwargs={"refusal": "요청을 처리할 수 없습니다."},
            usage_metadata={"input_tokens": 8, "output_tokens": 3, "total_tokens": 11},
            response_metadata={"finish_reason": "stop"},
        )
        response = invoke_model(
            GenerationPrompt("규칙", "질문"), Mock(return_value=message)
        )
        self.assertEqual(response.raw_text, "거절 원문")
        self.assertEqual(response.refusal, "요청을 처리할 수 없습니다.")
        self.assertEqual((response.input_tokens, response.output_tokens), (8, 3))
        self.assertEqual(response.finish_reason, "stop")

    def test_refusal_without_text_content_keeps_refusal_metadata(self):
        message = AIMessage(
            content=[{"type": "refusal", "refusal": "요청을 처리할 수 없습니다."}],
            additional_kwargs={"refusal": "요청을 처리할 수 없습니다."},
        )
        response = invoke_model(
            GenerationPrompt("규칙", "질문"), Mock(return_value=message)
        )
        self.assertIsNone(response.raw_text)
        self.assertEqual(response.refusal, "요청을 처리할 수 없습니다.")

    def test_ollama_receives_explicit_token_limits(self):
        config = GenerationConfig(GenerationProvider.OLLAMA, "model", 30, 40960, 512)
        with patch(
            "generation.providers.load_ollama_chat_model", return_value=Mock()
        ) as loader:
            constructor = loader.return_value
            build_ollama_model(config)
            constructor.assert_called_once_with(
                model="model",
                num_ctx=40960,
                num_predict=512,
                client_kwargs={"timeout": 30},
            )
            constructor.return_value.invoke.assert_not_called()

    def test_openai_rejects_context_window_before_client_creation(self):
        config = GenerationConfig(GenerationProvider.OPENAI, "model", 30, 40960, 512)
        with patch("generation.providers.ChatOpenAI") as constructor:
            with self.assertRaisesRegex(ValueError, "context_window"):
                build_openai_model(config)
            constructor.assert_not_called()

    def test_openai_maps_optional_generation_settings(self):
        config = GenerationConfig(
            GenerationProvider.OPENAI,
            "model",
            30,
            max_output_tokens=512,
            reasoning_effort="low",
        )
        with patch("generation.providers.ChatOpenAI") as constructor:
            build_openai_model(config)
            constructor.assert_called_once_with(
                model="model",
                timeout=30,
                max_retries=0,
                max_completion_tokens=512,
                reasoning_effort="low",
            )

    def test_openai_strict_mode_binds_named_schema_to_chat_completions(self):
        config = GenerationConfig(
            GenerationProvider.OPENAI,
            "model",
            30,
            output_mode=GenerationOutputMode.STRICT_JSON_SCHEMA,
        )
        with (
            patch("generation.providers.ChatOpenAI") as constructor,
            patch("generation.providers.OpenAI") as sdk_constructor,
        ):
            model = build_openai_model(config)
            constructor.assert_not_called()
            sdk_constructor.assert_called_once_with(timeout=30, max_retries=0)
        self.assertEqual(model.config, config)

    def test_strict_openai_adapter_builds_public_sdk_payload_without_network(self):
        config = GenerationConfig(
            GenerationProvider.OPENAI,
            "gpt-6-luna",
            30,
            output_mode=GenerationOutputMode.STRICT_JSON_SCHEMA,
        )
        prompt = GenerationPrompt("규칙", "질문")
        with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}):
            model = build_openai_model(config)
        payload = model.build_payload(to_messages(prompt))
        self.assertEqual(payload["response_format"], OPENAI_ANSWER_RESPONSE_FORMAT)
        self.assertEqual(
            payload["messages"],
            [
                {"content": "규칙", "role": "system"},
                {"content": "질문", "role": "user"},
            ],
        )
        model.close()

    def test_strict_openai_create_path_preserves_length_truncation(self):
        config = GenerationConfig(
            GenerationProvider.OPENAI,
            "gpt-6-luna",
            30,
            output_mode=GenerationOutputMode.STRICT_JSON_SCHEMA,
        )
        prompt = GenerationPrompt("규칙", "질문")
        message = Mock(
            content='{"answer":',
            refusal=None,
        )
        completion = Mock(
            id="chatcmpl-test",
            model="gpt-6-luna",
            choices=[Mock(message=message, finish_reason="length")],
            usage=Mock(prompt_tokens=12, completion_tokens=512, total_tokens=524),
        )
        with patch("generation.providers.OpenAI") as constructor:
            model = constructor.return_value
            model.chat.completions.create.return_value = completion
            result = generate(prompt, build_openai_call(config))

        model.chat.completions.create.assert_called_once()
        payload = model.chat.completions.create.call_args.kwargs
        self.assertEqual(payload["model"], "gpt-6-luna")
        self.assertEqual(payload["response_format"], OPENAI_ANSWER_RESPONSE_FORMAT)
        self.assertEqual(
            payload["messages"],
            [
                {"role": "system", "content": "규칙"},
                {"role": "user", "content": "질문"},
            ],
        )
        self.assertEqual(result.status, GenerationStatus.TRUNCATED)
        self.assertEqual(result.raw_text, '{"answer":')
        self.assertEqual((result.input_tokens, result.output_tokens), (12, 512))
        self.assertEqual(result.finish_reason, "length")

    def test_strict_openai_adapter_preserves_refusal_and_usage(self):
        config = GenerationConfig(
            GenerationProvider.OPENAI,
            "gpt-6-luna",
            30,
            output_mode=GenerationOutputMode.STRICT_JSON_SCHEMA,
        )
        prompt = GenerationPrompt("규칙", "질문")
        client = Mock()
        client.chat.completions.create.return_value = SimpleNamespace(
            id="chatcmpl-refusal",
            model="gpt-6-luna",
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=None, refusal="요청을 처리할 수 없습니다."
                    ),
                    finish_reason="stop",
                )
            ],
            usage=SimpleNamespace(
                prompt_tokens=8, completion_tokens=3, total_tokens=11
            ),
        )
        model = StrictOpenAIChatModel(config, client=client)

        result = invoke_model(prompt, model.invoke)

        self.assertIsNone(result.raw_text)
        self.assertEqual(result.refusal, "요청을 처리할 수 없습니다.")
        self.assertEqual((result.input_tokens, result.output_tokens), (8, 3))
        self.assertEqual(result.finish_reason, "stop")
        client.chat.completions.create.assert_called_once()

    def test_installed_sdk_handles_complete_json_with_length_finish_reason(self):
        config = GenerationConfig(
            GenerationProvider.OPENAI,
            "gpt-6-luna",
            30,
            output_mode=GenerationOutputMode.STRICT_JSON_SCHEMA,
        )
        prompt = GenerationPrompt("규칙", "질문")
        body = {
            "id": "chatcmpl-test",
            "object": "chat.completion",
            "created": 0,
            "model": "gpt-6-luna",
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": '{"answer":"안내"}',
                        "refusal": None,
                    },
                    "finish_reason": "length",
                }
            ],
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 5,
                "total_tokens": 15,
            },
        }
        requests = []

        def response_for(request):
            requests.append(request)
            return httpx.Response(200, json=body, request=request)

        model_messages = []
        http_client = httpx.Client(transport=httpx.MockTransport(response_for))
        client = OpenAI(
            api_key="test-key",
            timeout=config.timeout_seconds,
            max_retries=0,
            http_client=http_client,
        )
        model = StrictOpenAIChatModel(config, client=client)
        try:

            def invoke(messages):
                message = invoke_openai_message(config, model, messages)
                model_messages.append(message)
                return message

            result = generate(prompt, make_model_call(invoke))
        finally:
            model.close()

        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0].url.path, "/v1/chat/completions")
        request_payload = json.loads(requests[0].content)
        self.assertEqual(
            request_payload["response_format"], OPENAI_ANSWER_RESPONSE_FORMAT
        )
        self.assertEqual(result.status, GenerationStatus.TRUNCATED)
        self.assertEqual(result.raw_text, '{"answer":"안내"}')
        self.assertEqual((result.input_tokens, result.output_tokens), (10, 5))
        self.assertEqual(result.finish_reason, "length")
        self.assertEqual(model_messages[0].response_metadata["finish_reason"], "length")
        self.assertEqual(
            model_messages[0].response_metadata["model_name"], "gpt-6-luna"
        )

    def test_openai_passes_temperature_only_when_configured(self):
        for temperature, expected in ((None, {}), (0.3, {"temperature": 0.3})):
            with (
                self.subTest(temperature=temperature),
                patch("generation.providers.ChatOpenAI") as constructor,
            ):
                config = GenerationConfig(
                    GenerationProvider.OPENAI,
                    "model",
                    30,
                    temperature=temperature,
                )
                build_openai_model(config)
                constructor.assert_called_once_with(
                    model="model", timeout=30, max_retries=0, **expected
                )

    def test_ollama_passes_temperature_only_when_configured(self):
        for temperature, expected in ((None, {}), (0.3, {"temperature": 0.3})):
            with (
                self.subTest(temperature=temperature),
                patch(
                    "generation.providers.load_ollama_chat_model", return_value=Mock()
                ) as loader,
            ):
                constructor = loader.return_value
                config = GenerationConfig(
                    GenerationProvider.OLLAMA,
                    "model",
                    30,
                    temperature=temperature,
                )
                build_ollama_model(config)
                constructor.assert_called_once_with(
                    model="model",
                    num_ctx=None,
                    num_predict=None,
                    client_kwargs={"timeout": 30},
                    **expected,
                )

    def test_openai_timeout_preserves_cause_and_reaches_timeout_status(self):
        error = APITimeoutError(
            request=httpx.Request("POST", "https://example.invalid")
        )
        prompt = GenerationPrompt(system="규칙", user="질문")
        with self.assertRaises(TimeoutError) as caught:
            invoke_model(prompt, Mock(side_effect=error))
        self.assertIs(caught.exception.__cause__, error)

        config = GenerationConfig(GenerationProvider.OPENAI, "test-model", 12.5)
        with patch("generation.providers.ChatOpenAI") as constructor:
            constructor.return_value.invoke.side_effect = error
            result = generate(prompt, build_model_call(config))
            self.assertEqual(
                result, GenerationResult(GenerationStatus.TIMEOUT, None, None)
            )
            constructor.return_value.invoke.assert_called_once_with(to_messages(prompt))

    def test_openai_connection_error_is_not_mislabeled_as_timeout(self):
        error = APIConnectionError(
            request=httpx.Request("POST", "https://example.invalid")
        )
        with self.assertRaises(APIConnectionError) as caught:
            generate(
                GenerationPrompt(system="규칙", user="질문"),
                make_model_call(Mock(side_effect=error)),
            )
        self.assertIs(caught.exception, error)

    def test_dispatcher_returns_ollama_callable_without_calling_it(self):
        config = GenerationConfig(GenerationProvider.OLLAMA, "test-model", 30.0)
        with patch("generation.providers.build_ollama_call") as builder:
            result = build_model_call(config)
            builder.assert_called_once_with(config)
            self.assertIs(result, builder.return_value)
            result.assert_not_called()

    def test_dispatcher_returns_openai_callable_without_calling_it(self):
        config = GenerationConfig(GenerationProvider.OPENAI, "test-model", 30.0)
        with patch("generation.providers.build_openai_call") as builder:
            result = build_model_call(config)
            builder.assert_called_once_with(config)
            self.assertIs(result, builder.return_value)
            result.assert_not_called()

    def test_openai_builder_rejects_other_provider(self):
        config = GenerationConfig(GenerationProvider.OLLAMA, "test-model", 30.0)
        with patch("generation.providers.ChatOpenAI") as constructor:
            with self.assertRaises(ValueError):
                build_openai_model(config)
            constructor.assert_not_called()

    def test_openai_construction_and_deferred_generation(self):
        config = GenerationConfig(GenerationProvider.OPENAI, "test-model", 12.5)
        with patch("generation.providers.ChatOpenAI") as constructor:
            model = constructor.return_value
            raw = '{"answer": " 안내 "}'
            model.invoke.return_value = AIMessage(content=raw)
            model_call = build_model_call(config)
            constructor.assert_called_once_with(
                model="test-model", timeout=12.5, max_retries=0
            )
            model.invoke.assert_not_called()
            prompt = GenerationPrompt(system="규칙", user="질문")
            self.assertEqual(
                generate(prompt, model_call),
                GenerationResult(GenerationStatus.COMPLETED, raw, "안내"),
            )
            model.invoke.assert_called_once_with(to_messages(prompt))

    def test_http_timeouts_are_translated_with_original_cause(self):
        prompt = GenerationPrompt(system="규칙", user="질문")
        for kind in (
            httpx.ConnectTimeout,
            httpx.ReadTimeout,
            httpx.WriteTimeout,
            httpx.PoolTimeout,
        ):
            error = kind("timeout")
            with self.subTest(kind=kind), self.assertRaises(TimeoutError) as caught:
                invoke_model(prompt, Mock(side_effect=error))
            self.assertIs(caught.exception.__cause__, error)

    def test_ollama_http_timeout_reaches_generation_status(self):
        config = GenerationConfig(GenerationProvider.OLLAMA, "test-model", 12.5)
        with patch(
            "generation.providers.load_ollama_chat_model", return_value=Mock()
        ) as loader:
            constructor = loader.return_value
            constructor.return_value.invoke.side_effect = httpx.ReadTimeout("timeout")
            result = generate(
                GenerationPrompt(system="규칙", user="질문"), build_ollama_call(config)
            )
            self.assertEqual(
                result, GenerationResult(GenerationStatus.TIMEOUT, None, None)
            )

    def test_connection_error_is_not_mislabeled_as_timeout(self):
        error = httpx.ConnectError("connection failed")
        with self.assertRaises(httpx.ConnectError) as caught:
            generate(
                GenerationPrompt(system="규칙", user="질문"),
                make_model_call(Mock(side_effect=error)),
            )
        self.assertIs(caught.exception, error)

    def test_ollama_call_builds_once_and_defers_inference(self):
        config = GenerationConfig(GenerationProvider.OLLAMA, "test-model", 12.5)
        with patch(
            "generation.providers.load_ollama_chat_model", return_value=Mock()
        ) as loader:
            constructor = loader.return_value
            model = constructor.return_value
            raw = '{"answer": " 안내 "}'
            model.invoke.return_value = AIMessage(content=raw)
            model_call = build_ollama_call(config)
            constructor.assert_called_once_with(
                model="test-model",
                num_ctx=None,
                num_predict=None,
                client_kwargs={"timeout": 12.5},
            )
            model.invoke.assert_not_called()

            for question in ("첫 질문", "둘째 질문"):
                prompt = GenerationPrompt(system="규칙", user=question)
                self.assertEqual(
                    generate(prompt, model_call),
                    GenerationResult(GenerationStatus.COMPLETED, raw, "안내"),
                )
                model.invoke.assert_called_with(to_messages(prompt))
            self.assertEqual(model.invoke.call_count, 2)
            constructor.assert_called_once()

    def test_ollama_builder_passes_model_and_timeout_without_invoking(self):
        config = GenerationConfig(GenerationProvider.OLLAMA, "test-model", 12.5)
        with patch(
            "generation.providers.load_ollama_chat_model", return_value=Mock()
        ) as loader:
            constructor = loader.return_value
            model = build_ollama_model(config)
            constructor.assert_called_once_with(
                model="test-model",
                num_ctx=None,
                num_predict=None,
                client_kwargs={"timeout": 12.5},
            )
            self.assertIs(model, constructor.return_value)
            model.invoke.assert_not_called()

    def test_ollama_builder_rejects_other_provider_before_construction(self):
        config = GenerationConfig(GenerationProvider.OPENAI, "test-model", 30.0)
        with patch(
            "generation.providers.load_ollama_chat_model", return_value=Mock()
        ) as loader:
            constructor = loader.return_value
            with self.assertRaises(ValueError):
                build_ollama_model(config)
            constructor.assert_not_called()

    def test_factory_defers_calls_and_keeps_each_callable(self):
        first = Mock(return_value=AIMessage(content="first"))
        second = Mock(return_value=AIMessage(content="second"))
        first_call = make_model_call(first)
        second_call = make_model_call(second)
        first.assert_not_called()
        second.assert_not_called()

        prompt = GenerationPrompt(system="규칙", user="질문")
        self.assertEqual(first_call(prompt), ModelResponse("first"))
        self.assertEqual(second_call(prompt), ModelResponse("second"))
        first.assert_called_once_with(to_messages(prompt))
        second.assert_called_once_with(to_messages(prompt))

    def test_factory_connects_response_to_generation_result(self):
        prompt = GenerationPrompt(system="규칙", user="질문")
        for raw, status, answer in (
            (' {"answer": " 안내 "}\n', GenerationStatus.COMPLETED, "안내"),
            ("invalid JSON", GenerationStatus.PARSE_ERROR, None),
            ('{"answer": " "}', GenerationStatus.EMPTY_ANSWER, None),
        ):
            with self.subTest(raw=raw):
                invoke = Mock(return_value=AIMessage(content=raw))
                result = generate(prompt, make_model_call(invoke))
                self.assertEqual(result, GenerationResult(status, raw, answer))
                invoke.assert_called_once_with(to_messages(prompt))

    def test_factory_connects_timeout_to_generation_result(self):
        prompt = GenerationPrompt(system="규칙", user="질문")
        invoke = Mock(side_effect=TimeoutError("timeout"))
        self.assertEqual(
            generate(prompt, make_model_call(invoke)),
            GenerationResult(GenerationStatus.TIMEOUT, None, None),
        )
        invoke.assert_called_once_with(to_messages(prompt))

    def test_invoke_model_passes_roles_and_preserves_raw_response(self):
        prompt = GenerationPrompt(system="규칙", user="질문")
        raw_text = ' {"answer": " 안내 "}\n'
        invoke = Mock(return_value=AIMessage(content=raw_text))

        self.assertEqual(invoke_model(prompt, invoke), ModelResponse(raw_text))
        invoke.assert_called_once()
        self.assertEqual(
            invoke.call_args.args[0],
            [SystemMessage(content="규칙"), HumanMessage(content="질문")],
        )

    def test_invoke_model_rejects_content_blocks(self):
        invoke = Mock(return_value=AIMessage(content=[{"type": "text", "text": "답"}]))
        with self.assertRaises(TypeError):
            invoke_model(GenerationPrompt(system="규칙", user="질문"), invoke)

    def test_invoke_model_propagates_call_errors(self):
        for error in (TimeoutError("timeout"), RuntimeError("unexpected")):
            with self.subTest(error=error), self.assertRaises(type(error)) as caught:
                invoke_model(
                    GenerationPrompt(system="규칙", user="질문"),
                    Mock(side_effect=error),
                )
            self.assertIs(caught.exception, error)

    def test_extract_text_preserves_raw_content(self):
        for content in (' {"answer": " 안내 "}\n', "", "   ", "invalid JSON"):
            with self.subTest(content=content):
                self.assertEqual(extract_text(content), content)

    def test_extract_text_rejects_non_string_content(self):
        for content in (None, [], {}, 123, True, b"text"):
            with self.subTest(content=content), self.assertRaises(TypeError):
                extract_text(content)

    def test_messages_preserve_roles_order_and_each_requests_content(self):
        for prompt in (
            GenerationPrompt(system="첫 규칙", user="첫 질문"),
            GenerationPrompt(system="다른 규칙", user="문서\n\n다른 질문"),
        ):
            with self.subTest(prompt=prompt):
                messages = to_messages(prompt)
                self.assertEqual(len(messages), 2)
                self.assertIsInstance(messages[0], SystemMessage)
                self.assertIsInstance(messages[1], HumanMessage)
                self.assertEqual(messages[0].content, prompt.system)
                self.assertEqual(messages[1].content, prompt.user)
