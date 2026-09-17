# MNIST showcase

This example compiles an image-input handwritten-digit classifier entirely to
Apple Shortcuts actions:

1. `shortcutslib.image.decode_image()` accepts Shortcut Input directly.
2. The backend coerces it to an image and converts the **original-size** image
   to BMP. The generated Shortcut parses that BMP and performs its own fixed
   **2×2 supersampling** downscale to 7×7 before producing 49 normalized
   grayscale pixels. No Shortcuts `Resize Image` action is used.
3. `utils.py` inverts the common white-background/black-ink share-sheet input
   into MNIST's black-background/white-ink polarity. It is ordinary Python and
   deliberately exercises list-comprehension lowering (plus an append-based
   `threshold()` utility as a second reusable example).
4. `model.py` is ordinary Python: `predict()` computes a **49 → 16 → 10** ReLU
   MLP and argmax using assignments, arithmetic, indexing, and `if` statements.
   The compiler reads that sibling source module and inlines it into IR; the model
   contains no backend/plugin code.
5. The predicted digit is shown.

The intentionally small 7×7 model keeps the generated workflow practical while
still training on the real MNIST dataset.

## Build

```bash
py2shortcuts build examples/mnist --sign
```

The repository includes bootstrap weights so the source tree is immediately
buildable. They were trained on scikit-learn's small digits dataset only for
bootstrapping. For the actual MNIST showcase, replace them using `pretrain.py`.

## Train the recommended MNIST checkpoint

Training dependencies are example-only:

```bash
uv run --with torch --with torchvision python examples/mnist/pretrain.py
```

This downloads MNIST through torchvision, applies the same 2×2 supersampling
used by the generated Shortcut, trains the 7×7 compact MLP, saves `mnist.pt`,
and overwrites `weights.py` with plain Python constants consumed by the same
pure-Python `model.py`.

For custom training hyperparameters:

```bash
uv run --with torch --with torchvision python examples/mnist/train.py \
  --epochs 10 --learning-rate 0.001 --prune-threshold 0.01
```

The showcase inference source is intentionally fixed at **7×7 / 16 hidden
units**. `train.py` rejects a different image/hidden size so `weights.py` cannot
silently drift away from the checked-in pure-Python model structure.

`torch` and `torchvision` are deliberately not dependencies of py2shortcuts.
