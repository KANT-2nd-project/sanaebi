"""모델별 설정 → 공통 Transformer 학습. import는 실행하지 않는다."""

import sys
from pathlib import Path

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from archive.classification_v1.cli.train import run_training
from archive.classification_v1.models.presets import CONFIGS

CONFIG = CONFIGS["roberta_base"]


def main(argv=None):
    run_training(CONFIG, argv)


if __name__ == "__main__":
    try:
        main()
    except ValueError as error:
        raise SystemExit(str(error)) from error
