"""모델별 설정 → 공통 Transformer 학습. import는 실행하지 않는다."""

import sys
from pathlib import Path

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from classification.cli.train import transformer_main
from classification.models.transformer import TransformerConfig

CONFIG = TransformerConfig(
    model_name="monologg/koelectra-small-v3-discriminator",
    model_folder="koelectra_small",
)


def main(argv=None):
    transformer_main(CONFIG, argv)


if __name__ == "__main__":
    try:
        main()
    except ValueError as error:
        raise SystemExit(str(error)) from error
