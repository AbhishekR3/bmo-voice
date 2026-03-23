# BMO Voice - Project Structure

```
bmo-voice/
├── docs/
│   └── design/                # System design documents (you are here)
│
├── server/                    # Python backend
│   ├── pyproject.toml         # Dependencies (uv)
│   ├── main.py                # FastAPI app entry point + parallel model loading
│   ├── config.py              # Configuration loading + user preferences
│   │
│   ├── wake/
│   │   └── detector.py        # ◆ OpenWakeWord "Hey Beemo" listener
│   │
│   ├── audio/
│   │   ├── vad.py             # ◆ Silero VAD wrapper
│   │   ├── stt.py             # ◆ whisper.cpp (MLX) wrapper
│   │   └── tts.py             # ◆ Kokoro TTS wrapper
│   │
│   ├── llm/
│   │   ├── router.py          # Intent router (rule-based + LLM fallback)
│   │   ├── ollama.py          # ◆ Ollama client (streaming)
│   │   └── prompts.py         # System prompts + user context injection
│   │
│   ├── rag/
│   │   ├── indexer.py         # Document loading + chunking + ◆ BGE embedding
│   │   ├── retriever.py       # ◆ ChromaDB query interface
│   │   ├── watcher.py         # File system watcher (watchdog)
│   │   └── chunker.py         # Recursive text splitting
│   │
│   ├── search/
│   │   ├── brave.py           # ◆ Brave Search API (free tier)
│   │   └── searxng.py         # ◆ SearXNG fallback client
│   │
│   ├── session/
│   │   ├── manager.py         # Session lifecycle + conversation mode state machine
│   │   └── models.py          # Session state models + user preferences
│   │
│   └── ws/
│       └── handler.py         # WebSocket message routing
│
├── client/                    # Minimal web UI (voice-only)
│   ├── package.json
│   ├── src/
│   │   ├── App.tsx
│   │   ├── components/
│   │   │   ├── VoiceStatus.tsx     # Status: listening/thinking/speaking/conversation
│   │   │   ├── Transcript.tsx      # Live transcript display
│   │   │   └── FolderManager.tsx   # Add/remove RAG folders
│   │   ├── hooks/
│   │   │   ├── useWebSocket.ts     # WebSocket connection
│   │   │   ├── useAudioCapture.ts  # Mic capture via AudioWorklet
│   │   │   └── useAudioPlayer.ts   # Streaming audio playback
│   │   └── lib/
│   │       └── protocol.ts         # Message type definitions
│   └── public/
│       └── audio-worklet.js        # AudioWorklet processor
│
├── models/                    # Local model storage
│   └── .gitkeep               # Models downloaded at setup time
│
├── docker-compose.yml         # Optional: SearXNG container
├── Makefile                   # Common commands (dev, setup, index)
├── .env.example               # API keys template
└── setup.sh                   # One-command setup script
```

## Dependencies (All Open Source)

### Server (Python 3.12+)
```
# Core framework
fastapi                 # MIT
uvicorn[standard]       # BSD
websockets              # BSD

# Wake word
openwakeword            # Apache 2.0     ◆

# Audio / Voice
silero-vad              # MIT             ◆ (or torch + model directly)
mlx-whisper             # MIT             ◆ (whisper.cpp MLX binding)
kokoro                  # Apache 2.0      ◆

# LLM
ollama                  # MIT             ◆ (Python client for Ollama server)

# RAG
chromadb                # Apache 2.0      ◆
sentence-transformers   # Apache 2.0      (for ◆ BGE-small-en-v1.5)
unstructured            # Apache 2.0      (PDF/DOCX text extraction)
watchdog                # Apache 2.0

# Search
httpx                   # BSD             (HTTP client for Brave/SearXNG)
readability-lxml        # Apache 2.0      (web page content extraction)

# Config
pyyaml                  # MIT
pydantic                # MIT
pydantic-settings       # MIT
```

### Client (Node.js 20+)
```
react                   # MIT
react-dom               # MIT
typescript              # Apache 2.0
vite                    # MIT
tailwindcss             # MIT
```

### System Requirements
```
# Pre-installed / one-time setup
ollama                  # Local LLM server (brew install ollama)
docker (optional)       # Only needed for SearXNG fallback
```

## API Keys

| Key | Purpose | Required | Free? | Risk if Removed |
|-----|---------|----------|-------|-----------------|
| `BRAVE_SEARCH_API_KEY` | Web search (free tier) | Optional | Yes, 2000 queries/mo | Switch to SearXNG (self-hosted, unlimited) |

**That's it.** One optional free-tier API key. Everything else runs locally.

### Getting the Brave Key (Optional)
1. Go to https://brave.com/search/api/
2. Sign up (no credit card)
3. Copy API key to `.env` file

### SearXNG Setup (Fallback / if Brave is removed)
```
docker run -d -p 8888:8080 searxng/searxng
```
Zero configuration needed. Aggregates Google, Bing, DuckDuckGo results.

## Hardware Requirements

| Component | RAM Usage | Disk Usage |
|-----------|-----------|------------|
| Ollama + Qwen3 8B (Q4_K_M) | ~5GB | ~5GB |
| whisper-small.en | ~500MB | ~460MB |
| Kokoro TTS (82M) | ~400MB | ~350MB |
| BGE-small-en-v1.5 | ~100MB | ~130MB |
| OpenWakeWord | ~50MB | ~20MB |
| Silero VAD | ~50MB | ~10MB |
| ChromaDB + index | Variable | Variable |
| **Total** | **~6-7GB active** | **~6GB models** |

Fits comfortably on MacBook Pro M1 Pro (32GB RAM). Leaves ~25GB free for macOS and other apps. Mac Studio will have even more headroom for larger models.
