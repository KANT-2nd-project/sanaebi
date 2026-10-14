"""기존 Jev 단일 질문·평가·preview 명령의 진입점."""

import sys
from pathlib import Path

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from archive.classification_v1.cli.jev import jev_main
from archive.classification_v1.models.jev import JevRequestError

if __name__ == "__main__":
    try:
        jev_main()
    except JevRequestError as error:
        raise SystemExit(str(error)) from error
