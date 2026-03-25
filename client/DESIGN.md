# Web UI Client — `client/`

## Purpose & Responsibilities

- Capture microphone audio and stream to server via WebSocket
- Play back TTS audio from server in real-time
- Display current state (idle / listening / processing / speaking / conversation)
- Show live transcripts (user speech + BMO response)
- Manage RAG folders (add/remove, view index status)
- Configure user preferences (name, location, units)

**This is NOT a chat app.** It's a voice-only interface with minimal visual status indicators.

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│                    Web UI (React + TypeScript)             │
│                                                           │
│  ┌────────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │  VoiceStatus   │  │  Transcript  │  │  Settings    │  │
│  │                │  │              │  │  Panel       │  │
│  │  State dot +   │  │  User speech │  │  Folders +   │  │
│  │  label +       │  │  BMO reply   │  │  Preferences │  │
│  │  timer         │  │  (streaming) │  │              │  │
│  └────────────────┘  └──────────────┘  └──────────────┘  │
│                                                           │
│  ┌──────────────────────────────────────────────────────┐ │
│  │                  Audio Engine                         │ │
│  │                                                       │ │
│  │  ┌──────────────────┐    ┌──────────────────────┐    │ │
│  │  │  AudioWorklet    │    │  Audio Player         │    │ │
│  │  │  (mic capture)   │    │  (streaming playback) │    │ │
│  │  │                  │    │                       │    │ │
│  │  │  Float32 → Int16 │    │  Int16 → Float32     │    │ │
│  │  │  PCM frames out  │    │  Buffer + play       │    │ │
│  │  └────────┬─────────┘    └───────────▲───────────┘    │ │
│  └───────────┼──────────────────────────┼────────────────┘ │
│              │      WebSocket           │                  │
└──────────────┼──────────────────────────┼──────────────────┘
               │  ws://localhost:8000/ws   │
               ▼                          │
        [Server: raw audio in]    [Server: TTS audio out]
```

## Technology Stack

| Technology | License | Purpose |
|---|---|---|
| React | MIT | Component-based UI |
| TypeScript | Apache 2.0 | Type safety |
| Vite | MIT | Fast dev server + build |
| Tailwind CSS | MIT | Minimal styling |
| Web Audio API | Browser native | Mic capture + audio playback |
| AudioWorklet | Browser native | Dedicated audio processing thread |

No additional audio libraries needed — Web Audio API handles everything.

## Audio Capture (Mic → Server)

### getUserMedia Configuration

```typescript
navigator.mediaDevices.getUserMedia({
  audio: {
    echoCancellation: false,    // server handles echo (mic muting)
    noiseSuppression: false,    // server handles noise (RNNoise)
    autoGainControl: false,     // raw audio for server processing
    sampleRate: 16000,
    channelCount: 1
  }
})
```

**All browser audio processing disabled** — the server's audio pipeline (RNNoise, VAD) handles noise and echo. Sending raw audio gives the server maximum control.

### AudioWorklet Pipeline

```
Mic → MediaStreamSource → AudioWorklet → WebSocket
```

1. AudioWorklet processor runs in dedicated thread
2. Receives Float32 audio frames from mic
3. Converts Float32 → Int16 PCM (16kHz, mono)
4. Posts binary data to main thread
5. Main thread sends binary frames over WebSocket

**When server state = SPEAKING**: Stop sending audio frames (mic conceptually muted on client side too).

## Audio Playback (Server → Speaker)

```
WebSocket → {"type": "audio_start"} → begin buffering
         → binary PCM frames → decode Int16 → Float32 → AudioBuffer queue
         → {"type": "audio_end"} → mark complete
```

### Playback Strategy

1. On `audio_start`: initialize playback buffer
2. Accumulate **100–200ms of audio** before starting playback (prevents gaps from network jitter)
3. Use `AudioBufferSourceNode` for each chunk — schedule sequentially for gapless playback
4. On `audio_end`: signal playback complete
5. Use `AudioContext.currentTime` for precise scheduling

## Components

### VoiceStatus

Visual indicator of BMO's current state:

| State | Visual | Label |
|---|---|---|
| idle | Dim gray dot | "Ready" |
| listening | Pulsing green dot | "Listening..." |
| processing | Pulsing yellow dot | "Thinking..." |
| speaking | Pulsing blue dot | "Speaking..." |
| conversation | Steady green dot + timer | "Listening... (25s)" |

Conversation mode shows countdown from `conversation_timer` server messages.

### Transcript

- **User speech**: Displayed from `transcript` server messages (left-aligned or prefixed "You:")
- **BMO response**: Streamed from `response_text` messages (right-aligned or prefixed "BMO:")
- Auto-scrolls to bottom
- Clears when conversation history expires (5 min of inactivity)
- Simple alternating display — not a full chat interface

### Settings Panel

Collapsible panel with two sections:

**Folder Manager:**
- Text input for folder path + display name
- "Add" button → sends `folder_add` message
- List of registered folders with status (indexing/indexed), file count, chunk count
- "Remove" button per folder → sends `folder_remove` message

**User Preferences:**
- Name (text input)
- Location (text input)
- Timezone (dropdown or auto-detect)
- Temperature units (toggle: F/C)
- Distance units (toggle: miles/km)
- Changes send `config_update` messages
- Cache in localStorage (server is source of truth)

## React Hooks

### `useWebSocket`

```typescript
function useWebSocket(url: string) {
  // Connect to ws://localhost:8000/ws
  // Handle binary messages (audio) vs JSON messages (control)
  // Auto-reconnect with exponential backoff: 1s → 2s → 4s → max 30s
  // Expose: sendBinary(), sendJSON(), lastMessage, connectionStatus
}
```

### `useAudioCapture`

```typescript
function useAudioCapture(ws: WebSocket, serverState: SessionState) {
  // Initialize AudioContext + AudioWorklet
  // Request mic permission
  // Start/stop capture based on server state
  // Convert Float32 → Int16 PCM in AudioWorklet
  // Send binary frames via WebSocket
  // Stop sending during SPEAKING state
}
```

### `useAudioPlayer`

```typescript
function useAudioPlayer(ws: WebSocket) {
  // Listen for audio_start/audio_end messages
  // Queue incoming binary PCM frames
  // Buffer 100-200ms before starting playback
  // Schedule AudioBufferSourceNode for gapless playback
  // Signal when playback completes
}
```

## TypeScript Protocol Types

```typescript
// Session states
type SessionState = "idle" | "listening" | "processing" | "speaking" | "conversation";

// Server → Client messages
type ServerMessage =
  | { type: "state"; state: SessionState; timestamp: number }
  | { type: "transcript"; text: string; is_final: boolean }
  | { type: "response_text"; text: string; is_final: boolean }
  | { type: "audio_start" }
  | { type: "audio_end" }
  | { type: "error"; message: string; recoverable: boolean }
  | { type: "health"; components: Record<string, "ok" | "degraded" | "unavailable" | "error"> }
  | { type: "folders"; folders: FolderInfo[] }
  | { type: "conversation_timer"; seconds_remaining: number };

// Client → Server messages
type ClientMessage =
  | { type: "audio_config"; sample_rate: number; channels: number; format: string }
  | { type: "folder_add"; path: string; name: string }
  | { type: "folder_remove"; path: string }
  | { type: "folder_list" }
  | { type: "config_update"; key: string; value: string };

// Folder info
interface FolderInfo {
  path: string;
  name: string;
  status: "indexing" | "indexed" | "error";
  files: number;
  chunks: number;
}
```

## Interface with Other Components

| Direction | Component | Channel |
|---|---|---|
| **To/From** | Server (all components) | Single WebSocket connection |
| **No direct access** | Any server component | Everything mediated by WS protocol |

The client knows nothing about the server's internal architecture. It only speaks the WebSocket protocol defined in [server/ws/DESIGN.md](../server/ws/DESIGN.md).

## Configuration

```typescript
const config = {
  serverUrl: "ws://localhost:8000/ws",   // configurable via env
  audio: {
    sampleRate: 16000,
    channels: 1,
    format: "pcm_s16le",
    playbackBufferMs: 150,               // buffer before playback starts
  },
  reconnect: {
    initialDelayMs: 1000,
    maxDelayMs: 30000,
    backoffMultiplier: 2,
  },
};
```

## Logging

Browser console with `[BMO]` prefix:

| Level | Message | When |
|---|---|---|
| debug | `[BMO] Audio frame: {640} samples sent` | Per-frame (verbose) |
| info | `[BMO] Connected to server` | WebSocket open |
| info | `[BMO] Disconnected from server` | WebSocket close |
| info | `[BMO] State: {listening}` | State change received |
| info | `[BMO] Mic permission granted` | getUserMedia success |
| info | `[BMO] Audio playback started` | audio_start received |
| info | `[BMO] Audio playback complete` | audio_end + buffer drained |
| warn | `[BMO] Reconnecting (attempt {3})` | Auto-reconnect |
| warn | `[BMO] Audio playback gap detected` | Buffer underrun |
| error | `[BMO] Mic permission denied` | getUserMedia rejected |
| error | `[BMO] WebSocket error: {error}` | Connection error |
| error | `[BMO] Server error: {message}` | Error message from server |

## Edge Cases

| Scenario | Handling |
|---|---|
| Mic permission denied | Show clear UI message, disable voice features, suggest fix |
| WebSocket disconnect | Show "Disconnected" status, auto-reconnect with backoff |
| Browser tab backgrounded | AudioContext may suspend — resume on focus with `audioContext.resume()` |
| Safari AudioContext | Requires user gesture (click) to start — show "Click to activate" |
| Audio playback underrun | Buffer more aggressively (increase to 200ms), accept slight latency |
| Multiple tabs open | Only one tab captures mic (browser handles this) |
| Server not running | Show "Cannot connect" with retry, suggest starting server |
| Slow network (LAN future) | Increase playback buffer, show latency warning |

## Project Structure

```
client/
├── package.json
├── tsconfig.json
├── vite.config.ts
├── tailwind.config.ts
├── index.html
├── DESIGN.md                     ← you are here
├── public/
│   └── audio-worklet.js          # AudioWorklet processor (runs in dedicated thread)
├── src/
│   ├── main.tsx                  # Entry point
│   ├── App.tsx                   # Root component, WebSocket provider
│   ├── components/
│   │   ├── VoiceStatus.tsx       # State indicator (dot + label + timer)
│   │   ├── Transcript.tsx        # Live transcript display
│   │   └── Settings.tsx          # Folder manager + user preferences
│   ├── hooks/
│   │   ├── useWebSocket.ts       # WebSocket connection + reconnect
│   │   ├── useAudioCapture.ts    # Mic capture via AudioWorklet
│   │   └── useAudioPlayer.ts     # Streaming audio playback
│   └── lib/
│       └── protocol.ts           # Message type definitions (shared types)
└── DESIGN.md
```

## macOS Considerations

- **Browser choice**: Chrome recommended (best AudioWorklet + Web Audio API support)
- **Safari quirks**: AudioContext requires user gesture to start; AEC quality varies
- **Mic permission**: Browser asks separately from macOS system permission — both must be granted
  - macOS: System Settings > Privacy & Security > Microphone > allow browser
  - Browser: allow mic access when prompted
- **No native macOS APIs**: Pure web standards — works in any modern browser
- **Audio output**: Uses system default audio output device (configurable in macOS Sound settings)

## Relation to Other Components

- **Sole interface**: Only component the user directly interacts with
- **Communicates with**: Server exclusively via WebSocket protocol
- **Depends on**: Server running and accessible at configured URL
- **Depended on by**: Nothing — the server operates independently
- **Protocol defined in**: [server/ws/DESIGN.md](../server/ws/DESIGN.md)
