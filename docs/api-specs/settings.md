# API Spec: Settings

> Feature: Runtime configuration for LLM channels, system prompts, and data source registry
> Status: Implemented
> Last Updated: 2026-05-04

---

## Section A: API Contract

### Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/settings/llm` | LLM channel config + key presence (never raw keys) |
| PUT | `/settings/llm` | Save channel config and runtime params |
| POST | `/settings/llm/test` | Test a single LLM channel without storing the key |
| GET | `/settings/prompts` | Current prompt blocks from settings.yaml |
| PUT | `/settings/prompts` | Update prompt blocks (partial update — only provided keys) |
| POST | `/settings/prompts/preview` | Compose full system prompt from draft edits for preview |
| POST | `/settings/prompts/reset` | Reset specified prompt blocks to hardcoded defaults |
| GET | `/settings/sources` | Source registry with enriched file status |
| PUT | `/settings/sources` | Update source configs (data_dir, enabled, file_patterns) |
| POST | `/settings/sources/test/{reader}` | Test whether a source file exists and is valid |
| POST | `/settings/sources/test-all` | Test all 6 readers; returns all results regardless of failures |
| POST | `/settings/sources/upload/{reader}` | Upload source file; auto-validates after save |
| GET | `/settings/sources/files/{reader}` | List matching files in resolved data directory |
| GET | `/settings/sources/upload-history` | All upload history across readers |
| GET | `/settings/sources/upload-history/{reader}` | Upload history for a specific reader |
| POST | `/settings/import-adapters/{key}/upload` | Upload file, detect headers, infer column mapping; `?import_type=holdings\|transactions&header_row=N` |
| POST | `/settings/import-adapters/{key}/validate` | Validate current column mapping against required fields |
| POST | `/settings/import-adapters/{key}/configure` | Save final column mapping (body: `{run_id, column_mapping, fx_rate}`) |
| POST | `/settings/import-adapters/{key}/stage` | Read full file using saved mapping, write rows to `import_adapter_staged_rows` |
| GET | `/settings/import-adapters/{key}/staged-rows` | Fetch staged rows for preview (`?run_id=N&limit=50`) |
| POST | `/settings/import-adapters/{key}/approve` | Finalize adapter — writes to `import_adapter_approvals`, enables sync pipeline injection |

### Key Response Types

```typescript
// GET /settings/llm
interface LLMSettingsResponse {
  channels: LLMChannel[];
  primary_model: string;
  fallback_models: string[];
  temperature: number;
  max_output_tokens: number;
  key_source: "env_file" | "secret_manager"; // secret_manager when UIS_GCS_BUCKET is set (cloud)
  keys_editable: boolean;                   // false on cloud: keys cannot be saved from the app
}
interface LLMChannel {
  name: string;
  provider: string;   // "gemini" | "deepseek" | "anthropic"
  enabled: boolean;
  api_key_env: string;          // env var name, e.g. "GEMINI_API_KEY"
  key_status: "configured" | "missing"; // the RUNNING server's env var — never the raw key
  models: string[];
}

// POST /settings/llm/test
interface ChannelTestRequest {
  provider: string;
  model: string;
  api_key?: string;     // typed key; omit/empty = test the server's key for api_key_env
  api_key_env?: string;
}

// GET /settings/sources
interface SourceRegistryResponse {
  sources: SourceEntry[];
  fallback_dir: string;
}
interface SourceEntry {
  key: string;          // e.g. "schwab_csv"
  enabled: boolean;
  data_dir: string | null;
  file_patterns: Record<string, string>;
  resolved_dir: string;
  file_found: boolean;
  file_path: string | null;
  file_size_bytes: number | null;
  file_mtime: string | null;    // ISO datetime
}

// POST /settings/sources/test/{reader}
interface SourceTestResult {
  reader: string;
  ok: boolean;
  file_path: string | null;
  warnings: string[];
  error: string | null;
}
```

### PUT /settings/sources — Request Body

```typescript
interface SourceRegistryUpdateRequest {
  sources: SourceUpdate[];
}
interface SourceUpdate {
  key: string;                            // reader key, must exist
  enabled?: boolean;
  data_dir?: string | null;              // empty string clears to null
  file_patterns?: Record<string, string>;
}
```

---

## Section B: Key Behaviours

- **API keys** are never stored in `settings.yaml`, and GET never returns the raw value, only `key_status`.
  - Local (`key_source: "env_file"`): PUT /settings/llm writes `api_key_value` to `.env` **and** the running process, so it takes effect without a restart.
  - Cloud (`key_source: "secret_manager"`): keys are Secret Manager env vars. A PUT carrying a non-null `api_key_value` is refused with **409** `ERR_KEYS_MANAGED_EXTERNALLY` and nothing (keys or config) is written. Rotate by adding a secret version, then a label-only `gcloud run services update` restart. A PUT without keys saves the config as usual.
  - `key_status` reflects `os.environ` (what the server uses), so a Secret Manager key shows as configured on cloud.
  - POST /settings/llm/test with no `api_key` tests the server's key for `api_key_env`.
- **Source test with draft path**: POST `/settings/sources/test/{reader}` accepts optional `{ data_dir }` body to validate a path before saving — useful for the Settings UI file picker.
- **Partial prompt updates**: PUT `/settings/prompts` only updates keys that are present and non-null; omitted keys are left unchanged.
- **Upload history**: stored in DuckDB `source_upload_history` table. Table is auto-created on first upload.

---

## Section C: Router Registration

```python
# src/api/main.py
app.include_router(settings_router, prefix="/settings")
```

All paths above are relative to `/settings`, e.g. `/settings/llm`, `/settings/sources`.
