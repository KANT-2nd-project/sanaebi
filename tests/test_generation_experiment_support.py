import ast
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from generation_evaluation.experiment_support import digest, file_hashes


class ExperimentSupportTests(unittest.TestCase):
    def test_digest_preserves_serialization_and_key_order(self):
        values = [{"한글": [1, None, {"b": True, "a": "값"}]}, [], "문자열", 1.5]
        for value in values:
            expected = hashlib.sha256(
                json.dumps(
                    value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                ).encode()
            ).hexdigest()
            self.assertEqual(digest(value), expected)
        self.assertEqual(digest({"b": 2, "a": 1}), digest({"a": 1, "b": 2}))

    def test_file_hashes_preserve_keys_bytes_and_missing_values(self):
        with tempfile.TemporaryDirectory(dir=".") as directory:
            root = Path(directory)
            path = root / "한글.bin"
            raw = b"\x00\xff\r\n"
            path.write_bytes(raw)
            keys = [str(path), str(root / "missing"), str(root)]
            self.assertEqual(
                file_hashes(keys),
                {
                    keys[0]: hashlib.sha256(raw).hexdigest(),
                    keys[1]: None,
                    keys[2]: None,
                },
            )

    def test_runtime_has_no_evaluation_strategy_import(self):
        for root in (Path("app"), Path("generation")):
            for path in root.rglob("*.py"):
                for node in ast.walk(ast.parse(path.read_text())):
                    if isinstance(node, ast.Import):
                        names = [a.name for a in node.names]
                    elif isinstance(node, ast.ImportFrom):
                        names = [node.module or ""]
                    else:
                        continue
                    self.assertFalse(
                        any("strategies" in name for name in names), str(path)
                    )

    def test_current_evaluation_does_not_load_dated_runners(self):
        # Frozen runners intentionally retain their historical dynamic imports.
        for path in Path("generation_evaluation").rglob("*.py"):
            if "experiments" in path.parts:
                continue
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    self.assertNotIn("experiments", node.module or "", str(path))
                elif isinstance(node, ast.Import):
                    self.assertFalse(
                        any("experiments" in a.name for a in node.names), str(path)
                    )
                elif isinstance(node, ast.Call):
                    name = ast.unparse(node.func)
                    self.assertNotIn(
                        name,
                        (
                            "importlib.import_module",
                            "importlib.util.spec_from_file_location",
                            "__import__",
                        ),
                        str(path),
                    )
