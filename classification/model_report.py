"""기존 저장 모델 평가 명령의 진입점."""

import sys
from pathlib import Path

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from classification.cli.evaluate import main

if __name__ == "__main__":
    main()
