"""Minimal Shortcuts plist construction helpers.

This module intentionally models the plist format directly. It is the first
layer of the compiler, before Python syntax is compiled into actions.
"""

from __future__ import annotations

import plistlib
import uuid

type PlistValue = str | int | float | bool | bytes | list[PlistValue] | dict[str, PlistValue]
type Action = dict[str, PlistValue]
type Workflow = dict[str, PlistValue]


def raw_action(identifier: str, /, **parameters: PlistValue) -> Action:
    """Create one action using an exact reverse-DNS identifier."""
    return {
        "WFWorkflowActionIdentifier": identifier,
        "WFWorkflowActionParameters": {**parameters, "UUID": str(uuid.uuid4()).upper()},
    }


def action(identifier: str, /, **parameters: PlistValue) -> Action:
    """Create one first-party Shortcuts action with a fresh action UUID."""
    return raw_action(f"is.workflow.actions.{identifier}", **parameters)


def action_output(action_value: Action, output_name: str) -> dict[str, PlistValue]:
    """Reference an action output with the compact token representation."""
    parameters = action_value["WFWorkflowActionParameters"]
    if not isinstance(parameters, dict):
        raise ValueError("Action has no parameter dictionary")
    action_uuid = parameters.get("UUID")
    if not isinstance(action_uuid, str):
        raise ValueError("Action has no UUID")
    return {
        "Value": {
            "OutputUUID": action_uuid,
            "OutputName": output_name,
            "Type": "ActionOutput",
        },
        "WFSerializationType": "WFTextTokenAttachment",
    }


def action_output_text(action_value: Action, output_name: str) -> dict[str, PlistValue]:
    """Reference an action output as a text token.

    The Health actions use this form for start and end dates. It is different
    from WFTextTokenAttachment and matches the corrected shortcut exported
    from the user's iPhone.
    """
    reference = action_output(action_value, output_name)["Value"]
    if not isinstance(reference, dict):
        raise ValueError("Action output reference is malformed")
    return {
        "Value": {
            "string": "\ufffc",
            "attachmentsByRange": {"{0, 1}": reference},
        },
        "WFSerializationType": "WFTextTokenString",
    }


def text_with_action_output(
    prefix: str,
    action_value: Action,
    output_name: str,
    suffix: str = "",
) -> dict[str, PlistValue]:
    """Build a text-token string whose placeholder references one action output."""
    reference = action_output(action_value, output_name)["Value"]
    if not isinstance(reference, dict):
        raise ValueError("Action output reference is malformed")
    utf16_offset = len(prefix.encode("utf-16-le")) // 2
    return {
        "Value": {
            "string": f"{prefix}\ufffc{suffix}",
            "attachmentsByRange": {f"{{{utf16_offset}, 1}}": reference},
        },
        "WFSerializationType": "WFTextTokenString",
    }


def workflow(
    actions: list[Action],
    *,
    name: str,
    input_classes: tuple[str, ...] = (),
    workflow_types: tuple[str, ...] = (),
    has_shortcut_input: bool = False,
) -> Workflow:
    """Create the smallest workflow wrapper needed by a signed shortcut."""
    return {
        "WFWorkflowName": name,
        "WFWorkflowClientVersion": "2700.0.4",
        "WFWorkflowClientRelease": "18.0",
        "WFWorkflowMinimumClientVersion": 900,
        "WFWorkflowTypes": list(workflow_types),
        "WFWorkflowInputContentItemClasses": list(input_classes),
        "WFWorkflowHasShortcutInputVariables": has_shortcut_input,
        "WFWorkflowImportQuestions": [],
        "WFWorkflowHasOutputFallback": False,
        "WFWorkflowIcon": {
            "WFWorkflowIconStartColor": 4251333119,
            "WFWorkflowIconGlyphNumber": 59511,
        },
        "WFWorkflowActions": actions,
    }


def compile_xml_plist(workflow_value: Workflow) -> bytes:
    """Compile a workflow to the XML plist accepted by the signing step."""
    return plistlib.dumps(workflow_value, fmt=plistlib.FMT_XML, sort_keys=False)


def compile_binary_plist(workflow_value: Workflow) -> bytes:
    """Compile a workflow to a binary plist for direct inspection or signing."""
    return plistlib.dumps(workflow_value, fmt=plistlib.FMT_BINARY, sort_keys=False)
