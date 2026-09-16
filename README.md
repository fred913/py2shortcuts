# py2shortcuts

`py2shortcuts` treats Python as a **frontend** and Apple Shortcuts as a
**backend**:

```text
Python source
    ↓ ast.parse()
Python frontend
    ↓
py2shortcuts IR
    ↓
Shortcuts backend + typed adapters
    ↓
WFWorkflowActions plist
    ↓ optional signing
.shortcut
```

The goal is not CPython compatibility. The goal is to make large native
Shortcuts workflows maintainable in a text editor while still producing normal
Shortcuts actions that can participate in iOS/macOS automation.

The project targets **Python 3.14+** and ships inline type information
(`py.typed`).

## The `ios` compile-time package

Installing `py2shortcuts` also installs a top-level `ios` package. It is a
typed **compiler API facade**, not a CPython implementation of iOS APIs:

```python
from ios import device, notifications, ui
from ios.app.health import log_sleep

name = ui.ask_text("Name?")
battery = device.battery_level()
notifications.notify(f"Hello {name}; battery={battery}%")

log_sleep(
    "2001-01-01T12:00:00+08:00",
    "2001-01-01T12:01:00+08:00",
    stage="REM",
)
```

Running one of these intrinsic functions directly in CPython raises a clear
`RuntimeError`. `py2shortcuts` recognizes the imported symbol at compile time
and emits native Shortcuts actions instead.

The first built-in namespaces are:

```text
ios.ui
  alert(message, title="")
  ask_text(prompt="") -> str
  show(value)

ios.notifications
  notify(body, title="", *, sound=True)

ios.web
  request(url, *, method="GET") -> ShortcutContent
  get_text(url) -> str
  get_json(url) -> dict[str, JSONValue]
  open(url)

ios.clipboard
  get() -> ShortcutContent
  get_text() -> str
  set(value, *, local_only=False)

ios.location
  current() -> Location
  maps_url(location) -> str

ios.device
  detail(...)
  name() -> str
  model() -> str
  system_version() -> str
  screen_width() -> float
  screen_height() -> float
  volume() -> float
  brightness() -> float
  battery_level() -> float
  set_wifi(bool)
  set_bluetooth(bool)
  set_cellular_data(bool)
  set_low_power_mode(bool=True)
  set_brightness(0.0..1.0)
  set_volume(0.0..1.0)
  set_flashlight("Off" | "On" | "Toggle")

ios.app.health
  log_sleep(start, end, *, stage=...) -> HealthSample

ios.shortcuts
  comment(text)
  raw_action(identifier, *, output=None, **literal_parameters)
  stop() -> Never
```

`ios.types` contains the public `Literal` choices and opaque compiler-value
types, including `HTTPMethod`, `DeviceDetail`, `FlashlightMode`, `SleepStage`,
`JSONValue`, `ShortcutContent`, `Location`, and `HealthSample`.

Health sleep-stage logging intentionally remains conservative: the compiler
uses the Health action wire format already present in this project, while exact
accepted category labels can still vary with Shortcuts/iOS versions. Device
import/run testing remains the final authority.

For this first `ios` API pass, device toggles, brightness/volume levels,
flashlight mode, HTTP method, notification sound, clipboard `local_only`, and
sleep stage are intentionally required to be **compile-time literals**. This
keeps enum/slider wire encoding conservative until more current device exports
are collected.

## Current Python subset

The compiler currently supports:

- literals: `None`, `bool`, `int`, `float`, `str`
- simple variables and assignment
- `+=`, `-=`, `*=`, `/=`, `%=` and `**=` where the underlying operation exists
- arithmetic: `+ - * / % **`
- comparisons: `== != < <= > >=`
- boolean `and`, `or`, `not`
- `if` / `else`
- `for x in range(...)` with `step=1`
- `for x in iterable`
- list literals
- flat dictionary literals with literal string keys
- `value[0]` and `value["key"]`
- simple f-strings
- `print(...)`, `input(...)`, `len(...)`
- single-expression inline functions such as `def square(x): return x * x`
- compile-time imports used as adapter namespaces

Features such as `while`, `break`, `continue`, arbitrary classes, generators,
`async`, exceptions, comprehensions, `eval`, and `exec` deliberately fail with
`CompileError` instead of silently producing incorrect workflows.

## Example

```python
from ios import device, notifications, ui


def square(x):
    return x * x


name = ui.ask_text("Your name?")

for i in range(1, 4):
    value = square(i)
    if value >= 4:
        notifications.notify(
            f"{name}: square({i}) = {value}; battery={device.battery_level()}%",
            title="py2shortcuts",
        )
```

Compile it:

```bash
py2shortcuts build example.py -o Example.plist --name "Example"
```

A project directory can be passed directly when it contains `main.py`:

```bash
py2shortcuts build examples/simple_nn
```

This uses `examples/simple_nn/main.py` as the entrypoint and, unless `-o` is
given, writes `examples/simple_nn/main.plist`. Local sibling modules that expose
`register(registry)` continue to act as compiler plugins.

Inspect the IR:

```bash
py2shortcuts dump-ir example.py
```

The existing signing helper can still be used explicitly:

```bash
py2shortcuts build example.py --sign --signed-output Example.shortcut
```

## IR

The frontend removes Python-specific syntax before the backend sees it. For
example:

```python
x += 1
```

becomes conceptually:

```text
Assign(
  name="x",
  value=Binary("+", Var("x"), Literal(1))
)
```

The Shortcuts backend is therefore concerned with actions, Magic Variables,
control-flow groups, and plist serialization rather than Python AST details.

## Backend adapters/plugins

Target-specific calls are resolved by a `PluginRegistry`. Built-in first-party
`ios.*` adapters use the same mechanism as custom plugins. Adapters can also
publish a compact result type (`text`, `number`, `dict`, etc.), so type
information survives an assignment and can improve later Shortcuts lowering.

The old `py2shortcuts.shortcuts` facade remains supported for compatibility,
but new code should prefer the typed `ios` package.

A custom call lowerer still looks like this:

```python
from py2shortcuts.plugins import PluginRegistry

registry = PluginRegistry()


@registry.call("myapp.double", result_type="number")
def lower_double(backend, call):
    if len(call.args) != 1:
        raise ValueError("myapp.double() expects one argument")
    value = backend.require_value(backend.emit_expr(call.args[0]), context="double")
    return backend.emit_math(value, "*", "2")
```

Third-party App Intent adapters are deliberately not bundled yet.

## Generated workflow validation

Every compilation performs a structural validation pass. It checks:

- duplicate action UUIDs
- dangling or forward `OutputUUID` references
- balanced `If` / `Repeat` / menu grouping identifiers
- valid control-flow start/middle/end ordering

This is not presented as an Apple schema validator. Action identifiers and
parameter schemas are reverse-engineered and can change with Shortcuts/iOS
versions, so device import/run testing remains the final oracle.

## Existing Health probe

The original Health sleep-stage probe remains available and is not coupled to
the compiler core:

```bash
python examples/build_health_sleep_probe.py --output Sleep-Stage-Write-Probe.plist
```

It remains useful as a low-level reference when validating Health action wire
formats on a new iOS release.

## Shortcut input, Content Graph, and built-in utilities

Projects can declare accepted Shortcut input types in `py2shortcuts.toml`:

```toml
[shortcut]
name = "MNIST"

[shortcut.input]
types = ["images", "files", "pdfs", "safari-webpages"]
```

`ios.shortcuts.input()` compiles to the `ExtensionInput` magic value rather
than a fake runtime action. Explicit content conversion is available through
Shortcuts' Content Graph:

```python
from ios.shortcuts import input
from ios.content import Image, coerce
from ios.images import resize, convert
from ios.data import as_bytes

source = input()
image = coerce(source, Image)
image = resize(image, width=28, height=28)
bmp = convert(image, format="BMP")
data = as_bytes(bmp)
```

The `shortcutslib` top-level package is the compiler's portable utility
library. It is intentionally separate from `ios`: `ios.*` describes target
capabilities, while `shortcutslib.*` contains reusable implementations that
may expand to several actions. The first image utility keeps preprocessing
code small:

```python
from ios.shortcuts import input
from shortcutslib.image import to_bmp_bytes

bmp = to_bmp_bytes(input(), width=28, height=28)
```

On the Shortcuts backend, the current `bytes` transport is Base64 text. That is
an implementation detail of the backend; application code should not invoke
Base64 actions directly. The next layer for the MNIST showcase is the reusable
BMP pixel decoder in `shortcutslib.image`, built on top of this abstraction.

## MNIST showcase

`examples/mnist` is a complete image-input neural-network showcase. Its
application entrypoint intentionally stays small:

```python
from ios.shortcuts import input
from ios.ui import show
from shortcutslib.image import decode_bmp_grayscale, to_bmp_bytes
from model import predict

bmp = to_bmp_bytes(input(), width=7, height=7)
pixels = decode_bmp_grayscale(bmp, width=7, height=7)
digit = predict(pixels)
show(f"Predicted digit: {digit}")
```

The generated Shortcut performs the image conversion, Base64-backed BMP
parsing, grayscale extraction, a 49 → 16 → 10 ReLU MLP, and argmax at runtime.
The example uses 7×7 input rather than the original 28×28 MNIST resolution to
keep a native Shortcuts workflow tractable.

`shortcutslib.image.decode_bmp_grayscale()` currently accepts ordinary
bottom-up, uncompressed 24-bit BGR or 32-bit BGRA BMPs. It reads and checks the
BMP signature, dimensions, pixel-data offset, compression mode, bit depth, and
row padding in generated actions.

The source tree includes bootstrap weights so the example can be compiled
immediately. For a real MNIST checkpoint, run:

```bash
uv run --with torch --with torchvision python examples/mnist/pretrain.py
```

That script downloads MNIST, trains the compact model, writes `mnist.pt`, and
exports plain Python constants to `examples/mnist/weights.py`. The more general
`train.py` exposes epochs, hidden size, learning rate, and pruning controls.
PyTorch and torchvision remain example-only training dependencies and are not
installed with py2shortcuts.
