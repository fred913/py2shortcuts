"""Train the compact MNIST model used by the Shortcuts showcase.

Training dependencies are intentionally not part of py2shortcuts itself. Run with,
for example:

    uv run --with torch --with torchvision python examples/mnist/train.py
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import random


@dataclass(frozen=True, slots=True)
class TrainConfig:
    data_dir: Path
    output: Path
    checkpoint: Path | None = None
    image_size: int = 7
    hidden_size: int = 16
    epochs: int = 6
    batch_size: int = 256
    learning_rate: float = 1e-3
    seed: int = 913
    prune_threshold: float = 0.0


def _format_matrix(name: str, value: list[list[float]]) -> str:
    rows = ",\n    ".join(repr(row) for row in value)
    return f"{name} = [\n    {rows}\n]\n\n"


def _format_vector(name: str, value: list[float]) -> str:
    return f"{name} = {value!r}\n\n"


def _prune(values, threshold: float):
    if threshold <= 0:
        return values
    if isinstance(values, list):
        return [_prune(value, threshold) for value in values]
    value = float(values)
    if abs(value) < threshold:
        return 0.0
    return round(value, 6)


def export_weights(model, path: Path, *, accuracy: float, config: TrainConfig) -> None:
    state = model.state_dict()
    w1 = _prune(state["0.weight"].detach().cpu().tolist(), config.prune_threshold)
    b1 = _prune(state["0.bias"].detach().cpu().tolist(), config.prune_threshold)
    w2 = _prune(state["2.weight"].detach().cpu().tolist(), config.prune_threshold)
    b2 = _prune(state["2.bias"].detach().cpu().tolist(), config.prune_threshold)

    path.parent.mkdir(parents=True, exist_ok=True)
    text = (
        '"""Generated MNIST weights for examples/mnist. Do not edit by hand."""\n\n'
        f'SOURCE = "mnist"\n'
        f'TEST_ACCURACY = {accuracy!r}\n'
        f'IMAGE_SIZE = {config.image_size}\n'
        f'INPUT_SIZE = {config.image_size * config.image_size}\n'
        f'HIDDEN_SIZE = {config.hidden_size}\n'
        'NUM_CLASSES = 10\n\n'
    )
    text += _format_matrix("W1", w1)
    text += _format_vector("B1", b1)
    text += _format_matrix("W2", w2)
    text += _format_vector("B2", b2)
    path.write_text(text, encoding="utf-8")


def train_and_export(config: TrainConfig) -> float:
    try:
        import torch
        from torch import nn
        from torch.utils.data import DataLoader
        from torchvision import datasets, transforms
    except ImportError as error:
        raise SystemExit(
            "train.py requires torch and torchvision; run it with "
            "`uv run --with torch --with torchvision python examples/mnist/train.py`"
        ) from error

    random.seed(config.seed)
    torch.manual_seed(config.seed)

    transform = transforms.Compose(
        [
            transforms.Resize((config.image_size, config.image_size), antialias=True),
            transforms.ToTensor(),
            transforms.Lambda(lambda image: image.flatten()),
        ]
    )
    train_set = datasets.MNIST(config.data_dir, train=True, download=True, transform=transform)
    test_set = datasets.MNIST(config.data_dir, train=False, download=True, transform=transform)
    generator = torch.Generator().manual_seed(config.seed)
    train_loader = DataLoader(
        train_set,
        batch_size=config.batch_size,
        shuffle=True,
        generator=generator,
    )
    test_loader = DataLoader(test_set, batch_size=1024)

    model = nn.Sequential(
        nn.Linear(config.image_size * config.image_size, config.hidden_size),
        nn.ReLU(),
        nn.Linear(config.hidden_size, 10),
    )
    optimizer = torch.optim.Adam(model.parameters(), lr=config.learning_rate)
    loss_fn = nn.CrossEntropyLoss()

    for epoch in range(1, config.epochs + 1):
        model.train()
        running_loss = 0.0
        count = 0
        for images, labels in train_loader:
            optimizer.zero_grad(set_to_none=True)
            logits = model(images)
            loss = loss_fn(logits, labels)
            loss.backward()
            optimizer.step()
            running_loss += float(loss) * len(labels)
            count += len(labels)
        print(f"epoch {epoch}/{config.epochs}: loss={running_loss / count:.4f}")

    model.eval()
    correct = 0
    count = 0
    with torch.no_grad():
        for images, labels in test_loader:
            predictions = model(images).argmax(dim=1)
            correct += int((predictions == labels).sum())
            count += len(labels)
    accuracy = correct / count
    print(f"test accuracy: {accuracy:.2%}")

    if config.checkpoint is not None:
        config.checkpoint.parent.mkdir(parents=True, exist_ok=True)
        torch.save(
            {
                "model": model.state_dict(),
                "image_size": config.image_size,
                "hidden_size": config.hidden_size,
                "test_accuracy": accuracy,
            },
            config.checkpoint,
        )
    export_weights(model, config.output, accuracy=accuracy, config=config)
    print(f"exported compiler weights: {config.output}")
    return accuracy


def parse_args() -> argparse.Namespace:
    here = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=here / ".data")
    parser.add_argument("--output", type=Path, default=here / "weights.py")
    parser.add_argument("--checkpoint", type=Path, default=here / "mnist.pt")
    parser.add_argument("--image-size", type=int, default=7)
    parser.add_argument("--hidden-size", type=int, default=16)
    parser.add_argument("--epochs", type=int, default=6)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--learning-rate", type=float, default=1e-3)
    parser.add_argument("--seed", type=int, default=913)
    parser.add_argument(
        "--prune-threshold",
        type=float,
        default=0.0,
        help="Set weights with abs(value) below this threshold to zero before export.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    train_and_export(
        TrainConfig(
            data_dir=args.data_dir,
            output=args.output,
            checkpoint=args.checkpoint,
            image_size=args.image_size,
            hidden_size=args.hidden_size,
            epochs=args.epochs,
            batch_size=args.batch_size,
            learning_rate=args.learning_rate,
            seed=args.seed,
            prune_threshold=args.prune_threshold,
        )
    )


if __name__ == "__main__":
    main()
