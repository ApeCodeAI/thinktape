"""Regression tests for the generated iPhone Shortcut wiring."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from scripts.build_iphone_shortcuts import capture, retry  # noqa: E402


def test_recording_response_dictionary_values_have_explicit_value_mode():
    for workflow in (capture(), retry()):
        actions = workflow["WFWorkflowActions"]
        get_values = [
            action["WFWorkflowActionParameters"]
            for action in actions
            if action["WFWorkflowActionIdentifier"] == "is.workflow.actions.getvalueforkey"
        ]
        assert [params["WFDictionaryKey"] for params in get_values] == [
            "stored", "recording_id", "checksum",
        ]
        assert [params.get("WFGetDictionaryValueType") for params in get_values] == [
            "Value", "Value", "Value",
        ]


def test_recording_id_random_suffix_is_built_from_ungrouped_chunks():
    workflow = capture()
    actions = workflow["WFWorkflowActions"]
    randoms = [a["WFWorkflowActionParameters"] for a in actions
               if a["WFWorkflowActionIdentifier"] == "is.workflow.actions.number.random"]
    assert len(randoms) == 4
    assert all(p["WFRandomNumberMinimum"] == 100 and
               p["WFRandomNumberMaximum"] == 999 for p in randoms)
    # A 12-digit Number may be formatted with grouping commas by iOS when
    # inserted into a Text action. Four three-digit chunks cannot group.
    names = [a["WFWorkflowActionParameters"]["WFTextActionText"] for a in actions
             if a["WFWorkflowActionIdentifier"] == "is.workflow.actions.gettext"]
    assert any(len(v["Value"]["attachmentsByRange"]) == 5
               for v in names if isinstance(v, dict))


def test_retry_strips_legacy_grouping_commas_from_id_only():
    workflow = retry()
    actions = workflow["WFWorkflowActions"]
    replacements = [a["WFWorkflowActionParameters"] for a in actions
                    if a["WFWorkflowActionIdentifier"] == "is.workflow.actions.text.replace"]
    assert len(replacements) == 1
    assert replacements[0]["WFReplaceTextFind"] == ","
    assert replacements[0]["WFReplaceTextReplace"] == ""
    assert replacements[0]["WFReplaceTextRegularExpression"] is False
