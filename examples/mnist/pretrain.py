"""Train/export the recommended compact checkpoint for the MNIST showcase."""

from pathlib import Path

from train import TrainConfig, train_and_export


HERE = Path(__file__).resolve().parent


if __name__ == "__main__":
    train_and_export(
        TrainConfig(
            data_dir=HERE / ".data",
            output=HERE / "weights.py",
            checkpoint=HERE / "mnist.pt",
            image_size=7,
            hidden_size=16,
            epochs=8,
            batch_size=256,
            learning_rate=1e-3,
            seed=913,
            # A small amount of pruning reduces generated Shortcuts math actions
            # without changing the model architecture.
            prune_threshold=0.01,
        )
    )
