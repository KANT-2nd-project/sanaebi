import os

os.environ["HF_HUB_DISABLE_IMPLICIT_TOKEN"] = "1"
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from huggingface_hub import HfApi, hf_hub_download

models = [
    "intfloat/multilingual-e5-small",
    "exp-models/dragonkue-KoEn-E5-Tiny",
    "hotchpotch/bekko-embedding-v1-a8m",
    "hotchpotch/bekko-embedding-v1-a25m",
    "ibm-granite/granite-embedding-97m-multilingual-r2",
    "microsoft/harrier-oss-v1-270m",
    "minishlab/potion-multilingual-128M",
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
    "google/embeddinggemma-300m",
    "intfloat/multilingual-e5-base",
    "intfloat/multilingual-e5-large",
    "Snowflake/snowflake-arctic-embed-l-v2.0",
    "dragonkue/BGE-m3-ko",
    "nlpai-lab/KoE5",
]
out = Path(__file__).resolve().parent


def inspect(name):
    record = {"model": name}
    try:
        info = HfApi(token=False).model_info(name)
        record.update(revision=info.sha, gated=info.gated)
        files = [s.rfilename for s in info.siblings]
        record["weights"] = [
            f for f in files if f.endswith(".safetensors") and "/" not in f
        ]
        for f in [
            "config.json",
            "modules.json",
            "1_Pooling/config.json",
            "config_sentence_transformers.json",
            "sentence_bert_config.json",
        ]:
            if f in files:
                try:
                    record[f] = json.loads(
                        Path(
                            hf_hub_download(name, f, revision=info.sha, token=False)
                        ).read_text()
                    )
                except Exception as e:  # noqa: BLE001 - record public metadata access failures
                    record[f] = {"error_type": type(e).__name__}
    except Exception as e:  # noqa: BLE001 - record public metadata access failures
        record["error_type"] = type(e).__name__
    print(name, record.get("error_type", record.get("gated")), flush=True)
    return record


with ThreadPoolExecutor(max_workers=4) as pool:
    results = list(pool.map(inspect, models))
(out / "catalog.json").write_text(json.dumps(results, ensure_ascii=False, indent=2))
