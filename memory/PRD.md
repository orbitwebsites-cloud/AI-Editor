# KLIPPD — AI Video Editor (PRD)

## Original problem statement
> "how the hell do i edit my vids like they were edited by a 3k editor but i did it all for free bro"
> "no i need ai to edit my whole ass video taking out all ums uh stuttering add amazing captions add broll efects sfx all that shi"
> "Add viral-clip extraction; Add 9:16 aspect-ratio export for shorts; User-uploaded B-roll (not just Pexels); im not able to upload a .mov file"

## Architecture
- **Backend**: FastAPI + MongoDB + FFmpeg 5.1.9
  - Groq Whisper (`whisper-large-v3-turbo`) for transcription with word-level timestamps
  - LLM fallback chain: Groq `llama-3.3-70b-versatile` → Groq `llama-3.1-8b-instant` → Cerebras `gpt-oss-120b` → Cerebras `zai-glm-4.7`
  - Pexels API for stock B-roll videos
  - Fernet-encrypted API keys stored in MongoDB (seeded from `SEED_*_KEY` env vars)
  - FFmpeg subprocess pipeline (async via `asyncio.to_thread`) for cut/concat, ASS subtitle burn-in, B-roll overlay, SFX mixing
  - Supervisor hook (`ensure_ffmpeg`) auto-reinstalls FFmpeg if container is reset
- **Frontend**: React 19 + Tailwind
  - Brutalist streetwear aesthetic (Anton + Outfit fonts, neon #CCFF00 brand)

## User personas
- Gen-Z creators / TikTok / YouTube Shorts editors (primary) — want $3K editor output for $0
- Podcasters / vloggers doing long-form content

## Core requirements
- All AI runs on user's free-tier keys with automatic fallback
- Auto detect fillers, emphasis, B-roll moments in a single LLM pass
- User can manually toggle any word as filler (click) or jump to it (dbl-click)
- Feature toggles per render: cut fillers, captions, SFX, zoom, B-roll
- Two caption styles: TikTok (Impact + pink pop) vs YouTube (Arial + yellow)
- Three aspect ratios: 16:9, 9:16, 1:1
- Downloadable final MP4 + independent viral-clip MP4s

## What's been implemented

### Iteration 1 (2026-07-14) — MVP
- Video upload → audio extract → Whisper transcription → LLM analysis (fillers/emphasis/B-roll/title) → render pipeline (cut fillers, animated captions, SFX, B-roll overlay) → download
- Full 4-model LLM fallback (Groq→Cerebras)
- Interactive transcript editor with click-to-toggle-filler + karaoke sync
- Style picker (TikTok/YouTube), feature toggles per render
- Fernet-encrypted API key storage + live connection test
- Brutalist landing page, settings modal, editor page
- Passed 11/11 backend tests + all critical UI flows

### Iteration 2 (2026-07-14) — Extended features
- **Fixed .mov upload** — accepts files by extension when MIME type is empty/quicktime; improved error surfaces
- **9:16 / 1:1 aspect ratio** — new `aspect` field in RenderOptions; FFmpeg center-crop + scale; ASS subtitle resolution auto-syncs
- **Viral clip extraction** — new `POST /api/projects/{id}/viral_clips` LLM endpoint finds 3-5 punchiest 20-60s moments (hook/caption/score/reason); each rendered as its own 9:16 short (`viral_renders[label]`) — main render preserved separately
- **Custom B-roll upload** — new `POST /api/projects/{id}/broll_upload` accepts video → returns Pexels-compatible object → auto-selected in UI with "YOURS" badge → render pipeline handles local `file://` paths without redownloading
- **FFmpeg persistence** — supervisor pre-start hook ensures FFmpeg is always installed
- Verified end-to-end: 9:16 render produces 1080×1920 output, custom B-roll upload returns metadata, viral clip endpoint responds < 1s

## Backlog

### P0 (blocking)
- (none) — MVP + user's requested extensions all shipped

### P1
- Test with a real 10-30s speaking video (synthetic clips have no words for LLM to analyze)
- Long-transcript chunking for LLM (currently truncated at 1200 words)
- FFmpeg progress % parsing for smoother render bar
- Thumbnail generation on upload

### P2
- User accounts + project sharing (currently single-user MVP)
- Multi-language transcription
- Timeline visualization for keep/cut segments
- Zoom-in Ken Burns on emphasis words (currently only caption emphasis)
- Music/BGM library, auto beat-sync

### Future
- AI voice-over dubbing
- Cloud storage instead of local disk
- Real-time collaborative editing

## Environment
- FFmpeg 5.1.9 (`apt` package; auto-reinstalled via `ensure_ffmpeg` supervisor hook)
- SFX at `/app/backend/assets/sfx/` (whoosh.wav, impact.wav)
- Data dirs at `/app/data/{videos,audio,output,subtitles,broll}`
- `MASTER_ENCRYPTION_KEY` in `/app/backend/.env`
- All 3 API keys (Groq/Cerebras/Pexels) seeded from `SEED_*_KEY` env vars
