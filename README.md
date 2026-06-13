# FlashLearn

AI-powered flashcard app for students. Snap photos of your notes, AI creates quizzes, study with spaced repetition.

Built for my daughter Emma. 📚

## Features

- **Photo to Flashcards** — Take a photo of your notes/worksheet, AI reads it and generates quiz cards (flashcard, multiple choice, fill-in-the-blank)
- **Multi-Image Upload** — Select multiple photos at once, all cards merge into one deck
- **Subject Folders** — Organise decks into folders (Chemistry, History, Maths, etc.)
- **Spaced Repetition** — SM-2 algorithm schedules cards you struggle with more frequently
- **Gamification** — Earn XP, level up, unlock achievements, build study streaks
- **Works on Phone** — Mobile-first design, access from any device on your home network

## Quick Start

### Prerequisites

- [Docker](https://docs.docker.com/get-docker/) and Docker Compose
- [Ollama](https://ollama.ai) running on the host with a vision model

### 1. Install a vision model in Ollama

```bash
ollama pull gemma4:31b-cloud
```

Any Ollama-compatible vision model works. You can change it in the app settings.

### 2. Clone and run

```bash
git clone https://github.com/psylsph/flashlearn.git
cd flashlearn
docker compose up -d --build
```

### 3. Open in browser

```
http://localhost:5050
```

On your phone (same WiFi): `http://<your-computer-ip>:5050`

## How It Works

1. **Create subject folders** (optional) — Chemistry, History, etc.
2. **Tap the camera button** — Select one or more photos of your notes
3. **AI reads your notes** — The vision model extracts facts and creates quiz cards
4. **Study** — Flip flashcards, answer multiple choice, type fill-in-the-blank answers
5. **Earn XP** — Correct answers earn XP, build streaks, unlock achievements

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `PORT` | `5050` | Port the app runs on |
| `OLLAMA_URL` | `http://localhost:11434` | Ollama API base URL |
| `PDF_MAX_PAGES` | `10` | Maximum PDF pages processed per upload |
| `PDF_DPI` | `150` | DPI used when rendering PDF pages |

### AI Model

Change the model in the app's Settings page, or edit the database directly. The default is `gemma4:31b-cloud`.

Any Ollama model with vision capabilities works. For offline/local use:

```bash
ollama pull gemma3:4b
```

Then select it in Settings.

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/status` | Ollama connection status |
| GET | `/api/progress` | XP, level, streaks, stats |
| GET/PUT | `/api/settings` | AI model setting |
| GET | `/api/folders` | List all folders |
| POST | `/api/folders` | Create folder |
| PUT | `/api/folders/{id}` | Rename folder |
| DELETE | `/api/folders/{id}` | Delete folder |
| GET | `/api/decks` | List decks (optional `?folder_id=N`) |
| GET | `/api/decks/unassigned` | Decks not in any folder |
| POST | `/api/decks` | Create empty deck |
| PUT | `/api/decks/{id}/move` | Move deck to folder |
| DELETE | `/api/decks/{id}` | Delete deck and cards |
| POST | `/api/upload` | Upload photo(s), AI generates cards |
| GET | `/api/decks/{id}/study` | Get cards for review |
| POST | `/api/cards/{id}/review` | Submit card review |
| POST | `/api/session/complete` | End study session, award bonus XP |
| DELETE | `/api/cards/{id}` | Delete a card |
| GET | `/api/achievements` | List achievements |

## Tech Stack

- **Backend:** Python, FastAPI, SQLite
- **Frontend:** Vanilla HTML/CSS/JS (no framework)
- **AI:** Ollama vision models via local API
- **Deployment:** Docker with host networking

## Project Structure

```
flashlearn/
├── main.py              # FastAPI app and API routes
├── database.py          # SQLite schema, SM-2 spaced repetition, XP system
├── ai_service.py        # Ollama API integration, image processing
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── static/
│   ├── index.html       # Single-page app
│   ├── style.css        # Mobile-first dark theme
│   └── app.js           # Frontend logic
├── tests/
│   ├── conftest.py      # Test fixtures
│   ├── test_database.py # Database, SM-2, achievements tests
│   ├── test_api.py      # API endpoint tests
│   └── test_ai_service.py # AI service tests
└── README.md
```

## Running Tests

```bash
pip install pytest pytest-asyncio httpx
python -m pytest tests/ -v
```

## License

MIT License — see [LICENSE](LICENSE).

## Acknowledgements

- Inspired by [FocusTree](https://www.focustree.app/) and similar study apps
- Spaced repetition powered by the SM-2 algorithm
- AI flashcard generation via [Ollama](https://ollama.ai)
