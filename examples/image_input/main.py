from ios.shortcuts import input
from shortcutslib.image import to_bmp_bytes
from ios.ui import show

bmp = to_bmp_bytes(input(), width=28, height=28)
show(bmp)
