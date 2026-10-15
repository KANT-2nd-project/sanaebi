from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "deployment_model.py"
SCRIPT_SPEC = importlib.util.spec_from_file_location("deployment_model", SCRIPT_PATH)
if SCRIPT_SPEC is None or SCRIPT_SPEC.loader is None:
    raise RuntimeError("could not load deployment_model.py")
deployment_model = importlib.util.module_from_spec(SCRIPT_SPEC)
sys.modules[SCRIPT_SPEC.name] = deployment_model
SCRIPT_SPEC.loader.exec_module(deployment_model)

REPO_ID = "js2923/sanaebi-koelectra-base"
REVISION = "4a1d0c7964072535a52a66efe29389a6470dd6f4"
MODEL_ID = "9f51682d82d4455d8296077c339afd58"
LABELS = ["SEARCH_KNOWLEDGE", "CLARIFY", "UNSUPPORTED"]
PAYLOAD_NAMES = [
    "config.json",
    "metadata.json",
    "model.safetensors",
    "tokenizer.json",
    "tokenizer_config.json",
]


def make_payload(
    model_id: str = MODEL_ID, labels: list[str] | None = None
) -> dict[str, bytes]:
    actual_labels = LABELS if labels is None else labels
    config = {
        "id2label": {str(index): label for index, label in enumerate(actual_labels)},
        "label2id": {label: index for index, label in enumerate(actual_labels)},
    }
    metadata = {"schema_version": 1, "model_id": model_id, "labels": actual_labels}
    return {
        "config.json": json.dumps(config, sort_keys=True).encode(),
        "metadata.json": json.dumps(metadata, sort_keys=True).encode(),
        "model.safetensors": b"test weights",
        "tokenizer.json": b"test tokenizer",
        "tokenizer_config.json": b"{}",
    }


def write_manifest(path: Path, payload: dict[str, bytes]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    document = {
        "schema_version": 1,
        "repo_id": REPO_ID,
        "revision": REVISION,
        "model_id": MODEL_ID,
        "labels": LABELS,
        "files": [
            {
                "name": name,
                "bytes": len(payload[name]),
                "sha256": hashlib.sha256(payload[name]).hexdigest(),
            }
            for name in PAYLOAD_NAMES
        ],
    }
    path.write_text(json.dumps(document), encoding="utf-8")


def update_manifest_hashes(path: Path, payload: dict[str, bytes]) -> None:
    document = json.loads(path.read_text(encoding="utf-8"))
    for item in document["files"]:
        content = payload[item["name"]]
        item["bytes"] = len(content)
        item["sha256"] = hashlib.sha256(content).hexdigest()
    path.write_text(json.dumps(document), encoding="utf-8")


def make_download_mock(
    payload: dict[str, bytes],
    *,
    extra_files: dict[str, bytes] | None = None,
    missing: set[str] | None = None,
    symlink_name: str | None = None,
) -> tuple[list[dict[str, object]], object]:
    calls: list[dict[str, object]] = []

    def fake_snapshot_download(**kwargs: object) -> str:
        calls.append(kwargs)
        download_dir = Path(str(kwargs["local_dir"]))
        download_dir.mkdir(parents=True)
        for name, content in payload.items():
            if missing and name in missing:
                continue
            destination = download_dir / name
            if name == symlink_name:
                outside_file = download_dir.parent / "outside-payload"
                outside_file.write_bytes(content)
                destination.symlink_to(outside_file)
            else:
                destination.write_bytes(content)
        for name, content in (extra_files or {}).items():
            (download_dir / name).write_bytes(content)
        (download_dir / ".cache" / "huggingface").mkdir(parents=True)
        (download_dir / ".cache" / "huggingface" / "ignored.metadata").write_text(
            "cache", encoding="utf-8"
        )
        return str(download_dir)

    return calls, fake_snapshot_download


@contextmanager
def hf_token(value: str | None):
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("HF_TOKEN", None)
        if value is not None:
            os.environ["HF_TOKEN"] = value
        yield


class DeploymentModelTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(temporary_directory.cleanup)
        self.tmp_path = Path(temporary_directory.name)

    def invoke(self, manifest: Path, root: Path) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            result = deployment_model.main(
                ["--manifest", str(manifest), "--root", str(root)]
            )
        return result, stdout.getvalue(), stderr.getvalue()

    def test_downloads_pinned_release_and_excludes_hf_local_cache(self) -> None:
        manifest = self.tmp_path / "manifest.json"
        root = self.tmp_path / "models"
        payload = make_payload()
        write_manifest(manifest, payload)
        calls, download = make_download_mock(payload)

        with (
            hf_token("runtime-token-that-must-not-be-printed"),
            patch.object(deployment_model, "snapshot_download", side_effect=download),
        ):
            result, stdout, _ = self.invoke(manifest, root)

        destination = root / MODEL_ID / REVISION
        self.assertEqual(result, 0)
        self.assertEqual(
            sorted(path.name for path in destination.iterdir()), PAYLOAD_NAMES
        )
        self.assertEqual(calls[0]["repo_id"], REPO_ID)
        self.assertEqual(calls[0]["revision"], REVISION)
        self.assertEqual(calls[0]["repo_type"], "model")
        self.assertEqual(calls[0]["token"], "runtime-token-that-must-not-be-printed")
        self.assertEqual(set(calls[0]["allow_patterns"]), set(PAYLOAD_NAMES))
        self.assertTrue(Path(str(calls[0]["local_dir"])).is_relative_to(root))
        self.assertNotIn(".cache", {path.name for path in destination.iterdir()})
        self.assertEqual(stdout.strip(), str(destination))

    def test_verified_existing_release_is_reused_without_network(self) -> None:
        manifest = self.tmp_path / "manifest.json"
        root = self.tmp_path / "models"
        payload = make_payload()
        write_manifest(manifest, payload)
        destination = root / MODEL_ID / REVISION
        destination.mkdir(parents=True)
        for name, content in payload.items():
            (destination / name).write_bytes(content)

        with (
            hf_token(None),
            patch.object(
                deployment_model,
                "snapshot_download",
                side_effect=AssertionError("verified cache must not access the Hub"),
            ),
        ):
            result, _, error = self.invoke(manifest, root)

        self.assertEqual(result, 0, error)

    def test_corrupted_existing_release_fails_closed_and_is_preserved(self) -> None:
        manifest = self.tmp_path / "manifest.json"
        root = self.tmp_path / "models"
        payload = make_payload()
        write_manifest(manifest, payload)
        destination = root / MODEL_ID / REVISION
        destination.mkdir(parents=True)
        for name, content in payload.items():
            (destination / name).write_bytes(content)
        corrupted = destination / "model.safetensors"
        corrupted.write_bytes(b"corrupted existing weights")
        calls: list[dict[str, object]] = []

        def forbidden_download(**kwargs: object) -> str:
            calls.append(kwargs)
            raise AssertionError("invalid cache must not be replaced")

        with patch.object(
            deployment_model, "snapshot_download", side_effect=forbidden_download
        ):
            result, _, error = self.invoke(manifest, root)

        self.assertEqual(result, 1)
        self.assertEqual(corrupted.read_bytes(), b"corrupted existing weights")
        self.assertEqual(calls, [])
        self.assertIn("cached release", error)

    def test_interrupted_download_leaves_no_partial_release_and_preserves_previous(
        self,
    ) -> None:
        manifest = self.tmp_path / "manifest.json"
        root = self.tmp_path / "models"
        payload = make_payload()
        write_manifest(manifest, payload)
        previous = root / MODEL_ID / "previous-release"
        previous.mkdir(parents=True)
        (previous / "marker").write_text("keep", encoding="utf-8")
        calls: list[dict[str, object]] = []

        def interrupted_download(**kwargs: object) -> str:
            calls.append(kwargs)
            download_dir = Path(str(kwargs["local_dir"]))
            download_dir.mkdir(parents=True)
            (download_dir / "config.json").write_bytes(payload["config.json"])
            (download_dir / "model.safetensors").write_bytes(b"partial")
            raise RuntimeError(
                "download failed with runtime-token-that-must-not-be-printed"
            )

        with (
            hf_token("test-hf-read-token"),
            patch.object(
                deployment_model, "snapshot_download", side_effect=interrupted_download
            ),
        ):
            result, _, error = self.invoke(manifest, root)

        self.assertEqual(result, 1)
        self.assertEqual(len(calls), 1)
        self.assertFalse((root / MODEL_ID / REVISION).exists())
        self.assertEqual(list(root.glob(".staging-*")), [])
        self.assertEqual((previous / "marker").read_text(encoding="utf-8"), "keep")
        self.assertIn("download", error)
        self.assertNotIn("runtime-token-that-must-not-be-printed", error)

    def test_rejects_wrong_pinned_repository_revision_or_model_path(self) -> None:
        for index, (field, value) in enumerate(
            [
                ("repo_id", "attacker/other-model"),
                ("revision", "main"),
                ("model_id", "../outside"),
            ]
        ):
            with self.subTest(field=field):
                case = self.tmp_path / f"wrong-pin-{index}"
                manifest = case / "manifest.json"
                root = case / "models"
                write_manifest(manifest, make_payload())
                document = json.loads(manifest.read_text(encoding="utf-8"))
                document[field] = value
                manifest.write_text(json.dumps(document), encoding="utf-8")
                calls: list[dict[str, object]] = []

                def forbidden_download(
                    captured_calls: list[dict[str, object]] = calls,
                    **kwargs: object,
                ) -> None:
                    captured_calls.append(kwargs)

                with patch.object(
                    deployment_model,
                    "snapshot_download",
                    side_effect=forbidden_download,
                ):
                    result, _, error = self.invoke(manifest, root)

                self.assertEqual(result, 1)
                self.assertFalse(root.exists())
                self.assertEqual(calls, [])
                self.assertIn("manifest", error)

    def test_rejects_path_traversal_in_manifest_inventory(self) -> None:
        manifest = self.tmp_path / "manifest.json"
        root = self.tmp_path / "models"
        write_manifest(manifest, make_payload())
        document = json.loads(manifest.read_text(encoding="utf-8"))
        document["files"][0]["name"] = "../outside/config.json"
        manifest.write_text(json.dumps(document), encoding="utf-8")
        calls: list[dict[str, object]] = []

        with patch.object(
            deployment_model,
            "snapshot_download",
            side_effect=lambda **kwargs: calls.append(kwargs),
        ):
            result, _, error = self.invoke(manifest, root)

        self.assertEqual(result, 1)
        self.assertFalse(root.exists())
        self.assertEqual(calls, [])
        self.assertIn("manifest", error)

    def test_rejects_symlinked_model_path_before_download(self) -> None:
        manifest = self.tmp_path / "manifest.json"
        root = self.tmp_path / "models"
        write_manifest(manifest, make_payload())
        root.mkdir()
        outside = self.tmp_path / "outside"
        outside.mkdir()
        (root / MODEL_ID).symlink_to(outside, target_is_directory=True)
        calls: list[dict[str, object]] = []

        with patch.object(
            deployment_model,
            "snapshot_download",
            side_effect=lambda **kwargs: calls.append(kwargs),
        ):
            result, _, error = self.invoke(manifest, root)

        self.assertEqual(result, 1)
        self.assertEqual(calls, [])
        self.assertIn("symlink", error)

    def test_private_download_requires_runtime_token(self) -> None:
        manifest = self.tmp_path / "manifest.json"
        root = self.tmp_path / "models"
        write_manifest(manifest, make_payload())
        calls, download = make_download_mock(make_payload())

        with (
            hf_token(None),
            patch.object(deployment_model, "snapshot_download", side_effect=download),
        ):
            result, _, error = self.invoke(manifest, root)

        self.assertEqual(result, 1)
        self.assertEqual(calls, [])
        self.assertIn("HF_TOKEN", error)

    def test_rejects_download_with_extra_missing_or_symlink_payload(self) -> None:
        cases = [
            ({"unexpected.bin": b"x"}, None, None),
            (None, {"tokenizer.json"}, None),
            (None, None, "tokenizer.json"),
        ]
        for index, (extra_files, missing, symlink_name) in enumerate(cases):
            with self.subTest(index=index):
                case = self.tmp_path / f"bad-payload-{index}"
                manifest = case / "manifest.json"
                root = case / "models"
                payload = make_payload()
                write_manifest(manifest, payload)
                calls, download = make_download_mock(
                    payload,
                    extra_files=extra_files,
                    missing=missing,
                    symlink_name=symlink_name,
                )

                with (
                    hf_token("test-hf-read-token"),
                    patch.object(
                        deployment_model, "snapshot_download", side_effect=download
                    ),
                ):
                    result, _, error = self.invoke(manifest, root)

                self.assertEqual(result, 1)
                self.assertEqual(len(calls), 1)
                self.assertFalse((root / MODEL_ID / REVISION).exists())
                self.assertTrue("payload" in error or "symlink" in error)

    def test_rejects_bad_label_or_model_metadata_even_when_hashes_match(self) -> None:
        payloads = [
            make_payload(labels=["SEARCH_KNOWLEDGE", "UNSUPPORTED", "CLARIFY"]),
            make_payload(model_id="wrong-model"),
        ]
        for index, payload in enumerate(payloads):
            with self.subTest(index=index):
                case = self.tmp_path / f"bad-metadata-{index}"
                manifest = case / "manifest.json"
                root = case / "models"
                write_manifest(manifest, make_payload())
                update_manifest_hashes(manifest, payload)
                calls, download = make_download_mock(payload)

                with (
                    hf_token("test-hf-read-token"),
                    patch.object(
                        deployment_model, "snapshot_download", side_effect=download
                    ),
                ):
                    result, _, error = self.invoke(manifest, root)

                self.assertEqual(result, 1)
                self.assertEqual(len(calls), 1)
                self.assertFalse((root / MODEL_ID / REVISION).exists())
                self.assertTrue("metadata" in error or "label" in error)

    def test_rejects_hash_mismatch_without_publishing(self) -> None:
        manifest = self.tmp_path / "manifest.json"
        root = self.tmp_path / "models"
        expected = make_payload()
        actual = make_payload()
        write_manifest(manifest, expected)
        actual["model.safetensors"] = b"different weights"
        calls, download = make_download_mock(actual)

        with (
            hf_token("test-hf-read-token"),
            patch.object(deployment_model, "snapshot_download", side_effect=download),
        ):
            result, _, error = self.invoke(manifest, root)

        self.assertEqual(result, 1)
        self.assertEqual(len(calls), 1)
        self.assertFalse((root / MODEL_ID / REVISION).exists())
        self.assertIn("hash", error)


if __name__ == "__main__":
    unittest.main()
