"""Package already-built web output and the pinned model contract for deployment."""

import argparse
import hashlib
import json
import re
import shutil
from pathlib import Path


def package(directory: Path, git_sha: str, run_id: str, image_digest: str) -> dict:
    if not re.fullmatch(r"[a-f0-9]{40}", git_sha):
        raise ValueError("Invalid Git SHA")
    if not re.fullmatch(r"[0-9]+", run_id):
        raise ValueError("Invalid run ID")
    if not re.fullmatch(r"sha256:[a-f0-9]{64}", image_digest):
        raise ValueError("Invalid image digest")
    source = Path(__file__).resolve().parents[1] / "deployment/model-release.json"
    shutil.copyfile(source, directory / "model-release.json")
    retrieval_source = (
        Path(__file__).resolve().parents[1] / "deployment/retrieval-release.json"
    )
    shutil.copyfile(retrieval_source, directory / "retrieval-release.json")

    def digest(name):
        with (directory / name).open("rb") as stream:
            return hashlib.file_digest(stream, "sha256").hexdigest()

    manifest = {
        "schema_version": 2,
        "release_id": f"{git_sha}-{run_id}",
        "image": f"ghcr.io/kant-2nd-project/sanaebi-api@{image_digest}",
        "web_archive": "web.tar.gz",
        "web_sha256": digest("web.tar.gz"),
        "model_manifest": "model-release.json",
        "model_manifest_sha256": digest("model-release.json"),
        "retrieval_manifest": "retrieval-release.json",
        "retrieval_manifest_sha256": digest("retrieval-release.json"),
    }
    (directory / "release.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--git-sha", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--image-digest", required=True)
    args = parser.parse_args()
    package(args.directory, args.git_sha, args.run_id, args.image_digest)
