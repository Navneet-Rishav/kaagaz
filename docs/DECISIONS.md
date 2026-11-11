# Design decisions

Why each major choice was made, and what else was considered.

## 1. Stack: FastAPI + SQLAlchemy 2 + Postgres, React + Vite + TypeScript

- **FastAPI**: typed request/response models with Pydantic v2, automatic validation errors, simple dependency injection for auth and DB sessions. Flask or Django would need more glue for the same typing.
- **SQLAlchemy 2 + Alembic**: typed models (`Mapped[...]`) and versioned migrations. Every schema change is a migration, tested with upgrade → downgrade → upgrade and `alembic check` (models and migrations agree).
- **Postgres** does three jobs: data, the job queue (§4) and search (§6). One managed service (Neon free tier) instead of three.
- **React + Vite + TanStack Query + Tailwind** on the frontend: polling, caching and loading/error states come from TanStack Query instead of hand-written effects.

## 2. Privacy: mask before any model sees the text

The upload is read (PDF text layer or OCR), then **masked with Microsoft Presidio pattern recognizers** before anything is stored or sent to a language model.

- Masked: Aadhaar (12 digits, never starting 0/1, **Verhoeff checksum** must pass), PAN, Indian mobiles (+91/0 prefixes, 5+5 spacing), IFSC, email, bank account numbers (only right after "A/c", "account" or "खाता").
- **Devanagari digits (०–९) are normalised to ASCII first**, so `२३४५ ६७८९ ०१२६` is caught like `2345 6789 0126`.
- Only the masked text and **counts** of what was masked are stored. Never the values.
- **The original file is deleted** after processing (success or failure). It lives in the job row only while processing (§4).
- **Honest limit:** OCR (Sarvam Vision) does see the raw document; the chat model never does. Names and addresses are not masked: that needs an NER model (spaCy/transformers), which does not fit Render's free 512 MB RAM. Pattern recognizers keep the API at about 120 MB.
- Alternatives: regex only (Presidio gives a standard recognizer/anonymizer structure and is easy to extend); a cloud PII API (another vendor seeing raw data).

## 3. Broken Devanagari text layers go to OCR

PDFs printed from browsers or Word often store Devanagari in visual glyph order: `मासिक` comes back from pypdf as `मािसक`, and conjuncts like `ख्य` disappear. Feeding that to a model gives confident nonsense.
`devanagari_garbled()` looks for impossible sequences (a vowel sign at the start of a word, the short-i sign after another vowel sign). If any page is garbled or nearly empty, **the whole file goes to OCR**, so page numbers stay consistent.
The demo documents have this problem too. The demo has no OCR credits, so each sample PDF ships with a `.pages.json` of prepared page text, standing in for a cached OCR result. The UI says "text prepared in advance" for them.

## 4. A job queue in Postgres (`FOR UPDATE SKIP LOCKED`)

Uploads return `202` immediately; a worker thread inside the API process works the queue.
- `SELECT … FOR UPDATE SKIP LOCKED` lets several workers claim jobs without ever taking the same one (tested with two sessions).
- The job row holds the uploaded bytes until processing ends, then they are set to NULL. Render's free disk is wiped on restart; a row is not, so **queued work survives a restart**.
- Retryable AI errors (timeouts, 429, 5xx) back off 30 s, 60 s and give up after 3 attempts. Jobs stuck in `running` for 10 minutes (process died) are re-queued.
- Document status (`queued → reading → masking → extracting → ready | failed`) is committed at each step so the UI can show progress, and failures carry a user-readable message.
- Alternatives: Celery/RQ + Redis (another service to host and pay for), a cron poller (slower, same complexity), FastAPI `BackgroundTasks` (lost on restart).

## 5. One AI interface, two implementations

`AiProvider` (a `Protocol`) has `chat`, `parse_document`, `transcribe` and `speak`. The pipeline only knows this interface.
- **`SarvamProvider`**: Sarvam Vision OCR results come back as layout blocks with a reading order (checked against the live API); blocks are joined as paragraphs so the chunker keeps them apart. Timeouts, retries with backoff on 429/5xx/network errors, fail-fast on other 4xx. JSON replies are validated with Pydantic and retried once with the validation error (`complete_json`).
- **`DemoProvider`**: offline and rule-based (keywords, regexes, best-matching sentence). **It is not a model.** Tests, CI and the public demo use it, so nothing calls a paid API. OCR and voice are not faked: they return a clear "needs the Sarvam API" error, and the UI disables those buttons with that explanation.
- No eval numbers are published from the demo provider; they would only measure regexes written next to the sample documents.

## 6. Retrieval: Postgres full-text search, not embeddings

- Chunks (page → paragraph, ~800 characters, ~150 overlap, never across pages) get a generated `tsvector` with the **`simple`** config: no stemming, so Hindi words stay intact.
- The question is rewritten by the model into keywords in **both Hindi and English** (a Hindi question about an English rent agreement still finds "notice period"), then OR-ed.
- If that finds nothing: **pg_trgm** word similarity (typos, OCR noise), or ILIKE where the extension is missing (local test Postgres).
- Why not embeddings: a multilingual embedding model does not fit the free-tier RAM, and a hosted embedding API is another paid dependency. The retriever sits behind a `Retriever` protocol so pgvector can be added later.
- Bug found by a test: the Devanagari Unicode block includes the danda (।), so `किराया।` was a "word". Tokenisers now exclude U+0964/U+0965.

## 7. Answers must cite retrieved pages, or refuse

The model answers only from the retrieved excerpts and cites pages like `[p.2]`. Then code checks it:
- Citations to pages that were **not retrieved** are removed; if none remain, the answer is replaced by a refusal (tested with a provider that confidently cites a wrong page).
- `found=false`, an empty answer, or no retrieved chunks → **"यह जानकारी दस्तावेज़ में नहीं मिली / Not found in this document"**.
- Answers are in the language of the question. Every question and answer is stored as history.

## 8. Auth and demo accounts

- JWT bearer tokens (API and UI are on different domains), bcrypt with 12 rounds. Passwords are truncated to bcrypt's 72 **bytes** explicitly: a 30-character Hindi password is already ~90 bytes.
- Login gives the same error for unknown email and wrong password.
- **Each "Try the demo" click creates a fresh demo account** seeded with the three sample documents, deleted after 24 hours. A shared demo account would let one visitor read another visitor's uploads. Demo creation is rate-limited per IP.
- Every document route checks ownership; another user's document returns 404, not 403, so IDs cannot be probed.

## 9. Limits and rate limits

- Uploads: PDF/PNG/JPG detected from the **file's magic bytes** (not its name), ≤ 10 MB (the server never reads more than limit + 1 byte), ≤ 30 pages, encrypted PDFs rejected, duplicates detected by SHA-256 per user.
- Per-user sliding-window limits on the endpoints that cost money (upload, ask, voice). In memory, so per process: fine for one free instance, would need Postgres/Redis for several.

## 10. Hosting (free tiers)

- **API on Render** (Singapore), **Postgres on Neon** (Singapore, same AWS region), **UI on Vercel**.
- Render's free instance sleeps after 15 idle minutes; the first request can take up to a minute. The UI says so on the demo button.
- Migrations run on every start (`alembic upgrade head` is a no-op when current).

## 11. Evals: a small labelled set, no demo-provider numbers

`backend/evals/dataset.py` labels the demo documents (fields with pages) and 12 questions, including 3 that must be refused. The runner uses the same `process_document` and `ask` code as the API, creates a temporary user and deletes it afterwards. Matching is lenient where formatting legitimately differs (`18,500` = `18500`, a "(DEMO)" suffix) but numbers must be equal. Results from the rule-based demo provider are never reported: it was written alongside the documents, so a high score would only measure that. Only a real-model run produces numbers worth publishing, and they will be labelled with the set size.

## 12. Secret scanning (gitleaks in CI)

A separate workflow (`.github/workflows/gitleaks.yml`) scans the **full git history** on every push and pull request and fails if it finds a secret.
- Runs the gitleaks binary directly (pinned v8.30.1, SHA-256 checked) rather than a marketplace action: no extra token or permissions, and it's easy to see exactly what runs.
- `.gitleaks.toml` keeps all default rules and allow-lists only known placeholders (local docker/CI database credentials, the local docker JWT secret, test-only secrets), each matched exactly with a comment explaining why it is safe. A real token planted in any allow-listed file is still caught (checked by hand).
- Alternative considered: GitHub's built-in secret scanning push protection. It is useful too, but it can't be run locally or shown in CI, and it doesn't cover generic patterns the same way.
