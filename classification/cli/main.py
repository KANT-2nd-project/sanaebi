"""sanaebi train/eval 명령. 옵션은 한 번만 해석한다."""

import argparse
import shlex
from pathlib import Path

from .. import dataset, storage
from ..models.presets import CONFIGS


def command_hint(action, name, root, dataset_path, *, force=False):
    arguments = [
        "sanaebi",
        action,
        name,
        "--artifact-root",
        str(root),
        "--dataset",
        str(dataset_path.resolve()),
    ]
    if force:
        arguments.append("--force")
    return shlex.join(arguments)


def options(parser, *, training=False, fixed=False):
    if not fixed:
        parser.add_argument("model", choices=CONFIGS)
    parser.add_argument("--artifact-root", type=Path, default=storage.DEFAULT_ROOT)
    parser.add_argument("--dataset", type=Path, default=dataset.DATASET_PATH)
    if training:
        parser.add_argument("--force", action="store_true")
        parser.add_argument(
            "--preview-questions",
            "--preview-documents",
            dest="preview_questions",
            action="store_true",
        )
    return parser


def training_parser(*, compatibility=False, fixed=False):
    return options(
        argparse.ArgumentParser(
            description="학습 명령. 권장: sanaebi train MODEL"
            if compatibility
            else "학습"
        ),
        training=True,
        fixed=fixed,
    )


def invoke(args):
    root = args.artifact_root.resolve()
    if getattr(args, "command", "train") == "train":
        from .train import execute

        return execute(
            args.model,
            CONFIGS[args.model],
            artifact_root=root,
            dataset_path=args.dataset,
            force=args.force,
            preview=args.preview_questions,
        )
    from .evaluate import evaluate_current

    return evaluate_current(
        args.model, artifact_root=root, dataset_path=args.dataset, split=args.split
    )


def boundary(call):
    try:
        call()
    except (ValueError, OSError, RuntimeError) as error:
        raise SystemExit(str(error)) from error


def main(argv=None):
    parser = argparse.ArgumentParser(prog="sanaebi", description="분류 모델 학습·평가")
    commands = parser.add_subparsers(dest="command", required=True)
    options(
        commands.add_parser("train", help="학습 또는 동일 조건 모델 재사용"),
        training=True,
    )
    evaluation = options(
        commands.add_parser(
            "eval", help="저장 모델 validation 평가; test는 --split test로 명시"
        )
    )
    evaluation.add_argument(
        "--split",
        choices=("validation", "test"),
        default="validation",
        help="평가할 분할 (기본: validation)",
    )
    args = parser.parse_args(argv)
    boundary(lambda: invoke(args))


if __name__ == "__main__":
    main()
