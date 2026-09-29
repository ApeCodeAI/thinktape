#!/usr/bin/env python3
"""Build ThinkTape's two public, unsigned iPhone Shortcuts; optionally sign on macOS.

No credentials or device-specific file bookmarks are stored in these artifacts.
Folder picker values and URL/key are import questions resolved on the iPhone.
"""
from __future__ import annotations

import argparse
import plistlib
import subprocess
import uuid
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "docs" / "shortcuts"
OBJECT = "\ufffc"


def uid():
    return str(uuid.uuid4()).upper()


def variable(name: str):
    return {"Type": "Variable", "VariableName": name}


def output(action: dict, name: str):
    return {"Type": "ActionOutput", "OutputUUID": action["WFWorkflowActionParameters"]["UUID"], "OutputName": name}


def attachment(ref: dict):
    return {"Value": ref, "WFSerializationType": "WFTextTokenAttachment"}


def text(*parts):
    """A WFTextTokenString, with one replacement character per variable."""
    string = ""
    attachments = {}
    for part in parts:
        if isinstance(part, str):
            string += part
        else:
            attachments[f"{{{len(string)}, 1}}"] = part
            string += OBJECT
    return {"Value": {"string": string, "attachmentsByRange": attachments}, "WFSerializationType": "WFTextTokenString"}


def field(key: str, value, item_type: int = 0):
    return {"WFKey": text(key), "WFItemType": item_type, "WFValue": value}


def fields(items):
    return {"Value": {"WFDictionaryFieldValueItems": items}, "WFSerializationType": "WFDictionaryFieldValue"}


def act(identifier: str, **params):
    return {"WFWorkflowActionIdentifier": "is.workflow.actions." + identifier,
            "WFWorkflowActionParameters": {"UUID": uid(), **params}}


class Builder:
    def __init__(self):
        self.actions = []
        self.questions = []

    def add(self, identifier: str, **params):
        action = act(identifier, **params)
        self.actions.append(action)
        return action

    def question(self, action: dict, key: str, prompt: str):
        self.questions.append({"ActionIndex": self.actions.index(action), "Category": "Parameter",
                               "ParameterKey": key, "Text": prompt})

    def start_if(self, ref, *, string=None, boolean=None):
        group = uid()
        params = {"GroupingIdentifier": group, "WFControlFlowMode": 0, "WFCondition": 4,
                  "WFInput": {"Type": "Variable", "Variable": attachment(ref)}}
        if boolean is not None:
            params["WFBooleanValue"] = boolean
        else:
            params["WFConditionalActionString"] = string
        self.add("conditional", **params)
        return group

    def otherwise(self, group):
        self.add("conditional", WFControlFlowMode=1, GroupingIdentifier=group)

    def end_if(self, group):
        self.add("conditional", WFControlFlowMode=2, GroupingIdentifier=group)

    def note(self, message):
        self.add("notification", WFNotificationActionBody=message)

    def workflow(self, name):
        return {"WFWorkflowName": name, "WFWorkflowClientVersion": "3200",
                "WFWorkflowMinimumClientVersion": 900, "WFWorkflowMinimumClientVersionString": "900",
                "WFWorkflowTypes": ["NCWidget", "WatchKit"],
                "WFWorkflowInputContentItemClasses": [],
                "WFWorkflowIcon": {"WFWorkflowIconStartColor": 431817727,
                                   "WFWorkflowIconGlyphNumber": 59713},
                "WFWorkflowActions": self.actions,
                "WFWorkflowImportQuestions": self.questions}


def upload(b: Builder, file_ref, id_ref):
    # Do not calculate a digest from the temporary Record Audio output: hash the saved file.
    digest = b.add("hash", WFHashType="SHA256", WFInput=attachment(file_ref))
    url = b.add("gettext", WFTextActionText="")
    b.question(url, "WFTextActionText", "ThinkTape HTTPS base URL (no trailing slash). Example: https://example.invalid")
    key = b.add("gettext", WFTextActionText="")
    b.question(key, "WFTextActionText", "ThinkTape X-ThinkTape-Key. Paste privately on your iPhone; never put it in the public artifact.")
    request = b.add(
        "downloadurl", Advanced=True, WFHTTPMethod="POST", WFHTTPBodyType="Form",
        ShowHeaders=True,
        WFURL=text(output(url, "Text"), "/api/recordings"),
        WFHTTPHeaders=fields([field("X-ThinkTape-Key", text(output(key, "Text")))]),
        WFFormValues=fields([
            field("recording_id", text(id_ref)),
            field("audio", {"Value": attachment(file_ref),
                            "WFSerializationType": "WFTokenAttachmentParameterState"}, item_type=5),
        ]),
    )
    # Explicitly select a single dictionary value. Without this parameter,
    # newer Shortcuts builds import the action as an incomplete "Get
    # Dictionary Value" action and ask the user to configure its result mode
    # at runtime.
    stored = b.add("getvalueforkey", WFInput=attachment(output(request, "Contents of URL")),
                   WFDictionaryKey="stored", WFGetDictionaryValueType="Value")
    checked_id = b.add("getvalueforkey", WFInput=attachment(output(request, "Contents of URL")),
                       WFDictionaryKey="recording_id", WFGetDictionaryValueType="Value")
    checksum = b.add("getvalueforkey", WFInput=attachment(output(request, "Contents of URL")),
                      WFDictionaryKey="checksum", WFGetDictionaryValueType="Value")

    # All three tests are nested (logical AND), with the only Move inside the innermost branch.
    is_stored = b.start_if(output(stored, "Dictionary Value"), boolean=True)
    id_matches = b.start_if(output(checked_id, "Dictionary Value"), string=text(id_ref))
    sum_matches = b.start_if(output(checksum, "Dictionary Value"), string=text(output(digest, "Hash")))
    archive = b.add("file.move", WFFile=attachment(file_ref), WFReplaceExisting=False)
    b.question(archive, "WFFolder", "Choose On My iPhone / 录音 / 已上传 (archive; do not choose iCloud Drive).")
    b.note("ThinkTape: server confirmed stored, matching ID and matching SHA-256; archived original locally.")
    b.otherwise(sum_matches)
    b.note("ThinkTape: server checksum mismatch; original remains in 待上传. Inspect before retry.")
    b.end_if(sum_matches)
    b.otherwise(id_matches)
    b.note("ThinkTape: response ID mismatch; original remains in 待上传.")
    b.end_if(id_matches)
    b.otherwise(is_stored)
    b.note("ThinkTape: response did not confirm stored=true; original remains in 待上传.")
    b.end_if(is_stored)


def capture():
    b = Builder()
    b.add("comment", WFCommentActionText="Record -> save complete M4A locally -> POST saved file -> check stored, exact ID and SHA-256 -> move only on all matches. Install questions on iPhone. Never delete a recording.")
    recorded = b.add("recordaudio", WFRecordingStart="Immediately", WFRecordingEnd="On Tap",
                     WFRecordingCompression="Normal")
    date = b.add("date", WFDateActionMode="Current Date")
    stamp = b.add("format.date", WFDate=attachment(output(date, "Date")),
                  WFDateFormatStyle="Custom", WFDateFormat="yyyyMMdd-HHmmss",
                  WFTimeFormatStyle="None")
    # No Z: this is local wall-clock time. A twelve-digit Number interpolated
    # into Text can acquire locale grouping commas (123,456,789,012), yielding
    # an invalid recording ID. Four three-digit chunks cannot be grouped.
    chunks = [b.add("number.random", WFRandomNumberMinimum=100,
                    WFRandomNumberMaximum=999) for _ in range(4)]
    name = b.add("gettext", WFTextActionText=text(
        output(stamp, "Formatted Date"), "-",
        *(output(chunk, "Random Number") for chunk in chunks),
    ))
    renamed = b.add("setitemname", WFName=text(output(name, "Text"), ".m4a"),
                    WFInput=attachment(output(recorded, "Recorded Audio")))
    saved = b.add("documentpicker.save", WFInput=attachment(output(renamed, "Renamed Item")),
                  WFAskWhereToSave=False, WFSaveFileOverwrite=False,
                  WFFileDestinationPath=text(output(name, "Text"), ".m4a"))
    b.question(saved, "WFFolder", "Choose On My iPhone / 录音 / 待上传 (create in Files first; never iCloud Drive).")
    upload(b, output(saved, "Saved File"), output(name, "Text"))
    return b.workflow("ThinkTape 录音")


def retry():
    b = Builder()
    b.add("comment", WFCommentActionText="Manual retry: enumerate pending local files; retain original bytes; strip legacy number-grouping commas from filename ID; archive only on all three server checks. Non-M4A files are ignored.")
    pending = b.add("file.getfoldercontents", Recursive=False)
    b.question(pending, "WFFolder", "Choose On My iPhone / 录音 / 待上传 (the SAME folder as ThinkTape 录音).")
    group = uid()
    b.add("repeat.each", WFInput=attachment(output(pending, "Folder Contents")),
          GroupingIdentifier=group, WFControlFlowMode=0)
    item = variable("Repeat Item")
    extension = b.add("properties.files", WFInput=attachment(item), WFContentItemPropertyName="File Extension")
    correct_type = b.start_if(output(extension, "File Extension"), string="m4a")
    name = b.add("getitemname", WFInput=attachment(item))
    # The generated name has one dot before m4a. Split to re-use exactly its stable ID.
    split = b.add("text.split", text=attachment(output(name, "Name")),
                  WFTextSeparator="Custom", WFTextCustomSeparator=".")
    first = b.add("getitemfromlist", WFInput=attachment(output(split, "Split Text")),
                  WFItemSpecifier="First Item")
    # Earlier builds interpolated one large random Number, which iOS may
    # format with grouping commas. Repair only the *request ID*, not the
    # pending file or its bytes; retries still use a stable normalized ID.
    normalized = b.add("text.replace", WFInput=attachment(output(first, "Item from List")),
                       WFReplaceTextFind=",", WFReplaceTextReplace="",
                       WFReplaceTextRegularExpression=False)
    # A buggy earlier build omitted the date action mode and created names
    # such as `-665991610105.m4a`. Keep the original file and bytes, but make
    # the request ID valid and stable by prefixing only a leading hyphen.
    repaired = b.add("text.replace", WFInput=attachment(output(normalized, "Updated Text")),
                     WFReplaceTextFind="^-", WFReplaceTextReplace="iphone-",
                     WFReplaceTextRegularExpression=True)
    upload(b, item, output(repaired, "Updated Text"))
    b.end_if(correct_type)
    b.add("repeat.each", GroupingIdentifier=group, WFControlFlowMode=2)
    return b.workflow("ThinkTape 重试上传")


def verify(workflow):
    actions = workflow["WFWorkflowActions"]
    def names():
        return [a["WFWorkflowActionIdentifier"].removeprefix("is.workflow.actions.") for a in actions]
    n = names()
    assert n.count("downloadurl") == 1 and n.count("file.move") == 1
    assert n.index("documentpicker.save") < n.index("hash") < n.index("downloadurl") < n.index("file.move") if "documentpicker.save" in n else n.index("file.getfoldercontents") < n.index("hash") < n.index("downloadurl") < n.index("file.move")
    assert n.index("getvalueforkey") > n.index("downloadurl")
    # A move must only occur inside the stored, exact-ID, and checksum branches.
    active = []
    for action in actions:
        ident = action["WFWorkflowActionIdentifier"].removeprefix("is.workflow.actions.")
        params = action["WFWorkflowActionParameters"]
        if ident == "conditional":
            mode = params["WFControlFlowMode"]
            if mode == 0:
                active.append([params["GroupingIdentifier"], True])
            elif mode == 1:
                assert active[-1][0] == params["GroupingIdentifier"]
                active[-1][1] = False
            else:
                assert active[-1][0] == params["GroupingIdentifier"]
                active.pop()
        if ident == "file.move":
            assert len(active) == (4 if "repeat.each" in n else 3) and all(then for _, then in active)
            assert params["WFReplaceExisting"] is False
    assert not active
    request = actions[n.index("downloadurl")]["WFWorkflowActionParameters"]
    assert request["WFHTTPMethod"] == "POST" and request["WFHTTPBodyType"] == "Form"
    items = request["WFFormValues"]["Value"]["WFDictionaryFieldValueItems"]
    assert [(x["WFKey"]["Value"]["string"], x["WFItemType"]) for x in items] == [("recording_id", 0), ("audio", 5)]
    assert [actions[i]["WFWorkflowActionParameters"]["WFDictionaryKey"] for i in range(n.index("getvalueforkey"), n.index("getvalueforkey") + 3)] == ["stored", "recording_id", "checksum"]
    assert [actions[i]["WFWorkflowActionParameters"]["WFGetDictionaryValueType"] for i in range(n.index("getvalueforkey"), n.index("getvalueforkey") + 3)] == ["Value", "Value", "Value"]
    assert any(q["ParameterKey"] == "WFFolder" for q in workflow["WFWorkflowImportQuestions"])
    for q in workflow["WFWorkflowImportQuestions"]:
        assert q["ParameterKey"] not in actions[q["ActionIndex"]]["WFWorkflowActionParameters"] or actions[q["ActionIndex"]]["WFWorkflowActionParameters"][q["ParameterKey"]] == ""
    assert not any("http://" in str(a) or "https://" in str(a) and "example.invalid" not in str(a) for a in actions)
    all_ids = {a["WFWorkflowActionParameters"]["UUID"] for a in actions}
    assert len(all_ids) == len(actions)
    assert not any(x in str(workflow) for x in ("yyyyMMdd'T'HHmmss'Z'", "Content-Type: multipart/form-data"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sign", action="store_true", help="Run Apple's shortcuts sign --mode anyone")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    for slug, workflow in (("thinktape-record", capture()), ("thinktape-retry", retry())):
        verify(workflow)
        unsigned = OUT / (slug + ".unsigned.shortcut")
        unsigned.write_bytes(plistlib.dumps(workflow, fmt=plistlib.FMT_BINARY, sort_keys=True))
        assert plistlib.loads(unsigned.read_bytes()) == workflow
        print(f"{unsigned}: {len(workflow['WFWorkflowActions'])} actions, {len(workflow['WFWorkflowImportQuestions'])} import questions")
        if args.sign:
            signed = OUT / (slug + ".shortcut")
            subprocess.run(["/usr/bin/shortcuts", "sign", "--mode", "anyone", "--input",
                            str(unsigned), "--output", str(signed)], check=True)
            assert signed.is_file() and signed.stat().st_size > unsigned.stat().st_size
            print(f"{signed}: Apple-signed ({signed.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
