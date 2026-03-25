# Web Search — `server/search/`

## Purpose & Responsibilities

- Search the web for current/real-time information
- Format results as context for the LLM
- Handle failover between search providers (Brave → SearXNG)
- Respect rate limits and timeouts
- Support parallel execution with RAG for hybrid queries

## Architecture

```
Query (from Intent Router via Session Manager)
         │
         ▼
┌───────────────────────────────────────────┐
│  Search Dispatcher                         │
│                                            │
│  1. Try primary provider (Brave)           │
│  2. On failure/timeout → try fallback      │
│  3. On both fail → return empty + flag     │
│                                            │
│  Hard timeout: 3 seconds per provider      │
└──────────┬────────────────────────────────┘
           │
     ┌─────┴─────────────────┐
     │                        │
     ▼                        ▼
┌─────────────────┐  ┌──────────────────┐
│  Brave Search   │  │  SearXNG         │
│  API (primary)  │  │  (fallback)      │
│                 │  │                  │
│  Free tier      │  │  Self-hosted     │
│  2000 req/mo    │  │  Docker          │
│  No credit card │  │  Unlimited       │
└────────┬────────┘  └────────┬─────────┘
         │                     │
         └──────────┬──────────┘
                    │
                    ▼
         ┌──────────────────┐
         │  Result Formatter │
         │                   │
         │  Top 3-5 results  │
         │  ~1500 tokens     │
         │  Title + URL +    │
         │  snippet          │
         └────────┬──────────┘
                  │
                  ▼
           LLM Component
           (context injection)
```

### Parallel with RAG (Hybrid Intent)

```
Intent Router classifies: hybrid
         │
    ┌────┴────────────────┐
    │                      │
    ▼                      ▼
[RAG Engine]         [Web Search]
 (~30ms local)       (~700ms network)
    │                      │
    └──────────┬───────────┘
               │
               ▼
        LLM with combined context
        Latency = max(RAG, web), not sum
```

## Search Providers

### Primary: Brave Search API (Free Tier)

- **2000 free queries/month** — no credit card required
- Highest benchmark score for LLM grounding
- Lowest latency among search APIs (~669ms average)
- Independent index, privacy-first
- Returns: title, URL, snippet per result
- **Default**: Use snippets only (fastest, no page fetching)
- **Optional**: Fetch top 1–2 page bodies via `httpx` + `readability-lxml` when snippets are insufficient

### Fallback: SearXNG (Self-Hosted)

- AGPL-3.0, fully self-hosted via Docker
- Aggregates from Google, Bing, DuckDuckGo — broad coverage
- Zero cost, unlimited queries
- Setup: `docker run -d -p 8888:8080 searxng/searxng` (zero config)
- If Brave is ever removed, SearXNG becomes primary with no loss of functionality

### Provider Comparison

| Provider | License | Free Limit | Latency | Self-Hosted | Decision |
|---|---|---|---|---|---|
| **Brave Search** | Proprietary (free API) | 2000/mo | ~669ms | No | **Primary** |
| **SearXNG** | AGPL-3.0 | Unlimited | Variable | Yes (Docker) | **Fallback** |
| DuckDuckGo (unofficial) | N/A | Unofficial | Variable | No | Could break anytime |
| Tavily | Proprietary | 1000/mo | ~800ms | No | Less generous tier |

**Free tier risk**: Even at heavy use (20 searches/day) = 600/month, well within 2000 limit.

## Result Formatting

**Format for LLM context:**
```
Web search results for "{query}":

[1] {title}
Source: {url}
{snippet text}

[2] {title}
Source: {url}
{snippet text}

...
```

- **Top 3–5 results** included
- **~1500 tokens** total web context
- Source URLs included so LLM can cite verbally ("I found online that...")

### Optional Page Fetching

When snippets are insufficient for a query:
1. Fetch top 1–2 full page URLs via `httpx`
2. Extract readable content via `readability-lxml`
3. Truncate to ~500 tokens per page
4. Append to snippet context

## Failover Strategy

```
1. Try Brave Search API
   ├─ Success → return results
   ├─ Timeout (3s) → try SearXNG
   ├─ Rate limit (429) → try SearXNG
   └─ Error → try SearXNG

2. Try SearXNG
   ├─ Success → return results
   ├─ Timeout (3s) → return empty
   └─ Error → return empty

3. Both failed
   → Return empty results
   → Set flag: "web_search_unavailable"
   → LLM told: "I couldn't reach the web right now"
```

**Rate limit tracking**: Count Brave API calls per month. Warn when approaching 2000.

**Future improvements** (backlog B-20):
- Circuit breaker pattern: after N Brave failures, switch to SearXNG for M minutes
- Parallel fire: send to both, use whichever returns first

## Startup Behavior

**Web search is NOT required for BMO to start.** Unlike core voice models, web search is optional.

- If Brave API key configured → test query "test" → verify 200 response. If fails, warn but continue.
- If SearXNG URL configured → `GET /` → verify 200. If fails, warn but continue.
- If neither configured/reachable → BMO starts with web search disabled. Intent router skips `web_search` classification.

## Interface with Other Components

| Direction | Component | Data |
|---|---|---|
| **Input from** | Intent Router (LLM) | Search query string (when intent=web_search or hybrid) |
| **Output to** | LLM Component | Formatted search results (text + source URLs) |
| **Parallel with** | RAG Engine | Both run concurrently for hybrid intent |
| **Config from** | Config / .env | API keys, SearXNG URL, timeout |

## Configuration

```yaml
search:
  primary: brave                     # or searxng
  fallback: searxng                  # or none
  brave_api_key: ${BRAVE_SEARCH_API_KEY}
  searxng_url: http://localhost:8888
  timeout_seconds: 3                 # hard timeout per provider
  max_results: 5                     # results to return
  fetch_pages: false                 # fetch full page content
  fetch_pages_max: 2                 # max pages to fetch
```

## Logging

Logger name: **`bmo.search`**

| Level | Message | When |
|---|---|---|
| DEBUG | `Brave API response: {status}, {body_preview}` | Raw response |
| DEBUG | `Result parsing: {N} results extracted` | Parse details |
| INFO | `Search: "{query}" via {brave} → {5} results (latency={720}ms)` | Successful search |
| INFO | `Page fetch: {url} (latency={450}ms, {1200} chars extracted)` | Page fetching |
| INFO | `Fallback: Brave failed ({timeout}), trying SearXNG` | Failover |
| WARNING | `Search timeout ({3}s) for "{query}" via {brave}` | Timeout |
| WARNING | `Brave API usage: {1850}/2000 queries this month` | Approaching limit |
| WARNING | `Brave rate limit hit (429) — switching to SearXNG` | Rate limit |
| ERROR | `Brave API error: {status} {message}` | API error |
| ERROR | `SearXNG unreachable at {url}: {error}` | Fallback down |
| ERROR | `All search providers failed for "{query}"` | Total failure |

## Health Checks

Run at startup. **Failures are warnings, not fatal** (web search is optional).

1. **Brave API** (if key configured): Test query "test" → 200 response
2. **SearXNG** (if URL configured): `GET /` → 200 response
3. **Neither available**: Log warning "Web search unavailable — BMO will function without web results"

## Edge Cases

| Scenario | Handling |
|---|---|
| Network failure | 3s timeout, proceed without web context, inform user |
| Brave rate limit (429) | Automatic SearXNG fallback |
| Empty results | LLM told "no web results found for this query" |
| Brave key missing | Use SearXNG only, or disable web search entirely |
| SearXNG not running | Use Brave only, or disable web search entirely |
| Neither configured | Web search disabled, intent router skips web_search |
| Very slow response | 3s hard timeout, strict |
| Malformed API response | Log error, treat as empty results |

## macOS Considerations

- **Outbound HTTPS**: Brave API calls go to `api.search.brave.com`. May need firewall allowance if user has strict firewall.
- **Docker for SearXNG**: Requires Docker Desktop for Mac. Optional — system works without it.
- **DNS resolution**: Uses system DNS. If user has custom DNS (e.g., Pi-hole), ensure search APIs are not blocked.

## Relation to Other Components

- **Upstream**: Receives search query from intent router (LLM component)
- **Downstream**: Sends formatted results to LLM for context injection
- **Parallel with**: RAG engine — both run concurrently for hybrid intent
- **Depends on**: Network connectivity, Brave API / SearXNG availability
- **Depended on by**: LLM component (for web-augmented responses)
- **Optional**: BMO functions fully without web search (general + RAG still work)
