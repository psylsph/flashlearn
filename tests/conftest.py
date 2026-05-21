import os
import sys
import tempfile
from unittest.mock import patch

import pytest

# Make sure we can import from parent dir
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from database import Database


@pytest.fixture
def db(tmp_path):
    """Create a fresh test database in a temp directory."""
    db_path = tmp_path / "test_flashlearn.db"
    with patch("database.DB_PATH", db_path):
        db = Database()
        # Override the path since __init__ already ran with the patched path
        yield db


@pytest.fixture
def db_with_deck(db):
    """Create a database with one deck."""
    deck_id = db.create_deck(name="Test Deck", subject="Biology")
    return db, deck_id


@pytest.fixture
def db_with_cards(db_with_deck):
    """Create a database with a deck and some cards."""
    db, deck_id = db_with_deck
    card_ids = []
    for i in range(5):
        cid = db.add_card(
            deck_id=deck_id,
            question=f"Question {i+1}?",
            answer=f"Answer {i+1}",
            card_type="flashcard",
            difficulty=i % 5 + 1,
        )
        card_ids.append(cid)
    return db, deck_id, card_ids


@pytest.fixture
def sample_png_bytes():
    """Minimal valid PNG file bytes."""
    import struct
    import zlib
    # 1x1 white pixel PNG
    signature = b'\x89PNG\r\n\x1a\n'
    def chunk(ctype, data):
        c = ctype + data
        return struct.pack('>I', len(data)) + c + struct.pack('>I', zlib.crc32(c) & 0xffffffff)
    ihdr = chunk(b'IHDR', struct.pack('>IIBBBBB', 1, 1, 8, 2, 0, 0, 0))
    raw = zlib.compress(b'\x00\xff\xff\xff')
    idat = chunk(b'IDAT', raw)
    iend = chunk(b'IEND', b'')
    return signature + ihdr + idat + iend
