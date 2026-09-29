# iPhone durable recording capture

The two **signed** Shortcuts built from `scripts/build_iphone_shortcuts.py` are:

- [`shortcuts/thinktape-record.shortcut`](shortcuts/thinktape-record.shortcut) — `ThinkTape 录音`, for the Action Button.
- [`shortcuts/thinktape-retry.shortcut`](shortcuts/thinktape-retry.shortcut) — `ThinkTape 重试上传`, run manually after reconnecting.

They are in this one public repository. The unsigned `.unsigned.shortcut` sources alongside them are generated for inspection and re-signing. Rebuild on a Mac with `python3 scripts/build_iphone_shortcuts.py --sign` (Apple's `/usr/bin/shortcuts sign --mode anyone`). **Signing and structural checks on macOS do not prove iPhone import or execution.** Physical iPhone testing remains required; specifically, confirm import questions correctly populate each File/Folder picker and inspect the resulting actions before recording anything important.

## What the pair does

```text
Record Audio (Immediately; stop On Tap; Normal-quality M4A)
  → ID = local yyyyMMdd-HHmmss + '-' + 12-digit random number (no false UTC Z)
  → Set Name to ID.m4a
  → Save complete file to Files / On My iPhone / 录音 / 待上传 (no overwrite)
  → hash the saved file with SHA-256
  → POST saved file and same ID as multipart form to /api/recordings
  → require stored == true AND response recording_id == ID AND response checksum == local SHA-256
  → only then Move File to On My iPhone / 录音 / 已上传 (no overwrite)
```

The manual retry enumerates files in `待上传`, ignores non-M4A files, recovers a stable ID from each filename (removing legacy grouping commas), then performs the same hash, upload and three checks. It **never creates a fresh random recording ID for an existing file**. Each file is moved only after confirmation; neither Shortcut has a Delete File action. A request error or timeout may stop the Shortcut; files already saved remain in `待上传`. If one retry fails, later items may not be attempted in that run; run it again after fixing the cause.

The ID uses a local `yyyyMMdd-HHmmss` timestamp plus a twelve-digit random suffix built from four three-digit random chunks, **not a UUID**. The Date action explicitly uses **Current Date**. A single twelve-digit random Number can gain locale grouping commas when inserted into Shortcuts Text, making the ID invalid. The local timestamp must not be represented with a `Z` (which denotes UTC). Example: `20260929-211530-123456789012.m4a`. The retry action splits the generated filename at the dot to recover `recording_id`; it removes grouping commas and prefixes legacy IDs that start with `-` with `iphone-`, without modifying the original file or its bytes. Do not rename pending files or put unrelated M4A files in this folder.

`stored: true` means the asset is committed to ThinkTape's persistent store, **not** that transcription is done. The server checks repeated uploads with the same ID and bytes idempotently, and rejects a different file under the same ID with HTTP 409. The API also returns `checksum` (SHA-256 of the stored audio). The Shortcuts compare that value to the saved local file's hash before archiving. Missing or mismatched fields leave the original in `待上传`.

## Import and configure on the iPhone

1. In **Files → On My iPhone**, create `录音/待上传` and `录音/已上传`. Do not use iCloud Drive for the pending folder.
2. Provision the first phone key **on the trusted host** with `thinktape pair --name iphone-action-button`, or reuse an existing privately provisioned phone key. `POST /api/pair` requires an existing key and cannot bootstrap access. Transfer the key to the iPhone privately; never paste it or the private URL into a public issue or repository. The header is `X-ThinkTape-Key`. The public signed shortcuts contain only blank prompts.
3. Download each **signed** `.shortcut` file to the iPhone and import both in Shortcuts. For **each** import, answer the four setup questions:
   - Select the appropriate `WFFolder` for `待上传` (record: **Save File**; retry: **Get Contents of Folder**).
   - Enter the ThinkTape **HTTPS base URL with no trailing slash**, excluding `/api/recordings` (both shortcuts). The latter path is appended automatically.
   - Enter the device key (both shortcuts). These answers live in the personal imported copies; the published files have empty URL and key fields.
   - Select the `WFFolder` for **Move File**: `On My iPhone/录音/已上传` (both shortcuts).
4. **Before using the Action Button**, open each imported Shortcut in the editor and verify those folder, URL and key values resolved into their intended action fields. Check Form field `audio` is a **File** magic variable from the saved file / Repeat Item, not text; Form field `recording_id` is text; no hand-written multipart `Content-Type` header is present. Confirm that **Move File** is nested inside all three `If` checks and has overwrite disabled. If an import question does not populate a Folder picker on your iOS version, select that picker manually in the editor; do not run it with a blank destination.
5. Allow microphone, Files and network permissions when requested. Assign `ThinkTape 录音` to the iPhone Action Button, then make a **short throwaway recording**. Stop it manually, verify the actual `.m4a` exists locally, then check the response/archive. Run `ThinkTape 重试上传` manually after an offline test. Do not rely on iOS background automation as a guaranteed retry daemon.

**Import gate:** macOS signing and static structure checks succeeded, but this Mac could not inspect the Shortcuts import GUI because Accessibility/Screen Recording permission is pending. Folder-question resolution and executable behavior are **not yet verified** on iPhone. Until verified there, treat these as signed candidate artifacts, not a proven one-tap capture system. The three **Get Dictionary Value** actions explicitly select `Value` and the keys `stored`, `recording_id`, and `checksum`; an earlier candidate omitted the value-mode parameter and could ask for a value at runtime. It also omitted the Date action mode, which produced a filename such as `-665991610105.m4a` and caused HTTP 422 `invalid recording_id`. The corrected retry shortcut normalizes only the ID sent to the server, then checks the receipt against that normalized ID and the original file hash; the original file remains unchanged.

## Server contract

```http
POST /api/recordings
X-ThinkTape-Key: <device-key>
Content-Type: multipart/form-data  (automatically generated by Shortcuts)

recording_id=<filename without .m4a>
audio=<saved complete .m4a file>
```

Response fields include `recording_id`, `checksum`, `byte_size`, `stored`, `item_id`, and `transcription_status`. The server also supports `GET /api/recordings/<recording_id>` and `POST /api/recordings/<recording_id>/retry` for inspection/retrying transcription, which are different from the phone's manual upload retry.

## Acceptance check on the phone and server

1. Normal capture: a local `.m4a` is created in `待上传` **before network upload**. The resulting item appears in ThinkTape; only after matching stored, ID and SHA-256 does the file move to `已上传`. The file remains on the iPhone in that archive folder.
2. Offline capture: after manual stop, the recording remains in `待上传`. Reconnect and manually run `ThinkTape 重试上传`; the **same** filename/ID moves to `已上传` on success, without creating a second server item.
3. Mismatched ID/checksum, failed auth, 409, timeout, or absent `stored`: file stays in `待上传`; diagnose without deleting or overwriting it.
4. Play the server-side audio and check transcription or its retryable failure state. Successful file upload does not imply successful transcription.

No physical iPhone test, permissions, folder bookmark resolution, or live service write was performed during artifact generation.
