from ios.shortcuts import input
from ios.ui import show
from shortcutslib.image import decode_bmp_grayscale, to_bmp_bytes

from model import predict


bmp = to_bmp_bytes(input(), width=7, height=7)
pixels = decode_bmp_grayscale(bmp, width=7, height=7)
digit = predict(pixels)

show(f"Predicted digit: {digit}")
