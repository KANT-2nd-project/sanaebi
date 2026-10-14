"""모델별 설정 → 공통 Transformer 학습. import는 실행하지 않는다."""

import sys
from pathlib import Path

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from classification.cli.train import run_training
from classification.models.transformer import TransformerConfig

CONFIG = TransformerConfig(
    model_name="모델명 입력",
    model_folder="결과 저장 폴더 명 입력",
)


def main(argv=None):
    run_training(CONFIG, argv)


if __name__ == "__main__":
    try:
        main()
    except ValueError as error:
        raise SystemExit(str(error)) from error
