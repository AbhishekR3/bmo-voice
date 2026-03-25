# Speech-to-Text — `server/stt/`

## Purpose & Responsibilities

- Convert buffered audio to text after VAD signals end-of-turn
- Fast, accurate English transcription using whisper.cpp with MLX backend
- Support wake word verification (quick STT pass to confirm "hey beemo" in audio)

## Architecture

```
Clean Audio Buffer (from Audio Pipeline, on speech-end event)
         │
         ▼
┌──────────────────────────────┐
│   whisper.cpp MLX Engine     │
│                              │
│   Model: whisper-tiny.en     │
│   Backend: MLX (Apple Si)    │
│   Language: English only     │
│                              │
│   Kept loaded in memory      │
│   (no reload per utterance)  │
└──────────┬───────────────────┘
           │
           ▼
    Transcript: "what's the weather today"
           │
     ┌─────┴──────────────────────┐
     │                             │
     ▼                             ▼
Session Manager               Wake Word Verification
(→ Intent Router)             (confirms "hey beemo" in transcript)
```

### Processing Mode

**Not streaming** — processes the complete utterance buffer at once. This is efficient because:
- Wake word detection already identifies the start of speech
- VAD already identifies the end of speech
- The complete buffer is typically 1–10 seconds — whisper.cpp transcribes this faster than real-time

## Technology Choice & Tradeoffs

| Considered | License | Local | Latency (M1 Pro) | Decision |
|---|---|---|---|---|
| **whisper.cpp (MLX)** | MIT | Yes | ~300–500ms | **CHOSEN** |
| faster-whisper | MIT | Yes | ~600–1000ms | CTranslate2 less optimized for Apple Silicon |
| Deepgram Nova-3 | Proprietary | No | ~200ms | Paid service |
| WhisperKit (Swift) | MIT | Yes | ~460ms | Swift-only, harder Python integration |

**Why whisper.cpp with MLX:**
- MIT license, runs 100% locally
- MLX backend specifically optimized for Apple Silicon (M1/M2/M3/M4)
- Uses Apple's unified memory — no CPU↔GPU transfer overhead
- Faster than real-time on M1 Pro
- No API keys, no network, no cost

**Fallback:** faster-whisper (CTranslate2) as direct replacement. Same input/output contract.

## Model Selection

| Model | Params | RAM | Disk | English WER | Speed (M1 Pro) | Notes |
|---|---|---|---|---|---|---|
| **tiny.en** | 39M | ~273 MB | 75 MiB | ~7.6% | ~10x RT | **CHOSEN** — fastest, lowest resource |
| base.en | 74M | ~388 MB | 142 MiB | ~5.0% | ~5x RT | Better accuracy, still fast |
| small.en | 244M | ~852 MB | 466 MiB | ~3.4% | ~3x RT | Upgrade if accuracy insufficient |
| medium.en | 769M | ~2.1 GB | 1.5 GiB | ~2.9% | ~1.5x RT | High accuracy, noticeable wait |

*RT = Real-time. 10x RT means a 5-second utterance takes ~0.5 seconds.*

**Practical impact for a typical 3–5 second voice query:**

| Model | Time to transcribe 5s audio | Effective error rate |
|---|---|---|
| **tiny.en** | **~0.5s** | **~1 in 13 words wrong** |
| base.en | ~1.0s | ~1 in 20 words wrong |
| small.en | ~1.5–1.7s | ~1 in 30 words wrong |

**Why tiny.en:** For short, clear utterances (3–5s) in a home environment with noise suppression (RNNoise), the effective WER is better than the benchmark 7.6%. The ~0.5s latency savings vs small.en is significant for perceived responsiveness.

**Upgrade path:** If users report frequent transcription errors, switch to small.en via config. No code changes needed.

### Wake Word Verification

Same whisper.cpp engine, used for a quick STT pass on the wake word audio buffer:
1. Wake word detector fires with audio buffer
2. Run STT on that buffer
3. Check if transcript contains "hey beemo" (or variants: "hey bmo", "hey beamo")
4. If not → discard, return to IDLE (false positive caught)
5. If yes → proceed with pipeline

Adds ~100–200ms but eliminates most false positives.

## Interface with Other Components

| Direction | Component | Data |
|---|---|---|
| **Input from** | Audio Pipeline | Clean PCM audio buffer (16kHz, 16-bit, mono) on speech-end event |
| **Input from** | Wake Word | Audio buffer for verification pass |
| **Output to** | Session Manager | Transcript text string |
| **Output to** | Session Manager | Wake word verification result (confirmed/rejected) |

## Optimization

- **Keep model loaded in memory** — no reload per utterance (model stays warm)
- **MLX unified memory** — no CPU↔GPU data transfer on Apple Silicon
- **English-only model** — faster and more accurate than multilingual for English
- **Pre-allocated audio buffer** — avoid allocation during recording
- **beam_size: 5** — good accuracy/speed tradeoff

## Configuration

```yaml
stt:
  model: whisper-tiny.en        # upgrade to whisper-small.en if accuracy insufficient
  backend: mlx                  # or cpu (fallback for non-Apple-Silicon)
  language: en
  beam_size: 5
  model_dir: ~/.bmo-voice/models/
```

## Logging

Logger name: **`bmo.stt`**

| Level | Message | When |
|---|---|---|
| DEBUG | `Whisper decode step details` | Internal decode (debug only) |
| INFO | `Transcription: "{text}" (audio={2.3}s, latency={412}ms)` | Every transcription |
| INFO | `Wake word verification: "{text}" confirmed={true}` | After verification pass |
| INFO | `Model loaded: {model_name} ({backend}) in {X}ms` | Startup |
| WARNING | `Empty transcript for {2.3}s audio` | Possible issue |
| WARNING | `3 consecutive empty transcripts — STT may be degraded` | Recurring issue |
| WARNING | `STT latency {650}ms exceeds 500ms target` | Performance |
| ERROR | `Failed to load whisper model: {model} — {error}` | Startup failure |
| ERROR | `Model file not found: {path}` | Missing model |

## Health Checks

All run at startup. **If any fails, BMO refuses to start.**

1. **Model exists**: Verify model files exist at configured path. If missing, error with download instructions (`mlx_whisper download whisper-tiny.en` or equivalent).
2. **Model loads**: Load into MLX/ONNX runtime without error.
3. **Inference test**: Transcribe a short synthetic "hello" audio clip → non-empty transcript within 2 seconds.

## Edge Cases

| Scenario | Handling |
|---|---|
| Empty/mumbled input | Transcript empty or <3 chars → play "Sorry, I didn't catch that" |
| Background noise transcribed | Confidence filtering — discard low-confidence results |
| Long utterance (>30s) | Process in 30s segments, concatenate transcripts |
| Model not downloaded | Clear error at startup with download instructions |
| Corrupted model file | Inference test catches at startup |

## macOS Considerations

- **MLX backend**: Leverages Apple Silicon unified memory — models stay in shared CPU/GPU memory pool. No data copying between processors.
- **Core ML acceleration**: Available for additional speed on supported models
- **Model storage**: `~/.bmo-voice/models/` — ensure adequate disk space (~75MB for tiny.en, ~466MB for small.en)
- **Memory**: tiny.en uses ~273MB resident. Stays loaded permanently.

## Relation to Other Components

- **Upstream**: Receives clean audio buffer from audio pipeline (after noise reduction + VAD)
- **Downstream**: Sends transcript to session manager, which routes to intent router (in LLM component)
- **Also serves**: Wake word component (verification passes)
- **Depends on**: Audio pipeline (for clean audio), session manager (for triggering)
- **Depended on by**: LLM/intent router (needs transcript text), wake word (verification)
