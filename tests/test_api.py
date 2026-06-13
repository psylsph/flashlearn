import os
import sys
import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import database as db_module
import tempfile
tmp = tempfile.mkdtemp()
bootstrap_db_path = Path(tmp) / "bootstrap.db"

# Patch DB_PATH before importing main so module-level Database init does not touch app data.
db_module.DB_PATH = bootstrap_db_path

from database import Database
test_db = None
import main


@pytest.fixture
def client(tmp_path):
    global test_db
    db_module.DB_PATH = tmp_path / "test.db"
    test_db = Database()
    main.db = test_db
    main.PHOTO_DIR = tmp_path / "photos"
    main.PHOTO_DIR.mkdir(parents=True, exist_ok=True)
    main.study_sessions.clear()
    return TestClient(main.app)


class TestStatusEndpoint:
    def test_favicon(self, client):
        r = client.get("/favicon.ico")
        assert r.status_code == 200

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

    def test_update_settings_rejects_blank_model(self, client):
        r = client.put("/api/settings?model=%20%20%20")
        assert r.status_code == 400

    def test_update_settings_strips_model(self, client):
        r = client.put("/api/settings?model=%20gemma3:4b%20")
        assert r.status_code == 200
        assert test_db.get_model() == "gemma3:4b"


class TestFolderEndpoints:
    def test_create_folder(self, client):
        r = client.post("/api/folders", data={"name": "Chemistry", "icon": "🧪"})
        assert r.status_code == 200
        assert "id" in r.json()

    def test_create_folder_rejects_blank_name(self, client):
        r = client.post("/api/folders", data={"name": "   "})
        assert r.status_code == 400

    def test_create_folder_rejects_bad_color(self, client):
        r = client.post("/api/folders", data={"name": "Bad", "color": "red"})
        assert r.status_code == 400

    def test_create_folder_rejects_long_icon(self, client):
        r = client.post("/api/folders", data={"name": "Bad", "icon": "x" * 9})
        assert r.status_code == 400

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

    def test_create_deck_rejects_blank_name(self, client):
        r = client.post("/api/decks", data={"name": "   "})
        assert r.status_code == 400

    def test_create_deck_strips_and_caps_name(self, client):
        r = client.post("/api/decks", data={"name": f"  {'x' * 250}  "})
        assert r.status_code == 200
        deck = test_db.get_deck(r.json()["id"])
        assert len(deck["name"]) == 200
        assert deck["name"] == "x" * 200

    def test_create_deck_in_folder(self, client):
        f = client.post("/api/folders", data={"name": "Bio"})
        fid = f.json()["id"]
        r = client.post("/api/decks", data={"name": "Cells", "folder_id": fid})
        assert r.status_code == 200
        did = r.json()["id"]
        deck = test_db.get_deck(did)
        assert deck["folder_id"] == fid

    def test_create_deck_invalid_folder(self, client):
        r = client.post("/api/decks", data={"name": "Cells", "folder_id": 99999})
        assert r.status_code == 400

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

    def test_move_deck_invalid_folder(self, client):
        d = client.post("/api/decks", data={"name": "Mover"})
        did = d.json()["id"]
        r = client.put(f"/api/decks/{did}/move?folder_id=99999")
        assert r.status_code == 400

    def test_delete_deck(self, client):
        d = client.post("/api/decks", data={"name": "Delete Me"})
        did = d.json()["id"]
        assert client.delete(f"/api/decks/{did}").status_code == 200

    def test_delete_deck_removes_all_image_records_and_files(self, client, sample_png_bytes):
        ai_result = {"success": True, "cards": [{"question": "Q?", "answer": "A", "type": "flashcard"}]}
        with patch("main.generate_cards", return_value=ai_result):
            r = client.post("/api/upload", files=[
                ("photos", ("img1.png", sample_png_bytes, "image/png")),
                ("photos", ("img2.png", sample_png_bytes, "image/png")),
            ], data={"deck_name": "Images", "folder_id": "", "model": ""})
        did = r.json()["deck"]["id"]
        image_paths = [img["image_path"] for img in test_db.get_deck_images(did)]
        assert len(image_paths) == 2
        assert all((main.PHOTO_DIR / p).exists() for p in image_paths)
        assert client.delete(f"/api/decks/{did}").status_code == 200
        assert test_db.get_deck_images(did) == []
        assert all(not (main.PHOTO_DIR / p).exists() for p in image_paths)


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
        assert r.status_code == 400

    def test_upload_ai_failure(self, client, sample_png_bytes):
        with patch("main.generate_cards", return_value={"success": False, "error": "AI down"}):
            r = client.post("/api/upload", files=[
                ("photos", ("test.png", sample_png_bytes, "image/png")),
            ], data={"deck_name": "", "folder_id": "", "model": ""})
        assert r.status_code == 502

    def test_upload_invalid_folder(self, client, sample_png_bytes):
        r = client.post("/api/upload", files=[
            ("photos", ("test.png", sample_png_bytes, "image/png")),
        ], data={"deck_name": "", "folder_id": "99999", "model": ""})
        assert r.status_code == 400

    def test_upload_mixed_valid_and_invalid_image_succeeds(self, client, sample_png_bytes):
        ai_result = {"success": True, "cards": [{"question": "Q?", "answer": "A", "type": "flashcard"}]}
        with patch("main.generate_cards", return_value=ai_result):
            r = client.post("/api/upload", files=[
                ("photos", ("good.png", sample_png_bytes, "image/png")),
                ("photos", ("bad.txt", b"not an image", "text/plain")),
            ], data={"deck_name": "Mixed", "folder_id": "", "model": ""})
        assert r.status_code == 200
        assert r.json()["images_processed"] == 1
        assert len(r.json()["errors"]) == 1

    def test_upload_cleans_saved_files_after_database_failure(self, client, sample_png_bytes):
        ai_result = {"success": True, "cards": [{"question": "Q?", "answer": "A", "type": "flashcard"}]}
        with patch("main.generate_cards", return_value=ai_result), \
             patch.object(test_db, "create_deck_with_cards", side_effect=RuntimeError("db failed")):
            with pytest.raises(RuntimeError):
                client.post("/api/upload", files=[
                    ("photos", ("test.png", sample_png_bytes, "image/png")),
                ], data={"deck_name": "", "folder_id": "", "model": ""})
        assert list(main.PHOTO_DIR.iterdir()) == []

    def test_upload_cleans_saved_files_after_mid_loop_exception(self, client, sample_png_bytes):
        ai_result = {"success": True, "cards": [{"question": "Q?", "answer": "A", "type": "flashcard"}]}
        with patch("main.generate_cards", return_value=ai_result), \
             patch("main._normalize_image", side_effect=[sample_png_bytes, RuntimeError("boom")]):
            with pytest.raises(RuntimeError):
                client.post("/api/upload", files=[
                    ("photos", ("img1.png", sample_png_bytes, "image/png")),
                    ("photos", ("img2.png", sample_png_bytes, "image/png")),
                ], data={"deck_name": "", "folder_id": "", "model": ""})
        assert list(main.PHOTO_DIR.iterdir()) == []

    def test_upload_strips_and_caps_ai_metadata(self, client, sample_png_bytes):
        ai_result = {
            "success": True,
            "subject": f"  {'s' * 250}  ",
            "deck_name": f"  {'d' * 250}  ",
            "description": f"  {'x' * 2500}  ",
            "cards": [{"question": "Q?", "answer": "A", "type": "flashcard"}],
        }
        with patch("main.generate_cards", return_value=ai_result):
            r = client.post("/api/upload", files=[
                ("photos", ("test.png", sample_png_bytes, "image/png")),
            ], data={"deck_name": "", "folder_id": "", "model": ""})
        deck = r.json()["deck"]
        assert deck["name"] == "d" * 200
        assert deck["subject"] == "s" * 200
        assert deck["description"] == "x" * 2000


class TestStudyEndpoints:
    def test_get_study_cards(self, client):
        d = client.post("/api/decks", data={"name": "Study Deck"})
        did = d.json()["id"]
        test_db.add_card(did, "Q?", "A")
        r = client.get(f"/api/decks/{did}/study")
        assert r.status_code == 200
        assert len(r.json()["cards"]) >= 1

    def test_nonexistent_deck_study_returns_404(self, client):
        r = client.get("/api/decks/99999/study")
        assert r.status_code == 404

    def test_get_study_cards_cleans_expired_sessions(self, client):
        main.study_sessions["expired"] = {
            "deck_id": 1,
            "card_ids": set(),
            "reviewed": {},
            "created_at": 0,
            "completed": False,
        }
        d = client.post("/api/decks", data={"name": "Study Deck"})
        did = d.json()["id"]
        test_db.add_card(did, "Q?", "A")
        assert client.get(f"/api/decks/{did}/study").status_code == 200
        assert "expired" not in main.study_sessions

    def test_review_card(self, client):
        d = client.post("/api/decks", data={"name": "Review Deck"})
        did = d.json()["id"]
        cid = test_db.add_card(did, "Q?", "A")
        session = client.get(f"/api/decks/{did}/study").json()["session_id"]
        r = client.post(f"/api/cards/{cid}/review?correct=true&time_ms=500&session_id={session}")
        assert r.status_code == 200
        assert r.json()["xp_earned"] == 15

    def test_duplicate_review_returns_409(self, client):
        d = client.post("/api/decks", data={"name": "Review Deck"})
        did = d.json()["id"]
        cid = test_db.add_card(did, "Q?", "A")
        session = client.get(f"/api/decks/{did}/study").json()["session_id"]
        assert client.post(f"/api/cards/{cid}/review?correct=true&session_id={session}").status_code == 200
        r = client.post(f"/api/cards/{cid}/review?correct=true&session_id={session}")
        assert r.status_code == 409

    def test_complete_session_before_all_cards_reviewed_returns_400(self, client):
        d = client.post("/api/decks", data={"name": "Partial Deck"})
        did = d.json()["id"]
        cids = [test_db.add_card(did, f"Q{i}?", f"A{i}") for i in range(2)]
        session = client.get(f"/api/decks/{did}/study").json()["session_id"]
        assert client.post(f"/api/cards/{cids[0]}/review?correct=true&session_id={session}").status_code == 200
        r = client.post(f"/api/session/complete?deck_id={did}&session_id={session}")
        assert r.status_code == 400

    def test_session_complete(self, client):
        d = client.post("/api/decks", data={"name": "Session Deck"})
        did = d.json()["id"]
        cids = [test_db.add_card(did, f"Q{i}?", f"A{i}") for i in range(10)]
        session = client.get(f"/api/decks/{did}/study").json()["session_id"]
        for cid in cids[:9]:
            assert client.post(f"/api/cards/{cid}/review?correct=true&session_id={session}").status_code == 200
        assert client.post(f"/api/cards/{cids[9]}/review?correct=false&session_id={session}").status_code == 200
        r = client.post(f"/api/session/complete?deck_id={did}&session_id={session}")
        assert r.status_code == 200
        assert r.json()["bonus_xp"] == 50  # 90%+

    def test_fast_session_unlocks_speed_demon(self, client):
        d = client.post("/api/decks", data={"name": "Fast Deck"})
        did = d.json()["id"]
        cids = [test_db.add_card(did, f"Q{i}?", f"A{i}") for i in range(3)]
        session = client.get(f"/api/decks/{did}/study").json()["session_id"]
        for cid in cids:
            assert client.post(f"/api/cards/{cid}/review?correct=true&time_ms=3000&session_id={session}").status_code == 200
        assert client.post(f"/api/session/complete?deck_id={did}&session_id={session}").status_code == 200
        achievements = test_db.get_achievements()
        speed_demon = next(a for a in achievements if a["name"] == "Speed Demon")
        assert speed_demon["unlocked_at"] is not None

    def test_slow_session_does_not_unlock_speed_demon(self, client):
        d = client.post("/api/decks", data={"name": "Slow Deck"})
        did = d.json()["id"]
        cids = [test_db.add_card(did, f"Q{i}?", f"A{i}") for i in range(3)]
        session = client.get(f"/api/decks/{did}/study").json()["session_id"]
        for cid in cids:
            assert client.post(f"/api/cards/{cid}/review?correct=true&time_ms=7000&session_id={session}").status_code == 200
        assert client.post(f"/api/session/complete?deck_id={did}&session_id={session}").status_code == 200
        achievements = test_db.get_achievements()
        speed_demon = next(a for a in achievements if a["name"] == "Speed Demon")
        assert speed_demon["unlocked_at"] is None


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
