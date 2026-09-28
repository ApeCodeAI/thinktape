# iPhone durable recording capture

This is the operator guide for sending an iPhone recording to ThinkTape without losing the original when the network is unavailable.

The implementation is deliberately **save first, upload second**:

```text
Record audio
  -> save the original file to On My iPhone/录音/待上传/
  -> upload with the same recording_id
  -> move the file to On My iPhone/录音/已上传/ only after stored: true
```

The `待上传` copy is the recovery queue. A failed request must never delete it. The `已上传` copy is retained; it is not an upload backup unless the server has confirmed storage.

## Server contract

The recording API is part of the same ThinkTape application as the web UI and CLI. It is not a private fork or a second deployment-only implementation.

### Pair the phone once

An operator creates a device key through the authenticated pairing endpoint:

```http
POST /api/pair
Content-Type: application/json

{"name":"iphone"}
```

The response contains the device key. Store it in the iPhone Shortcut as a private value. **Never commit or publish the key.** Every remote API request must send it as:

```http
X-ThinkTape-Key: <device-key>
```

### Upload

```http
POST /api/recordings
Content-Type: multipart/form-data
X-ThinkTape-Key: <device-key>

recording_id=<stable-id>
audio=<complete .m4a file>
```

The response contains:

```json
{
  "recording_id": "20260928T211530Z-<uuid>",
  "item_id": "20260928-211530-ab12",
  "checksum": "sha256...",
  "byte_size": 12345,
  "stored": true,
  "transcription_status": "queued"
}
```

`stored: true` means that the complete audio has been verified and committed to ThinkTape's persistent asset store. It does **not** mean that transcription has finished.

The phone must reuse the same `recording_id` when retrying. Replaying the same bytes is idempotent; replaying different bytes with the same ID is rejected with `409`.

### Inspect and retry

```http
GET  /api/recordings/<recording_id>
POST /api/recordings/<recording_id>/retry
```

The server keeps the original audio if transcription fails. Transcription status is durable (`pending`, `queued`, `running`, `failed`, `completed`) and is recovered after a service restart with a bounded retry count.

## iPhone Files folders

Create these folders in **Files → On My iPhone**:

```text
录音/
├── 待上传/
└── 已上传/
```

Use a filename containing the recording ID, for example:

```text
20260928T211530Z-550e8400-e29b-41d4-a716-446655440000.m4a
```

The filename is the recovery handle. The retry Shortcut extracts the ID from the filename and sends the same ID again.

## Shortcut 1: `ThinkTape 录音`

Create this Shortcut on the iPhone. Action names can vary slightly with the iOS language; the order and branching are the important parts.

1. **Record Audio**. Use manual stop. Keep the returned audio as a variable named `Audio`.
2. **Get Current Date**. Format it as `yyyyMMdd'T'HHmmss'Z'`.
3. **Get UUID**. Combine date and UUID with a hyphen. This is `Recording ID`.
4. **Set Name** for `Audio` to `Recording ID.m4a`.
5. **Save File** to `On My iPhone/录音/待上传/`. Turn off **Ask Where to Save**. This is the first durable local-save point.
6. Show a notification such as `录音已保存，正在上传`.
7. **Get Contents of URL** for the ThinkTape URL plus `/api/recordings`:
   - Method: `POST`
   - Request body: `Form`
   - Form field `recording_id`: the `Recording ID` text
   - Form field `audio`: the saved file (not an in-memory recording variable)
   - Header `X-ThinkTape-Key`: the private device key
8. **Get Dictionary from Input** and read `stored`.
9. If `stored` is exactly `true`, **Move File** from `待上传` to `已上传`, then notify `已上传 ThinkTape`.
10. Otherwise, show `已保存，待上传` and do not move or delete the file.

The Move action must be after the server response check. If the request errors or times out, Shortcuts may stop immediately; that is safe because the file is already in `待上传`.

## Shortcut 2: `ThinkTape 补传录音`

1. Get files from `On My iPhone/录音/待上传/`.
2. Repeat with each file, in filename order.
3. Get the file name and remove `.m4a` to recover `Recording ID`.
4. POST the file and the same ID to `/api/recordings` with the same device key.
5. Read `stored` from the response.
6. Only when it is `true`, move the repeated file to `已上传/`.
7. If one request fails, leave the current file and the remaining files in `待上传/`; show a notification and stop or continue according to the chosen Shortcut behavior.

A Wi-Fi-connected, charger-connected, or scheduled personal automation may run this Shortcut once, but iOS background execution is not a guaranteed daemon. Keep the manual `补传录音` Shortcut.

## ThinkPad acceptance check

On ThinkPad, open the ThinkTape web URL and verify:

1. A new item appears after upload.
2. Its audio can be played from the item.
3. The placeholder changes to the local Whisper transcript, or the item shows a retryable transcription failure while the audio remains present.
4. Repeating the upload does not create a second item.
5. A deliberate offline upload leaves the file in `待上传/`; running `补传录音` after reconnecting moves it to `已上传/`.

The first physical test still requires the owner to grant iPhone microphone/files permissions, enter the device key in the Shortcut, and assign `ThinkTape 录音` to the iPhone Action Button. Those are device-local operations that cannot be verified from the Mac deployment host.
