"""Pin downloads, then run models one at a time on two CPUs."""

import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

os.environ["HF_HUB_DISABLE_IMPLICIT_TOKEN"] = "1"
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
from huggingface_hub import snapshot_download

base = Path(__file__).resolve().parent
catalog = json.loads((base / "catalog.json").read_text())
entries = [
    e
    for e in catalog
    if not e["gated"] and e["model"] != "minishlab/potion-multilingual-128M"
]
status = []


def download(e):
    try:
        snapshot_download(
            e["model"],
            revision=e["revision"],
            token=False,
            allow_patterns=["*.json", "*.model", "vocab.txt", "*.safetensors"],
            ignore_patterns=[
                "onnx/*",
                "openvino/*",
                "*/model.safetensors",
                "trainer_state.json",
            ],
            max_workers=2,
        )
        return True
    except Exception as exc:  # noqa: BLE001 - isolate external model download failures
        return type(exc).__name__


with ThreadPoolExecutor(max_workers=2) as pool:
    futures = {e["model"]: pool.submit(download, e) for e in entries}
    for e in entries:
        name = e["model"]
        print("WAIT_DOWNLOAD", name, flush=True)
        downloaded = futures[name].result()
        if downloaded is not True:
            status.append(
                {"model": name, "status": "download_failed", "error_type": downloaded}
            )
        else:
            print("RUN", name, flush=True)
            with (base / (name.replace("/", "--") + ".log")).open("w") as log:
                try:
                    result = subprocess.run(
                        [sys.executable, str(base / "run.py"), name],
                        stdout=log,
                        stderr=log,
                        timeout=1200,
                        check=False,
                    )
                    status.append(
                        {
                            "model": name,
                            "status": "completed"
                            if result.returncode == 0
                            else "failed",
                            "exit_code": result.returncode,
                        }
                    )
                except subprocess.TimeoutExpired:
                    status.append({"model": name, "status": "timeout_20min"})
        (base / "batch-status.json").write_text(json.dumps(status, indent=2))
        print("STATUS", status[-1], flush=True)
