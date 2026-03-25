# Audio Pipeline — `server/audio/`

VAD + Noise Reduction. Does **not** include STT or TTS (see `server/stt/` and `server/tts/`).

## Purpose & Responsibilities

- Clean incoming audio via noise gate + neural noise suppression (RNNoise)
- Detect when the user starts and stops speaking (Silero VAD)
- Provide end-of-turn signal to trigger STT processing
- Buffer clean audio for handoff to STT
- Handle mic muting during SPEAKING state (echo cancellation)
- Calibrate to ambient noise at session start

## Architecture

```
Raw PCM Audio (from WebSocket)
         │
         ▼
┌─────────────────────────┐
│  Stage 1: Noise Gate    │  ← Discard frames below energy threshold
│  (~0% CPU)              │     Calibrated at session start
└────────┬────────────────┘
         │ frames above gate
         ▼
┌─────────────────────────┐
│  Stage 2: RNNoise       │  ← Neural noise suppression
│  (10ms frames, ~2% CPU) │     Removes fan, AC, TV, traffic
└────────┬────────────────┘
         │ clean audio
         ▼
┌─────────────────────────┐
│  Stage 3: Silero VAD    │  ← Voice activity detection
│  (30ms frames, ~5% CPU) │     Detects speech start/end
└────────┬────────────────┘
         │
    ┌────┴────────────────────┐
    │                          │
    ▼                          ▼
speech-start event       speech-end event
(begin buffering)        (send buffer → STT)
    │                          │
    └──────────┬───────────────┘
               ▼
        Session Manager
```

### Mic Muting (Echo Cancellation)

```
Session State = SPEAKING
    → Mic input DISABLED entirely
    → No audio flows through pipeline
    → Wake word detector also paused

TTS playback complete
    → Wait 200ms (reverb decay)
    → Mic input ENABLED
    → Pipeline resumes
```

## Sub-Components

### Stage 1: Noise Gate

- Discard audio frames below a minimum energy threshold
- Near-zero CPU cost
- **Calibration**: At session start, measure 2 seconds of ambient noise. Set gate threshold at 1.5x the ambient noise floor.
- Filters: dead silence, quiet electrical hum, very low background noise
- Always-on when audio pipeline is active

### Stage 2: RNNoise Neural Noise Suppression

| Considered | License | Latency | Strength | Decision |
|---|---|---|---|---|
| **RNNoise** | BSD | < 1ms/frame | Excellent for steady noise | **CHOSEN** |
| DeepFilterNet | MIT | ~5ms/frame | Better speech separation | Overkill for home noise |
| WebRTC NS | Open | < 1ms/frame | Good for low noise | Weak on TV speech |

**Why RNNoise:**
- BSD license, fully open source, by Mozilla/Xiph.org
- Designed specifically for real-time speech denoising
- Handles home noise well: fans, AC, TV, keyboard, traffic
- ~2% CPU on M1 Pro, processes 10ms frames
- Runs before VAD and STT — both see cleaner audio and perform better

**Fallback:** WebRTC noise suppression or `noisereduce` Python library.

### Stage 3: Silero VAD

| Considered | License | TPR@5% FPR | Decision |
|---|---|---|---|
| **Silero VAD** | MIT | 87.7% | **CHOSEN** |
| WebRTC VAD | Open | 50% | Unacceptable accuracy |
| Cobra (Picovoice) | Proprietary | 98.9% | Paid |

**Why Silero VAD:**
- MIT license, zero cost, runs locally
- 87.7% TPR is strong — wake word pre-filters most noise before VAD sees it
- PyTorch/ONNX — native Apple Silicon support

**VAD Logic:**
- Process 30ms frames
- **Speech start**: 3 consecutive frames above speech threshold → begin buffering audio
- **Speech end**: 500ms of continuous silence (configurable) → trigger STT with buffered audio
- **Adaptive threshold**: Calibrate based on ambient noise measurement at session start

**Fallback:** WebRTC VAD (degraded accuracy) or whisper.cpp built-in silence detection.

### Echo Cancellation

**Chosen approach: Mic muting during SPEAKING state.**

BMO does not accept any input while speaking. The mic is fully muted during the SPEAKING state. After TTS playback completes, wait 200ms for room reverb decay, then unmute.

| Approach | How | Pros | Cons |
|---|---|---|---|
| **Mic muting (CHOSEN)** | Disable mic during playback | Simplest, zero echo | No wake word during speech |
| Software AEC | Subtract TTS reference from mic | Wake word works during speech | Complex time-alignment |
| WebRTC AEC3 | Browser built-in | Zero server work | Quality varies by browser |
| Hybrid | Client AEC + server gating | Defense in depth | Most complex |

Mic muting is the permanent design. The alternatives are documented for reference if the design ever changes to allow barge-in (see backlog).

## Home Environment Noise Handling

| Noise Source | Primary Defense | Secondary Defense |
|---|---|---|
| **TV playing** | RNNoise reduces significantly | Wake word gate ignores non-"Hey Beemo" audio |
| **Fan / AC / hum** | RNNoise handles excellently | Noise gate filters below-speech energy |
| **Other people** | 30s conversation window limits exposure | 500ms min speech filter in conversation mode |
| **Kitchen sounds** | RNNoise + noise gate | Intermittent — VAD pauses between sounds |

For persistent noise issues: push-to-talk mode (backlog B-10).

## Interface with Other Components

| Direction | Component | Data |
|---|---|---|
| **Input from** | WebSocket handler | Raw PCM audio (16kHz, 16-bit, mono) |
| **Output to** | STT | Clean buffered audio on speech-end event |
| **Output to** | Session Manager | Speech-start and speech-end events |
| **Controlled by** | Session Manager | Mute/unmute commands, activate/deactivate |
| **Shares with** | Wake Word | Same raw audio stream (wake word runs on raw; this pipeline processes it) |

### When Each Stage is Active

| Session State | Noise Gate | RNNoise | VAD |
|---|---|---|---|
| IDLE | Off | Off | Off |
| LISTENING | On | On | On |
| PROCESSING | Off | Off | Off |
| SPEAKING | Off (muted) | Off (muted) | Off (muted) |
| CONVERSATION | On | On | On |

## Configuration

```yaml
audio:
  noise_gate_enabled: true
  noise_gate_calibration_seconds: 2      # ambient noise measurement duration
  rnnoise_enabled: true                  # neural noise suppression
  echo_cancellation: mute               # only option currently
  reverb_decay_ms: 200                  # delay after playback before unmute

conversation:
  min_speech_duration_ms: 500           # minimum speech to trigger processing
  silence_threshold_ms: 500             # silence duration to trigger end-of-speech
  max_utterance_seconds: 30             # segment long utterances
  no_speech_timeout_seconds: 5          # timeout if no speech after wake word
```

## Logging

Logger name: **`bmo.audio`**

| Level | Message | When |
|---|---|---|
| DEBUG | `VAD frame: confidence={0.87}` | Per-frame (debug only) |
| DEBUG | `Noise gate: {passed}/{total} frames passed` | Periodic summary |
| INFO | `Ambient noise calibrated: threshold={X} dB` | Session start |
| INFO | `Speech started` | VAD detects speech onset |
| INFO | `Speech ended (duration={2.3}s, buffer_size={36800} samples)` | VAD end-of-speech |
| INFO | `Mic muted for playback` | Entering SPEAKING |
| INFO | `Mic unmuted after {200}ms reverb decay` | Leaving SPEAKING |
| WARNING | `VAD listening >60s with no speech detected — mic may be disconnected` | Watchdog |
| WARNING | `RNNoise frame latency {X}ms exceeds 5ms target` | Performance |
| ERROR | `Failed to load Silero VAD model: {error}` | Startup |
| ERROR | `Failed to initialize RNNoise: {error}` | Startup |

## Health Checks

All run at startup. **If any fails, BMO refuses to start.**

1. **Silero VAD silence test**: Feed 1 second of silent audio → all frames below speech threshold
2. **Silero VAD speech test**: Feed synthetic speech clip → detects speech frames
3. **RNNoise load test**: Initialize and process one test frame without error

## Edge Cases

| Scenario | Handling |
|---|---|
| Filler words ("um", "uh") | Don't trigger end-of-turn on pauses < 300ms |
| No speech after wake word | 5-second timeout → return to IDLE |
| Very long utterance (>30s) | Segment at 30s boundaries, concatenate transcripts |
| Min speech in conversation mode | Require 500ms continuous speech (prevents noise triggers) |
| Back-to-back utterances | 200ms grace period before returning to idle |
| Mic disconnected mid-session | VAD watchdog detects, logs warning |

## macOS Considerations

- **Audio input device**: Use system default or allow user to configure a specific device
- **Sample rate negotiation**: Pipeline needs 16kHz. If mic provides 44.1/48kHz, resample down. Use `sounddevice` or `pyaudio` for Core Audio access.
- **Core Audio via PyAudio or sounddevice**: Both support macOS Core Audio backend natively
- **Energy**: Combined ~7% CPU (noise gate + RNNoise + VAD) during active listening. Negligible thermal impact.

## Relation to Other Components

- **Upstream**: Receives raw audio from WebSocket handler
- **Downstream**: Sends clean buffered audio to STT on speech-end; sends events to session manager
- **Parallel with**: Wake word detector (both consume same raw audio stream)
- **Depends on**: WebSocket handler (for audio input), session manager (for state commands)
- **Depended on by**: STT (needs clean audio), session manager (needs speech events)
