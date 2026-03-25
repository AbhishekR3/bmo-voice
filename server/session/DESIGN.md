# Session Management & Conversation Mode — `server/session/`

## Purpose & Responsibilities

- Central orchestrator — coordinates all pipeline components
- Manage the conversation state machine (IDLE → LISTENING → PROCESSING → SPEAKING → CONVERSATION)
- Track conversation history (5-minute TTL)
- Handle WebSocket session lifecycle
- Manage mic muting during SPEAKING state
- Handle conversation mode follow-ups (30s window)
- Route events between all components

## State Machine

```
┌─────────────────┐
│      IDLE        │  Wake-word-only mode (~2% CPU)
│                  │  Only wake word detector is active
│                  │  VAD, audio pipeline: OFF
└────────┬─────────┘
         │ Wake word detected
         ▼
┌─────────────────┐
│    LISTENING     │  Audio pipeline active (noise gate → RNNoise → VAD)
│                  │  Recording and buffering audio
│                  │  Wake word still active (but detections ignored)
└────────┬─────────┘
         │ VAD: end-of-speech
         │ (or 5s timeout → IDLE)
         ▼
┌─────────────────┐
│   PROCESSING     │  STT → Intent Router → Context gathering → LLM
│                  │  Audio pipeline: OFF
│                  │  Mic: still open but not recording
└────────┬─────────┘
         │ First TTS audio ready
         │ (or error → play error clip → IDLE)
         ▼
┌─────────────────┐
│    SPEAKING      │  TTS → audio streaming to client
│                  │  *** MIC IS MUTED ***
│                  │  No audio input accepted whatsoever
│                  │  No wake word, no VAD, nothing
│                  │  User MUST wait for BMO to finish
└────────┬─────────┘
         │ TTS playback complete + 200ms reverb decay
         ▼
┌─────────────────┐
│  CONVERSATION    │  Listening WITHOUT wake word for 30s
│                  │  Audio pipeline: ON (noise gate → RNNoise → VAD)
│                  │  Wake word: active (always accepts "Hey Beemo")
│                  │  500ms min speech duration filter
│                  │
│                  │──→ Speech detected → PROCESSING
│                  │──→ 30s silence → IDLE
│                  │──→ "Hey Beemo" → LISTENING
└──────────────────┘
```

## State Transition Table

| From | To | Trigger | Action |
|---|---|---|---|
| IDLE | LISTENING | Wake word detected | Activate audio pipeline, start VAD |
| LISTENING | PROCESSING | VAD end-of-speech | Send audio buffer to STT |
| LISTENING | IDLE | 5s timeout (no speech) | Deactivate audio pipeline |
| PROCESSING | SPEAKING | First TTS audio ready | Mute mic, begin audio streaming |
| PROCESSING | IDLE | Pipeline error | Play error feedback clip, cleanup |
| SPEAKING | CONVERSATION | Playback complete | Unmute mic (after 200ms), start 30s timer |
| CONVERSATION | PROCESSING | Speech detected (500ms+) | Send audio to STT, reset timer |
| CONVERSATION | IDLE | 30s silence | Deactivate audio pipeline |
| CONVERSATION | LISTENING | "Hey Beemo" detected | Reset — treat as new activation |
| ANY | IDLE | Fatal error | Cleanup all resources, log error |
| ANY | IDLE | WebSocket disconnect | Cleanup session |

## Session State Model

```python
class SessionState(Enum):
    IDLE = "idle"
    LISTENING = "listening"
    PROCESSING = "processing"
    SPEAKING = "speaking"
    CONVERSATION = "conversation"

class Session:
    id: str
    websocket: WebSocket
    state: SessionState
    conversation_history: list[Message]    # pruned to 5-min TTL
    active_folders: list[str]             # folders registered for RAG
    current_task: asyncio.Task | None     # current pipeline run
    conversation_timer: Timer | None       # 30s conversation mode timeout
    user_preferences: UserPreferences      # name, location, units, timezone
    last_response_audio: bytes | None      # cached for "repeat that" (future)
    pipeline_start_time: float | None      # for latency tracking

class Message:
    role: str          # "user" or "assistant"
    content: str
    timestamp: float   # epoch seconds

class UserPreferences:
    name: str
    location: str
    timezone: str
    temp_units: str           # "fahrenheit" | "celsius"
    distance_units: str       # "miles" | "km"
    response_verbosity: str   # "brief" | "normal" | "detailed"
    custom_vocabulary: list[str]
```

## Pipeline Coordination

### What's Active Per State

| State | Wake Word | Audio Pipeline | STT | LLM | TTS | Mic |
|---|---|---|---|---|---|---|
| IDLE | ON | OFF | OFF | OFF | OFF | Open (wake word only) |
| LISTENING | ON (ignored) | ON | OFF | OFF | OFF | Open |
| PROCESSING | ON (ignored) | OFF | ON→OFF | ON | OFF | Open (idle) |
| SPEAKING | OFF | OFF | OFF | Finishing | ON | **MUTED** |
| CONVERSATION | ON | ON | OFF | OFF | OFF | Open |

### Full Pipeline Sequence (Happy Path)

```
1. IDLE: Wake word fires → transition to LISTENING
2. LISTENING: Audio pipeline processes frames → VAD detects end-of-speech
3. LISTENING → PROCESSING:
   a. Send clean audio buffer to STT
   b. STT returns transcript
   c. (Optional) STT verifies wake word in transcript
   d. Intent router classifies: general/rag/web_search/hybrid
   e. If web_search: immediately play "Hmm, let me search the internet"
   f. Gather context (RAG and/or web search, parallel if hybrid)
   g. Start 3s feedback timer
   h. Send context + transcript + history to LLM (streaming)
   i. LLM streams tokens → sentence buffer
4. PROCESSING → SPEAKING:
   a. First complete sentence ready → send to TTS
   b. Mute mic
   c. TTS synthesizes → audio chunks → WebSocket → client
   d. Pipeline parallel: TTS on sentence N while LLM generates N+1
   e. Cancel 3s timer if audio is flowing
5. SPEAKING → CONVERSATION:
   a. All TTS audio sent
   b. Wait 200ms for reverb decay
   c. Unmute mic
   d. Start 30s conversation timer
   e. Activate audio pipeline (VAD listening)
6. CONVERSATION:
   a. If speech detected (500ms+) → go to step 3 (PROCESSING)
   b. If 30s silence → IDLE
   c. If "Hey Beemo" → go to step 2 (LISTENING)
```

## Conversation Memory

- **Storage**: In-memory list of `Message` objects with timestamps
- **TTL**: 5 minutes — prune messages older than 5 minutes before each LLM call
- **No persistence**: Resets on server restart or after 5 minutes of silence
- **Typical capacity**: 5–15 turns depending on conversation pace
- **Cleared when**: 5-minute TTL expires, server restarts, or explicit reset

## Mic Muting Rules

**During SPEAKING state, the mic is FULLY MUTED.**

- No audio flows through the pipeline
- No wake word detection
- No VAD
- Nothing can interrupt BMO's response
- User must wait for BMO to finish speaking

**On playback complete:**
1. Wait 200ms for room reverb to decay
2. Unmute mic
3. Transition to CONVERSATION state
4. Audio pipeline activates

## Conversation Mode Rules

| Rule | Detail |
|---|---|
| Entry | After TTS playback completes |
| Duration | 30 seconds (configurable) |
| Timer reset | Each follow-up resets the 30s timer |
| Speech filter | 500ms minimum continuous speech to trigger processing |
| Wake word | "Hey Beemo" always works (resets to LISTENING) |
| Exit on silence | 30s with no speech → IDLE |
| Exit on disconnect | WebSocket drops → cleanup → no state |
| History cleared | After 5 minutes of no interaction |

## Interface with Other Components

| Direction | Component | Events/Data |
|---|---|---|
| **From** Wake Word | Detection event `{confidence, timestamp}` |
| **From** Audio Pipeline | `speech_start`, `speech_end` events + clean audio buffer |
| **To** STT | Clean audio buffer for transcription |
| **From** STT | Transcript text, wake word verification result |
| **To** LLM (Intent Router) | Transcript + conversation history + user preferences |
| **From** LLM | Intent classification, streaming token response |
| **To/From** RAG | Query → top-K chunks (when intent=rag/hybrid) |
| **To/From** Search | Query → search results (when intent=web_search/hybrid) |
| **To** TTS | Sentence strings for synthesis |
| **From** TTS | Audio chunks, playback complete signal |
| **To** WebSocket | Audio chunks, state change notifications, transcripts |
| **From** WebSocket | Raw audio from client, control messages |

## Configuration

```yaml
conversation:
  window_seconds: 30             # follow-up listening window
  ttl_seconds: 300               # 5-minute conversation history
  min_speech_duration_ms: 500    # minimum speech in conversation mode
  no_speech_timeout_seconds: 5   # timeout if no speech after wake word
  processing_timeout_seconds: 60 # max time in PROCESSING before error recovery

user:
  name: ""
  location: ""
  timezone: "auto"               # auto-detect from system
  temp_units: "fahrenheit"
  distance_units: "miles"
  response_verbosity: "normal"   # brief | normal | detailed
  custom_vocabulary: []          # names, technical terms for STT hints
```

## Logging

Logger name: **`bmo.session`**

| Level | Message | When |
|---|---|---|
| DEBUG | `Timer: conversation mode {25}s remaining` | Periodic |
| DEBUG | `Pipeline step: {step} started` | Internal pipeline |
| INFO | `State: {IDLE} → {LISTENING}` | Every state transition |
| INFO | `Session created: {id}` | New WebSocket connection |
| INFO | `Session ended: {id} (duration={300}s)` | WebSocket disconnect |
| INFO | `Conversation history pruned: removed {3} messages older than 5min` | Before LLM call |
| INFO | `Pipeline complete: total={1420}ms (stt={450}ms, intent={5}ms, context={30}ms, llm_ttft={280}ms, tts_ttfb={210}ms)` | End of pipeline |
| INFO | `Conversation mode: listening for follow-ups ({30}s)` | Entering CONVERSATION |
| INFO | `Conversation mode expired → IDLE` | 30s timeout |
| WARNING | `Pipeline error: {error} — returning to IDLE` | Recoverable error |
| WARNING | `Processing timeout ({60}s) — forcing IDLE` | Stuck pipeline |
| ERROR | `Fatal session error: {error}` | Unrecoverable |

## Health Checks

Session manager itself has no model to load, but it coordinates startup health checks for all components:

```
Startup sequence:
1. Load all models in PARALLEL (threads):
   - OpenWakeWord (wake/)
   - Silero VAD (audio/)
   - RNNoise (audio/)
   - whisper.cpp (stt/)
   - Kokoro TTS (tts/)
   - BGE-small-en (rag/)
   - ChromaDB (rag/)

2. Run health checks for each (parallel):
   - Wake word: silence test
   - VAD: silence + speech test
   - RNNoise: frame test
   - STT: inference test ("hello")
   - TTS: inference test ("Hello, I am BMO") + pre-generate feedback clips
   - RAG: embedding test + DB open

3. Check external services:
   - Ollama: GET /api/tags, model available, test prompt
   - Brave Search: test query (warn if fails, don't block)
   - SearXNG: GET / (warn if fails, don't block)

4. ANY required check fails → BMO REFUSES TO START
   - Print which component failed
   - Print how to fix (download model, start Ollama, etc.)

5. Optional checks (Brave, SearXNG) → warn but continue
```

## Error Recovery

| Error | Recovery |
|---|---|
| Component error during PROCESSING | Play error feedback clip → IDLE |
| Ollama drops mid-generation | Play "Sorry, I had a problem" → IDLE |
| WebSocket disconnects | Cancel pipeline, cleanup session |
| State stuck >60s in PROCESSING | Timeout → error recovery → IDLE |
| STT returns empty 3x in a row | Log warning, continue operating |
| TTS fails on one sentence | Skip sentence, continue with next |

## Edge Cases

| Scenario | Handling |
|---|---|
| Background noise in conversation mode | 500ms min speech filter |
| User talking to someone else | 30s window limits exposure |
| User walks away | 30s timeout → IDLE |
| "Hey Beemo, never mind" | Detect dismiss phrases → IDLE |
| Concurrent requests | One session at a time, reject second connection |
| WebSocket disconnect mid-pipeline | Cancel all tasks, cleanup |
| Very long silence in LISTENING | 5s timeout → IDLE |

## macOS Considerations

- **`launchd` for auto-start**: Session manager is the main process that `launchd` would manage as a daemon
- **Process management**: Use `asyncio` for all coordination — single process, multiple async tasks
- **Signal handling**: Handle SIGTERM/SIGINT gracefully — cleanup sessions, stop models
- **Memory monitoring**: Track total process RSS; if approaching system limits, log warnings (future: backlog B-17 for graceful degradation)

## Relation to Other Components

- **Central hub**: Every component communicates through session manager
- **Depends on**: All components (wake, audio, STT, LLM, TTS, RAG, search, WebSocket)
- **Depended on by**: All components (provides state context, routing, lifecycle)
- **Coordinates**: Startup (parallel model loading), runtime (pipeline sequencing), shutdown (cleanup)
