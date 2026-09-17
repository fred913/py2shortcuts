from __future__ import annotations

import os
import plistlib
import tempfile

import pytest
import unittest
from unittest.mock import patch
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

    def test_cli_build_directory_uses_directory_name_for_output(self) -> None:
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmpdir:
            source_dir = Path(tmpdir) / "project"
            source_dir.mkdir()
            (source_dir / "main.py").write_text("print(1)\n", encoding="utf-8")

            result = runner.invoke(app, ["build", str(source_dir)])

            self.assertEqual(result.exit_code, 0, msg=result.stdout)
            self.assertTrue(source_dir.with_suffix(".plist").exists())
            self.assertFalse((source_dir / "main.plist").exists())

    def test_cli_build_explicit_main_py_keeps_main_output_name(self) -> None:
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmpdir:
            source_dir = Path(tmpdir) / "project"
            source_dir.mkdir()
            source = source_dir / "main.py"
            source.write_text("print(1)\n", encoding="utf-8")

            result = runner.invoke(app, ["build", str(source)])

            self.assertEqual(result.exit_code, 0, msg=result.stdout)
            self.assertTrue((source_dir / "main.plist").exists())
            self.assertFalse(source_dir.with_suffix(".plist").exists())


    def test_cli_build_directory_sign_uses_directory_name(self) -> None:
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmpdir:
            source_dir = Path(tmpdir) / "project"
            source_dir.mkdir()
            (source_dir / "main.py").write_text("print(1)\n", encoding="utf-8")

            with patch("py2shortcuts.sign_xml_plist", return_value=b"signed"):
                result = runner.invoke(app, ["build", str(source_dir), "--sign"])

            self.assertEqual(result.exit_code, 0, msg=result.stdout)
            self.assertTrue(source_dir.with_suffix(".plist").exists())
            self.assertEqual(source_dir.with_suffix(".shortcut").read_bytes(), b"signed")
            self.assertFalse((source_dir / "main.shortcut").exists())


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
            "from ios.shortcuts import shortcut_input\n"
            "from ios.content import Image, coerce\n"
            "from ios.images import resize, convert\n"
            "from ios.data import as_bytes\n"
            "source = shortcut_input()\n"
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
            "from ios.shortcuts import shortcut_input\n"
            "from shortcutslib.image import to_bmp_bytes\n"
            "data = to_bmp_bytes(shortcut_input(), width=28, height=28)\n"
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
            "from ios.shortcuts import shortcut_input\nprint(shortcut_input())\n",
            include_header_comment=False,
        )


def test_shortcutslib_bmp_decoder_emits_runtime_parser() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        project = Path(tmpdir)
        (project / "py2shortcuts.toml").write_text(
            '[shortcut.input]\ntypes = ["images"]\n', encoding="utf-8"
        )
        (project / "main.py").write_text(
            "from ios.shortcuts import shortcut_input\n"
            "from shortcutslib.image import to_bmp_bytes, decode_bmp_grayscale\n"
            "bmp = to_bmp_bytes(shortcut_input(), width=1, height=1)\n"
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

    assert "is.workflow.actions.image.resize" not in ids
    assert "is.workflow.actions.image.convert" in ids
    assert "is.workflow.actions.base64encode" in ids
    assert "is.workflow.actions.text.match" in ids
    assert "is.workflow.actions.getvalueforkey" in ids
    assert "is.workflow.actions.math" in ids
    assert "is.workflow.actions.conditional" in ids
    assert "is.workflow.actions.showresult" in ids
    assert len(ids) > 1000  # prove the NN/parser was not folded to a constant prediction


def test_shortcutslib_decode_image_expands_full_image_pipeline() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        project = Path(tmpdir)
        (project / "py2shortcuts.toml").write_text(
            '[shortcut.input]\ntypes = ["images", "files"]\n', encoding="utf-8"
        )
        (project / "main.py").write_text(
            "from ios.shortcuts import shortcut_input\n"
            "from shortcutslib.image import decode_image\n"
            'pixels = decode_image(shortcut_input(), width=2, height=1, mode="grayscale")\n'
            "print(pixels)\n",
            encoding="utf-8",
        )
        workflow = compile_file(project, include_header_comment=False).workflow

    ids = [a["WFWorkflowActionIdentifier"] for a in workflow["WFWorkflowActions"]]
    # decode_image() keeps the original image dimensions and performs its own
    # fixed-size software supersampling over the parsed BMP.
    assert ids.count("is.workflow.actions.image.resize") == 0
    assert ids.count("is.workflow.actions.image.convert") == 1
    assert ids.count("is.workflow.actions.base64encode") == 1
    assert "is.workflow.actions.list" in ids
    assert "is.workflow.actions.exit" in ids


def test_shortcutslib_decode_image_rgb_and_bgr_are_supported() -> None:
    for mode in ("rgb", "bgr"):
        with tempfile.TemporaryDirectory() as tmpdir:
            project = Path(tmpdir)
            (project / "py2shortcuts.toml").write_text(
                '[shortcut.input]\ntypes = ["images"]\n', encoding="utf-8"
            )
            (project / "main.py").write_text(
                "from ios.shortcuts import shortcut_input\n"
                "from shortcutslib.image import decode_image\n"
                f'pixels = decode_image(shortcut_input(), width=1, height=1, mode="{mode}")\n'
                "print(pixels)\n",
                encoding="utf-8",
            )
            workflow = compile_file(project, include_header_comment=False).workflow

        actions = workflow["WFWorkflowActions"]
        # RGB/BGR decoding returns three numeric channel values. They are
        # materialized through Add to Variable so their numeric types are
        # preserved instead of being stringified inside WFItems.
        assert sum(
            a["WFWorkflowActionIdentifier"] == "is.workflow.actions.appendvariable"
            for a in actions
        ) >= 3
        assert all(
            a["WFWorkflowActionParameters"].get("WFItems") == []
            for a in actions
            if a["WFWorkflowActionIdentifier"] == "is.workflow.actions.list"
        )


def test_shortcutslib_decode_image_uses_compiler_supersampling() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        project = Path(tmpdir)
        (project / "py2shortcuts.toml").write_text(
            '[shortcut.input]\ntypes = ["images"]\n', encoding="utf-8"
        )
        (project / "main.py").write_text(
            "from ios.shortcuts import shortcut_input\n"
            "from shortcutslib.image import decode_image\n"
            'pixels = decode_image(shortcut_input(), width=2, height=2, mode="grayscale")\n',
            encoding="utf-8",
        )
        workflow = compile_file(project, include_header_comment=False).workflow

    actions = workflow["WFWorkflowActions"]
    ids = [item["WFWorkflowActionIdentifier"] for item in actions]
    assert "is.workflow.actions.image.resize" not in ids
    assert ids.count("is.workflow.actions.image.convert") == 1
    # Runtime source dimensions feed the compiler-generated sample-coordinate
    # math, so this path must contain modulus/floor emulation and substantially
    # more arithmetic than a simple pre-resized pixel decode.
    assert ids.count("is.workflow.actions.math") > 100
    assert any(
        item["WFWorkflowActionIdentifier"] == "is.workflow.actions.math"
        and item["WFWorkflowActionParameters"].get("WFScientificMathOperation") == "Modulus"
        for item in actions
    )


def test_shortcutslib_decode_image_rejects_unknown_mode() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        project = Path(tmpdir)
        (project / "py2shortcuts.toml").write_text(
            '[shortcut.input]\ntypes = ["images"]\n', encoding="utf-8"
        )
        (project / "main.py").write_text(
            "from ios.shortcuts import shortcut_input\n"
            "from shortcutslib.image import decode_image\n"
            'pixels = decode_image(shortcut_input(), width=1, height=1, mode="rgba")\n',
            encoding="utf-8",
        )
        with pytest.raises(CompileError, match="grayscale, rgb, bgr"):
            compile_file(project, include_header_comment=False)


def test_shortcut_input_is_distinct_from_python_input() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        project = Path(tmpdir)
        (project / "py2shortcuts.toml").write_text(
            '[shortcut.input]\ntypes = ["images"]\n', encoding="utf-8"
        )
        (project / "main.py").write_text(
            "from ios.shortcuts import shortcut_input\n"
            "shared = shortcut_input()\n"
            'typed = input("Type something")\n'
            "print(shared, typed)\n",
            encoding="utf-8",
        )
        workflow = compile_file(project, include_header_comment=False).workflow

    ids = [a["WFWorkflowActionIdentifier"] for a in workflow["WFWorkflowActions"]]
    assert workflow["WFWorkflowHasShortcutInputVariables"] is True
    assert ids.count("is.workflow.actions.ask") == 1


def test_bmp_diagnostic_contains_actual_bytes_and_base64_prefix() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        project = Path(tmpdir)
        (project / "py2shortcuts.toml").write_text(
            '[shortcut.input]\ntypes = ["images"]\n', encoding="utf-8"
        )
        (project / "main.py").write_text(
            "from ios.shortcuts import shortcut_input\n"
            "from shortcutslib.image import decode_image\n"
            'pixels = decode_image(shortcut_input(), width=1, height=1)\n',
            encoding="utf-8",
        )
        workflow = compile_file(project, include_header_comment=False).workflow

    alert = next(
        a for a in workflow["WFWorkflowActions"]
        if a["WFWorkflowActionIdentifier"] == "is.workflow.actions.alert"
        and a["WFWorkflowActionParameters"].get("WFAlertActionTitle") == "Invalid BMP signature"
    )
    message = alert["WFWorkflowActionParameters"]["WFAlertActionMessage"]
    text = message["Value"]["string"]
    assert 'Expected bytes[0:2]: 66, 77 (0x42 0x4D, "BM")' in text
    assert "Actual bytes[0:2]:" in text
    assert "Base64 prefix:" in text
    assert "starts with Qk" in text
    assert len(message["Value"]["attachmentsByRange"]) == 6


def test_bmp_numeric_guards_use_numeric_comparisons() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        project = Path(tmpdir)
        (project / "py2shortcuts.toml").write_text(
            '[shortcut.input]\ntypes = ["images"]\n', encoding="utf-8"
        )
        (project / "main.py").write_text(
            "from ios.shortcuts import shortcut_input\n"
            "from shortcutslib.image import decode_image\n"
            'pixels = decode_image(shortcut_input(), width=1, height=1)\n',
            encoding="utf-8",
        )
        workflow = compile_file(project, include_header_comment=False).workflow

    actions = workflow["WFWorkflowActions"]
    first_signature_alert_index = next(
        index for index, item in enumerate(actions)
        if item["WFWorkflowActionIdentifier"] == "is.workflow.actions.alert"
        and item["WFWorkflowActionParameters"].get("WFAlertActionTitle") == "Invalid BMP signature"
    )
    condition = actions[first_signature_alert_index - 1]
    params = condition["WFWorkflowActionParameters"]
    assert condition["WFWorkflowActionIdentifier"] == "is.workflow.actions.conditional"
    assert params["WFCondition"] == 0
    assert params["WFNumberValue"] == "66"
    assert "WFConditionalActionString" not in params

    numeric_signature_conditions = [
        item["WFWorkflowActionParameters"]
        for item in actions
        if item["WFWorkflowActionIdentifier"] == "is.workflow.actions.conditional"
        and item["WFWorkflowActionParameters"].get("WFNumberValue") in {"66", "77"}
    ]
    assert {params["WFCondition"] for params in numeric_signature_conditions} == {0, 2}


def test_bmp_bitfields_support_and_diagnostics_are_emitted() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        project = Path(tmpdir)
        (project / "py2shortcuts.toml").write_text(
            '[shortcut.input]\ntypes = ["images"]\n', encoding="utf-8"
        )
        (project / "main.py").write_text(
            "from ios.shortcuts import shortcut_input\n"
            "from shortcutslib.image import decode_image\n"
            'pixels = decode_image(shortcut_input(), width=1, height=1)\n',
            encoding="utf-8",
        )
        workflow = compile_file(project, include_header_comment=False).workflow

    actions = workflow["WFWorkflowActions"]
    alerts = [
        a["WFWorkflowActionParameters"]
        for a in actions
        if a["WFWorkflowActionIdentifier"] == "is.workflow.actions.alert"
    ]
    mask_alert = next(a for a in alerts if a.get("WFAlertActionTitle") == "Unsupported BI_BITFIELDS masks")
    mask_text = mask_alert["WFAlertActionMessage"]["Value"]["string"]
    assert "R mask = 16711680 (0x00FF0000)" in mask_text
    assert "G mask = 65280 (0x0000FF00)" in mask_text
    assert "B mask = 255 (0x000000FF)" in mask_text
    assert "Actual:" in mask_text

    compression_alert = next(a for a in alerts if a.get("WFAlertActionTitle") == "Unsupported BMP compression")
    compression_text = compression_alert["WFAlertActionMessage"]["Value"]["string"]
    assert "BI_RGB (0) and BI_BITFIELDS (3)" in compression_text

    # The BI_BITFIELDS-only branch is guarded by numeric `compression > 0`.
    assert any(
        a["WFWorkflowActionIdentifier"] == "is.workflow.actions.conditional"
        and a["WFWorkflowActionParameters"].get("WFCondition") == 2
        and a["WFWorkflowActionParameters"].get("WFNumberValue") == "0"
        for a in actions
    )


def test_bmp_height_is_signed_and_supports_top_down_images() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        project = Path(tmpdir)
        (project / "py2shortcuts.toml").write_text(
            '[shortcut.input]\ntypes = ["images"]\n', encoding="utf-8"
        )
        (project / "main.py").write_text(
            "from ios.shortcuts import shortcut_input\n"
            "from shortcutslib.image import decode_image\n"
            'pixels = decode_image(shortcut_input(), width=7, height=7)\n',
            encoding="utf-8",
        )
        workflow = compile_file(project, include_header_comment=False).workflow

    actions = workflow["WFWorkflowActions"]
    assert any(
        item["WFWorkflowActionIdentifier"] == "is.workflow.actions.conditional"
        and item["WFWorkflowActionParameters"].get("WFCondition") == 2
        and item["WFWorkflowActionParameters"].get("WFNumberValue") == "127"
        for item in actions
    )

    # decode_image() no longer expects the BMP itself to be 7x7: it parses the
    # original-size image and uses the signed height only to select row order.
    assert not any(
        item["WFWorkflowActionIdentifier"] == "is.workflow.actions.alert"
        and item["WFWorkflowActionParameters"].get("WFAlertActionTitle") == "Unexpected BMP height"
        for item in actions
    )
    assert not any(
        item["WFWorkflowActionIdentifier"] == "is.workflow.actions.image.resize"
        for item in actions
    )

    assert any(
        item["WFWorkflowActionIdentifier"] == "is.workflow.actions.number"
        and item["WFWorkflowActionParameters"].get("WFNumberActionNumber") == "4294967296"
        for item in actions
    )


def test_local_source_module_multistatement_function_is_inlined() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        project = Path(tmpdir)
        (project / "helper.py").write_text(
            "SCALE = 3\n"
            "def transform(x):\n"
            "    y = x * SCALE\n"
            "    if y > 5:\n"
            "        y = y + 1\n"
            "    return y\n",
            encoding="utf-8",
        )
        (project / "main.py").write_text(
            "from helper import transform\n"
            "value = transform(2)\n"
            "print(value)\n",
            encoding="utf-8",
        )
        compilation = compile_file(project, include_header_comment=False)

    ids = [item["WFWorkflowActionIdentifier"] for item in compilation.workflow["WFWorkflowActions"]]
    assert "is.workflow.actions.math" in ids
    assert "is.workflow.actions.conditional" in ids
    assert "is.workflow.actions.showresult" in ids
    assert not any("helper" in identifier for identifier in ids)


def test_inline_function_argument_with_side_effect_is_evaluated_once() -> None:
    workflow = compile_source(
        "def twice(x):\n"
        "    y = x + x\n"
        "    return y\n"
        "value = twice(input('Number?'))\n"
        "print(value)\n",
        include_header_comment=False,
    ).workflow
    ids = [item["WFWorkflowActionIdentifier"] for item in workflow["WFWorkflowActions"]]
    assert ids.count("is.workflow.actions.ask") == 1
    assert "is.workflow.actions.math" in ids


def test_mnist_inference_is_pure_python_source_not_backend_plugin() -> None:
    project = Path(__file__).resolve().parents[1] / "examples" / "mnist"
    model_source = (project / "model.py").read_text(encoding="utf-8")
    assert "def predict(" in model_source
    assert "def register(" not in model_source
    assert "py2shortcuts.backend" not in model_source
    assert "py2shortcuts.plist" not in model_source
    assert "ValueRef" not in model_source
    assert "backend." not in model_source

    workflow = compile_file(project, include_header_comment=False).workflow
    ids = [item["WFWorkflowActionIdentifier"] for item in workflow["WFWorkflowActions"]]
    assert ids.count("is.workflow.actions.getitemfromlist") >= 49
    assert ids.count("is.workflow.actions.math") > 1000
    assert "is.workflow.actions.conditional" in ids


def test_list_append_lowers_to_add_to_variable() -> None:
    workflow = compile_source(
        "values = []\n"
        "values.append(1.0)\n"
        "values.append(2.0)\n"
        "print(len(values))\n",
        include_header_comment=False,
    ).workflow
    actions = workflow["WFWorkflowActions"]
    append_actions = [
        item for item in actions
        if item["WFWorkflowActionIdentifier"] == "is.workflow.actions.appendvariable"
    ]
    assert len(append_actions) == 2
    assert all(
        item["WFWorkflowActionParameters"].get("WFVariableName") == "values"
        for item in append_actions
    )


def test_list_comprehension_desugars_to_repeat_and_append() -> None:
    workflow = compile_source(
        "values = [0.0, 0.25, 1.0]\n"
        "inverted = [1.0 - value for value in values]\n"
        "print(len(inverted))\n",
        include_header_comment=False,
    ).workflow
    ids = [item["WFWorkflowActionIdentifier"] for item in workflow["WFWorkflowActions"]]
    assert "is.workflow.actions.repeat.each" in ids
    assert "is.workflow.actions.appendvariable" in ids
    assert "is.workflow.actions.math" in ids


def test_list_comprehension_filter_desugars_to_if() -> None:
    workflow = compile_source(
        "values = [-1.0, 0.5, 2.0]\n"
        "positive = [value for value in values if value > 0.0]\n"
        "print(len(positive))\n",
        include_header_comment=False,
    ).workflow
    ids = [item["WFWorkflowActionIdentifier"] for item in workflow["WFWorkflowActions"]]
    assert "is.workflow.actions.repeat.each" in ids
    assert "is.workflow.actions.conditional" in ids
    assert "is.workflow.actions.appendvariable" in ids


def test_mnist_uses_pure_python_invert_utility() -> None:
    project = Path(__file__).resolve().parents[1] / "examples" / "mnist"
    main_source = (project / "main.py").read_text(encoding="utf-8")
    utils_source = (project / "utils.py").read_text(encoding="utf-8")
    assert "pixels = invert(pixels)" in main_source
    assert "return [1.0 - value for value in values]" in utils_source
    assert "result.append(" in utils_source

    workflow = compile_file(project, include_header_comment=False).workflow
    ids = [item["WFWorkflowActionIdentifier"] for item in workflow["WFWorkflowActions"]]
    assert "is.workflow.actions.appendvariable" in ids
    assert "is.workflow.actions.repeat.each" in ids

def test_repeat_special_values_use_magic_variables() -> None:
    workflow = compile_source(
        "values = [1.0, 2.0]\n"
        "out = [1.0 - value for value in values]\n"
        "for i in range(2):\n"
        "    print(i)\n"
    ).workflow

    def iter_dicts(value):
        if isinstance(value, dict):
            yield value
            for child in value.values():
                yield from iter_dicts(child)
        elif isinstance(value, list):
            for child in value:
                yield from iter_dicts(child)

    dicts = list(iter_dicts(workflow))
    names = {
        item.get("VariableName")
        for item in dicts
        if item.get("Type") == "Variable"
    }
    assert "Repeat Item" in names
    assert "Repeat Index" in names


def test_numeric_list_items_are_not_serialized_as_text_tokens() -> None:
    workflow = compile_source(
        "values = [1.0, 2.0]\n"
        "out = [1.0 - value for value in values]\n"
        "print(out[0])\n",
        include_header_comment=False,
    ).workflow
    actions = workflow["WFWorkflowActions"]

    # Typed Python list construction should use an empty List plus Add to
    # Variable, not WFTextTokenString entries that coerce numbers to text.
    list_actions = [
        a for a in actions
        if a["WFWorkflowActionIdentifier"] == "is.workflow.actions.list"
    ]
    assert list_actions
    assert all(a["WFWorkflowActionParameters"].get("WFItems") == [] for a in list_actions)
    assert sum(
        a["WFWorkflowActionIdentifier"] == "is.workflow.actions.appendvariable"
        for a in actions
    ) >= 3  # two list-literal items + one runtime list-comprehension append


def test_mnist_decoded_pixels_are_materialized_as_typed_list() -> None:
    root = Path(__file__).resolve().parents[1]
    workflow = compile_file(root / "examples" / "mnist").workflow
    actions = workflow["WFWorkflowActions"]

    # The decoder used to end with one List action containing 49
    # WFTextTokenString values. That stringified the pixels and caused
    # Calculate to fail once invert() iterated them. The decoder now appends
    # numeric Calculation Results into a list variable.
    assert sum(
        a["WFWorkflowActionIdentifier"] == "is.workflow.actions.appendvariable"
        for a in actions
    ) >= 50  # 49 decoder pixels + one append action repeated by invert()

