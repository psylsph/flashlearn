import os
import sys
import json
from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Patch the database path before importing main
import database as db_module
import tempfile
tmp = tempfile.mkdtemp()
test_db_path = os.path.join(tmp, "test.db")
db_module.DB_PATH = type('', (), {'parent': type('', (), {'mkdir': lambda **kw: None})(), '__truediv__': lambda s, o: test_db_path})()

from database import Database
test_db = Database()

# Patch main's db instance
import main
main.db = test_db


@pytest.fixture
def client():
    return TestClient(main.app)


class TestStatusEndpoint:
    def test_get_status(self, client):
        with patch("main.check_ollama_status") as mock:
            mock.return_value = {"running": True, "models": ["gemma4:31b-cloud"]}
            response = client.get("/api/status")
        assert response.status_code == 200
        assert response.json()["running"] is True


class TestProgressEndpoint:
    def test_get_progress(self, client):
        response = client.get("/api/progress")
        assert response.status_code == 200
        data = response.json()
        assert "total_xp" in data
        assert "level" in data


class TestSettingsEndpoints:
    def test_get_settings(self, client):
        response = client.get("/api/settings")
        assert response.status_code == 200
        assert "model" in response.json()

    def test_update_settings(self, client):
        response = client.put("/api/settings?model=gemma3:4b")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"


class TestDeckEndpoints:
    def test_create_deck(self, client):
        response = client.post("/api/decks", data={"name": "Test Deck", "subject": "Math"})
        assert response.status_code == 200
        data = response.json()
        assert "id" in data
        assert data["status"] == "ok"

    def test_list_decks(self, client):
        client.post("/api/decks", data={"name": "Deck 1"})
        response = client.get("/api/decks")
        assert response.status_code == 200
        assert len(response.json()["decks"]) >= 1

    def test_get_deck(self, client):
        create = client.post("/api/decks", data={"name": "Get Deck"})
        deck_id = create.json()["id"]
        response = client.get(f"/api/decks/{deck_id}")
        assert response.status_code == 200
        assert response.json()["deck"]["name"] == "Get Deck"

    def test_get_nonexistent_deck(self, client):
        response = client.get("/api/decks/99999")
        assert response.status_code == 404

    def test_delete_deck(self, client):
        create = client.post("/api/decks", data={"name": "Delete Me"})
        deck_id = create.json()["id"]
        response = client.delete(f"/api/decks/{deck_id}")
        assert response.status_code == 200
        assert client.get(f"/api/decks/{deck_id}").status_code == 404


class TestUploadEndpoint:
    def test_upload_creates_deck(self, client, sample_png_bytes):
        ai_result = {
            "success": True,
            "subject": "Biology",
            "deck_name": "Cell Biology",
            "description": "Cells",
            "cards": [
                {"question": "Q1?", "answer": "A1", "type": "flashcard", "difficulty": 2},
                {"question": "Q2?", "answer": "A2", "type": "multiple_choice", "options": ["A2", "B", "C", "D"], "difficulty": 3},
            ],
        }

        with patch("main.generate_cards", return_value=ai_result):
            response = client.post(
                "/api/upload",
                files={"photo": ("test.png", sample_png_bytes, "image/png")},
                data={"deck_name": "", "model": ""},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["deck"]["name"] == "Cell Biology"
        assert len(data["cards"]) == 2

    def test_upload_invalid_image(self, client):
        response = client.post(
            "/api/upload",
            files={"photo": ("test.txt", b"not an image", "text/plain")},
            data={"deck_name": "", "model": ""},
        )
        assert response.status_code == 400

    def test_upload_ai_failure(self, client, sample_png_bytes):
        with patch("main.generate_cards", return_value={"success": False, "error": "AI failed"}):
            response = client.post(
                "/api/upload",
                files={"photo": ("test.png", sample_png_bytes, "image/png")},
                data={"deck_name": "", "model": ""},
            )
        assert response.status_code == 500


class TestStudyEndpoints:
    def test_get_study_cards(self, client):
        create = client.post("/api/decks", data={"name": "Study Deck"})
        deck_id = create.json()["id"]
        # Add a card manually via DB
        test_db.add_card(deck_id, "Q?", "A")

        response = client.get(f"/api/decks/{deck_id}/study")
        assert response.status_code == 200
        assert len(response.json()["cards"]) >= 1

    def test_review_card_correct(self, client):
        create = client.post("/api/decks", data={"name": "Review Deck"})
        deck_id = create.json()["id"]
        card_id = test_db.add_card(deck_id, "Q?", "A")

        response = client.post(f"/api/cards/{card_id}/review?correct=true&time_ms=1000")
        assert response.status_code == 200
        data = response.json()
        assert data["xp_earned"] == 15  # 5 base + 10 correct
        assert data["level"] >= 1

    def test_review_card_wrong(self, client):
        create = client.post("/api/decks", data={"name": "Wrong Deck"})
        deck_id = create.json()["id"]
        card_id = test_db.add_card(deck_id, "Q?", "A")

        response = client.post(f"/api/cards/{card_id}/review?correct=false&time_ms=500")
        assert response.status_code == 200
        data = response.json()
        assert data["xp_earned"] == 5  # 5 base only

    def test_review_nonexistent_card(self, client):
        response = client.post("/api/cards/99999/review?correct=true")
        assert response.status_code == 404

    def test_session_complete(self, client):
        create = client.post("/api/decks", data={"name": "Session Deck"})
        deck_id = create.json()["id"]

        response = client.post(f"/api/session/complete?deck_id={deck_id}&correct_count=8&total_count=10")
        assert response.status_code == 200
        data = response.json()
        assert data["bonus_xp"] == 25  # 80% correct
        assert "level" in data

    def test_session_perfect_bonus(self, client):
        create = client.post("/api/decks", data={"name": "Perfect Deck"})
        deck_id = create.json()["id"]

        response = client.post(f"/api/session/complete?deck_id={deck_id}&correct_count=5&total_count=5")
        assert response.status_code == 200
        assert response.json()["bonus_xp"] == 50


class TestCardEndpoints:
    def test_delete_card(self, client):
        create = client.post("/api/decks", data={"name": "Card Delete Deck"})
        deck_id = create.json()["id"]
        card_id = test_db.add_card(deck_id, "Q?", "A")

        response = client.delete(f"/api/cards/{card_id}")
        assert response.status_code == 200
        assert test_db.get_card(card_id) is None

    def test_delete_nonexistent_card(self, client):
        response = client.delete("/api/cards/99999")
        assert response.status_code == 404


class TestAchievementsEndpoint:
    def test_get_achievements(self, client):
        response = client.get("/api/achievements")
        assert response.status_code == 200
        data = response.json()
        assert "achievements" in data
        assert len(data["achievements"]) == 13
