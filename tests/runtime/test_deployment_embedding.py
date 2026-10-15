import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.deployment_embedding import (
    EXPECTED_FILES,
    EXPECTED_MODEL_ID,
    EXPECTED_REVISION,
    EXPECTED_SPLITTER_FILES,
    KURE_EXPECTED_FILES,
    LEGACY_MODEL_ID,
    LEGACY_REVISION,
    EmbeddingModel,
    FileRecord,
    ReleaseError,
    RetrievalRelease,
    SplitterModel,
    model_sidecar,
    parse_manifest,
    prepare_embedding,
    validate_model_directory,
)

MANIFEST_PATH = (
    Path(__file__).resolve().parents[2] / "deployment/retrieval-release.json"
)
LEGACY_TINY_MANIFEST_PATH = (
    Path(__file__).resolve().parent / "fixtures/retrieval-release-tiny-v1.json"
)


class DeploymentEmbeddingManifestTests(unittest.TestCase):
    def test_static_release_descriptor_pins_kure_and_splitter_contract(self):
        release = parse_manifest(MANIFEST_PATH.read_bytes())

        self.assertEqual(release.default_mode, "rag")
        self.assertEqual(release.baseline_schema_version, 1)
        self.assertEqual(release.index_schema_version, 1)
        self.assertEqual(release.model.model_id, EXPECTED_MODEL_ID)
        self.assertEqual(release.model.revision, EXPECTED_REVISION)
        self.assertEqual(release.model.dimension, 1024)
        self.assertEqual(release.model.max_length, 8192)
        self.assertEqual(release.model.query_max_length, 512)
        self.assertEqual(release.model.pooling, "cls")
        self.assertEqual(release.model.query_prefix, "")
        self.assertEqual(release.model.passage_prefix, "")
        self.assertEqual(
            release.model.splitter.model_id, "exp-models/dragonkue-KoEn-E5-Tiny"
        )
        self.assertEqual(
            release.model.splitter.revision,
            "292c09c78c71a3f00ed56ee0d1ed9f0d39182fc9",
        )
        self.assertEqual(release.model.splitter.directory, "splitter")

    def test_legacy_tiny_descriptor_remains_valid_for_rollback(self):
        release = parse_manifest(LEGACY_TINY_MANIFEST_PATH.read_bytes())

        self.assertEqual(release.model.model_id, "exp-models/dragonkue-KoEn-E5-Tiny")
        self.assertEqual(release.model.dimension, 384)
        self.assertEqual(release.model.max_length, 512)
        self.assertIsNone(release.model.splitter)
        self.assertEqual(
            model_sidecar(release.model),
            {
                "model_id": LEGACY_MODEL_ID,
                "revision": LEGACY_REVISION,
                "dimension": 384,
                "pooling": "attention-mask-mean",
                "normalization": "l2",
                "query_prefix": "query: ",
                "passage_prefix": "passage: ",
                "dtype": "float32",
            },
        )

        value = json.loads(LEGACY_TINY_MANIFEST_PATH.read_text(encoding="utf-8"))
        value["default_mode"] = "full"
        full_release = parse_manifest(json.dumps(value).encode())
        self.assertEqual(full_release.default_mode, "full")

    def test_legacy_full_descriptor_remains_valid(self):
        value = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        value["default_mode"] = "full"

        release = parse_manifest(json.dumps(value).encode())

        self.assertEqual(release.default_mode, "full")

    def test_compose_api_and_indexer_default_to_rag_with_override_support(self):
        compose = (
            Path(__file__).resolve().parents[2] / "deployment/compose.production.yaml"
        ).read_text(encoding="utf-8")

        self.assertEqual(
            compose.count("SANAEBI_RETRIEVAL_MODE: ${SANAEBI_RETRIEVAL_MODE:-rag}"),
            2,
        )
        self.assertIn(
            "SANAEBI_RETRIEVAL_BASELINE: ${SANAEBI_RETRIEVAL_BUNDLE_CONTAINER_PATH:-/retrieval-baselines/not-ready.sqlite3}",
            compose,
        )

    def test_descriptor_rejects_unpinned_model_or_file_inventory(self):
        value = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        value["embedding"]["revision"] = "0" * 40

        with self.assertRaises(ReleaseError):
            parse_manifest(json.dumps(value).encode())

        value = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        value["embedding"]["files"].pop()
        with self.assertRaises(ReleaseError):
            parse_manifest(json.dumps(value).encode())

        value = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        value["embedding"]["splitter"]["revision"] = "0" * 40
        with self.assertRaises(ReleaseError):
            parse_manifest(json.dumps(value).encode())

        value = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        value["embedding"]["files"][-1]["name"] = "../config.json"
        with self.assertRaises(ReleaseError):
            parse_manifest(json.dumps(value).encode())

    def test_sidecar_matches_retrieval_runtime_contract_without_secrets(self):
        sidecar = model_sidecar(parse_manifest(MANIFEST_PATH.read_bytes()).model)

        self.assertEqual(
            sidecar,
            {
                "model_id": EXPECTED_MODEL_ID,
                "revision": EXPECTED_REVISION,
                "dimension": 1024,
                "max_length": 8192,
                "query_max_length": 512,
                "pooling": "cls",
                "normalization": "l2",
                "query_prefix": "",
                "passage_prefix": "",
                "dtype": "float32",
                "splitter": {
                    "model_id": "exp-models/dragonkue-KoEn-E5-Tiny",
                    "revision": "292c09c78c71a3f00ed56ee0d1ed9f0d39182fc9",
                    "directory": "splitter",
                },
            },
        )
        self.assertFalse(any("token" in key.lower() for key in sidecar))

    def test_embedding_download_uses_a_copyable_local_directory(self):
        payload = {name: f"payload:{name}".encode() for name in KURE_EXPECTED_FILES}
        splitter_payload = {
            name: f"splitter:{name}".encode() for name in EXPECTED_SPLITTER_FILES
        }
        records = tuple(
            FileRecord(name, len(content), hashlib.sha256(content).hexdigest())
            for name, content in payload.items()
        )
        splitter_records = tuple(
            FileRecord(name, len(content), hashlib.sha256(content).hexdigest())
            for name, content in splitter_payload.items()
        )
        model = EmbeddingModel(
            model_id=EXPECTED_MODEL_ID,
            revision=EXPECTED_REVISION,
            dimension=1024,
            max_length=8192,
            query_max_length=512,
            pooling="cls",
            normalization="l2",
            query_prefix="",
            passage_prefix="",
            dtype="float32",
            files=records,
            splitter=SplitterModel(
                model_id="exp-models/dragonkue-KoEn-E5-Tiny",
                revision="292c09c78c71a3f00ed56ee0d1ed9f0d39182fc9",
                directory="splitter",
                files=splitter_records,
            ),
        )
        release = RetrievalRelease("full", 1, 1, model)
        calls = []

        def download(**kwargs):
            calls.append(kwargs)
            directory = Path(kwargs["local_dir"])
            directory.mkdir(parents=True, exist_ok=True)
            response = (
                payload if kwargs["repo_id"] == EXPECTED_MODEL_ID else splitter_payload
            )
            for name, content in response.items():
                path = directory / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
            return str(directory)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = root / "retrieval-release.json"
            manifest.write_text("{}", encoding="utf-8")
            with patch(
                "scripts.deployment_embedding.parse_manifest", return_value=release
            ):
                published = prepare_embedding(
                    manifest, root / "models", downloader=download
                )

            self.assertEqual(
                published,
                root / "models" / "nlpai-lab--KURE-v1" / EXPECTED_REVISION,
            )
            self.assertEqual(len(calls), 2)
            self.assertEqual(calls[0]["repo_id"], EXPECTED_MODEL_ID)
            self.assertEqual(calls[0]["revision"], EXPECTED_REVISION)
            self.assertEqual(calls[0]["token"], False)
            self.assertNotIn("cache_dir", calls[0])
            self.assertEqual(calls[1]["repo_id"], model.splitter.model_id)
            self.assertEqual(calls[1]["revision"], model.splitter.revision)
            self.assertEqual(calls[1]["token"], False)
            for name, content in payload.items():
                self.assertEqual((published / name).read_bytes(), content)
            for name, content in splitter_payload.items():
                self.assertEqual((published / "splitter" / name).read_bytes(), content)
            expected_paths = {
                "retrieval-model.json",
                *KURE_EXPECTED_FILES,
                *(f"splitter/{name}" for name in EXPECTED_SPLITTER_FILES),
            }
            self.assertEqual(
                {
                    path.relative_to(published).as_posix()
                    for path in published.rglob("*")
                    if path.is_file()
                },
                expected_paths,
            )
            pooling_directory = published / "1_Pooling"
            pooling_directory.chmod(0o755)
            (pooling_directory / "unexpected.json").write_text("{}", encoding="utf-8")
            with self.assertRaises(ReleaseError):
                validate_model_directory(published, release)

    def test_legacy_tiny_prepare_keeps_single_model_directory_for_rollback(self):
        payload = {name: f"legacy:{name}".encode() for name in EXPECTED_FILES}
        records = tuple(
            FileRecord(name, len(content), hashlib.sha256(content).hexdigest())
            for name, content in payload.items()
        )
        model = EmbeddingModel(
            model_id=LEGACY_MODEL_ID,
            revision=LEGACY_REVISION,
            dimension=384,
            max_length=512,
            query_max_length=512,
            pooling="attention-mask-mean",
            normalization="l2",
            query_prefix="query: ",
            passage_prefix="passage: ",
            dtype="float32",
            files=records,
        )
        release = RetrievalRelease("rag", 1, 1, model)
        calls = []

        def download(**kwargs):
            calls.append(kwargs)
            directory = Path(kwargs["local_dir"])
            directory.mkdir(parents=True, exist_ok=True)
            for name, content in payload.items():
                (directory / name).write_bytes(content)
            return str(directory)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = root / "retrieval-release.json"
            manifest.write_text("{}", encoding="utf-8")
            with patch(
                "scripts.deployment_embedding.parse_manifest", return_value=release
            ):
                published = prepare_embedding(
                    manifest, root / "models", downloader=download
                )
            self.assertEqual(
                published,
                root
                / "models"
                / "exp-models--dragonkue-KoEn-E5-Tiny"
                / LEGACY_REVISION,
            )
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0]["repo_id"], LEGACY_MODEL_ID)
            self.assertEqual(
                {path.name for path in published.iterdir()},
                {*EXPECTED_FILES, "retrieval-model.json"},
            )

    def test_embedding_download_rejects_symlinked_model_parent_before_network(self):
        calls = []

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "models"
            root.mkdir()
            outside = Path(temporary) / "outside"
            outside.mkdir()
            (root / "nlpai-lab--KURE-v1").symlink_to(outside, target_is_directory=True)
            downloader = lambda **kwargs: calls.append(kwargs)

            with self.assertRaises(ReleaseError):
                prepare_embedding(MANIFEST_PATH, root, downloader=downloader)

            self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
