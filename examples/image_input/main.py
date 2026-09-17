from ios.shortcuts import shortcut_input
from shortcutslib.image import to_bmp_bytes
from ios.ui import show

bmp = to_bmp_bytes(shortcut_input(), width=28, height=28)
show(bmp)
