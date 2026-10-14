"""CLI에서만 사용하는 로컬 MLflow 기록. 학습 계산과 가중치 저장은 맡지 않는다."""

import csv
import json
import math
import os
import subprocess
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from . import storage
from .artifacts import ROOT


def tracking_uri(root):
    return "sqlite:///" + str((root / "tracking/mlflow.db").resolve())


def client_for(root):
    os.environ["MLFLOW_DISABLE_TELEMETRY"] = "true"
    from mlflow.tracking import MlflowClient

    (root / "tracking").mkdir(parents=True, exist_ok=True)
    uri = tracking_uri(root)
    return MlflowClient(tracking_uri=uri, registry_uri=uri)


def scalar_metrics(values, prefix=""):
    """행렬·오분류는 산출물에 두고 숫자 지표만 UI에 등록한다."""
    output = {}
    for key, value in values.items():
        key = f"{prefix}{key}"
        if isinstance(value, dict):
            output.update(scalar_metrics(value, key + "."))
        elif (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(value)
        ):
            output[key] = value
    return output


@dataclass
class Run:
    client: object
    run_id: str
    saved_path: Path | None = None

    def tags(self, **tags):
        for key, value in tags.items():
            self.client.set_tag(self.run_id, key, str(value))

    def params(self, params):
        for key, value in params.items():
            self.client.log_param(
                self.run_id, key, json.dumps(value, ensure_ascii=False)
            )

    def metrics(self, values, prefix="", step=0):
        for key, value in scalar_metrics(values, prefix).items():
            self.client.log_metric(self.run_id, key, value, step=step)

    def document(self, name, value):
        self.client.log_dict(self.run_id, value, name)

    def training(self, summary):
        self.metrics(summary["validation_scores"], "validation.")
        self.metrics({"selection_seconds": summary["selection_seconds"]})
        self.document("training_summary.json", summary)
        trials = summary.get("trials", [])
        if not trials:
            return
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trials.csv"
            with path.open("w", encoding="utf-8", newline="") as file:
                writer = csv.DictWriter(
                    file,
                    fieldnames=list(dict.fromkeys(k for row in trials for k in row)),
                )
                writer.writeheader()
                writer.writerows(trials)
            self.client.log_artifact(self.run_id, str(path))
        for trial in trials:
            candidate = (
                f"C_{trial['C']}"
                if "C" in trial
                else f"length_{trial['max_length']}_lr_{trial['learning_rate']}"
            )
            self.metrics(
                {
                    k: v
                    for k, v in trial.items()
                    if k in {"train_loss", "validation_accuracy", "validation_macro_f1"}
                },
                f"candidate.{candidate}.",
                step=trial.get("epoch", 0),
            )

    def evaluation(self, report, predictions):
        for split in ("validation", "test"):
            if split in report:
                self.metrics(report[split], split + ".")
        self.metrics(report.get("benchmark", {}), "benchmark.")
        self.tags(
            test_exposure=report.get("test_exposure", "미기록"),
            data_review=report.get("data_review", "미기록"),
        )
        self.tags(
            measurement_policy=storage.digest(
                report.get(
                    "measurement_policy",
                    report.get("benchmark", {}).get("mode", "unknown"),
                )
            )
        )
        self.document("metrics.json", report)
        self.document("predictions.json", predictions)


@contextmanager
def start_run(root, name, kind, data, *, split="none", model_id="", training_run_id=""):
    """초기화는 학습/외부 요청 전에, 기록 실패는 로컬 저장 여부와 구분해 알린다."""
    run = None
    try:
        client = client_for(root)
        experiment = client.get_experiment_by_name("classification")
        experiment_id = (
            experiment.experiment_id
            if experiment
            else client.create_experiment(
                "classification",
                artifact_location=(root / "tracking/artifacts").resolve().as_uri(),
            )
        )
        commit = subprocess.run(
            ["git", "-C", str(ROOT.parent), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip()
        tags = {
            "model_name": name,
            "kind": kind,
            "split": split,
            "model_id": model_id,
            "training_run_id": training_run_id,
            "dataset_sha256": data.record["dataset_sha256"],
            "split_id": storage.digest(data.record),
            "code_commit": commit or "미기록",
            "data_review": "합성 질문 · AI 검수 · 사람 승인 0건"
            if data.record["dataset_sha256"]
            == "a7d65d3556899a529278f69d5e4d177722fc73fa71c23bbfc006149b0c551c98"
            else "미기록",
            "test_exposure": "이미 열람한 개발 평가 자료"
            if data.record["dataset_sha256"]
            == "a7d65d3556899a529278f69d5e4d177722fc73fa71c23bbfc006149b0c551c98"
            else "미기록",
            "mlflow.runName": f"{name}-{kind}-{split}",
        }
        info = client.create_run(experiment_id, tags=tags).info
        run = Run(client, info.run_id)
        run.document("data_split.json", data.record)
        run.document("environment.json", storage.environment())
        yield run
        client.set_terminated(run.run_id, status="FINISHED")
    except Exception as error:
        # 외부 기록 실패를 숨기지 않는다. 이미 저장한 모델/결과를 되돌리지 않는다.
        if run is not None:
            try:
                run.client.set_terminated(run.run_id, status="FAILED")
            except Exception as tracking_error:  # noqa: BLE001 - preserve both external failures
                raise RuntimeError(
                    f"실행 오류: {error}; MLflow 실패 상태 기록도 실패: {tracking_error}. "
                    f"로컬 저장 위치: {run.saved_path or '저장 완료 전'}"
                ) from error
        saved = (
            f"로컬 저장 완료: {run.saved_path}. MLflow 기록은 미완료이며 재학습하지 마세요. "
            if run and run.saved_path
            else ""
        )
        raise RuntimeError(f"{saved}실험 실행/기록 실패: {error}") from error
