"""TF-IDF 설정과 실행 진입점. import는 학습하지 않는다."""

import sys
from pathlib import Path

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from classification.cli.train import tfidf_main
from classification.models.tfidf import TfidfConfig

CONFIG = TfidfConfig()


def main(argv=None):
    tfidf_main(CONFIG, argv)


if __name__ == "__main__":
    main()
