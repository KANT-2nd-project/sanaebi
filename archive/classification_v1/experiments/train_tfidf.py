"""TF-IDF 설정과 실행 진입점. import는 학습하지 않는다."""

import sys
from pathlib import Path

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from archive.classification_v1.cli.train import run_training
from archive.classification_v1.models.presets import CONFIGS

CONFIG = CONFIGS["tfidf"]


def main(argv=None):
    run_training(CONFIG, argv)


if __name__ == "__main__":
    main()
