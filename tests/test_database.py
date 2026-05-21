import os
import sys
from unittest.mock import patch
from datetime import datetime, timedelta

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
        # At 0 XP, level 1, need 25 to reach level 2
        assert xp_to_next_level(0) == 25

    def test_xp_to_next_level_mid(self):
        # At 10 XP, level 1, need 15 more to reach level 2
        assert xp_to_next_level(10) == 15


class TestDeckCRUD:
    def test_create_deck(self, db):
        deck_id = db.create_deck(name="Biology 101")
        assert deck_id is not None
        assert isinstance(deck_id, int)

    def test_get_deck(self, db):
        deck_id = db.create_deck(name="Biology 101", subject="Biology", description="Intro course")
        deck = db.get_deck(deck_id)
        assert deck is not None
        assert deck["name"] == "Biology 101"
        assert deck["subject"] == "Biology"
        assert deck["description"] == "Intro course"

    def test_get_nonexistent_deck(self, db):
        assert db.get_deck(9999) is None

    def test_list_decks(self, db):
        db.create_deck(name="Deck A")
        db.create_deck(name="Deck B")
        decks = db.get_decks()
        assert len(decks) == 2
        names = [d["name"] for d in decks]
        assert "Deck A" in names
        assert "Deck B" in names

    def test_delete_deck(self, db):
        deck_id = db.create_deck(name="To Delete")
        db.delete_deck(deck_id)
        assert db.get_deck(deck_id) is None

    def test_delete_deck_cascades_cards(self, db):
        deck_id = db.create_deck(name="With Cards")
        db.add_card(deck_id, "Q?", "A")
        db.delete_deck(deck_id)
        assert db.get_cards_by_deck(deck_id) == []


class TestCardCRUD:
    def test_add_card(self, db_with_deck):
        db, deck_id = db_with_deck
        card_id = db.add_card(deck_id, "What is DNA?", "Deoxyribonucleic acid")
        assert card_id is not None

    def test_get_card(self, db_with_deck):
        db, deck_id = db_with_deck
        card_id = db.add_card(deck_id, "What is DNA?", "Deoxyribonucleic acid", card_type="flashcard")
        card = db.get_card(card_id)
        assert card["question"] == "What is DNA?"
        assert card["answer"] == "Deoxyribonucleic acid"
        assert card["card_type"] == "flashcard"

    def test_get_cards_by_deck(self, db_with_cards):
        db, deck_id, card_ids = db_with_cards
        cards = db.get_cards_by_deck(deck_id)
        assert len(cards) == 5

    def test_add_mc_card(self, db_with_deck):
        db, deck_id = db_with_deck
        card_id = db.add_card(
            deck_id, "Color of sky?", "Blue",
            card_type="multiple_choice",
            options=["Blue", "Red", "Green", "Yellow"],
        )
        card = db.get_card(card_id)
        assert card["card_type"] == "multiple_choice"
        assert card["options"] == ["Blue", "Red", "Green", "Yellow"]

    def test_delete_card(self, db_with_cards):
        db, deck_id, card_ids = db_with_cards
        db.delete_card(card_ids[0])
        assert db.get_card(card_ids[0]) is None
        cards = db.get_cards_by_deck(deck_id)
        assert len(cards) == 4


class TestSpacedRepetition:
    def test_first_correct_review(self, db_with_deck):
        db, deck_id = db_with_deck
        card_id = db.add_card(deck_id, "Q?", "A")
        result = db.update_card_review(card_id, correct=True)
        assert result["interval"] == 1
        assert result["repetitions"] == 1

    def test_second_correct_review(self, db_with_deck):
        db, deck_id = db_with_deck
        card_id = db.add_card(deck_id, "Q?", "A")
        db.update_card_review(card_id, correct=True)
        result = db.update_card_review(card_id, correct=True)
        assert result["interval"] == 6
        assert result["repetitions"] == 2

    def test_third_correct_increases_interval(self, db_with_deck):
        db, deck_id = db_with_deck
        card_id = db.add_card(deck_id, "Q?", "A")
        db.update_card_review(card_id, correct=True)
        db.update_card_review(card_id, correct=True)
        result = db.update_card_review(card_id, correct=True)
        assert result["interval"] > 6
        assert result["repetitions"] == 3

    def test_wrong_answer_resets(self, db_with_deck):
        db, deck_id = db_with_deck
        card_id = db.add_card(deck_id, "Q?", "A")
        db.update_card_review(card_id, correct=True)
        db.update_card_review(card_id, correct=True)
        result = db.update_card_review(card_id, correct=False)
        assert result["repetitions"] == 0
        assert result["interval"] == 1

    def test_ease_factor_minimum(self, db_with_deck):
        db, deck_id = db_with_deck
        card_id = db.add_card(deck_id, "Q?", "A")
        # Many wrong answers to push ease down
        for _ in range(10):
            db.update_card_review(card_id, correct=False)
        card = db.get_card(card_id)
        assert card["ease_factor"] >= 1.3

    def test_nonexistent_card_review(self, db):
        result = db.update_card_review(9999, correct=True)
        assert result == {}


class TestProgress:
    def test_initial_progress(self, db):
        progress = db.get_progress()
        assert progress["total_xp"] == 0
        assert progress["level"] == 1
        assert progress["current_streak"] == 0

    def test_add_xp(self, db):
        db.add_xp(50)
        progress = db.get_progress()
        assert progress["total_xp"] == 50

    def test_record_review(self, db_with_deck):
        db, deck_id = db_with_deck
        card_id = db.add_card(deck_id, "Q?", "A")
        db.record_review(card_id, deck_id, correct=True)
        progress = db.get_progress()
        assert progress["total_cards_reviewed"] == 1
        assert progress["total_correct"] == 1

    def test_record_wrong_review(self, db_with_deck):
        db, deck_id = db_with_deck
        card_id = db.add_card(deck_id, "Q?", "A")
        db.record_review(card_id, deck_id, correct=False)
        progress = db.get_progress()
        assert progress["total_cards_reviewed"] == 1
        assert progress["total_correct"] == 0


class TestAchievements:
    def test_initial_achievements_locked(self, db):
        achievements = db.get_achievements()
        assert len(achievements) == 13
        unlocked = [a for a in achievements if a["unlocked_at"]]
        assert len(unlocked) == 0

    def test_first_deck_achievement(self, db):
        db.create_deck(name="First")
        achievements = db.get_achievements()
        first_deck = [a for a in achievements if a["name"] == "First Deck"]
        assert len(first_deck) == 1
        assert first_deck[0]["unlocked_at"] is not None

    def test_unlock_achievement_idempotent(self, db):
        db.create_deck(name="First")
        # Second deck shouldn't re-unlock
        result = db.unlock_achievement("First Deck")
        assert result is False


class TestSettings:
    def test_default_model(self, db):
        assert db.get_model() == "gemma4:31b-cloud"

    def test_set_model(self, db):
        db.set_setting("model", "gemma3:4b")
        assert db.get_model() == "gemma3:4b"

    def test_get_nonexistent_setting(self, db):
        assert db.get_setting("nonexistent") == ""
        assert db.get_setting("nonexistent", "default") == "default"
