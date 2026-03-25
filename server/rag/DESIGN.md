# RAG Engine — `server/rag/`

## Purpose & Responsibilities

- Index user-specified folders into a local vector database (text content only)
- Retrieve relevant chunks for user queries
- Keep index up-to-date as files change via file watcher
- Support folder registration and unregistration
- Provide context to the LLM for document-aware responses

## Architecture

```
┌───────────────────────────────────────────────────────────────┐
│  INDEXING PIPELINE (background)                                │
│                                                                │
│  Folder Registration                                           │
│       │                                                        │
│       ▼                                                        │
│  ┌──────────────────┐                                          │
│  │  File Watcher    │  ← watchdog (FSEvents on macOS)          │
│  │  (background)    │     Monitors all registered folders      │
│  │  2s debounce     │     Detects add/modify/delete            │
│  └────────┬─────────┘                                          │
│           │ file event                                         │
│           ▼                                                    │
│  ┌──────────────────┐                                          │
│  │  Document Loader │  ← unstructured (PDF/DOCX)              │
│  │                  │     raw read (text/code)                 │
│  │  Text extraction │     Images/diagrams skipped              │
│  │  only            │                                          │
│  └────────┬─────────┘                                          │
│           │ raw text + metadata                                │
│           ▼                                                    │
│  ┌──────────────────┐                                          │
│  │  Chunker         │  ← Recursive character splitting         │
│  │                  │     512 tokens, 50 token overlap          │
│  │                  │     Code: AST-aware via tree-sitter       │
│  └────────┬─────────┘                                          │
│           │ chunks + metadata                                  │
│           ▼                                                    │
│  ┌──────────────────┐                                          │
│  │  BGE Embedder    │  ← BGE-small-en-v1.5 (384 dims)         │
│  │  (batches of 32) │     via sentence-transformers             │
│  └────────┬─────────┘                                          │
│           │ vectors                                            │
│           ▼                                                    │
│  ┌──────────────────┐                                          │
│  │  ChromaDB        │  ← Persistent at ~/.bmo-voice/chroma/   │
│  │  (per-folder     │     HNSW indexing                         │
│  │   collections)   │     Metadata filtering                    │
│  └──────────────────┘                                          │
│                                                                │
└───────────────────────────────────────────────────────────────┘

┌───────────────────────────────────────────────────────────────┐
│  QUERY FLOW (on demand)                                        │
│                                                                │
│  User Query (from Intent Router)                               │
│       │                                                        │
│       ▼                                                        │
│  [BGE Embed Query] → [ChromaDB Similarity Search] → Top-K     │
│       (~10-20ms)         (~5ms)                    Chunks      │
│                                                       │        │
│                                                       ▼        │
│                                              LLM Context       │
│                                              (~2500 tokens)    │
└───────────────────────────────────────────────────────────────┘
```

## Sub-Components

### Document Loader

**Supported formats:**

| Format | Extraction Method | Notes |
|---|---|---|
| `.txt`, `.md` | Raw read | Direct text |
| `.py`, `.js`, `.ts`, `.json`, `.yaml`, `.csv` | Raw read | Code/data files |
| `.html` | Raw read + strip tags | Text content only |
| `.pdf` | `unstructured` library | Text extraction only — images/diagrams skipped |
| `.docx` | `unstructured` library | Text extraction only — images/charts skipped |

**Text extraction only**: Images, diagrams, and non-text elements are silently skipped. BMO responds based on whatever text is available.

**Metadata per document**: file path, file type, folder name, last modified timestamp, title (if extractable).

### Chunker

- **Strategy**: Recursive character splitting at 512 tokens
- **Overlap**: 50 tokens (~10%) for context continuity at chunk boundaries
- **Separators** (priority order): `\n\n` → `\n` → `. ` → ` ` → `` (empty)
- **Code files**: Split at function/class boundaries when possible using tree-sitter for AST-aware splitting
- **Metadata per chunk**: source file path, chunk index, character offset, folder name
- **Benchmark**: Recursive 512-token splitting topped Feb 2026 benchmarks at 69% accuracy

### Embedding & Storage

**Embedding model: BGE-small-en-v1.5**

| Considered | License | Local | Latency | Dimensions | Decision |
|---|---|---|---|---|---|
| **BGE-small-en-v1.5** | MIT | Yes | ~10–20ms | 384 | **CHOSEN** |
| all-MiniLM-L6-v2 | Apache 2.0 | Yes | ~10ms | 384 | Slightly lower retrieval quality |
| BGE-M3 | MIT | Yes | ~50ms | 1024 | Overkill — multilingual not needed |

**Why BGE-small-en-v1.5**: Optimized for English, 384 dimensions (fast similarity search), ~10–20ms per embedding, runs on CPU. Fallback: all-MiniLM-L6-v2 (drop-in, same dimension).

**Vector database: ChromaDB**

| Considered | License | In-Process | Metadata Filtering | Decision |
|---|---|---|---|---|
| **ChromaDB** | Apache 2.0 | Yes | Yes | **CHOSEN** |
| FAISS | MIT | Yes | No | Lower-level, no metadata |
| LanceDB | Apache 2.0 | Yes | Yes | Newer, less ecosystem |
| Qdrant | Apache 2.0 | No (separate process) | Yes | Heavier |

**Why ChromaDB**: In-process (zero network latency), metadata filtering (filter by folder/file type), persistent to disk, HNSW indexing.

**Storage**:
- Persistent at `~/.bmo-voice/chroma/`
- One collection per registered folder
- Batch embedding: process chunks in batches of 32 during indexing
- Parallel indexing: multiple files can be chunked and embedded concurrently

### Retrieval

- Embed query with same BGE model → ChromaDB cosine similarity search
- **Top-k**: 5 chunks by default (configurable)
- **Metadata filtering**: Restrict to specific folders if user mentions one by name
- **Total context**: ~2500 tokens from top-5 chunks (512 tokens × 5)
- **Future improvement**: Reranking with cross-encoder (backlog B-09, adds ~50–100ms but improves relevance)

### File Watcher

- **Library**: `watchdog` (Apache 2.0) — uses macOS FSEvents natively
- Monitors all registered folders recursively
- **On file add/modify**: Re-chunk and re-embed only the affected file (delete old chunks first)
- **On file delete**: Remove all chunks for that file from ChromaDB
- **Debounce**: 2-second delay to batch rapid saves (e.g., IDE auto-save)
- Runs as background thread, never blocks the voice pipeline

## Interface with Other Components

| Direction | Component | Data |
|---|---|---|
| **Input from** | Intent Router (LLM) | Query text string (when intent=rag or hybrid) |
| **Input from** | Config / WebSocket | Folder registration/unregistration commands |
| **Output to** | LLM Component | Top-K chunks with metadata (source file, score) |
| **Background** | File system | Watches registered folders for changes |

## Configuration

```yaml
rag:
  embedding_model: bge-small-en-v1.5
  chunk_size: 512              # tokens per chunk
  chunk_overlap: 50            # overlap between chunks
  top_k: 5                    # retrieval results per query
  max_chunks_per_file: 1000   # prevent index bloat from huge files
  batch_size: 32              # embedding batch size
  chroma_path: ~/.bmo-voice/chroma/

folders:
  - path: /Users/me/Documents/notes
    name: "My Notes"
  - path: /Users/me/projects/myapp
    name: "MyApp Code"
```

## Logging

Logger name: **`bmo.rag`**

| Level | Message | When |
|---|---|---|
| DEBUG | `Embedding chunk {3}/{47}: latency={12}ms` | Per-chunk (debug only) |
| DEBUG | `Similarity scores: [{0.89}, {0.76}, {0.71}, ...]` | Query results detail |
| INFO | `Indexed: {path} → {47} chunks` | File indexed |
| INFO | `Re-indexed: {path} (modified)` | File updated |
| INFO | `Removed from index: {path}` | File deleted |
| INFO | `Query: "{text}" → {5} results (top_score={0.89}, latency={25}ms)` | Each query |
| INFO | `Folder registered: {path} ({120} files, {2340} chunks, {45}s)` | Folder added |
| INFO | `Folder unregistered: {path} (removed {2340} chunks)` | Folder removed |
| WARNING | `Embedding latency {520}ms exceeds 500ms target` | Performance |
| WARNING | `Zero results for query against non-empty collection "{name}"` | Possible issue |
| WARNING | `File exceeds 1000 chunk limit: {path} (truncated)` | Large file |
| WARNING | `Unsupported file type skipped: {path}` | Binary/unknown file |
| ERROR | `Failed to load BGE model: {error}` | Startup failure |
| ERROR | `ChromaDB error: {error}` | Database issue |

## Health Checks

All run at startup. **If any fails, BMO refuses to start.**

1. **BGE model loads**: Load BGE-small-en-v1.5, embed "hello world" → 384-dim vector within 1 second
2. **ChromaDB opens**: Open persistent storage at configured path without corruption
3. **Folder check**: If folders are configured, verify at least one collection exists and is queryable

## Edge Cases

| Scenario | Handling |
|---|---|
| Folder deleted while indexed | File watcher detects deletion, removes chunks, logs warning |
| Very large files | Cap at 1000 chunks per file to prevent index bloat |
| Binary files in watched folder | Skip non-supported file types silently |
| Conflicting info across folders | Return chunks from all relevant folders, LLM synthesizes |
| Empty folder | Valid — just produces no chunks, queries return empty |
| Rapid file saves (IDE) | 2-second debounce batches rapid changes |
| ChromaDB corruption | Detected at startup, error with instructions to rebuild |
| Folder permissions denied | Log error, skip folder, continue with others |

## macOS Considerations

- **FSEvents**: `watchdog` uses macOS native FSEvents for efficient file monitoring — low overhead, no polling
- **Large folder indexing**: Use background-priority threads to avoid thermal throttling on MacBook
- **APFS**: Works natively with APFS file system (macOS default)
- **Spotlight**: Not used — `watchdog` with FSEvents is sufficient and more controllable
- **File permissions**: macOS may require Full Disk Access for certain folders (e.g., Desktop, Documents under newer macOS versions)

## Relation to Other Components

- **Upstream**: Receives query text from intent router (LLM component), folder config from config/WebSocket
- **Downstream**: Sends top-K chunks to LLM component for context injection
- **Background**: File watcher runs independently, keeping index fresh
- **Depends on**: Config (folder list), BGE model, ChromaDB
- **Depended on by**: LLM component (needs RAG context for document-related queries)
- **Parallel with**: Web search — for hybrid intent, both run concurrently
