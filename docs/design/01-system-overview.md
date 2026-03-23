# BMO Voice - System Overview

## Vision

A fully free, open-source, low-latency voice assistant that you can talk to naturally. Activated by the wake word **"Hey Beemo"**. It can:

1. Answer general questions using a local LLM
2. Perform RAG against user-specified local folders (text documents, code, notes)
3. Search the web for up-to-date information
4. Seamlessly blend all three knowledge sources in conversation
5. Hold natural back-and-forth conversations with follow-ups

## Constraints

- **Free**: Zero ongoing cost. No paid API subscriptions. All models run locally or use free-tier APIs with documented fallbacks.
- **Open source**: Every component must be open source or have an open-source alternative.
- **English only**: No multi-language support needed. (Multilingual STT model may be evaluated if it outperforms English-only — see 02-technology-decisions.md)
- **Voice-only interface**: Primary interaction is speak → listen. Minimal visual UI (status indicators only).
- **Conversation mode**: After BMO responds, it listens for follow-ups without requiring the wake word for a configurable window (default 30s). Conversation history has a 5-minute TTL.
- **Hardware**: Development on MacBook Pro M1 Pro (32GB RAM). Deployment target is Mac Studio 64GB RAM M4 Max.

## Latency Target

| Metric | Target | Notes |
|--------|--------|-------|
| Wake word detection | < 200ms | Local, always-on |
| Voice-to-first-audio (end-to-end) | < 2000ms | Realistic for fully local stack |
| STT latency | < 1000ms | whisper-small.en on M1 Pro 32GB (~0.75-1.0s for 5s utterance) |
| LLM time-to-first-token | < 300ms | Local 8B model via Ollama |
| TTS time-to-first-byte | < 300ms | Local Kokoro inference |
| Turn detection | < 200ms | Local Silero VAD |

## High-Level Architecture

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
│  │              Wake Word Detection                       │  │
│  │     ┌─────────────────────────────────┐                │  │
│  │     │ ◆ OpenWakeWord ("Hey Beemo")    │                │  │
│  │     └─────────────────────────────────┘                │  │
│  │              Always listening, triggers pipeline        │  │
│  └────────────────────┬───────────────────────────────────┘  │
│                       │ wake detected                        │
│                       │           ┌──────────────────────┐   │
│                       │           │  Conversation Mode   │   │
│                       │◄──────────│  (30s auto-listen    │   │
│                       │           │   after response)    │   │
│                       │           └──────────────────────┘   │
│  ┌────────────────────▼───────────────────────────────────┐  │
│  │              Voice Activity Detection (VAD)             │  │
│  │     ┌─────────────────────────────────┐                │  │
│  │     │ ◆ Silero VAD                    │                │  │
│  │     └─────────────────────────────────┘                │  │
│  └────────────────────┬───────────────────────────────────┘  │
│                       │ speech ended                         │
│  ┌────────────────────▼───────────────────────────────────┐  │
│  │              Speech-to-Text (STT)                       │  │
│  │     ┌─────────────────────────────────┐                │  │
│  │     │ ◆ whisper.cpp (MLX backend)     │                │  │
│  │     └─────────────────────────────────┘                │  │
│  └────────────────────┬───────────────────────────────────┘  │
│                       │ transcript                           │
│  ┌────────────────────▼───────────────────────────────────┐  │
│  │              Intent Router                              │  │
│  │  - Decides: RAG / Web Search / General / Hybrid         │  │
│  └──────┬─────────────┬──────────────────┬────────────────┘  │
│         │             │                  │                    │
│  ┌──────▼──────┐ ┌────▼────────┐ ┌──────▼──────────────┐    │
│  │  RAG Engine │ │ Web Search  │ │  LLM (direct)       │    │
│  │ ┌─────────┐ │ │┌───────────┐│ │                     │    │
│  │ │◆ChromaDB│ │ ││◆Brave /   ││ │                     │    │
│  │ │◆BGE-sm  │ │ ││ SearXNG   ││ │                     │    │
│  │ └─────────┘ │ │└───────────┘│ │                     │    │
│  └──────┬──────┘ └────┬────────┘ └──────┬──────────────┘    │
│         │             │                  │                    │
│  ┌──────▼─────────────▼──────────────────▼────────────────┐  │
│  │              LLM Response Generation                    │  │
│  │     ┌─────────────────────────────────┐                │  │
│  │     │ ◆ Ollama (Qwen3 8B)            │                │  │
│  │     └─────────────────────────────────┘                │  │
│  └────────────────────┬───────────────────────────────────┘  │
│                       │ token stream (pipeline parallel)     │
│  ┌────────────────────▼───────────────────────────────────┐  │
│  │              Text-to-Speech (TTS)                       │  │
│  │     ┌─────────────────────────────────┐                │  │
│  │     │ ◆ Kokoro TTS (82M)             │                │  │
│  │     └─────────────────────────────────┘                │  │
│  └────────────────────┬───────────────────────────────────┘  │
│                       │ audio chunks                         │
│                       ▼                                      │
│              → Client playback                               │
│              → Enter conversation mode (listen for follow-up)│
└──────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────┐
│                   INDEXING SERVICE (background)                │
│  ┌──────────────┐  ┌──────────────┐  ┌────────────────────┐  │
│  │ File Watcher │  │  Chunker     │  │  Vector Store      │  │
│  │ ┌──────────┐ │  │  (recursive  │  │ ┌────────────────┐ │  │
│  │ │◆watchdog │→│→ │   512 tok)   │→ │ │◆ ChromaDB      │ │  │
│  │ └──────────┘ │  │              │  │ │◆ BGE-small-en  │ │  │
│  └──────────────┘  └──────────────┘  │ └────────────────┘ │  │
│                                      └────────────────────┘  │
└──────────────────────────────────────────────────────────────┘

◆ = Specific model/service choice (see 02-technology-decisions.md for review)
```

## Data Flow (Happy Path)

1. **"Hey Beemo"** detected by OpenWakeWord → pipeline activates
2. User speaks; audio streamed via WebSocket to server
3. Silero VAD detects end-of-speech (silence threshold)
4. Buffered audio sent to whisper.cpp → transcript
5. Intent Router classifies: RAG / web search / general / hybrid
6. Context gathered from RAG and/or web search (**parallel** if both needed)
7. Context + transcript + conversation history (5-min TTL) → Ollama LLM (streaming)
8. LLM token stream buffered into sentences → Kokoro TTS (**pipeline parallel**: TTS processes sentence N while LLM generates sentence N+1)
9. Audio chunks streamed back to client immediately
10. Client plays audio; BMO enters **conversation mode** (listens for follow-ups without wake word for 30s)
11. If follow-up detected → repeat from step 3; if silence → return to wake-word-only mode

## Conversation Flow Example

```
[Wake-word-only mode — low CPU, always listening]

User: "Hey Beemo, what's the weather today?"
  → Wake word detected → VAD → STT → Web Search → LLM → TTS
BMO: "Today is partly cloudy with a high of 85 and a low of 63."

[Conversation mode — 30s window, listening without wake word]

User: "What's the chance of rain?"
  → VAD detects speech → STT → LLM (with conversation context) → TTS
BMO: "There's a 15% chance of rain between 4 and 6 PM."

[Conversation mode resets — another 30s window]

User: [silence for 30 seconds]

[Back to wake-word-only mode]
```

## Parallelism Strategy

### Startup (all models load in parallel)
```
Thread 1: OpenWakeWord    ──┐
Thread 2: Silero VAD      ──┤
Thread 3: Whisper model   ──┤  All load concurrently
Thread 4: Ollama warmup   ──┤  Startup time = slowest model (~8-10s)
Thread 5: Kokoro TTS      ──┤  instead of sum of all (~30s sequential)
Thread 6: BGE + ChromaDB  ──┘
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

## Key Design Principles

- **Free forever**: No paid APIs in the critical path. Free-tier APIs only for non-essential features, with self-hosted fallbacks documented.
- **Local-first**: All latency-critical components (wake word, VAD, STT, LLM, TTS, embeddings, vector DB) run on the local machine.
- **Stream everything**: STT processes buffered audio, LLM streams tokens, TTS streams audio chunks.
- **Parallel when possible**: Startup model loading, RAG + web search, LLM→TTS pipeline.
- **Conversation mode**: Natural back-and-forth without repeating the wake word.
- **Graceful interruption**: "Hey Beemo" during a response immediately stops TTS and begins processing.
- **English only**: All models optimized for English. No multi-language overhead.
- **User-aware**: Configurable user preferences (location, name, units) for personalized responses.
