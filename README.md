# FlashLearn

AI-powered flashcard app. Snap a photo of your notes, AI creates quizzes.

## Quick Start (Docker)

Make sure Ollama is running on the host first:

    ollama serve

Then:

    docker compose up -d --build

Open http://localhost:5050 on your phone (same WiFi network).

## Manual (no Docker)

    pip install -r requirements.txt
    python main.py

Open http://localhost:5050

## Running Tests

    pip install pytest pytest-asyncio
    python -m pytest tests/ -v

## How it works

1. Tap the camera button to upload a photo of your notes/worksheet
2. AI (via Ollama) reads the image and generates 8-15 quiz cards
3. Cards include flashcards, multiple choice, and fill-in-the-blank
4. Study with spaced repetition - cards you struggle with come back more often
5. Earn XP, level up, unlock achievements, build streaks

## Tech

- FastAPI backend with SQLite
- Ollama API for AI (vision model reads photos directly)
- Spaced repetition algorithm (SM-2 based)
- Mobile-friendly PWA-style frontend
- Docker deployment with host networking
