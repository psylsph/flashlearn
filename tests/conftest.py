import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import database as db_module

# Create temp DB for tests
tmp = tempfile.mkdtemp()
test_db_path = os.path.join(tmp, "test.db")


@pytest.fixture
def db():
    """Fresh Database instance per test with temp DB."""
    # Patch DB_PATH
    original = db_module.DB_PATH
    db_module.DB_PATH = Path(test_db_path)
    d = db_module.Database()
    yield d
    # Cleanup
    if os.path.exists(test_db_path):
        os.unlink(test_db_path)
    db_module.DB_PATH = original


@pytest.fixture
def db_with_deck(db):
    """Database with one empty deck."""
    did = db.create_deck(name="Test Deck", subject="Testing")
    return db, did


@pytest.fixture
def db_with_cards(db):
    """Database with a deck containing 5 flashcards."""
    did = db.create_deck(name="Cards Deck", subject="Mixed")
    cids = []
    for i in range(5):
        cid = db.add_card(did, f"Question {i}?", f"Answer {i}",
                          card_type="flashcard" if i % 2 == 0 else "multiple_choice",
                          options=["A", "B", "C", "D"] if i % 2 == 1 else [])
        cids.append(cid)
    return db, did, cids


@pytest.fixture
def sample_png_bytes():
    """Minimal valid PNG image bytes."""
    import struct
    import zlib

    def make_png():
        signature = b'\x89PNG\r\n\x1a\n'
        # IHDR: 1x1, 8-bit RGB
        ihdr_data = struct.pack('>IIBBBBB', 1, 1, 8, 2, 0, 0, 0)
        ihdr_crc = zlib.crc32(b'IHDR' + ihdr_data) & 0xffffffff
        ihdr = struct.pack('>I', 13) + b'IHDR' + ihdr_data + struct.pack('>I', ihdr_crc)
        # IDAT: single white pixel
        raw = zlib.compress(b'\x00\xff\xff\xff')
        idat_crc = zlib.crc32(b'IDAT' + raw) & 0xffffffff
        idat = struct.pack('>I', len(raw)) + b'IDAT' + raw + struct.pack('>I', idat_crc)
        # IEND
        iend_crc = zlib.crc32(b'IEND') & 0xffffffff
        iend = struct.pack('>I', 0) + b'IEND' + struct.pack('>I', iend_crc)
        return signature + ihdr + idat + iend

    return make_png()
