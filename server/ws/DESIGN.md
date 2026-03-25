# WebSocket Protocol & Handler — `server/ws/`

## Purpose & Responsibilities

- Define the WebSocket message protocol between client and server
- Handle bidirectional audio streaming (mic audio in, TTS audio out)
- Send state change notifications, transcripts, and status updates to client
- Manage connection lifecycle (connect, disconnect, reconnect)
- Route incoming messages to appropriate components

## Architecture

```
Browser (Client)
    │
    │  ws://localhost:8000/ws
    │
    ▼
┌──────────────────────────────────────────────────────────┐
│  WebSocket Handler                                        │
│                                                           │
│  ┌─────────────────────────────────────────────────────┐  │
│  │  Message Router                                      │  │
│  │                                                      │  │
│  │  Binary messages ──→ Audio Pipeline (raw PCM)        │  │
│  │  JSON messages   ──→ Parse type → route:             │  │
│  │    audio_config  ──→ Negotiate audio format           │  │
│  │    folder_*      ──→ RAG Engine (folder management)   │  │
│  │    config_update ──→ Session (user preferences)       │  │
│  └─────────────────────────────────────────────────────┘  │
│                                                           │
│  ┌─────────────────────────────────────────────────────┐  │
│  │  Outbound Sender                                     │  │
│  │                                                      │  │
│  │  Session state changes ──→ JSON to client             │  │
│  │  STT transcripts       ──→ JSON to client             │  │
│  │  LLM response text     ──→ JSON to client (streaming) │  │
│  │  TTS audio chunks      ──→ Binary to client           │  │
│  │  Health/error/timer    ──→ JSON to client             │  │
│  └─────────────────────────────────────────────────────┘  │
│                                                           │
└──────────────────────────────────────────────────────────┘
```

## Protocol Specification

### Transport

- **URL**: `ws://localhost:8000/ws`
- **Binary messages**: Always audio (PCM frames)
- **Text messages**: Always JSON with a `type` field

### Audio Format

```
Sample rate:  16000 Hz (16kHz)
Bit depth:    16-bit signed integer
Channels:     1 (mono)
Encoding:     Little-endian (pcm_s16le)
Frame size:   Flexible (typically 640 samples = 40ms at 16kHz)
```

### Message Types: Client → Server

#### Binary: Audio Frames
Raw PCM audio from client microphone. Sent continuously while in LISTENING or CONVERSATION state. No framing header — all binary messages are audio.

#### `audio_config` — Audio Format Negotiation
Sent once at connection start.
```json
{
  "type": "audio_config",
  "sample_rate": 16000,
  "channels": 1,
  "format": "pcm_s16le"
}
```

#### `folder_add` — Register RAG Folder
```json
{
  "type": "folder_add",
  "path": "/Users/me/Documents/notes",
  "name": "My Notes"
}
```

#### `folder_remove` — Unregister RAG Folder
```json
{
  "type": "folder_remove",
  "path": "/Users/me/Documents/notes"
}
```

#### `folder_list` — Request Folder Status
```json
{
  "type": "folder_list"
}
```

#### `config_update` — Update User Preference
```json
{
  "type": "config_update",
  "key": "user.name",
  "value": "Alex"
}
```
Supported keys: `user.name`, `user.location`, `user.timezone`, `user.temp_units`, `user.distance_units`, `user.response_verbosity`.

### Message Types: Server → Client

#### Binary: Audio Frames
TTS audio for playback. Sent between `audio_start` and `audio_end` JSON messages. Same format as client audio (16kHz, 16-bit, mono, LE).

#### `state` — Session State Change
Sent on every state transition.
```json
{
  "type": "state",
  "state": "idle",
  "timestamp": 1711382400000
}
```
States: `"idle"`, `"listening"`, `"processing"`, `"speaking"`, `"conversation"`

#### `transcript` — User Speech Transcript
Sent after STT completes.
```json
{
  "type": "transcript",
  "text": "What's the weather today?",
  "is_final": true
}
```

#### `response_text` — BMO's Response (Streaming)
Sent as LLM generates tokens. Allows client to display response text in real-time.
```json
{
  "type": "response_text",
  "text": "It's partly cloudy with a high of 85",
  "is_final": false
}
```
`is_final: true` on the last chunk.

#### `audio_start` / `audio_end` — Audio Stream Bookends
```json
{"type": "audio_start"}
```
Binary audio frames follow between these two messages.
```json
{"type": "audio_end"}
```
Client: on `audio_start` → begin buffering/playing. On `audio_end` → playback complete.

#### `error` — Error Notification
```json
{
  "type": "error",
  "message": "Ollama connection lost",
  "recoverable": true
}
```

#### `health` — System Health Status
Sent at connection start and optionally on change.
```json
{
  "type": "health",
  "components": {
    "wake": "ok",
    "audio": "ok",
    "stt": "ok",
    "llm": "ok",
    "tts": "ok",
    "rag": "ok",
    "search": "unavailable"
  }
}
```
Values: `"ok"`, `"degraded"`, `"unavailable"`, `"error"`

#### `folders` — Folder Status Response
Response to `folder_list` or after `folder_add`/`folder_remove`.
```json
{
  "type": "folders",
  "folders": [
    {
      "path": "/Users/me/Documents/notes",
      "name": "My Notes",
      "status": "indexed",
      "files": 45,
      "chunks": 1230
    }
  ]
}
```
Status: `"indexing"`, `"indexed"`, `"error"`

#### `conversation_timer` — Conversation Mode Countdown
Sent every 5 seconds during CONVERSATION state and on reset.
```json
{
  "type": "conversation_timer",
  "seconds_remaining": 25
}
```

## Connection Lifecycle

```
1. Client opens WebSocket → ws://localhost:8000/ws

2. Server accepts → sends:
   {"type": "health", "components": {...}}
   {"type": "state", "state": "idle", "timestamp": ...}

3. Client sends:
   {"type": "audio_config", "sample_rate": 16000, "channels": 1, "format": "pcm_s16le"}

4. Bidirectional streaming begins
   - Client sends binary audio frames
   - Server sends JSON state/transcript/response messages
   - Server sends binary audio frames between audio_start/audio_end

5. Client disconnects → Server cleans up session
```

### Reconnection

Client should implement exponential backoff: 1s → 2s → 4s → 8s → max 30s. On reconnect, server creates a fresh session (conversation history is lost).

## Audio Streaming Details

### Client → Server (Mic Audio)

```
Client AudioWorklet captures mic → Float32 → convert to Int16 PCM
    → send binary frames over WebSocket
    → Server receives → routes to audio pipeline (when LISTENING/CONVERSATION)
    → Server discards audio when not in LISTENING/CONVERSATION state
```

### Server → Client (TTS Audio)

```
TTS generates PCM audio
    → Server sends {"type": "audio_start"}
    → Server sends binary PCM frames (one per TTS sentence chunk)
    → Server sends {"type": "audio_end"}
    → Client buffers 100-200ms then begins playback
```

## Single-Client Design

BMO supports **one client connection at a time**. If a second client connects, the server rejects it with a close frame:

```json
{"type": "error", "message": "Another client is already connected", "recoverable": false}
```

Then closes the WebSocket with code 4000.

## Interface with Other Components

| Direction | Component | Data |
|---|---|---|
| **Receives from** | Client | Binary audio frames, JSON control messages |
| **Sends to** | Client | Binary TTS audio, JSON state/transcript/error |
| **Routes to** | Session Manager | All incoming audio and control messages |
| **Routes to** | Audio Pipeline | Raw PCM audio frames |
| **Routes to** | RAG Engine | Folder management commands |
| **Receives from** | Session Manager | State changes, pipeline results |
| **Receives from** | TTS | Audio chunks for delivery |

## Server Configuration

```yaml
server:
  host: "127.0.0.1"    # localhost only by default
  port: 8000
  ws_path: "/ws"
  max_message_size: 1048576   # 1MB max message
```

For LAN access (future — backlog B-15): change host to `"0.0.0.0"` and add authentication.

## Logging

Logger name: **`bmo.ws`**

| Level | Message | When |
|---|---|---|
| DEBUG | `Audio frame received: {640} samples` | Per-frame (debug only) |
| DEBUG | `JSON received: type={folder_list}` | Per-message |
| INFO | `Client connected: {addr}` | Connection open |
| INFO | `Client disconnected: {addr} (duration={120}s)` | Connection close |
| INFO | `Audio config: {16000}Hz {1}ch {pcm_s16le}` | Format negotiation |
| INFO | `Sending state: {listening}` | State notification |
| WARNING | `Client audio gap >{500}ms — possible network issue` | Audio dropout |
| WARNING | `WebSocket send backpressure — client may be slow` | Slow consumer |
| WARNING | `Rejected second client connection from {addr}` | Multi-client attempt |
| ERROR | `WebSocket error: {error}` | Connection error |
| ERROR | `Invalid message: {preview}` | Malformed message |

## Security

- **Local-only by default**: Binds to `127.0.0.1`, not `0.0.0.0`
- **No authentication**: Single-user, local machine — no auth needed
- **No TLS**: Local connection, no encryption needed (add for LAN access)
- **Message size limit**: Reject messages > 1MB
- **No audio persistence**: Audio frames are processed in-memory only, never written to disk
- **Future (B-15)**: Add token-based auth and TLS for mobile/LAN access

## Edge Cases

| Scenario | Handling |
|---|---|
| Client disconnects mid-pipeline | Cancel current pipeline task, cleanup session |
| Slow client (backpressure) | Buffer up to 5s of outbound audio, then drop oldest |
| Second client connects | Reject with error, close with code 4000 |
| Invalid JSON message | Log warning, ignore, don't crash |
| Message > 1MB | Reject, log warning |
| Client sends audio during SPEAKING | Discard silently (mic is conceptually muted) |
| Network latency spike | Audio buffering on client side handles small spikes |

## macOS Considerations

- **Localhost binding**: Works without firewall rules or special permissions
- **Port 8000**: Standard unprivileged port, no root needed
- **If binding to 0.0.0.0** (future): macOS firewall will prompt "allow incoming connections"
- **Browser connection**: Client connects from `http://localhost:3000` (Vite dev) or same-origin in production

## Relation to Other Components

- **Entry point**: All client communication flows through WebSocket handler
- **Upstream**: Client (browser)
- **Downstream**: Routes messages to session manager, audio pipeline, RAG engine
- **Receives from**: Session manager (state changes), TTS (audio chunks), STT (transcripts), LLM (response text)
- **Depends on**: FastAPI (server framework), session manager
- **Depended on by**: Client (sole communication channel)
