"""The Health sleep-stage probe previously generated in this workspace.

The values below are intentionally a probe, rather than a claim that native
Shortcuts can write Core, Deep, or REM sleep stages on every iOS version.
"""

from __future__ import annotations

import uuid

from .plist import Action, Workflow, action, action_output, action_output_text, text_with_action_output, workflow

type SleepProbeCase = tuple[str, str | int]

DEFAULT_SLEEP_PROBE_CASES: tuple[SleepProbeCase, ...] = (
    ("Core", "Core"),
    ("Deep", "Deep"),
    ("REM", "REM"),
    ("Awake - baseline", "Awake"),
    ("Asleep Core - alternate label", "Asleep Core"),
    ("Asleep Deep - alternate label", "Asleep Deep"),
    ("Asleep REM - alternate label", "Asleep REM"),
)


def build_sleep_stage_probe(
    cases: tuple[SleepProbeCase, ...] = DEFAULT_SLEEP_PROBE_CASES,
) -> Workflow:
    """Build the isolated Health write probe as a Shortcuts workflow.

    Each menu choice writes a one-minute sample on 2001-01-01 at UTC+08:00.
    The old date intentionally makes test data easy to identify and delete.
    """
    if not cases:
        raise ValueError("At least one sleep probe case is required")
    if len(cases) > 30:
        raise ValueError("At most 30 cases fit in the fixed test hour")

    menu_group = str(uuid.uuid4()).upper()
    actions: list[Action] = [
        action(
            "comment",
            WFCommentActionText=(
                "Sleep stage write probe. No network or credentials. Each selection "
                "attempts one 60-second sample on 2001-01-01 at UTC+08:00. "
                "Core/Deep/REM enum labels are experimental. Do not rerun a successful "
                "case: this probe does not deduplicate. Delete test samples manually "
                "in Health after checking."
            ),
        ),
        action(
            "choosefrommenu",
            GroupingIdentifier=menu_group,
            WFControlFlowMode=0,
            WFMenuPrompt=(
                "睡眠分期写入测试：选择一次将尝试写入2001-01-01的一分钟样本。"
                "先试Core、Deep；Awake为基础对照。成功项请勿重复运行。"
            ),
            WFMenuItems=[title for title, _ in cases],
        ),
    ]

    for index, (title, enum_value) in enumerate(cases):
        start_minute = index * 2
        end_minute = start_minute + 1
        start = f"2001-01-01T12:{start_minute:02d}:00+08:00"
        end = f"2001-01-01T12:{end_minute:02d}:00+08:00"

        actions.append(
            action(
                "choosefrommenu",
                GroupingIdentifier=menu_group,
                WFControlFlowMode=1,
                WFMenuItemTitle=title,
            )
        )
        start_date = action("date", WFDateActionMode="Specified Date", WFDateActionDate=start)
        end_date = action("date", WFDateActionMode="Specified Date", WFDateActionDate=end)
        actions.extend((start_date, end_date))

        health_log = action(
            "health.quantity.log",
            WFQuantitySampleType="Sleep",
            WFCategorySampleEnumeration=enum_value,
            # These WFTextTokenString values preserve the date fix made on iOS.
            WFQuantitySampleDate=action_output_text(start_date, "日期"),
            WFSampleEndDate=action_output_text(end_date, "日期"),
        )
        actions.append(health_log)
        value = action(
            "properties.health.quantity",
            WFContentItemPropertyName="Value",
            WFInput=action_output(health_log, "Health Sample"),
        )
        actions.append(value)
        actions.append(
            action(
                "showresult",
                Text=text_with_action_output(
                    f"请求值：{enum_value}\n测试时间：{start} — {end}\n写入动作返回的 Value：",
                    value,
                    "Value",
                    "\n\n这不是独立数据库回读。请在健康App→睡眠→显示所有数据中检查"
                    "2001-01-01：必须保留目标分期，只有“睡眠/Asleep”不算成功。"
                    "检查后删除测试样本。",
                ),
            )
        )

    actions.append(action("choosefrommenu", GroupingIdentifier=menu_group, WFControlFlowMode=2))
    return workflow(actions, name="Sleep Stage Write Probe")
