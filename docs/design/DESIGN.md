# BMO Voice — System Design

> The overall system design document. Each component has its own detailed DESIGN.md in its folder.
> BMO is pronounced "Beemo" (like the Adventure Time character).

---

## 1. Vision & Constraints

A fully free, open-source, low-latency voice assistant activated by the wake word **"Hey Beemo"**. It can:

1. Answer general questions using a local LLM
2. Perform RAG against user-specified local folders (documents, code, notes)
3. Search the web for up-to-date information
4. Seamlessly blend all three knowledge sources in conversation
5. Hold natural back-and-forth conversations with follow-ups

### Constraints

| Constraint | Detail |
|---|---|
| **Free** | Zero ongoing cost. No paid APIs. All models run locally or use free-tier APIs with documented fallbacks. |
| **Open source** | Every component must be open source or have an open-source alternative. |
| **English only** | All models optimized for English. No multi-language overhead. |
| **Voice-only** | Primary interaction is speak → listen. Minimal visual UI (status indicators only). |
| **Conversation mode** | After BMO responds, it listens for follow-ups without wake word for 30s (configurable). Conversation history has 5-minute TTL. |
| **No barge-in** | BMO does not listen while speaking. Mic is muted during playback. User must wait for BMO to finish. |
| **Audio privacy** | No audio is ever saved to disk. All audio processed in-memory only. |
| **Hardware** | Dev: MacBook Pro M1 Pro 32GB. Deploy: Mac Studio M4 Max 64GB. |

---

## 2. High-Level Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                     CLIENT (Minimal Web UI)                   │
│  ┌──────────┐  ┌──────────────┐  ┌────────────────────────┐  │
│  │   Mic    │  │ Audio Player │  │  Status Display        │  │
│  │ Capture  │  │ (streaming)  │  │  (listening/thinking/  │  │
│  │          │  │              │  │   speaking + transcript)│  │
│  └────┬─────┘  └──────▲───────┘  └────────────────────────┘  │
│       │               │                                      │
│       └───────┬───────┘                                      │
│               │  WebSocket                                   │
└───────────────┼──────────────────────────────────────────────┘
                │
┌───────────────┼──────────────────────────────────────────────┐
│               ▼  ORCHESTRATION SERVER (Python)               │
│                                                              │
│  ┌────────────────────────────────────────────────────────┐  │
│  │              Wake Word Detection (server/wake/)        │  │
│  │              OpenWakeWord ("Hey Beemo")                │  │
│  │              Always listening, triggers pipeline        │  │
│  └────────────────────┬───────────────────────────────────┘  │
│                       │ wake detected                        │
│                       │           ┌──────────────────────┐   │
│                       │           │  Conversation Mode   │   │
│                       │◄──────────│  (30s auto-listen    │   │
│                       │           │   after response)    │   │
│                       │           └──────────────────────┘   │
│  ┌────────────────────▼───────────────────────────────────┐  │
│  │         Audio Pipeline (server/audio/)                  │  │
│  │         Noise Gate → RNNoise → Silero VAD              │  │
│  └────────────────────┬───────────────────────────────────┘  │
│                       │ clean audio + end-of-speech           │
│  ┌────────────────────▼───────────────────────────────────┐  │
│  │         Speech-to-Text (server/stt/)                    │  │
│  │         whisper.cpp (MLX, tiny.en)                      │  │
│  └────────────────────┬───────────────────────────────────┘  │
│                       │ transcript                           │
│  ┌────────────────────▼───────────────────────────────────┐  │
│  │         Intent Router (server/llm/)                     │  │
│  │         Rule-based + LLM fallback                       │  │
│  └──────┬─────────────┬──────────────────┬────────────────┘  │
│         │             │                  │                    │
│  ┌──────▼──────┐ ┌────▼────────┐ ┌──────▼──────────────┐    │
│  │ RAG Engine  │ │ Web Search  │ │  LLM (direct)       │    │
│  │server/rag/  │ │server/search│ │                     │    │
│  │ChromaDB     │ │Brave/SearXNG│ │                     │    │
│  │BGE-small    │ │             │ │                     │    │
│  └──────┬──────┘ └────┬────────┘ └──────┬──────────────┘    │
│         │             │                  │                    │
│  ┌──────▼─────────────▼──────────────────▼────────────────┐  │
│  │         LLM Response (server/llm/)                      │  │
│  │         Ollama + Qwen3 8B (streaming)                   │  │
│  └────────────────────┬───────────────────────────────────┘  │
│                       │ token stream (pipeline parallel)     │
│  ┌────────────────────▼───────────────────────────────────┐  │
│  │         Text-to-Speech (server/tts/)                    │  │
│  │         Kokoro TTS (82M)                                │  │
│  └────────────────────┬───────────────────────────────────┘  │
│                       │ audio chunks                         │
│                       ▼                                      │
│         → WebSocket Handler (server/ws/) → Client playback   │
│         → Session Manager (server/session/) →                │
│           Enter conversation mode (listen for follow-up)     │
│                                                              │
└──────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────┐
│                   INDEXING SERVICE (background)                │
│  File Watcher (watchdog) → Chunker (512 tok) → BGE Embed     │
│  → ChromaDB (persistent at ~/.bmo-voice/chroma/)              │
└──────────────────────────────────────────────────────────────┘
```

---

## 3. Component Map

| # | Component | Folder | Purpose | Design Doc |
|---|---|---|---|---|
| 1 | Wake Word | `server/wake/` | Detect "Hey Beemo", activate pipeline | [DESIGN.md](../../server/wake/DESIGN.md) |
| 2 | Audio Pipeline | `server/audio/` | Noise reduction (RNNoise) + VAD (Silero) | [DESIGN.md](../../server/audio/DESIGN.md) |
| 3 | Speech-to-Text | `server/stt/` | whisper.cpp MLX transcription | [DESIGN.md](../../server/stt/DESIGN.md) |
| 4 | Text-to-Speech | `server/tts/` | Kokoro TTS speech synthesis | [DESIGN.md](../../server/tts/DESIGN.md) |
| 5 | LLM + Intent Router | `server/llm/` | Intent classification + Ollama response | [DESIGN.md](../../server/llm/DESIGN.md) |
| 6 | RAG Engine | `server/rag/` | Document indexing + retrieval | [DESIGN.md](../../server/rag/DESIGN.md) |
| 7 | Web Search | `server/search/` | Brave API + SearXNG fallback | [DESIGN.md](../../server/search/DESIGN.md) |
| 8 | Session Manager | `server/session/` | State machine + orchestration | [DESIGN.md](../../server/session/DESIGN.md) |
| 9 | WebSocket Protocol | `server/ws/` | Client-server protocol + handler | [DESIGN.md](../../server/ws/DESIGN.md) |
| 10 | Web UI Client | `client/` | Mic capture, audio playback, status UI | [DESIGN.md](../../client/DESIGN.md) |

---

## 4. Data Flow (Happy Path)

1. **"Hey Beemo"** detected by OpenWakeWord → pipeline activates
2. User speaks; audio streamed via WebSocket to server
3. Audio passes through **noise gate → RNNoise** suppression pipeline
4. **Silero VAD** detects end-of-speech (silence threshold)
5. Buffered audio sent to **whisper.cpp** → transcript
6. STT verifies transcript contains "hey beemo" before proceeding (false positive filter)
7. **Intent Router** classifies: RAG / web search / general / hybrid
8. If web search intent: immediately play pre-generated "Hmm, let me search the internet" audio
9. Context gathered from RAG and/or web search (**parallel** if both needed)
10. Context + transcript + conversation history (5-min TTL) → **Ollama LLM** (streaming)
11. If no TTS audio sent within 3s: play pre-generated "Complex question, I'm still thinking"
12. LLM token stream buffered into sentences → **Kokoro TTS** (**pipeline parallel**: TTS processes sentence N while LLM generates sentence N+1)
13. Audio chunks streamed back to client via WebSocket. **Mic muted during playback.**
14. Client plays audio; BMO enters **conversation mode** (listens for follow-ups without wake word for 30s)
15. If follow-up detected → repeat from step 3; if silence → return to wake-word-only mode

---

## 5. Conversation Flow Example

```
[Wake-word-only mode — low CPU, always listening]

User: "Hey Beemo, what's the weather today?"
  → Wake word → Audio Pipeline → STT → Web Search → LLM → TTS
BMO: "Today is partly cloudy with a high of 85 and a low of 63."

[Conversation mode — 30s window, listening without wake word]

User: "What's the chance of rain?"
  → VAD detects speech → STT → LLM (with conversation context) → TTS
BMO: "There's a 15% chance of rain between 4 and 6 PM."

[Conversation mode resets — another 30s window]

User: [silence for 30 seconds]

[Back to wake-word-only mode]
```

---

## 6. Parallelism Strategy

### Startup (all models load in parallel)
```
Thread 1: OpenWakeWord    ──┐
Thread 2: Silero VAD      ──┤
Thread 3: RNNoise         ──┤  All load concurrently
Thread 4: Whisper model   ──┤  Startup time = slowest model (~8-10s)
Thread 5: Ollama warmup   ──┤  instead of sum of all (~30s sequential)
Thread 6: Kokoro TTS      ──┤
Thread 7: BGE + ChromaDB  ──┘
```

### Runtime pipeline parallelism
```
Time →
LLM:  [generate sentence 1] [generate sentence 2] [generate sentence 3]
TTS:                         [synthesize sent 1]   [synthesize sent 2]
Play:                                              [play sent 1] [play sent 2]
```

### Query parallelism (hybrid intent)
```
                ┌─ RAG retrieval (local, ~30ms)  ──┐
Intent Router ──┤                                   ├── LLM with combined context
                └─ Web search (network, ~700ms) ──┘
```

---

## 7. Technology Summary

| # | Component | Technology | License | Type |
|---|---|---|---|---|
| 1 | Wake Word | OpenWakeWord | Apache 2.0 | Local model |
| 2 | VAD | Silero VAD | MIT | Local model |
| 3 | Noise Suppression | RNNoise | BSD | Local model |
| 4 | STT Engine | whisper.cpp (MLX) | MIT | Local inference |
| 5 | STT Model | whisper-tiny.en | MIT | Local model |
| 6 | LLM Runtime | Ollama | MIT | Local inference |
| 7 | LLM Model | Qwen3 8B (Q4_K_M) | Apache 2.0 | Local model |
| 8 | TTS | Kokoro TTS (82M) | Apache 2.0 | Local model |
| 9 | Embeddings | BGE-small-en-v1.5 | MIT | Local model |
| 10 | Vector DB | ChromaDB | Apache 2.0 | Local DB |
| 11 | Web Search (primary) | Brave Search API | Proprietary (free) | Free API |
| 12 | Web Search (fallback) | SearXNG | AGPL-3.0 | Self-hosted |
| 13 | Server Framework | FastAPI + WebSockets | MIT + BSD | Framework |
| 14 | Client Framework | React + Vite | MIT | Framework |

---

## 8. Latency Budget

```
"Hey Beemo" detected              0ms
├─ Wake word processing            ~150ms
├─ User speaks (VAD listening)     variable
├─ VAD detects end of speech       ~100ms
├─ whisper.cpp STT (tiny.en)       ~300-500ms
├─ Intent routing                  ~10ms
├─ RAG retrieval (if needed)       ~30ms     (local ChromaDB + BGE)
├─ Web search (if needed)          ~700ms    (Brave API, parallel with RAG)
├─ Ollama LLM TTFT                 ~200-300ms
├─ Kokoro TTS TTFB                 ~200-300ms
└─ Audio buffer                    ~50ms
                                   ────────
Total (general query):             ~1000-1400ms
Total (RAG query):                 ~1050-1450ms
Total (web search query):          ~1400-1800ms
```

Target: voice-to-first-audio < 1500ms for general queries.

---

## 9. Startup Behavior

### Parallel Model Loading

All models load concurrently in separate threads. Startup time = slowest model (~8–10s) instead of sum (~30s sequential).

### Health Checks

Each component runs health checks at startup. See individual component DESIGN.md for specifics.

### Fail-Fast Policy

**If ANY required component fails to load, BMO refuses to start.**

Required components (startup fails without them):
- OpenWakeWord (wake word model)
- Silero VAD
- RNNoise
- whisper.cpp (STT model)
- Ollama + configured LLM model
- Kokoro TTS
- BGE-small-en (embedding model)
- ChromaDB

Optional components (warn but continue):
- Brave Search API (web search disabled if unavailable)
- SearXNG (web search disabled if unavailable)

**On failure, BMO prints:**
```
[ERROR] BMO failed to start: {component} health check failed
[ERROR] {specific error message}
[ERROR] To fix: {actionable instruction}
```

Example:
```
[ERROR] BMO failed to start: LLM health check failed
[ERROR] Ollama model 'qwen3:8b' not found
[ERROR] To fix: run 'ollama pull qwen3:8b'
```

---

## 10. Logging Convention

All components use Python `logging` with structured format.

### Logger Naming

Each component gets its own logger under the `bmo` namespace:

```
bmo.wake       — Wake word detection
bmo.audio      — Audio pipeline (VAD + noise)
bmo.stt        — Speech-to-text
bmo.tts        — Text-to-speech
bmo.llm        — LLM + intent router
bmo.rag        — RAG engine
bmo.search     — Web search
bmo.session    — Session management
bmo.ws         — WebSocket handler
```

### Log Format

```
[2026-03-25 14:30:05.123] [bmo.stt] [INFO] Transcription: "what time is it" (audio=2.1s, latency=380ms)
```

### Log Levels

| Level | Usage |
|---|---|
| **DEBUG** | Internal state, per-frame data, token-level details. Off by default. |
| **INFO** | State transitions, pipeline milestones, latency measurements. Default level. |
| **WARNING** | Degraded performance, approaching limits, potential issues. |
| **ERROR** | Component failures, connection drops, startup failures. |

### Latency Timing

Every pipeline stage logs its latency at INFO level:
```
[INFO] [bmo.stt] Transcription: "..." (latency=380ms)
[INFO] [bmo.llm] Intent: web_search (method=rule_based)
[INFO] [bmo.llm] LLM TTFT: 280ms
[INFO] [bmo.tts] TTS: "First sentence..." (latency=180ms)
[INFO] [bmo.session] Pipeline complete: total=1420ms (stt=380ms, llm_ttft=280ms, tts_ttfb=180ms)
```

---

## 11. macOS Considerations

### Microphone Permission

- macOS requires explicit mic permission: System Settings > Privacy & Security > Microphone
- The terminal app (or IDE) running BMO must be granted mic access
- Browser also requires separate mic permission when accessing the client UI
- **If denied**: BMO logs clear error at startup with instructions

### Audio Devices

- Uses system default input/output devices by default
- Configurable for users with multiple audio devices
- Core Audio accessed via `sounddevice` or `pyaudio` (both support macOS natively)
- Sample rate negotiation: pipeline needs 16kHz; resample if device provides 44.1/48kHz

### Apple Silicon (MLX)

- whisper.cpp MLX backend leverages Apple Silicon unified memory
- No CPU↔GPU data transfer overhead — models live in shared memory
- Ollama automatically uses Metal for GPU-accelerated LLM inference
- All other models (VAD, RNNoise, Kokoro, BGE) run efficiently on CPU

### Auto-Start (launchd)

For always-on operation, BMO can be configured as a `launchd` daemon:
```xml
<!-- ~/Library/LaunchAgents/com.bmo-voice.plist -->
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.bmo-voice</string>
    <key>ProgramArguments</key>
    <array>
        <string>/path/to/bmo-voice/start.sh</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
</dict>
</plist>
```

### Energy & Thermal

- Idle (wake word only): ~2% CPU — negligible thermal impact
- Active conversation: LLM generation is the hottest operation (~90% CPU burst)
- MacBook Pro: sustained use may spin fans. Short conversations are fine.
- Mac Studio: handles sustained load without thermal issues

---

## 12. Privacy Policy

| Category | Policy |
|---|---|
| **Audio** | Never saved to disk. Processed in-memory only. Buffers discarded after STT. |
| **Conversations** | In-memory only, 5-minute TTL. No persistence. No transcripts saved. |
| **Models** | All run 100% locally. No telemetry, no usage reporting. |
| **Network** | Only outbound: Brave Search API (optional) and SearXNG (localhost). |
| **Telemetry** | None. Ollama telemetry should be disabled. |
| **Crash dumps** | Must not include audio buffers. |

---

## 13. Configuration

### Config File: `~/.bmo-voice/config.yaml`

```yaml
user:
  name: ""
  location: ""
  timezone: "auto"
  temp_units: "fahrenheit"
  distance_units: "miles"
  response_verbosity: "normal"
  custom_vocabulary: []

conversation:
  window_seconds: 30
  ttl_seconds: 300
  min_speech_duration_ms: 500
  no_speech_timeout_seconds: 5

wake_word:
  model_path: ~/.bmo-voice/models/hey_beemo.onnx
  threshold: 0.5
  debounce_ms: 500
  stt_verification: true

audio:
  noise_gate_enabled: true
  noise_gate_calibration_seconds: 2
  rnnoise_enabled: true
  echo_cancellation: mute
  reverb_decay_ms: 200

stt:
  model: whisper-tiny.en
  backend: mlx
  language: en
  beam_size: 5

llm:
  model: qwen3:8b
  host: http://localhost:11434
  keep_alive: -1

tts:
  model: kokoro-82m
  voice: default-en
  sample_rate: 16000
  format: pcm_s16le

rag:
  embedding_model: bge-small-en-v1.5
  chunk_size: 512
  chunk_overlap: 50
  top_k: 5

folders:
  - path: /Users/me/Documents/notes
    name: "My Notes"

search:
  primary: brave
  fallback: searxng
  brave_api_key: ${BRAVE_SEARCH_API_KEY}
  searxng_url: http://localhost:8888
  timeout_seconds: 3

server:
  host: "127.0.0.1"
  port: 8000
```

---

## 14. Hardware Requirements

| Component | RAM | Disk |
|---|---|---|
| Ollama + Qwen3 8B (Q4_K_M) | ~5 GB | ~5 GB |
| whisper-tiny.en | ~273 MB | ~75 MB |
| Kokoro TTS (82M) | ~400 MB | ~350 MB |
| BGE-small-en-v1.5 | ~100 MB | ~130 MB |
| OpenWakeWord | ~50 MB | ~20 MB |
| Silero VAD | ~50 MB | ~10 MB |
| ChromaDB + index | Variable | Variable |
| **Total** | **~6–6.5 GB active** | **~5.6 GB models** |

Fits comfortably on MacBook Pro M1 Pro 32GB (~25GB headroom). Mac Studio 64GB has ample room for larger models.

---

## 15. Cost Summary

| Component | Cost |
|---|---|
| All local models | Free |
| Brave Search (free tier) | Free (2000 queries/month) |
| SearXNG (self-hosted) | Free |
| **Total ongoing cost** | **$0.00/month** |

Only costs: electricity and the Mac hardware you already own.

---

## 16. Implementation Phases

### Phase 1: Core Voice Loop

**Goal**: Say "Hey Beemo", speak, hear a response, ask a follow-up without repeating the wake word.

**Build:**
1. FastAPI server with WebSocket endpoint (`server/ws/`)
2. WebSocket protocol implementation (binary audio + JSON control)
3. Parallel model loading at startup — **fail-fast on any failure**
4. Client: mic capture via AudioWorklet → WebSocket → server (`client/`)
5. OpenWakeWord "Hey Beemo" listener (`server/wake/`)
6. Audio pipeline: noise gate → RNNoise → Silero VAD (`server/audio/`)
7. whisper.cpp STT with MLX backend (`server/stt/`)
8. Ollama + Qwen3 8B response generation, streaming (`server/llm/`)
9. Kokoro TTS speech synthesis (`server/tts/`)
10. LLM→TTS pipeline parallelism (sentence-level overlap)
11. Audio streaming back to client for playback
12. Session manager with full state machine (`server/session/`)
13. Conversation mode (30s follow-up window)
14. Mic muting during SPEAKING state
15. Pre-generated audio feedback clips
16. User preferences config (name, location, units, timezone)
17. Structured logging (`bmo.*` loggers) across all components
18. macOS mic permissions handling
19. STT wake word verification (false positive filter)

**Skip:** RAG, web search, intent routing, UI polish, SearXNG

**Success criteria:**
- "Hey Beemo" activates → speak → hear response in < 2 seconds
- Follow-up works without wake word
- 30s silence → returns to wake-word-only mode
- Mic muted during BMO's speech
- Clean audio even with fan/AC
- TV audio doesn't trigger false activations
- All health checks pass, startup < 15 seconds
- Startup fails clearly if any model is missing

### Phase 2: RAG Integration

**Goal**: "Hey Beemo, what does my project README say about deployment?"

**Build:**
1. Document loader (all supported formats) (`server/rag/`)
2. Recursive 512-token chunker with AST-aware code splitting
3. BGE-small-en-v1.5 embedding pipeline (local, batched)
4. ChromaDB storage and retrieval (per-folder collections)
5. File watcher for incremental updates (`watchdog`)
6. Intent router — rule-based detection of document queries (`server/llm/`)
7. RAG context injection into LLM prompt
8. Parallel file indexing (concurrent chunk + embed)
9. Folder management via WebSocket messages (add/remove/list)

**Success criteria:**
- Index a folder → "Hey Beemo, what's in my notes about X?" → accurate answer
- File changes → answer updates without manual re-index
- Follow-up "What else does it say?" → works in conversation mode

### Phase 3: Web Search

**Goal**: "Hey Beemo, what happened in tech news today?"

**Build:**
1. Brave Search API integration (free tier) (`server/search/`)
2. SearXNG client as fallback
3. Optional page content extraction (httpx + readability-lxml)
4. Intent router: detect web search queries
5. Web context injection into LLM prompt
6. Hybrid queries: RAG + web search in parallel
7. 3-second timeout with graceful degradation
8. Failover: Brave → SearXNG → proceed without web

**Success criteria:**
- "Hey Beemo, search for the latest Python release" → current answer
- Hybrid: "How does my code compare to OWASP recommendations?" → uses RAG + web
- Network failure → graceful degradation, user informed
- "Let me search the internet" feedback plays immediately

### Phase 4: Polish & Stability

**Goal**: Production-quality experience.

**Build:**
1. Web UI: status indicator, live transcript, conversation timer
2. Folder management UI (add/remove, indexing status)
3. User preferences UI (name, location, units)
4. Setup script (`setup.sh`) — one-command installation
5. Latency profiling per component (log analysis dashboard)
6. Error recovery (model crash → restart, network → degradation)
7. Config validation with helpful error messages
8. `launchd` plist for auto-start daemon mode
9. Local-only observability (structured log viewer)

**Success criteria:**
- Multi-turn conversation works naturally
- UI shows state clearly (including conversation mode timer)
- New user sets up the system with one script
- End-to-end latency consistently < 2 seconds for general queries
- System recovers from crashes without user intervention

---

## 17. Backlog

Items **not in the MVP (Phases 1–4)**, ordered roughly by priority.

| ID | Item | Complexity | Dependencies |
|---|---|---|---|
| B-01 | Conversation memory persistence | High | Research needed |
| B-02 | Multi-user support (speaker ID) | High | Speaker embedding research |
| B-03 | Multi-modal analysis (images) | High | Vision model research |
| B-04 | Text chat interface | Medium | Phase 4 complete |
| B-05 | Personality fine-tuning | Low–Medium | None |
| B-06 | Voice cloning | High | TTS research |
| B-07 | Energy/resource dashboard | Medium | None |
| B-08 | Agentic actions | Very High | B-02 for security |
| B-09 | RAG reranking (cross-encoder) | Low | Phase 2 complete |
| B-10 | Push-to-talk mode | Low | Phase 1 complete |
| B-11 | Proactive suggestions | High | Phase 2 complete |
| B-12 | Mac Studio deployment optimization | Medium | Hardware available |
| B-13 | Response length control | Low | Phase 1 complete |
| B-14 | Citation display in UI | Low | Phase 2 + Phase 4 |
| B-15 | Mobile access (LAN PWA) | Medium | Phase 4 complete |
| B-16 | Adaptive endpointing (variable silence) | Medium | Phase 1, needs measurement |
| B-17 | Graceful degradation under memory pressure | Medium | Phase 1 complete |
| B-18 | Kokoro prosody continuity | Low–Medium | Research needed |
| B-19 | Common voice patterns ("repeat that", "stop") | Low | Phase 1 complete |
| B-20 | Smart search fallback (circuit breaker) | Medium | Phase 3 complete |
| **B-21** | **Comprehensive testing suite** | **High** | **Phase 1 complete** |

### B-21: Comprehensive Testing Suite (NEW)

**Status**: Primary backlog item — implement after Phase 4.

**Scope:**
- **Unit tests per component**: Synthetic audio fixtures for STT, mock Ollama for LLM, mock audio for wake word/VAD
- **Integration tests**: Full pipeline tests (audio in → response out) with recorded test fixtures
- **Performance regression tests**: Automated latency measurement against targets (STT < 500ms, TTFT < 300ms, etc.)
- **Load testing**: Sustained conversation simulation to verify thermal/memory stability
- **Protocol tests**: WebSocket message format validation (client ↔ server contract)
- **Health check tests**: Verify startup behavior with missing/corrupt models

---

## 18. Project Structure

```
bmo-voice/
├── docs/
│   └── design/
│       └── DESIGN.md              ← You are here (overall system design)
│
├── server/                        # Python backend
│   ├── pyproject.toml
│   ├── main.py                    # FastAPI entry point + parallel model loading
│   ├── config.py                  # Configuration loading
│   │
│   ├── wake/
│   │   ├── DESIGN.md              # Wake word design doc
│   │   └── detector.py            # OpenWakeWord listener
│   │
│   ├── audio/
│   │   ├── DESIGN.md              # Audio pipeline design doc
│   │   ├── vad.py                 # Silero VAD wrapper
│   │   └── noise.py               # RNNoise + noise gate
│   │
│   ├── stt/
│   │   ├── DESIGN.md              # STT design doc
│   │   └── transcriber.py         # whisper.cpp MLX wrapper
│   │
│   ├── tts/
│   │   ├── DESIGN.md              # TTS design doc
│   │   └── synthesizer.py         # Kokoro TTS wrapper
│   │
│   ├── llm/
│   │   ├── DESIGN.md              # LLM + intent router design doc
│   │   ├── router.py              # Intent router
│   │   ├── ollama.py              # Ollama client (streaming)
│   │   └── prompts.py             # System prompts + context
│   │
│   ├── rag/
│   │   ├── DESIGN.md              # RAG engine design doc
│   │   ├── indexer.py             # Document loading + chunking + embedding
│   │   ├── retriever.py           # ChromaDB query interface
│   │   ├── watcher.py             # File system watcher
│   │   └── chunker.py             # Recursive text splitting
│   │
│   ├── search/
│   │   ├── DESIGN.md              # Web search design doc
│   │   ├── brave.py               # Brave Search API client
│   │   └── searxng.py             # SearXNG fallback client
│   │
│   ├── session/
│   │   ├── DESIGN.md              # Session management design doc
│   │   ├── manager.py             # State machine + pipeline coordination
│   │   └── models.py              # Session state + user preference models
│   │
│   └── ws/
│       ├── DESIGN.md              # WebSocket protocol design doc
│       └── handler.py             # WebSocket message routing
│
├── client/                        # Minimal web UI
│   ├── DESIGN.md                  # Client design doc
│   ├── package.json
│   ├── src/
│   │   ├── App.tsx
│   │   ├── components/
│   │   │   ├── VoiceStatus.tsx
│   │   │   ├── Transcript.tsx
│   │   │   └── Settings.tsx
│   │   ├── hooks/
│   │   │   ├── useWebSocket.ts
│   │   │   ├── useAudioCapture.ts
│   │   │   └── useAudioPlayer.ts
│   │   └── lib/
│   │       └── protocol.ts
│   └── public/
│       └── audio-worklet.js
│
├── models/                        # Local model storage
│   └── .gitkeep
│
├── docker-compose.yml             # Optional: SearXNG container
├── Makefile                       # Common commands
├── .env.example                   # API keys template
└── setup.sh                       # One-command setup
```
