import os
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from database import Database, level_from_xp, xp_for_level, xp_to_next_level


class TestLevelSystem:
    def test_level_1_at_zero_xp(self):
        assert level_from_xp(0) == 1

    def test_level_2_at_25_xp(self):
        assert level_from_xp(25) == 2

    def test_level_5_at_400_xp(self):
        assert level_from_xp(400) == 5

    def test_xp_for_level_1(self):
        assert xp_for_level(1) == 0

    def test_xp_for_level_2(self):
        assert xp_for_level(2) == 25

    def test_xp_to_next_level(self):
        assert xp_to_next_level(0) == 25

    def test_xp_to_next_level_mid(self):
        assert xp_to_next_level(10) == 15


class TestFolderCRUD:
    def test_create_folder(self, db):
        fid = db.create_folder(name="Chemistry", icon="🧪")
        assert fid is not None

    def test_get_folder(self, db):
        fid = db.create_folder(name="History", icon="🏛️")
        folder = db.get_folder(fid)
        assert folder["name"] == "History"
        assert folder["icon"] == "🏛️"

    def test_get_nonexistent_folder(self, db):
        assert db.get_folder(9999) is None

    def test_list_folders(self, db):
        db.create_folder(name="Folder A")
        db.create_folder(name="Folder B")
        folders = db.get_folders()
        assert len(folders) == 2

    def test_update_folder(self, db):
        fid = db.create_folder(name="Old Name")
        db.update_folder(fid, name="New Name", icon="🔬")
        folder = db.get_folder(fid)
        assert folder["name"] == "New Name"
        assert folder["icon"] == "🔬"

    def test_delete_folder(self, db):
        fid = db.create_folder(name="Delete Me")
        db.delete_folder(fid)
        assert db.get_folder(fid) is None

    def test_delete_folder_moves_decks_to_null(self, db):
        fid = db.create_folder(name="Temp Folder")
        did = db.create_deck(name="Orphan Deck", folder_id=fid)
        db.delete_folder(fid)
        deck = db.get_deck(did)
        assert deck is not None
        assert deck["folder_id"] is None

    def test_folder_auto_color(self, db):
        fid = db.create_folder(name="Colored")
        folder = db.get_folder(fid)
        assert folder["color"] != ""


class TestDeckWithFolders:
    def test_create_deck_in_folder(self, db):
        fid = db.create_folder(name="Chemistry")
        did = db.create_deck(name="Organic Chem", folder_id=fid)
        deck = db.get_deck(did)
        assert deck["folder_id"] == fid

    def test_create_deck_no_folder(self, db):
        did = db.create_deck(name="Standalone")
        deck = db.get_deck(did)
        assert deck["folder_id"] is None

    def test_get_decks_by_folder(self, db):
        fid = db.create_folder(name="Math")
        db.create_deck(name="Algebra", folder_id=fid)
        db.create_deck(name="Standalone")
        decks = db.get_decks(folder_id=fid)
        assert len(decks) == 1
        assert decks[0]["name"] == "Algebra"

    def test_get_unassigned_decks(self, db):
        fid = db.create_folder(name="Physics")
        db.create_deck(name="Mechanics", folder_id=fid)
        db.create_deck(name="Free Deck")
        unassigned = db.get_unassigned_decks()
        assert len(unassigned) == 1
        assert unassigned[0]["name"] == "Free Deck"

    def test_move_deck_to_folder(self, db):
        fid = db.create_folder(name="Bio")
        did = db.create_deck(name="Cells")
        db.move_deck_to_folder(did, fid)
        deck = db.get_deck(did)
        assert deck["folder_id"] == fid

    def test_move_deck_out_of_folder(self, db):
        fid = db.create_folder(name="Geo")
        did = db.create_deck(name="Rocks", folder_id=fid)
        db.move_deck_to_folder(did, None)
        deck = db.get_deck(did)
        assert deck["folder_id"] is None


class TestDeckCRUD:
    def test_create_deck(self, db):
        did = db.create_deck(name="Biology 101")
        assert did is not None

    def test_get_deck(self, db):
        did = db.create_deck(name="Biology 101", subject="Biology")
        deck = db.get_deck(did)
        assert deck["name"] == "Biology 101"
        assert deck["subject"] == "Biology"

    def test_get_nonexistent_deck(self, db):
        assert db.get_deck(9999) is None

    def test_list_decks(self, db):
        db.create_deck(name="Deck A")
        db.create_deck(name="Deck B")
        decks = db.get_decks()
        assert len(decks) == 2

    def test_delete_deck(self, db):
        did = db.create_deck(name="To Delete")
        db.delete_deck(did)
        assert db.get_deck(did) is None

    def test_delete_deck_cascades_cards(self, db):
        did = db.create_deck(name="With Cards")
        db.add_card(did, "Q?", "A")
        db.delete_deck(did)
        assert db.get_cards_by_deck(did) == []


class TestCardCRUD:
    def test_add_card(self, db_with_deck):
        db, did = db_with_deck
        cid = db.add_card(did, "What is DNA?", "Deoxyribonucleic acid")
        assert cid is not None

    def test_get_card(self, db_with_deck):
        db, did = db_with_deck
        cid = db.add_card(did, "What is DNA?", "Deoxyribonucleic acid")
        card = db.get_card(cid)
        assert card["question"] == "What is DNA?"
        assert card["answer"] == "Deoxyribonucleic acid"

    def test_get_cards_by_deck(self, db_with_cards):
        db, did, cids = db_with_cards
        cards = db.get_cards_by_deck(did)
        assert len(cards) == 5

    def test_add_mc_card(self, db_with_deck):
        db, did = db_with_deck
        cid = db.add_card(did, "Color?", "Blue", card_type="multiple_choice", options=["Blue", "Red", "Green"])
        card = db.get_card(cid)
        assert card["options"] == ["Blue", "Red", "Green"]

    def test_delete_card(self, db_with_cards):
        db, did, cids = db_with_cards
        db.delete_card(cids[0])
        assert db.get_card(cids[0]) is None
        assert len(db.get_cards_by_deck(did)) == 4


class TestSpacedRepetition:
    def test_first_correct(self, db_with_deck):
        db, did = db_with_deck
        cid = db.add_card(did, "Q?", "A")
        r = db.update_card_review(cid, True)
        assert r["interval"] == 1
        assert r["repetitions"] == 1

    def test_second_correct(self, db_with_deck):
        db, did = db_with_deck
        cid = db.add_card(did, "Q?", "A")
        db.update_card_review(cid, True)
        r = db.update_card_review(cid, True)
        assert r["interval"] == 6
        assert r["repetitions"] == 2

    def test_wrong_resets(self, db_with_deck):
        db, did = db_with_deck
        cid = db.add_card(did, "Q?", "A")
        db.update_card_review(cid, True)
        db.update_card_review(cid, True)
        r = db.update_card_review(cid, False)
        assert r["repetitions"] == 0
        assert r["interval"] == 1

    def test_ease_minimum(self, db_with_deck):
        db, did = db_with_deck
        cid = db.add_card(did, "Q?", "A")
        for _ in range(10):
            db.update_card_review(cid, False)
        card = db.get_card(cid)
        assert card["ease_factor"] >= 1.3

    def test_nonexistent_card(self, db):
        assert db.update_card_review(9999, True) == {}


class TestProgress:
    def test_initial(self, db):
        p = db.get_progress()
        assert p["total_xp"] == 0
        assert p["level"] == 1

    def test_add_xp(self, db):
        db.add_xp(50)
        assert db.get_progress()["total_xp"] == 50

    def test_record_review(self, db_with_deck):
        db, did = db_with_deck
        cid = db.add_card(did, "Q?", "A")
        db.record_review(cid, did, True)
        p = db.get_progress()
        assert p["total_cards_reviewed"] == 1
        assert p["total_correct"] == 1


class TestAchievements:
    def test_initial_locked(self, db):
        achievements = db.get_achievements()
        assert len(achievements) == 13
        assert all(a["unlocked_at"] is None for a in achievements)

    def test_first_deck_unlocks(self, db):
        db.create_deck(name="First")
        a = [a for a in db.get_achievements() if a["name"] == "First Deck"]
        assert a[0]["unlocked_at"] is not None

    def test_unlock_idempotent(self, db):
        db.create_deck(name="First")
        assert db.unlock_achievement("First Deck") is False


class TestSettings:
    def test_default_model(self, db):
        assert db.get_model() == "gemma4:31b-cloud"

    def test_set_model(self, db):
        db.set_setting("model", "gemma3:4b")
        assert db.get_model() == "gemma3:4b"
