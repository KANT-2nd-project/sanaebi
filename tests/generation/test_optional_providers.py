import builtins
import unittest
from unittest.mock import patch

from generation.optional_providers import load_ollama_chat_model


class OptionalProviderTests(unittest.TestCase):
    def test_missing_ollama_explains_install_command(self):
        original = builtins.__import__

        def missing(name, *args, **kwargs):
            if name == "langchain_ollama":
                raise ModuleNotFoundError(name=name)
            return original(name, *args, **kwargs)

        with (
            patch("builtins.__import__", side_effect=missing),
            self.assertRaisesRegex(ImportError, "uv sync --locked --extra ollama"),
        ):
            load_ollama_chat_model()

    def test_transitive_import_failure_is_not_disguised(self):
        error = ModuleNotFoundError(name="broken_dependency")
        with (
            patch("builtins.__import__", side_effect=error),
            self.assertRaises(ModuleNotFoundError) as caught,
        ):
            load_ollama_chat_model()
        self.assertIs(caught.exception, error)
