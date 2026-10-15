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
    EmbeddingModel,
    FileRecord,
    ReleaseError,
    RetrievalRelease,
    model_sidecar,
    parse_manifest,
    prepare_embedding,
)

MANIFEST_PATH = (
    Path(__file__).resolve().parents[2] / "deployment/retrieval-release.json"
)


class DeploymentEmbeddingManifestTests(unittest.TestCase):
    def test_static_release_descriptor_pins_tiny_and_runtime_schema(self):
        release = parse_manifest(MANIFEST_PATH.read_bytes())

        self.assertEqual(release.default_mode, "rag")
        self.assertEqual(release.baseline_schema_version, 1)
        self.assertEqual(release.index_schema_version, 1)
        self.assertEqual(release.model.model_id, EXPECTED_MODEL_ID)
        self.assertEqual(release.model.revision, EXPECTED_REVISION)
        self.assertEqual(release.model.dimension, 384)
        self.assertEqual(release.model.max_length, 512)

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

    def test_sidecar_matches_retrieval_runtime_contract_without_secrets(self):
        sidecar = model_sidecar(parse_manifest(MANIFEST_PATH.read_bytes()).model)

        self.assertEqual(
            sidecar,
            {
                "model_id": EXPECTED_MODEL_ID,
                "revision": EXPECTED_REVISION,
                "dimension": 384,
                "pooling": "attention-mask-mean",
                "normalization": "l2",
                "query_prefix": "query: ",
                "passage_prefix": "passage: ",
                "dtype": "float32",
            },
        )
        self.assertFalse(any("token" in key.lower() for key in sidecar))

    def test_embedding_download_uses_a_copyable_local_directory(self):
        payload = {name: f"payload:{name}".encode() for name in EXPECTED_FILES}
        records = tuple(
            FileRecord(name, len(content), hashlib.sha256(content).hexdigest())
            for name, content in payload.items()
        )
        model = EmbeddingModel(
            model_id=EXPECTED_MODEL_ID,
            revision=EXPECTED_REVISION,
            dimension=384,
            max_length=512,
            pooling="attention-mask-mean",
            normalization="l2",
            query_prefix="query: ",
            passage_prefix="passage: ",
            dtype="float32",
            files=records,
        )
        release = RetrievalRelease("full", 1, 1, model)
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
                / EXPECTED_REVISION,
            )
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0]["repo_id"], EXPECTED_MODEL_ID)
            self.assertEqual(calls[0]["revision"], EXPECTED_REVISION)
            self.assertEqual(calls[0]["token"], False)
            self.assertNotIn("cache_dir", calls[0])
            for name, content in payload.items():
                self.assertEqual((published / name).read_bytes(), content)

    def test_embedding_download_rejects_symlinked_model_parent_before_network(self):
        calls = []

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "models"
            root.mkdir()
            outside = Path(temporary) / "outside"
            outside.mkdir()
            (root / "exp-models--dragonkue-KoEn-E5-Tiny").symlink_to(
                outside, target_is_directory=True
            )
            downloader = lambda **kwargs: calls.append(kwargs)

            with self.assertRaises(ReleaseError):
                prepare_embedding(MANIFEST_PATH, root, downloader=downloader)

            self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
