# LLM & Intent Router — `server/llm/`

## Purpose & Responsibilities

- Classify user intent: `general`, `rag`, `web_search`, or `hybrid`
- Generate conversational responses using local LLM via Ollama
- Stream tokens for pipeline-parallel TTS processing
- Manage system prompts and user context injection
- Buffer LLM output into sentences for TTS handoff

## Architecture

```
Transcript (from STT via Session Manager)
         │
         ▼
┌──────────────────────────────────────────────┐
│  Intent Router                                │
│                                               │
│  1. Rule-based first pass (near-zero latency) │
│  2. LLM classification (when ambiguous)       │
│                                               │
│  Output: general | rag | web_search | hybrid  │
└──────────────┬───────────────────────────────┘
               │
     ┌─────────┼───────────┬──────────────┐
     │         │           │              │
     ▼         ▼           ▼              ▼
  general     rag      web_search      hybrid
     │         │           │              │
     │    ┌────▼────┐ ┌────▼─────┐   ┌───▼──────────┐
     │    │RAG      │ │Web Search│   │RAG + Web     │
     │    │Engine   │ │Component │   │(parallel)    │
     │    └────┬────┘ └────┬─────┘   └──┬────┬──────┘
     │         │           │            │    │
     └─────────┴───────────┴────────────┴────┘
               │
               ▼
┌──────────────────────────────────────────────┐
│  Ollama LLM (Qwen3 8B)                       │
│                                               │
│  Input:  system prompt + user context         │
│          + conversation history               │
│          + RAG/web context (if applicable)     │
│          + user transcript                    │
│                                               │
│  Output: streaming token response             │
│          via /api/chat (stream: true)          │
└──────────────┬───────────────────────────────┘
               │ token stream
               ▼
┌──────────────────────────────────────────────┐
│  Sentence Buffer                              │
│                                               │
│  Accumulate tokens → flush on . ? ! \n        │
│  Force flush at 100 tokens                    │
│  Batch very short sentences                   │
└──────────────┬───────────────────────────────┘
               │ complete sentences
               ▼
           TTS Component
```

## Intent Router

### Rule-Based First Pass (near-zero latency)

| Pattern | Intent |
|---|---|
| "look up", "google", "search for", "search the web" | `web_search` |
| "in my documents", "from my files", "in [folder name]" | `rag` |
| Follow-up referencing previous RAG/search context | Same as previous |
| Everything else | `general` |

### LLM Classification (when ambiguous)

When rule-based routing is uncertain, use the same Qwen3 8B with a short classification prompt:

```
Classify this user query into one of: general, rag, web_search, hybrid.
- general: answerable from general knowledge
- rag: references user's local files/documents
- web_search: needs current/real-time information
- hybrid: needs both local files and web information
Query: "{transcript}"
Classification:
```

### Follow-Up Handling

When in conversation mode:
1. Check if query references previous turn (pronouns: "it", "that", "those"; continuation: "what about", "and also")
2. If previous turn used RAG/web search, default to same source
3. Include previous Q&A pairs in LLM context
4. Allow explicit source switching: "Actually, search the web for that instead"

## Technology Choice & Tradeoffs

| Considered | License | Local | Speed (M1 Pro) | Tool Use | Decision |
|---|---|---|---|---|---|
| **Ollama + Qwen3 8B** | MIT + Apache 2.0 | Yes | ~30–50 tok/s | Yes | **CHOSEN** |
| Ollama + Llama 3.3 8B | MIT | Yes | ~30–50 tok/s | Yes | Slightly lower instruction quality |
| Ollama + Mistral Small 3 7B | Apache 2.0 | Yes | Highest tok/s | Limited | Weaker tool use |

**Why Qwen3 8B:**
- Best-in-class instruction following and conversation for 8B class
- Q4_K_M quantization — ~5GB RAM, fits comfortably on M1 Pro 32GB
- Supports tool/function calling (useful for intent routing)
- `/think` mode for complex queries (chain-of-thought)
- ~30–50 tokens/second — fast enough for streaming to TTS

**Alternative models** (same Ollama infrastructure, swappable via config):
- Qwen3.5 9B — newer, potentially better quality
- Llama 3.3 8B — strong all-around
- Mistral Small 3 7B — fastest if latency is top priority

**Fallback:** llama.cpp directly (Ollama wraps it) or LM Studio.

## System Prompt (Voice-Optimized)

```
You are BMO, a helpful voice assistant. You speak out loud to the user.

Rules:
- Keep responses under 20 seconds of speech (~50-60 words, ~80 tokens). Only expand
  if the user asks: "tell me more", "go on", "expand on that" — then add up to 150
  additional tokens.
- Use natural spoken English, not written language.
- No markdown, bullet points, or formatting — this will be spoken aloud.
- Don't preface answers with "according to your documents" — just answer naturally.
- If unsure, say so briefly: "I'm not sure about that."
- Numbers: say "about two hundred" not "approximately 200".
- When citing sources, say "based on [filename]" or "I found online that..."
- For multi-part questions: "First... Second... And finally..."
- If asked to do something you can't do: "I can't do that yet"
- Speak dates naturally: "March twenty-first" not "2026-03-21"
- For lists: "There are three things. First... second... and third..."

User context:
- Name: {user_name}
- Location: {user_location}
- Temperature units: {temp_units}
- Distance units: {distance_units}
- Timezone: {timezone}
```

## Conversation Memory (5-Minute TTL)

- In-memory list of `{role, content, timestamp}` objects
- Before each LLM call, prune messages with `timestamp` older than 5 minutes
- No persistence to disk — resets on restart or after 5 minutes of silence
- Typically holds 5–15 turns depending on conversation pace
- Owned by session manager, passed to LLM component per request

## Context Window Management

| Source | Typical Tokens |
|---|---|
| System prompt + user context | ~300 |
| Conversation history (within 5-min window) | ~2000 |
| RAG context (top 5 chunks) | ~2500 |
| Web search context (3–5 results) | ~1500 |
| **Total per request** | **~4000–6300** |

Well within 8B model context window (typically 8K–32K tokens).

## Streaming Pipeline

```
Ollama /api/chat (stream:true)
    → token accumulator
    → sentence boundary detection (. ? ! \n)
    → complete sentence → TTS
    → continue accumulating next sentence
```

- **Pipeline parallel**: While TTS synthesizes sentence N, LLM continues generating sentence N+1
- **Force flush**: If buffer exceeds 100 tokens without punctuation
- **Batch short**: Very short sentences batched with next for TTS prosody

## Audio Feedback Triggers

| Trigger | Action | Timing |
|---|---|---|
| Web search intent detected | Play cached "Hmm, let me search the internet." | Immediately |
| RAG intent detected | Play cached "Let me check your documents." | Immediately |
| 3s elapsed, no TTS audio sent | Play cached "Complex question. I'm still thinking." | After 3s timer |

## Ollama Configuration

```yaml
llm:
  model: qwen3:8b               # swappable via config
  host: http://localhost:11434   # Ollama default
  keep_alive: -1                 # model stays loaded PERMANENTLY
  stream: true                   # always stream
```

**`keep_alive: -1`** is critical. Ollama's default unloads models after 5 minutes of inactivity — unacceptable for a voice assistant that must respond instantly.

## Interface with Other Components

| Direction | Component | Data |
|---|---|---|
| **Input from** | Session Manager | Transcript text, conversation history, user preferences |
| **Input from** | RAG Engine | Top-K relevant chunks with metadata (when intent=rag/hybrid) |
| **Input from** | Search Component | Formatted search results (when intent=web_search/hybrid) |
| **Output to** | TTS (via sentence buffer) | Complete sentence strings |
| **Output to** | Session Manager | Intent classification result |
| **Triggers** | RAG Engine | Query for context (when intent=rag/hybrid) |
| **Triggers** | Search Component | Web search (when intent=web_search/hybrid) |

## Logging

Logger name: **`bmo.llm`**

| Level | Message | When |
|---|---|---|
| DEBUG | `Token: "{tok}"` | Per-token (debug only) |
| INFO | `Intent: {rag} (method=rule_based, pattern="in my documents")` | Classification |
| INFO | `LLM request: context_tokens={4200}, history_turns={3}` | Before generation |
| INFO | `LLM TTFT: {280}ms` | Time to first token |
| INFO | `LLM complete: {65} tokens in {1800}ms ({36} tok/s)` | Generation done |
| INFO | `Sentence → TTS: "{First, the weather today is}..."` | Each sentence flushed |
| WARNING | `TTFT {650}ms exceeds 2x baseline ({300}ms)` | Performance degradation |
| WARNING | `3s feedback timer triggered — playing thinking clip` | Slow response |
| ERROR | `Ollama connection failed: {error}` | Connection drop |
| ERROR | `Ollama model not found: {model}. Run: ollama pull {model}` | Missing model |

## Health Checks

All run at startup. **If any fails, BMO refuses to start.**

1. **Ollama running**: `GET /api/tags` returns 200. If not, error: "Ollama is not running. Start with: `ollama serve`"
2. **Model available**: Check `qwen3:8b` in model list. If not, error: "Model not found. Run: `ollama pull qwen3:8b`"
3. **Inference test**: Send prompt "Say hello" → tokens stream back within 5 seconds
4. **Keep-alive set**: Verify keep_alive is configured to -1 (warn if not)

## Edge Cases

| Scenario | Handling |
|---|---|
| Ollama crashes mid-response | Detect connection drop, play error clip, return to IDLE |
| Very long response | Cap at ~80 tokens. "Tell me more" → +150 additional |
| Empty context from RAG/web | Respond from general knowledge, mention couldn't find specific info |
| Ollama not running | Clear startup error with `ollama serve` instructions |
| Model not pulled | Clear startup error with `ollama pull qwen3:8b` instructions |
| Ambiguous intent | LLM classification fallback (adds ~200ms) |

## macOS Considerations

- **Ollama**: Runs as a macOS background service. Install via `brew install ollama`. Auto-starts with `ollama serve`.
- **Metal GPU**: Ollama automatically uses Metal for GPU-accelerated inference on Apple Silicon
- **Memory**: Qwen3 8B Q4_K_M uses ~5GB RAM. With `keep_alive: -1`, this is permanently allocated.
- **Thermal**: LLM generation is the most CPU/GPU-intensive operation. On MacBook, sustained use may cause fan spin. Mac Studio handles this better.

## Relation to Other Components

- **Upstream**: Receives transcript from STT (via session), context from RAG and Search
- **Downstream**: Sends sentence stream to TTS, intent classification to session manager
- **Triggers**: RAG engine and search component (based on intent classification)
- **Depends on**: STT (transcript), session manager (history/preferences), Ollama (external service)
- **Depended on by**: TTS (needs sentence stream), session manager (needs intent + completion signals)
