# KLIPPD — AI Video Editor

## Original Problem Statement
> "how the hell do i edit my vids like they were edited by a 3k editor but i did it all for free bro"
> "no i need ai to edit my whole ass video taking out all ums uh stuttering add amazing captions add broll efects sfx all that shi"
> User choices: use Groq + Cerebras free-tier keys with fallback, best model per task, edits existing videos (not creates), keys pasted in-app later

## Architecture
- **Frontend**: React 19 + Tailwind, brutalist gen-z aesthetic (Anton + Outfit, #ccff00 over #050505)
- **Backend**: FastAPI + Motor + FFmpeg subprocess pipeline
- **AI (OpenAI-compatible SDKs, encrypted keys in Mongo)**:
  - Groq primary: `whisper-large-v3-turbo` transcription, `llama-3.3-70b-versatile` reasoning
  - Cerebras fallback: `llama-3.3-70b` / `qwen-3-32b`
  - Pexels: B-roll stock video
- **Video pipeline**: extract audio → cut fillers (trim+concat) → burn ASS captions (TikTok/YouTube) → overlay B-roll → whoosh SFX at cuts → zoom pulses on emphasis
- **Storage**: MongoDB (projects, encrypted keys); disk at `/app/data/`

## Core Features (P0) — All Implemented
- ✅ Upload video (drag & drop)
- ✅ Whisper transcription + word timestamps
- ✅ LLM filler + emphasis + B-roll suggestions with Groq→Cerebras fallback
- ✅ Interactive transcript, click-to-seek, toggle filler/emphasis per word
- ✅ Style picker: TikTok vs YouTube captions
- ✅ Pexels B-roll picker (fetch per suggested moment, choose from grid)
- ✅ Zoom pulses, whoosh SFX toggles
- ✅ Final MP4 render + download
- ✅ Fernet-encrypted API key vault + connection test
- ✅ Gen-Z brutalist UI (Anton, neon, marquee, grain)

## Implemented (Jan 14, 2026)
- Backend: `server.py`, `ai_services.py`, `video_processor.py` — full pipeline verified end-to-end
- Frontend: Landing, Editor, Settings modal, TopBar with live key status pills
- FFmpeg pipeline: filler-cut, ASS caption burn-in, B-roll overlay, SFX mix, zoom pulses
- Backend keys pre-seeded for testing (Groq/Cerebras/Pexels — all pass connection test)

## Prioritized Backlog

### P1
- [ ] Thumbnail generation on upload (endpoint stubbed)
- [ ] Long transcript chunking for LLM (>1200 words currently truncated)
- [ ] Progress via WebSocket instead of polling
- [ ] Vertical 9:16 export preset for shorts

### P2
- [ ] Multi-language transcription (currently English)
- [ ] Custom caption theming (colors/fonts/position)
- [ ] Timeline visualization for keep/cut segments
- [ ] User accounts + project sharing
- [ ] B-roll fade + Ken Burns

### Future
- [ ] AI voice-over dubbing
- [ ] Auto highlight reel (best 60s from long-form)
- [ ] Music beat-sync auto-cuts

## Environment
- FFmpeg 5.1.9 installed
- SFX at `/app/backend/assets/sfx/` (whoosh.wav, impact.wav)
- Data dirs auto-created at `/app/data/{videos,audio,output,subtitles,broll}`
- `MASTER_ENCRYPTION_KEY` in `/app/backend/.env`
