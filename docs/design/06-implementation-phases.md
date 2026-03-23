# BMO Voice - Implementation Phases

## Phase 1: Wake Word + Voice Loop + Conversation Mode

**Goal**: Say "Hey Beemo", speak, hear a response, ask a follow-up without repeating the wake word.

### What to build:
1. FastAPI server with WebSocket endpoint
2. **Parallel model loading** at startup (all 6 models load concurrently)
3. Client: mic capture → WebSocket → server
4. ◆ OpenWakeWord listener (continuous, "Hey Beemo")
5. ◆ Silero VAD for end-of-turn detection
6. ◆ whisper.cpp (MLX, whisper-small.en) for transcription
7. ◆ Ollama + Qwen3 8B for response generation (streaming)
8. ◆ Kokoro TTS for speech synthesis
9. **LLM→TTS pipeline parallelism** (TTS processes sentence N while LLM generates N+1)
10. Audio streaming back to client for playback
11. **Conversation mode** (30s follow-up window after response)
12. Basic interruption handling ("Hey Beemo" stops current response)
13. User preferences config (name, location, units, timezone)

### What to skip:
- RAG, web search, intent routing
- UI polish
- SearXNG Docker setup

### Setup required:
- Install Ollama, pull qwen3:8b model
- Download whisper-small.en model
- Train "Hey Beemo" wake word model with OpenWakeWord
- Install Kokoro TTS

### Parallelism in this phase:
- **Startup**: All models load in parallel threads (~8-10s instead of ~30s)
- **Runtime**: LLM→TTS pipeline parallelism (sentence-level overlap)

### Edge cases to handle:
- Wake word but no speech → 5s timeout → return to IDLE
- Empty STT result → "Sorry, I didn't catch that"
- Ollama crash → "Sorry, I had a problem. Could you ask again?"
- Background noise in conversation mode → 500ms min speech filter
- Rapid duplicate wake words → 500ms debounce
- Very long utterances → 30s segmentation

### Success criteria:
- Say "Hey Beemo" → it activates
- Speak a question → hear a response in < 2.5 seconds
- Ask a follow-up without saying "Hey Beemo" again → works
- 30s silence after response → returns to wake-word-only mode
- "Hey Beemo" during response → stops and listens
- Audio quality is clear and natural
- No response when you don't say the wake word
- Startup completes in < 15 seconds (parallel model loading)

---

## Phase 2: RAG Integration

**Goal**: "Hey Beemo, what does my project README say about deployment?"

### What to build:
1. Folder registration (CLI command)
2. Document loader (text extraction from all supported formats)
3. Recursive 512-token chunker
4. ◆ BGE-small-en-v1.5 embedding pipeline (local)
5. ◆ ChromaDB storage and retrieval
6. File watcher for incremental updates (watchdog)
7. Intent router (rule-based: detect document-related queries)
8. RAG context injection into LLM prompt
9. **Parallel file indexing** (multiple files chunked and embedded concurrently)

### Parallelism in this phase:
- **Indexing**: Multiple files processed concurrently (chunk + embed in parallel)
- **Query**: RAG retrieval runs alongside other operations when applicable

### Edge cases to handle:
- Folder deleted while indexed → remove from ChromaDB
- Very large files → cap at 1000 chunks per file
- Binary files in folder → skip silently
- File changed rapidly → 2s debounce before re-index

### Success criteria:
- Index a folder of documents
- "Hey Beemo, what's in my notes about X?" → accurate answer citing the right file
- Changing a file → answer updates without manual re-index
- Follow-up "What else does it say?" → works in conversation mode

---

## Phase 3: Web Search

**Goal**: "Hey Beemo, what happened in tech news today?"

### What to build:
1. ◆ Brave Search API integration (free tier)
2. ◆ SearXNG client as fallback
3. Optional page content extraction (httpx + readability-lxml)
4. Intent router: detect web search queries
5. Web context injection into LLM prompt
6. **Hybrid queries: RAG + web search in parallel**
7. 3-second timeout for web search with graceful degradation

### Parallelism in this phase:
- **Hybrid intent**: RAG retrieval + web search run concurrently
- **Fallback**: If Brave times out, SearXNG fires immediately (not sequential)

### Edge cases to handle:
- Network failure → 3s timeout, proceed without web results
- Brave rate limit → automatic SearXNG fallback
- Empty results → "I couldn't find anything about that online"
- User location context → localized search results

### Setup required:
- Get free Brave Search API key
- Optionally: `docker run searxng/searxng` for fallback

### Success criteria:
- "Hey Beemo, search for the latest Python release" → relevant current answer
- Hybrid: "How does my auth code compare to OWASP recommendations?" → uses both RAG and web
- If Brave key is missing, falls back to SearXNG seamlessly
- Network failure → graceful degradation with user notification

---

## Phase 4: Polish + Stability

**Goal**: Production-quality experience.

### What to build:
1. Minimal web UI: status indicator (listening/thinking/speaking/conversation mode)
2. Live transcript display
3. Folder management UI (add/remove RAG folders)
4. User preferences UI (name, location, units)
5. Configurable settings (model choices, thresholds, conversation window)
6. Setup script (`setup.sh`) for one-command installation
7. Latency profiling and optimization per component
8. Model warm-up verification at startup
9. Error recovery (model crash → restart, network down → graceful degradation)
10. Audio quality improvements (noise reduction, echo cancellation)
11. Config validation and helpful error messages
12. Logging and basic telemetry (local only)

### Success criteria:
- Multi-turn conversation works naturally
- UI clearly shows what state BMO is in (including conversation mode indicator)
- New user can set up the entire system with one script
- End-to-end latency consistently under 2 seconds for general queries
- System recovers from crashes without user intervention

---

## Parallelism Summary Across All Phases

| What | Type | Benefit |
|------|------|---------|
| Model loading at startup | Concurrent threads | ~3x faster startup |
| LLM→TTS sentence pipeline | Pipeline parallel | First audio ~1 sentence faster |
| RAG + web search (hybrid) | Concurrent async | Latency = max(RAG, web) not sum |
| File indexing (multiple files) | Concurrent workers | ~Nx faster initial indexing |
| Wake word detection | Always-on thread | Never blocks pipeline |
| File watcher | Background thread | Never blocks pipeline |

---

## Resource Usage Estimate (During Active Conversation)

| Component | CPU | RAM | Notes |
|-----------|-----|-----|-------|
| OpenWakeWord (idle) | ~2% | 50MB | Always running |
| Silero VAD (active) | ~5% | 50MB | Only during recording |
| whisper.cpp STT | ~80% burst | 500MB | ~0.5-1s burst per utterance |
| Ollama LLM | ~90% burst | 5GB | During generation |
| Kokoro TTS | ~60% burst | 400MB | During synthesis |
| ChromaDB query | ~5% burst | 100MB | ~30ms per query |
| **Peak (STT or LLM)** | **~90%** | **~6.5GB** | Sequential, not simultaneous |

Note: STT, LLM, and TTS run in a pipeline (not fully simultaneous). LLM and TTS may overlap at sentence boundaries. Peak RAM is ~6.5GB. M1 Pro 32GB has ~25GB of headroom.
