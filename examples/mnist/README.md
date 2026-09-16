# MNIST showcase

This example compiles an image-input handwritten-digit classifier entirely to
Apple Shortcuts actions:

1. Shortcut Input is coerced to an image.
2. The image is resized to **7×7** and converted to BMP.
3. `shortcutslib.image.decode_bmp_grayscale()` parses the Base64-backed BMP in
   generated Shortcuts actions and returns 49 normalized pixels.
4. `model.predict()` lowers a **49 → 16 → 10** ReLU MLP and argmax to ordinary
   Calculate/If/List actions.
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

This downloads MNIST through torchvision, trains the 7×7 compact MLP, saves
`mnist.pt`, and overwrites `weights.py` with plain Python constants consumed by
the compiler plugin.

For custom hyperparameters:

```bash
uv run --with torch --with torchvision python examples/mnist/train.py \
  --epochs 10 --hidden-size 16 --prune-threshold 0.01
```

`torch` and `torchvision` are deliberately not dependencies of py2shortcuts.
