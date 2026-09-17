from ios.shortcuts import shortcut_input
from ios.ui import show
from shortcutslib.image import decode_image

from model import predict
from utils import invert


pixels = decode_image(shortcut_input(), width=7, height=7, mode="grayscale")
pixels = invert(pixels)
digit = predict(pixels)

show(f"Predicted digit: {digit}")
