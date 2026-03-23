# BMO Voice - Backlog

Items here are **not in the MVP (Phases 1-4)** but are planned for future development. Ordered roughly by expected priority, but subject to change.

---

## B-01: Conversation Memory & History Persistence
**Status**: Needs research and design
**Why deferred**: Current 5-minute TTL is a deliberate simplification. Persistent memory raises questions about:
- Storage format: flat files, SQLite, or vector DB?
- What to persist: full transcripts, summaries, or embeddings?
- Privacy: should conversations be encrypted at rest?
- Retrieval: how does BMO recall relevant past conversations?
- Retention policy: forever? 30 days? User-configurable?
- Cross-session context: "last time we discussed X" — how to implement efficiently?
- Rolling summary approach: summarize older turns to save context window space?

**Current state**: In-memory only, 5-minute TTL, no persistence.
**Research needed**: Evaluate rolling summary vs full history, vector-based conversation recall, and privacy/encryption models.

---

## B-02: Multi-User Support
**Status**: Needs design
**Description**: Support multiple users interacting with the same BMO instance.
- Speaker identification to distinguish users
- Per-user preferences (name, location, units)
- Per-user conversation history
- Speaker embedding models (e.g., Resemblyzer, SpeechBrain) for voice profiles
- Enrollment flow: "Hey Beemo, remember my voice as [name]"
- All processing local, voice profiles stored on device

---

## B-03: Multi-Modal Analysis
**Status**: Future consideration
**Description**: Analyze images, diagrams, and other non-text content.
- Image analysis in RAG documents (PDFs with charts, diagrams)
- Screen capture analysis
- Would require a vision-capable local model (e.g., LLaVA)
- Significant additional RAM requirements

---

## B-04: Text Chat Interface
**Status**: Future consideration
**Description**: Add text-based interaction alongside voice.
- Type questions in the web UI
- See responses as text (in addition to/instead of voice)
- Useful for noisy environments or when voice is inconvenient
- Same pipeline minus wake word/VAD/STT/TTS

---

## B-05: Personality Fine-Tuning
**Status**: Needs design
**Description**: Customizable BMO personality beyond the current neutral assistant.
- Personality profiles defined as system prompt templates
- Adjustable parameters: tone, humor level, formality, verbosity, character
- Named profiles: "professional", "casual", "playful", "BMO" (Adventure Time character)
- Per-session selection ("Hey Beemo, be more casual") or persistent default
- Could allow user-written custom personality prompts

---

## B-06: Voice Cloning
**Status**: Research needed
**Description**: Clone a specific voice for BMO's TTS output.
- Kokoro TTS may support voice cloning or fine-tuning (needs investigation)
- Alternative: XTTS v2 (open source) supports voice cloning from ~6 seconds of audio
- Use case: clone BMO from Adventure Time, or a user's preferred voice
- Privacy consideration: voice samples stored locally only

---

## B-07: Energy / Resource Dashboard
**Status**: Ready to implement
**Description**: Monitor and display system resource usage.
- Real-time CPU, RAM, GPU utilization per component
- Model loading status (which models are warm/cold)
- Per-component latency breakdown (wake word → VAD → STT → LLM → TTS)
- Temperature monitoring (important for sustained use on MacBook)
- Disk usage (model storage + ChromaDB index size)

---

## B-08: Agentic Actions
**Status**: Needs design + security model
**Description**: Let BMO execute actions beyond just answering questions.
- **Tier 1 (safe)**: Create/edit files, set timers, take notes
- **Tier 2 (cautious)**: Run shell commands, open applications, manage files
- **Tier 3 (dangerous)**: Send emails, interact with web services
- Requires explicit permission model
- Voice confirmation for destructive actions
- **Prerequisite**: Multi-user support (B-02) for security if needed

---

## B-09: Reranking for RAG
**Status**: Ready to implement
**Description**: Add a reranking step after initial vector retrieval for better precision.
- Use a cross-encoder model (e.g., `cross-encoder/ms-marco-MiniLM-L-6-v2`) — open source, runs locally
- Rerank top-20 results down to top-5 after initial ChromaDB retrieval
- Adds ~50-100ms latency but significantly improves answer relevance
- Only activate when retrieval returns chunks with similar scores (ambiguous results)

---

## B-10: Push-to-Talk Mode
**Status**: Ready to implement
**Description**: Alternative to wake word for noisy environments.
- Global keyboard shortcut to activate/deactivate listening
- Bypasses wake word detection entirely
- Hold-to-talk or toggle mode
- Could use macOS global hotkey or browser-based shortcut

---

## B-11: Proactive Suggestions
**Status**: Ambitious / research
**Description**: BMO notices changes in your files and offers insights.
- Monitor indexed folders for significant changes
- "Hey, I noticed you updated the API docs — want me to summarize what changed?"
- Only surfaces suggestions when user is idle
- Needs careful UX design to avoid being annoying

---

## B-12: Mac Studio Deployment Optimization
**Status**: Planned for hardware migration
**Description**: Optimize for Mac Studio's additional resources.
- Larger LLM models (Qwen3.5 27B or Llama 3.3 70B if RAM allows)
- whisper-medium.en or turbo for higher STT accuracy
- Run Ollama with more GPU layers
- Potentially run multiple models concurrently (STT + LLM overlap)
- Always-on daemon mode with launchd

---

## B-13: Response Length Control
**Status**: Ready to implement
**Description**: Let user control verbosity dynamically.
- "Hey Beemo, give me more detail" → switches to detailed mode
- "Hey Beemo, keep it short" → switches to concise mode
- Adjusts system prompt dynamically
- Persists preference in config

---

## B-14: Citation Display
**Status**: Ready to implement (after UI exists)
**Description**: Visual display of RAG sources in the UI.
- When RAG is used, show which files were referenced
- Clickable file paths to open in Finder/editor
- Verbal citation: "Based on your notes file..." (already in system prompt)

---

## B-15: Mobile Access
**Status**: Ambitious / future
**Description**: Access BMO from phone on same network.
- PWA (Progressive Web App) for mobile browser
- Same WebSocket protocol — phone connects to Mac over local network
- Useful for quick voice queries away from desk

---

## Backlog Summary

| ID | Item | Complexity | Dependencies |
|----|------|-----------|--------------|
| B-01 | Conversation memory persistence | High | Needs research |
| B-02 | Multi-user support | High | Speaker embedding research |
| B-03 | Multi-modal analysis | High | Vision model research |
| B-04 | Text chat interface | Medium | Phase 4 complete |
| B-05 | Personality fine-tuning | Low-Medium | None |
| B-06 | Voice cloning | High | TTS research |
| B-07 | Energy/resource dashboard | Medium | None |
| B-08 | Agentic actions | Very High | B-02 (for security) |
| B-09 | RAG reranking | Low | Phase 2 complete |
| B-10 | Push-to-talk | Low | Phase 1 complete |
| B-11 | Proactive suggestions | High | Phase 2 complete |
| B-12 | Mac Studio optimization | Medium | Hardware available |
| B-13 | Response length control | Low | Phase 1 complete |
| B-14 | Citation display | Low | Phase 2 + Phase 4 UI |
| B-15 | Mobile access | Medium | Phase 4 complete |
