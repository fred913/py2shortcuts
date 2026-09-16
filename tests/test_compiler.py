from __future__ import annotations

import os
import plistlib
import tempfile

import pytest
import unittest
from pathlib import Path

from typer.testing import CliRunner

from py2shortcuts import CompileError, app, compile_file, compile_source
from py2shortcuts.plugins import PluginRegistry


class CompilerTests(unittest.TestCase):
    def identifiers(self, source: str) -> list[str]:
        workflow = compile_source(
            source, name="Test", include_header_comment=False
        ).workflow
        return [
            action["WFWorkflowActionIdentifier"]
            for action in workflow["WFWorkflowActions"]
        ]

    def test_basic_assignment_and_print(self) -> None:
        compilation = compile_source(
            'x = 1 + 2\nprint(f"x={x}")\n', name="Test", include_header_comment=False
        )
        identifiers = [
            a["WFWorkflowActionIdentifier"]
            for a in compilation.workflow["WFWorkflowActions"]
        ]
        self.assertIn("is.workflow.actions.math", identifiers)
        self.assertIn("is.workflow.actions.setvariable", identifiers)
        self.assertIn("is.workflow.actions.showresult", identifiers)
        # It must also serialize as a valid plist.
        round_trip = plistlib.loads(compilation.xml())
        self.assertEqual(round_trip["WFWorkflowName"], "Test")

    def test_if_has_balanced_group(self) -> None:
        workflow = compile_source(
            'x = 3\nif x > 1:\n    print("yes")\nelse:\n    print("no")\n',
            name="Test",
            include_header_comment=False,
        ).workflow
        conditionals = [
            action
            for action in workflow["WFWorkflowActions"]
            if action["WFWorkflowActionIdentifier"] == "is.workflow.actions.conditional"
        ]
        self.assertEqual(
            [
                a["WFWorkflowActionParameters"]["WFControlFlowMode"]
                for a in conditionals
            ],
            [0, 1, 2],
        )
        groups = {
            a["WFWorkflowActionParameters"]["GroupingIdentifier"] for a in conditionals
        }
        self.assertEqual(len(groups), 1)

    def test_range_and_for_each(self) -> None:
        identifiers = self.identifiers(
            'items = ["a", "b"]\nfor i in range(1, 3):\n    print(i)\nfor item in items:\n    print(item)\n'
        )
        self.assertIn("is.workflow.actions.repeat.count", identifiers)
        self.assertIn("is.workflow.actions.repeat.each", identifiers)

    def test_inline_function(self) -> None:
        identifiers = self.identifiers(
            "def square(x):\n    return x * x\ny = square(4)\nprint(y)\n"
        )
        self.assertIn("is.workflow.actions.math", identifiers)

    def test_plugin_namespace_import_alias(self) -> None:
        identifiers = self.identifiers(
            'from shortcuts import notification as notify\nname = input("Name")\nnotify(f"Hello {name}")\n'
        )
        self.assertIn("is.workflow.actions.notification", identifiers)

    def test_py2shortcuts_facade_alias(self) -> None:
        identifiers = self.identifiers(
            'from py2shortcuts import shortcuts\nshortcuts.alert("Hello")\n'
        )
        self.assertIn("is.workflow.actions.alert", identifiers)

    def test_custom_plugins_extend_builtins(self) -> None:
        registry = PluginRegistry()

        @registry.call("demo.double")
        def lower_double(backend, call):
            value = backend.require_value(
                backend.emit_expr(call.args[0]), context="double"
            )
            return backend.emit_math(value, "*", "2")

        workflow = compile_source(
            "import demo\nfrom py2shortcuts import shortcuts\nx = 3\ny = demo.double(x)\nshortcuts.notification(y)\n",
            name="Test",
            plugins=registry,
            include_header_comment=False,
        ).workflow
        identifiers = [
            a["WFWorkflowActionIdentifier"] for a in workflow["WFWorkflowActions"]
        ]
        self.assertIn("is.workflow.actions.math", identifiers)
        self.assertIn("is.workflow.actions.notification", identifiers)

    def test_local_library_imports_are_loaded_from_script_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source_dir = Path(tmpdir)
            (source_dir / "lib.py").write_text(
                "from __future__ import annotations\n\n"
                "def register(registry):\n"
                "    @registry.call('lib.message')\n"
                "    def lower_message(backend, call):\n"
                "        return backend.emit_literal('hello from lib')\n",
                encoding="utf-8",
            )
            (source_dir / "main.py").write_text(
                "import lib\nlib.message()\n",
                encoding="utf-8",
            )

            workflow = compile_file(
                source_dir / "main.py",
                name="Local Lib Test",
                include_header_comment=False,
            ).workflow

        identifiers = [
            a["WFWorkflowActionIdentifier"] for a in workflow["WFWorkflowActions"]
        ]
        self.assertIn("is.workflow.actions.gettext", identifiers)

    def test_raw_action_escape_hatch(self) -> None:
        compilation = compile_source(
            'import shortcuts\nshortcuts.raw_action("is.workflow.actions.comment", WFCommentActionText="raw")\n',
            name="Test",
            include_header_comment=False,
        )
        action = compilation.workflow["WFWorkflowActions"][0]
        self.assertEqual(
            action["WFWorkflowActionIdentifier"], "is.workflow.actions.comment"
        )
        self.assertEqual(
            action["WFWorkflowActionParameters"]["WFCommentActionText"], "raw"
        )

    def test_ios_ui_notifications_and_import_aliases(self) -> None:
        workflow = compile_source(
            "from ios.ui import ask_text, alert\n"
            "from ios.notifications import notify as ping\n"
            'name = ask_text("Name?")\n'
            'alert(f"Hello {name}", title="Welcome")\n'
            'ping(f"Hi {name}", sound=False)\n',
            name="Test",
            include_header_comment=False,
        ).workflow
        identifiers = [
            a["WFWorkflowActionIdentifier"] for a in workflow["WFWorkflowActions"]
        ]
        self.assertIn("is.workflow.actions.ask", identifiers)
        self.assertIn("is.workflow.actions.alert", identifiers)
        self.assertIn("is.workflow.actions.notification", identifiers)
        notification = next(
            a
            for a in workflow["WFWorkflowActions"]
            if a["WFWorkflowActionIdentifier"] == "is.workflow.actions.notification"
        )
        self.assertFalse(
            notification["WFWorkflowActionParameters"]["WFNotificationActionSound"]
        )

    def test_ios_web_clipboard_and_location(self) -> None:
        workflow = compile_source(
            "import ios\n"
            'text = ios.web.get_text("https://example.com")\n'
            "ios.clipboard.set(text, local_only=True)\n"
            "copy = ios.clipboard.get_text()\n"
            "loc = ios.location.current()\n"
            "url = ios.location.maps_url(loc)\n"
            'ios.ui.show(f"{copy} {url}")\n',
            name="Test",
            include_header_comment=False,
        ).workflow
        identifiers = [
            a["WFWorkflowActionIdentifier"] for a in workflow["WFWorkflowActions"]
        ]
        self.assertIn("is.workflow.actions.downloadurl", identifiers)
        self.assertGreaterEqual(identifiers.count("is.workflow.actions.detect.text"), 2)
        self.assertIn("is.workflow.actions.setclipboard", identifiers)
        self.assertIn("is.workflow.actions.getclipboard", identifiers)
        self.assertIn("is.workflow.actions.getcurrentlocation", identifiers)
        self.assertIn("is.workflow.actions.getmapslink", identifiers)

    def test_ios_json_can_be_subscripted(self) -> None:
        identifiers = self.identifiers(
            "from ios.web import get_json\n"
            'data = get_json("https://example.com/data.json")\n'
            'print(data["name"])\n'
        )
        self.assertIn("is.workflow.actions.detect.dictionary", identifiers)
        self.assertIn("is.workflow.actions.getvalueforkey", identifiers)

    def test_ios_device_intrinsics_and_result_type(self) -> None:
        workflow = compile_source(
            "from ios import device\n"
            "battery = device.battery_level()\n"
            "if battery:\n"
            "    print(device.name())\n"
            "device.set_wifi(True)\n"
            "device.set_bluetooth(False)\n"
            "device.set_low_power_mode()\n"
            "device.set_brightness(0.5)\n"
            "device.set_volume(0.25)\n"
            'device.set_flashlight("Toggle")\n',
            name="Test",
            include_header_comment=False,
        ).workflow
        identifiers = [
            a["WFWorkflowActionIdentifier"] for a in workflow["WFWorkflowActions"]
        ]
        for identifier in (
            "is.workflow.actions.getbatterylevel",
            "is.workflow.actions.getdevicedetails",
            "is.workflow.actions.wifi.set",
            "is.workflow.actions.bluetooth.set",
            "is.workflow.actions.lowpowermode.set",
            "is.workflow.actions.setbrightness",
            "is.workflow.actions.setvolume",
            "is.workflow.actions.flashlight",
        ):
            self.assertIn(identifier, identifiers)
        conditional = next(
            a
            for a in workflow["WFWorkflowActions"]
            if a["WFWorkflowActionIdentifier"] == "is.workflow.actions.conditional"
        )
        self.assertEqual(
            conditional["WFWorkflowActionParameters"]["WFConditionalActionString"], "0"
        )

    def test_ios_health_sleep_intrinsic(self) -> None:
        source = """from ios.app.health import log_sleep
sample = log_sleep(
    "2001-01-01T12:00:00+08:00",
    "2001-01-01T12:01:00+08:00",
    stage="REM",
)
print(sample)
"""
        workflow = compile_source(
            source,
            name="Test",
            include_header_comment=False,
        ).workflow
        health = next(
            action
            for action in workflow["WFWorkflowActions"]
            if action["WFWorkflowActionIdentifier"]
            == "is.workflow.actions.health.quantity.log"
        )
        params = health["WFWorkflowActionParameters"]
        self.assertEqual(params["WFQuantitySampleType"], "Sleep")
        self.assertEqual(params["WFCategorySampleEnumeration"], "REM")
        self.assertEqual(
            params["WFQuantitySampleDate"]["WFSerializationType"], "WFTextTokenString"
        )
        self.assertEqual(
            params["WFSampleEndDate"]["WFSerializationType"], "WFTextTokenString"
        )

    def test_ios_raw_action_and_stop(self) -> None:
        identifiers = self.identifiers(
            "from ios.shortcuts import raw_action, stop\n"
            'raw_action("is.workflow.actions.comment", WFCommentActionText="hello")\n'
            "stop()\n"
        )
        self.assertIn("is.workflow.actions.comment", identifiers)
        self.assertIn("is.workflow.actions.exit", identifiers)

    def test_ios_compile_time_literal_validation(self) -> None:
        with self.assertRaisesRegex(CompileError, "literal bool"):
            compile_source(
                "from ios.device import set_wifi\n"
                'enabled = input("wifi?")\n'
                "set_wifi(enabled)\n",
                name="Test",
            )
        with self.assertRaisesRegex(CompileError, "between 0 and 1"):
            compile_source(
                "from ios.device import set_volume\nset_volume(1.5)\n",
                name="Test",
            )

    def test_while_is_explicit_error(self) -> None:
        with self.assertRaisesRegex(
            CompileError, "while is not natively representable"
        ):
            compile_source("while True:\n    print('x')\n", name="Test")

    def test_compile_directory_uses_main_py(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source_dir = Path(tmpdir) / "project"
            source_dir.mkdir()
            (source_dir / "main.py").write_text("x = 1 + 2\nprint(x)\n", encoding="utf-8")

            compilation = compile_file(source_dir, include_header_comment=False)

        identifiers = [
            action["WFWorkflowActionIdentifier"]
            for action in compilation.workflow["WFWorkflowActions"]
        ]
        self.assertIn("is.workflow.actions.math", identifiers)
        self.assertEqual(compilation.workflow["WFWorkflowName"], "Main")

    def test_compile_directory_requires_main_py(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with self.assertRaisesRegex(CompileError, "does not contain a main.py entrypoint"):
                compile_file(tmpdir)

    def test_simple_nn_is_lowered_to_runtime_actions(self) -> None:
        example = Path(__file__).resolve().parents[1] / "examples" / "simple_nn"
        workflow = compile_file(example, include_header_comment=False).workflow
        actions = workflow["WFWorkflowActions"]
        identifiers = [action["WFWorkflowActionIdentifier"] for action in actions]

        self.assertGreaterEqual(identifiers.count("is.workflow.actions.math"), 10)
        self.assertEqual(identifiers.count("is.workflow.actions.conditional"), 2)

        predicted_class = next(
            action
            for action in actions
            if action["WFWorkflowActionIdentifier"] == "is.workflow.actions.setvariable"
            and action["WFWorkflowActionParameters"].get("WFVariableName") == "predicted_class"
        )
        value = predicted_class["WFWorkflowActionParameters"]["WFInput"]["Value"]
        self.assertTrue(value["VariableName"].startswith("__py2s_argmax_index_"))

    def test_cli_build_directory_writes_next_to_main(self) -> None:
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmpdir:
            source_dir = Path(tmpdir) / "project"
            source_dir.mkdir()
            (source_dir / "main.py").write_text("print(1)\n", encoding="utf-8")

            result = runner.invoke(app, ["build", str(source_dir)])

            self.assertEqual(result.exit_code, 0, msg=result.stdout)
            self.assertTrue((source_dir / "main.plist").exists())
            self.assertFalse(source_dir.with_suffix(".plist").exists())


    def test_local_plugin_discovery_does_not_execute_non_plugins(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            project = Path(tmpdir)
            source = project / "main.py"
            source.write_text("print(1)\n", encoding="utf-8")
            (project / "not_a_plugin.py").write_text(
                "from ios.ui import show\nshow('must not execute during plugin discovery')\n",
                encoding="utf-8",
            )
            (project / "real_plugin.py").write_text(
                "def register(registry):\n    pass\n",
                encoding="utf-8",
            )

            compilation = compile_file(source, include_header_comment=False)

        identifiers = [
            action["WFWorkflowActionIdentifier"]
            for action in compilation.workflow["WFWorkflowActions"]
        ]
        self.assertIn("is.workflow.actions.showresult", identifiers)

    def test_cli_build_command(self) -> None:
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmpdir:
            old_cwd = os.getcwd()
            try:
                os.chdir(tmpdir)
                source = Path("demo.py")
                source.write_text("x = 1 + 2\nprint(x)\n", encoding="utf-8")

                result = runner.invoke(app, ["build", str(source), "-o", "demo.plist"])

                self.assertEqual(result.exit_code, 0, msg=result.stdout)
                self.assertTrue(Path("demo.plist").exists())
                self.assertIn("Wrote", result.stdout)
            finally:
                os.chdir(old_cwd)


if __name__ == "__main__":
    unittest.main()


def test_shortcut_input_content_graph_and_images() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        project = Path(tmpdir)
        (project / "py2shortcuts.toml").write_text(
            '[shortcut]\nname = "Image Demo"\n\n'
            '[shortcut.input]\ntypes = ["images", "files", "pdfs", "safari-webpages"]\n',
            encoding="utf-8",
        )
        (project / "main.py").write_text(
            "from ios.shortcuts import input\n"
            "from ios.content import Image, coerce\n"
            "from ios.images import resize, convert\n"
            "from ios.data import as_bytes\n"
            "source = input()\n"
            "image = coerce(source, Image)\n"
            "image = resize(image, width=28, height=28)\n"
            'bmp = convert(image, format="BMP")\n'
            "data = as_bytes(bmp)\n"
            "print(data)\n",
            encoding="utf-8",
        )
        workflow = compile_file(project, include_header_comment=False).workflow

    assert workflow["WFWorkflowName"] == "Image Demo"
    assert workflow["WFWorkflowHasShortcutInputVariables"] is True
    assert workflow["WFWorkflowTypes"] == ["ActionExtension"]
    assert workflow["WFWorkflowInputContentItemClasses"] == [
        "WFImageContentItem",
        "WFGenericFileContentItem",
        "WFPDFContentItem",
        "WFSafariWebPageContentItem",
    ]
    actions = workflow["WFWorkflowActions"]
    ids = [action["WFWorkflowActionIdentifier"] for action in actions]
    assert "is.workflow.actions.image.resize" in ids
    assert "is.workflow.actions.image.convert" in ids
    assert "is.workflow.actions.base64encode" in ids
    resize_action = next(a for a in actions if a["WFWorkflowActionIdentifier"] == "is.workflow.actions.image.resize")
    image_value = resize_action["WFWorkflowActionParameters"]["WFImage"]["Value"]
    assert image_value["Type"] == "Variable"
    # The assignment to `image` preserves the explicit Content Graph coercion.
    set_image = next(
        a for a in actions
        if a["WFWorkflowActionIdentifier"] == "is.workflow.actions.setvariable"
        and a["WFWorkflowActionParameters"].get("WFVariableName") == "image"
    )
    input_value = set_image["WFWorkflowActionParameters"]["WFInput"]["Value"]
    assert input_value["Type"] == "Variable"
    assert input_value["VariableName"] == "source"
    assert input_value["Aggrandizements"][0]["Type"] == "WFCoercionVariableAggrandizement"
    assert input_value["Aggrandizements"][0]["CoercionItemClass"] == "WFImageContentItem"


def test_shortcutslib_to_bmp_bytes_expands_cleanly() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        project = Path(tmpdir)
        (project / "py2shortcuts.toml").write_text(
            '[shortcut.input]\ntypes = ["images", "files"]\n', encoding="utf-8"
        )
        (project / "main.py").write_text(
            "from ios.shortcuts import input\n"
            "from shortcutslib.image import to_bmp_bytes\n"
            "data = to_bmp_bytes(input(), width=28, height=28)\n"
            "print(data)\n",
            encoding="utf-8",
        )
        workflow = compile_file(project, include_header_comment=False).workflow

    ids = [a["WFWorkflowActionIdentifier"] for a in workflow["WFWorkflowActions"]]
    assert ids.count("is.workflow.actions.image.resize") == 1
    assert ids.count("is.workflow.actions.image.convert") == 1
    assert ids.count("is.workflow.actions.base64encode") == 1
    assert "is.workflow.actions.input" not in ids


def test_shortcut_input_requires_declared_types() -> None:
    with pytest.raises(CompileError, match="shortcut.input.types"):
        compile_source(
            "from ios.shortcuts import input\nprint(input())\n",
            include_header_comment=False,
        )


def test_shortcutslib_bmp_decoder_emits_runtime_parser() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        project = Path(tmpdir)
        (project / "py2shortcuts.toml").write_text(
            '[shortcut.input]\ntypes = ["images"]\n', encoding="utf-8"
        )
        (project / "main.py").write_text(
            "from ios.shortcuts import input\n"
            "from shortcutslib.image import to_bmp_bytes, decode_bmp_grayscale\n"
            "bmp = to_bmp_bytes(input(), width=1, height=1)\n"
            "pixels = decode_bmp_grayscale(bmp, width=1, height=1)\n"
            "print(pixels)\n",
            encoding="utf-8",
        )
        workflow = compile_file(project, include_header_comment=False).workflow

    ids = [a["WFWorkflowActionIdentifier"] for a in workflow["WFWorkflowActions"]]
    assert "is.workflow.actions.text.match" in ids
    assert "is.workflow.actions.dictionary" in ids
    assert "is.workflow.actions.getvalueforkey" in ids
    assert "is.workflow.actions.getitemfromlist" in ids
    assert "is.workflow.actions.list" in ids
    assert "is.workflow.actions.exit" in ids


def test_local_plugin_can_import_sibling_module_without_executing_nonplugins() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        project = Path(tmpdir)
        source = project / "main.py"
        source.write_text("import model\nprint(model.answer())\n", encoding="utf-8")
        (project / "weights.py").write_text("VALUE = 7\n", encoding="utf-8")
        (project / "model.py").write_text(
            "from weights import VALUE\n"
            "def answer():\n    raise RuntimeError\n"
            "def register(registry):\n"
            "    @registry.call('model.answer', result_type='number')\n"
            "    def lower(backend, call):\n"
            "        return backend.emit_literal(VALUE)\n",
            encoding="utf-8",
        )
        workflow = compile_file(source, include_header_comment=False).workflow

    numbers = [
        action["WFWorkflowActionParameters"].get("WFNumberActionNumber")
        for action in workflow["WFWorkflowActions"]
        if action["WFWorkflowActionIdentifier"] == "is.workflow.actions.number"
    ]
    assert "7" in numbers


def test_mnist_showcase_compiles_to_runtime_image_and_nn_actions() -> None:
    project = Path(__file__).resolve().parents[1] / "examples" / "mnist"
    workflow = compile_file(project, include_header_comment=False).workflow
    ids = [a["WFWorkflowActionIdentifier"] for a in workflow["WFWorkflowActions"]]

    assert "is.workflow.actions.image.resize" in ids
    assert "is.workflow.actions.image.convert" in ids
    assert "is.workflow.actions.base64encode" in ids
    assert "is.workflow.actions.text.match" in ids
    assert "is.workflow.actions.getvalueforkey" in ids
    assert "is.workflow.actions.math" in ids
    assert "is.workflow.actions.conditional" in ids
    assert "is.workflow.actions.showresult" in ids
    assert len(ids) > 1000  # prove the NN/parser was not folded to a constant prediction
