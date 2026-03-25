# Text-to-Speech — `server/tts/`

## Purpose & Responsibilities

- Convert LLM-generated text to natural-sounding speech using Kokoro TTS
- Stream audio chunks to client for immediate playback
- Participate in LLM→TTS pipeline parallelism (synthesize sentence N while LLM generates N+1)
- Pre-generate and cache feedback audio clips at startup

## Architecture

```
LLM Token Stream
      │
      ▼
┌──────────────────────┐
│  Sentence Buffer     │  ← Accumulates tokens until sentence boundary (. ? ! \n)
│                      │     Flush if >100 tokens without punctuation
│                      │     Batch very short sentences with next
└──────────┬───────────┘
           │ complete sentence
           ▼
┌──────────────────────┐
│  Kokoro TTS Engine   │  ← 82M params, Apache 2.0
│                      │     Local inference, sub-300ms
│  Model kept loaded   │     16kHz 16-bit PCM output
└──────────┬───────────┘
           │ PCM audio chunks
           ▼
   WebSocket Handler → Client Playback

Pipeline Parallelism:
Time →
LLM:  [generate sentence 1] [generate sentence 2] [generate sentence 3]
TTS:                        [synthesize sent 1]   [synthesize sent 2]   [synth 3]
Play:                                             [play sent 1]        [play 2]
```

## Technology Choice & Tradeoffs

| Considered | License | Local | Latency | Quality | Decision |
|---|---|---|---|---|---|
| **Kokoro TTS (82M)** | Apache 2.0 | Yes | Sub-300ms | Best local quality | **CHOSEN** |
| Piper TTS | MIT | Yes | Very fast | Good but more robotic | Quality gap |
| Coqui/XTTS | Open | Yes | Slower | Good | Heavier, slower |
| Edge TTS | Proprietary (free API) | No | ~100ms | Good | Microsoft API, not open source |

**Why Kokoro TTS:**
- Apache 2.0 license, runs 100% locally
- 82M parameters — lightweight enough for CPU inference on M1 Pro
- Best quality among local TTS models (2026 benchmarks)
- Sub-300ms processing, 36x real-time on GPU
- Natural-sounding English voices

**Fallback chain:** Kokoro → Piper TTS (robotic but fast, battle-tested) → macOS `say` command (emergency, always available).

## Sentence Buffer Logic

The sentence buffer sits between LLM streaming output and TTS:

1. **Accumulate tokens** from LLM stream
2. **Detect sentence boundaries**: period `.`, question mark `?`, exclamation `!`, newline `\n`
3. **Flush on boundary**: Send complete sentence to Kokoro
4. **Force flush**: If buffer exceeds 100 tokens without punctuation, flush anyway
5. **Batch short sentences**: If sentence is very short ("Yes."), batch it with the next sentence for better prosody
6. **Final flush**: When LLM stream ends, flush any remaining buffer

## Pre-Generated Feedback Clips

At startup, synthesize and cache in memory (no TTS inference needed at runtime):

| Clip | Trigger |
|---|---|
| "Hmm, let me search the internet." | Web search intent detected |
| "Complex question. I'm still thinking." | 3s timer expires before TTS audio sent |
| "Let me check your documents." | RAG intent detected |
| "Sorry, I didn't catch that." | Empty STT transcript |
| "Sorry, I had a problem. Could you ask again?" | Pipeline error |

These clips are PCM audio arrays stored in memory, played instantly via WebSocket.

## Prosody Considerations

- **Limitation**: Kokoro processes each sentence independently — no prosody continuity across sentence boundaries
- **Within-chunk workaround**: Feed multiple sentences in a single chunk (up to ~510 phoneme tokens, ~30s audio) so the model sees them together
- **Audio stitching**: Apply 50–100ms crossfade between consecutive audio chunks to smooth boundaries
- **Practical impact**: Short responses (1–2 sentences) are unaffected. Only multi-sentence responses have potential discontinuity.
- **Future**: Backlog B-18 tracks research into better cross-sentence prosody

## Interface with Other Components

| Direction | Component | Data |
|---|---|---|
| **Input from** | LLM (via sentence buffer) | Complete sentence strings |
| **Output to** | WebSocket handler | PCM audio chunks (16kHz, 16-bit, mono, little-endian) |
| **Signals** | Session Manager | Playback started (→ SPEAKING), playback complete (→ CONVERSATION) |
| **Provides** | Session Manager | Pre-generated feedback clips for instant playback |

## Audio Format

```
Sample rate:  16000 Hz
Bit depth:    16-bit signed
Channels:     Mono
Encoding:     PCM little-endian (pcm_s16le)
```

## Configuration

```yaml
tts:
  model: kokoro-82m
  voice: default-en             # specific voice TBD after testing
  sample_rate: 16000
  format: pcm_s16le
  crossfade_ms: 75              # crossfade between chunks for prosody smoothing
  max_response_tokens: 80       # ~20s speech, ~50-60 words
  expand_tokens: 150            # additional tokens when user says "tell me more"
```

## Logging

Logger name: **`bmo.tts`**

| Level | Message | When |
|---|---|---|
| DEBUG | `Synthesis details: phonemes={N}, frames={M}` | Per-sentence internals |
| INFO | `TTS: "{sentence_preview}..." (latency={180}ms, audio={2.1}s)` | Each synthesis |
| INFO | `Pre-generated {5} feedback clips at startup ({X}ms total)` | Startup |
| INFO | `Playing feedback: "Hmm, let me search the internet."` | Feedback clip played |
| INFO | `Response audio complete: {3} sentences, total={4.2}s` | End of response |
| WARNING | `TTS inference >3s for single sentence` | Performance |
| ERROR | `Failed to load Kokoro model: {error}` | Startup failure |
| ERROR | `TTS synthesis failed for sentence, skipping: {error}` | Runtime failure |

## Health Checks

All run at startup. **If any fails, BMO refuses to start.**

1. **Model loads**: Load Kokoro model into memory without error
2. **Inference test**: Synthesize "Hello, I am BMO" → non-empty audio output within 2 seconds
3. **Feedback clips**: Pre-generate all feedback clips → verify all cached successfully

## Edge Cases

| Scenario | Handling |
|---|---|
| TTS fails on a sentence | Skip that sentence, continue with next |
| Special chars/URLs in LLM output | Strip or normalize before synthesis |
| Very short sentence ("Yes.") | Batch with next sentence for better prosody |
| Response too long | Cap at ~80 tokens (~20s speech). "Tell me more" → +150 tokens. |
| Kokoro model corrupted | Inference test catches at startup |

## macOS Considerations

- **CPU inference**: Kokoro 82M runs efficiently on CPU (~400MB RAM). No dedicated GPU needed.
- **Audio output device**: Audio is played by the client (browser), not by the server. Server only generates PCM data.
- **Memory**: ~400MB for model + ~5MB for cached feedback clips. Stays loaded permanently.
- **Apple Silicon**: Benefits from unified memory but Kokoro doesn't have an MLX backend (runs on PyTorch/ONNX)

## Relation to Other Components

- **Upstream**: Receives sentence strings from LLM component's streaming output (via sentence buffer)
- **Downstream**: Sends PCM audio to WebSocket handler for delivery to client
- **Signals**: Session manager (playback start/end for state transitions)
- **Depends on**: LLM (for text input), WebSocket handler (for audio delivery)
- **Depended on by**: Session manager (for state transitions), client (for audio playback)
