import os
import sys
import json
from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import database as db_module
import tempfile
tmp = tempfile.mkdtemp()
test_db_path = os.path.join(tmp, "test.db")

# Patch DB_PATH before Database init
db_module.DB_PATH = type('', (), {
    '__truediv__': lambda s, o: test_db_path,
    'parent': type('', (), {
        'mkdir': lambda **kw: None,
        '__truediv__': lambda s, o: type('', (), {'mkdir': lambda **kw: None})()
    })()
})()

from database import Database
test_db = Database()
import main
main.db = test_db


@pytest.fixture
def client():
    return TestClient(main.app)


class TestStatusEndpoint:
    def test_get_status(self, client):
        with patch("main.check_ollama_status", return_value={"running": True, "models": ["gemma4:31b-cloud"]}):
            r = client.get("/api/status")
        assert r.status_code == 200
        assert r.json()["running"] is True


class TestProgressEndpoint:
    def test_get_progress(self, client):
        r = client.get("/api/progress")
        assert r.status_code == 200
        assert "level" in r.json()


class TestSettingsEndpoints:
    def test_get_settings(self, client):
        r = client.get("/api/settings")
        assert r.status_code == 200

    def test_update_settings(self, client):
        r = client.put("/api/settings?model=gemma3:4b")
        assert r.status_code == 200


class TestFolderEndpoints:
    def test_create_folder(self, client):
        r = client.post("/api/folders", data={"name": "Chemistry", "icon": "🧪"})
        assert r.status_code == 200
        assert "id" in r.json()

    def test_list_folders(self, client):
        client.post("/api/folders", data={"name": "History"})
        r = client.get("/api/folders")
        assert r.status_code == 200
        assert len(r.json()["folders"]) >= 1

    def test_update_folder(self, client):
        create = client.post("/api/folders", data={"name": "Old"})
        fid = create.json()["id"]
        r = client.put(f"/api/folders/{fid}?name=New&icon=🔬")
        assert r.status_code == 200

    def test_delete_folder(self, client):
        create = client.post("/api/folders", data={"name": "Delete Me"})
        fid = create.json()["id"]
        r = client.delete(f"/api/folders/{fid}")
        assert r.status_code == 200

    def test_delete_nonexistent_folder(self, client):
        r = client.delete("/api/folders/99999")
        assert r.status_code == 404


class TestDeckEndpoints:
    def test_create_deck(self, client):
        r = client.post("/api/decks", data={"name": "Test Deck"})
        assert r.status_code == 200

    def test_create_deck_in_folder(self, client):
        f = client.post("/api/folders", data={"name": "Bio"})
        fid = f.json()["id"]
        r = client.post("/api/decks", data={"name": "Cells", "folder_id": fid})
        assert r.status_code == 200
        did = r.json()["id"]
        deck = test_db.get_deck(did)
        assert deck["folder_id"] == fid

    def test_list_decks_by_folder(self, client):
        f = client.post("/api/folders", data={"name": "Math"})
        fid = f.json()["id"]
        client.post("/api/decks", data={"name": "Algebra", "folder_id": fid})
        r = client.get(f"/api/decks?folder_id={fid}")
        assert r.status_code == 200
        assert len(r.json()["decks"]) >= 1

    def test_get_unassigned_decks(self, client):
        r = client.get("/api/decks/unassigned")
        assert r.status_code == 200

    def test_move_deck(self, client):
        f = client.post("/api/folders", data={"name": "Move Target"})
        fid = f.json()["id"]
        d = client.post("/api/decks", data={"name": "Mover"})
        did = d.json()["id"]
        r = client.put(f"/api/decks/{did}/move?folder_id={fid}")
        assert r.status_code == 200

    def test_delete_deck(self, client):
        d = client.post("/api/decks", data={"name": "Delete Me"})
        did = d.json()["id"]
        assert client.delete(f"/api/decks/{did}").status_code == 200


class TestMultiImageUpload:
    def test_single_image_upload(self, client, sample_png_bytes):
        ai_result = {
            "success": True, "subject": "Bio", "deck_name": "Cells",
            "description": "Cell biology",
            "cards": [
                {"question": "Q1?", "answer": "A1", "type": "flashcard", "difficulty": 2},
            ],
        }
        with patch("main.generate_cards", return_value=ai_result):
            r = client.post("/api/upload", files=[
                ("photos", ("test.png", sample_png_bytes, "image/png")),
            ], data={"deck_name": "", "folder_id": "", "model": ""})
        assert r.status_code == 200
        data = r.json()
        assert data["success"] is True
        assert data["images_processed"] == 1

    def test_multi_image_upload(self, client, sample_png_bytes):
        ai_result = {
            "success": True, "subject": "Math", "deck_name": "Algebra",
            "description": "Algebra basics",
            "cards": [
                {"question": "Q?", "answer": "A", "type": "flashcard", "difficulty": 2},
            ],
        }
        with patch("main.generate_cards", return_value=ai_result):
            r = client.post("/api/upload", files=[
                ("photos", ("img1.png", sample_png_bytes, "image/png")),
                ("photos", ("img2.png", sample_png_bytes, "image/png")),
                ("photos", ("img3.png", sample_png_bytes, "image/png")),
            ], data={"deck_name": "Multi Test", "folder_id": "", "model": ""})
        assert r.status_code == 200
        data = r.json()
        assert data["images_processed"] == 3
        assert data["total_images"] == 3
        assert len(data["cards"]) == 3  # 1 card per image

    def test_upload_to_folder(self, client, sample_png_bytes):
        f = client.post("/api/folders", data={"name": "Upload Folder"})
        fid = f.json()["id"]
        ai_result = {
            "success": True, "cards": [
                {"question": "Q?", "answer": "A", "type": "flashcard", "difficulty": 2},
            ],
        }
        with patch("main.generate_cards", return_value=ai_result):
            r = client.post("/api/upload", files=[
                ("photos", ("test.png", sample_png_bytes, "image/png")),
            ], data={"deck_name": "", "folder_id": str(fid), "model": ""})
        assert r.status_code == 200
        did = r.json()["deck"]["id"]
        deck = test_db.get_deck(did)
        assert deck["folder_id"] == fid

    def test_upload_invalid_image(self, client):
        r = client.post("/api/upload", files=[
            ("photos", ("bad.txt", b"not an image", "text/plain")),
        ], data={"deck_name": "", "folder_id": "", "model": ""})
        assert r.status_code == 500

    def test_upload_ai_failure(self, client, sample_png_bytes):
        with patch("main.generate_cards", return_value={"success": False, "error": "AI down"}):
            r = client.post("/api/upload", files=[
                ("photos", ("test.png", sample_png_bytes, "image/png")),
            ], data={"deck_name": "", "folder_id": "", "model": ""})
        assert r.status_code == 500


class TestStudyEndpoints:
    def test_get_study_cards(self, client):
        d = client.post("/api/decks", data={"name": "Study Deck"})
        did = d.json()["id"]
        test_db.add_card(did, "Q?", "A")
        r = client.get(f"/api/decks/{did}/study")
        assert r.status_code == 200
        assert len(r.json()["cards"]) >= 1

    def test_review_card(self, client):
        d = client.post("/api/decks", data={"name": "Review Deck"})
        did = d.json()["id"]
        cid = test_db.add_card(did, "Q?", "A")
        r = client.post(f"/api/cards/{cid}/review?correct=true&time_ms=500")
        assert r.status_code == 200
        assert r.json()["xp_earned"] == 15

    def test_session_complete(self, client):
        d = client.post("/api/decks", data={"name": "Session Deck"})
        did = d.json()["id"]
        r = client.post(f"/api/session/complete?deck_id={did}&correct_count=9&total_count=10")
        assert r.status_code == 200
        assert r.json()["bonus_xp"] == 50  # 90%+


class TestCardEndpoints:
    def test_delete_card(self, client):
        d = client.post("/api/decks", data={"name": "Del Deck"})
        did = d.json()["id"]
        cid = test_db.add_card(did, "Q?", "A")
        r = client.delete(f"/api/cards/{cid}")
        assert r.status_code == 200


class TestAchievementsEndpoint:
    def test_get_achievements(self, client):
        r = client.get("/api/achievements")
        assert r.status_code == 200
        assert len(r.json()["achievements"]) == 13
