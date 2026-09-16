"""Structural validation for generated workflow plists.

This does not claim to replace Apple's importer. It catches compiler bugs such
as dangling ActionOutput UUIDs and unbalanced control-flow markers before a
workflow is signed or moved to an iPhone.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .plist import Workflow


class WorkflowValidationError(ValueError):
    pass


_CONTROL_IDENTIFIERS = {
    "is.workflow.actions.conditional",
    "is.workflow.actions.repeat.count",
    "is.workflow.actions.repeat.each",
    "is.workflow.actions.choosefrommenu",
}


def validate_workflow(workflow: Workflow) -> None:
    actions = workflow.get("WFWorkflowActions")
    if not isinstance(actions, list):
        raise WorkflowValidationError("WFWorkflowActions must be a list")

    seen_uuids: set[str] = set()
    stack: list[tuple[str, str]] = []

    for index, action in enumerate(actions):
        if not isinstance(action, dict):
            raise WorkflowValidationError(f"action {index} is not a dictionary")
        identifier = action.get("WFWorkflowActionIdentifier")
        parameters = action.get("WFWorkflowActionParameters")
        if not isinstance(identifier, str) or not identifier:
            raise WorkflowValidationError(f"action {index} has no identifier")
        if not isinstance(parameters, dict):
            raise WorkflowValidationError(f"action {index} has no parameter dictionary")

        for output_uuid in _find_output_uuids(parameters):
            if output_uuid not in seen_uuids:
                raise WorkflowValidationError(
                    f"action {index} ({identifier}) references unknown/future OutputUUID {output_uuid}"
                )

        action_uuid = parameters.get("UUID")
        if action_uuid is not None:
            if not isinstance(action_uuid, str) or not action_uuid:
                raise WorkflowValidationError(f"action {index} has an invalid UUID")
            if action_uuid in seen_uuids:
                raise WorkflowValidationError(f"duplicate action UUID {action_uuid}")
            seen_uuids.add(action_uuid)

        if identifier in _CONTROL_IDENTIFIERS and "WFControlFlowMode" in parameters:
            mode = parameters["WFControlFlowMode"]
            group = parameters.get("GroupingIdentifier")
            if not isinstance(group, str) or not group:
                raise WorkflowValidationError(f"control-flow action {index} has no GroupingIdentifier")
            if mode == 0:
                stack.append((identifier, group))
            elif mode == 1:
                if identifier != "is.workflow.actions.conditional":
                    raise WorkflowValidationError(f"middle marker at action {index} is only valid for a conditional")
                if not stack or stack[-1] != (identifier, group):
                    raise WorkflowValidationError(f"unmatched conditional middle marker at action {index}")
            elif mode == 2:
                if not stack or stack[-1] != (identifier, group):
                    raise WorkflowValidationError(f"unmatched control-flow end marker at action {index}")
                stack.pop()
            else:
                raise WorkflowValidationError(f"invalid WFControlFlowMode {mode!r} at action {index}")

    if stack:
        identifier, group = stack[-1]
        raise WorkflowValidationError(f"unclosed control-flow group {group} ({identifier})")


def _find_output_uuids(value: Any):
    if isinstance(value, Mapping):
        output_uuid = value.get("OutputUUID")
        if isinstance(output_uuid, str):
            yield output_uuid
        for child in value.values():
            yield from _find_output_uuids(child)
    elif isinstance(value, list):
        for child in value:
            yield from _find_output_uuids(child)
