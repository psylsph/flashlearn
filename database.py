import sqlite3
import json
import math
from contextlib import closing
from pathlib import Path
from datetime import datetime, timedelta, UTC
from typing import Optional, List, Dict


DB_PATH = Path(__file__).parent / "data" / "flashlearn.db"
SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS folders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    icon TEXT DEFAULT '📁',
    color TEXT DEFAULT '',
    sort_order INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS decks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    folder_id INTEGER,
    name TEXT NOT NULL,
    subject TEXT DEFAULT '',
    description TEXT DEFAULT '',
    image_path TEXT,
    card_count INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (folder_id) REFERENCES folders(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS deck_images (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    deck_id INTEGER NOT NULL,
    image_path TEXT NOT NULL,
    sort_order INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (deck_id) REFERENCES decks(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS cards (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    deck_id INTEGER NOT NULL,
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    card_type TEXT DEFAULT 'flashcard',
    options TEXT DEFAULT '[]',
    difficulty INTEGER DEFAULT 3,
    next_review TEXT DEFAULT (datetime('now')),
    interval_days REAL DEFAULT 1.0,
    ease_factor REAL DEFAULT 2.5,
    repetitions INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (deck_id) REFERENCES decks(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS progress (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    total_xp INTEGER DEFAULT 0,
    current_streak INTEGER DEFAULT 0,
    longest_streak INTEGER DEFAULT 0,
    last_active TEXT DEFAULT '',
    total_cards_reviewed INTEGER DEFAULT 0,
    total_correct INTEGER DEFAULT 0,
    total_sessions INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS achievements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT DEFAULT '',
    icon TEXT DEFAULT '🏆',
    unlocked_at TEXT,
    sort_order INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS review_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    card_id INTEGER NOT NULL,
    deck_id INTEGER NOT NULL,
    correct INTEGER NOT NULL,
    time_taken_ms INTEGER DEFAULT 0,
    reviewed_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (card_id) REFERENCES cards(id) ON DELETE CASCADE,
    FOREIGN KEY (deck_id) REFERENCES decks(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT DEFAULT ''
);

INSERT OR IGNORE INTO progress (id) VALUES (1);

CREATE INDEX IF NOT EXISTS idx_decks_folder_id ON decks(folder_id);
CREATE INDEX IF NOT EXISTS idx_cards_deck_id ON cards(deck_id);
CREATE INDEX IF NOT EXISTS idx_cards_deck_review ON cards(deck_id, next_review);
CREATE INDEX IF NOT EXISTS idx_review_history_card_id ON review_history(card_id);
CREATE INDEX IF NOT EXISTS idx_review_history_deck_id ON review_history(deck_id);
CREATE INDEX IF NOT EXISTS idx_deck_images_deck_id ON deck_images(deck_id);
"""


def level_from_xp(xp: int) -> int:
    return int(math.floor(math.sqrt(xp / 25))) + 1


def xp_for_level(level: int) -> int:
    return (level - 1) ** 2 * 25


def xp_to_next_level(xp: int) -> int:
    current = level_from_xp(xp)
    return xp_for_level(current + 1) - xp


ACHIEVEMENT_DEFS = [
    ("First Deck", "Create your first deck", "📚", 1),
    ("Card Collector", "Have 25 cards across all decks", "🃏", 2),
    ("Card Master", "Have 100 cards across all decks", "🧠", 3),
    ("Getting Started", "Complete your first study session", "🌱", 4),
    ("Dedicated Learner", "Review 50 cards", "📖", 5),
    ("Study Pro", "Review 200 cards", "🎓", 6),
    ("Perfectionist", "Get a perfect round (all correct)", "💯", 7),
    ("On Fire", "Reach a 3-day streak", "🔥", 8),
    ("Week Warrior", "Reach a 7-day streak", "⚡", 9),
    ("Monthly Master", "Reach a 30-day streak", "👑", 10),
    ("Level 5", "Reach level 5", "⭐", 11),
    ("Level 10", "Reach level 10", "🌟", 12),
    ("Speed Demon", "Complete a speed round", "⏱️", 13),
]

FOLDER_COLORS = ["#6c63ff", "#00d2ff", "#00e676", "#ff9100", "#ff1744", "#ffd700", "#e040fb", "#00bfa5"]


class Database:
    def __init__(self):
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        (DB_PATH.parent / "photos").mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _conn(self):
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
        return conn

    def _init_db(self):
        with closing(self._conn()) as conn:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.executescript(SCHEMA)
            # Add folder_id column to existing decks table if missing (migration)
            cols = [row[1] for row in conn.execute("PRAGMA table_info(decks)").fetchall()]
            if "folder_id" not in cols:
                conn.execute("ALTER TABLE decks ADD COLUMN folder_id INTEGER REFERENCES folders(id) ON DELETE SET NULL")
            conn.execute(
                "INSERT OR IGNORE INTO deck_images (deck_id, image_path, sort_order) "
                "SELECT id, image_path, 0 FROM decks "
                "WHERE image_path IS NOT NULL "
                "AND image_path NOT IN (SELECT image_path FROM deck_images)"
            )
            conn.execute(
                "UPDATE decks SET card_count=(SELECT COUNT(*) FROM cards WHERE cards.deck_id=decks.id)"
            )
            conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            count = conn.execute("SELECT COUNT(*) FROM achievements").fetchone()[0]
            if count == 0:
                conn.executemany(
                    "INSERT INTO achievements (name, description, icon, sort_order) VALUES (?, ?, ?, ?)",
                    ACHIEVEMENT_DEFS,
                )
            conn.commit()

    # ── Settings ──────────────────────────────────────────────
    def get_setting(self, key: str, default: str = "") -> str:
        with closing(self._conn()) as conn:
            row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def set_setting(self, key: str, value: str):
        with closing(self._conn()) as conn:
            conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
            conn.commit()

    def get_model(self) -> str:
        return self.get_setting("model", "gemma4:31b-cloud")

    # ── Folders ───────────────────────────────────────────────
    def create_folder(self, name: str, icon: str = "📁", color: str = "") -> int:
        with closing(self._conn()) as conn:
            count = conn.execute("SELECT COUNT(*) FROM folders").fetchone()[0]
            if not color:
                color = FOLDER_COLORS[count % len(FOLDER_COLORS)]
            cur = conn.execute(
                "INSERT INTO folders (name, icon, color, sort_order) VALUES (?, ?, ?, ?)",
                (name, icon, color, count),
            )
            folder_id = cur.lastrowid
            conn.commit()
        return folder_id

    def get_folders(self) -> List[Dict]:
        with closing(self._conn()) as conn:
            rows = conn.execute(
                "SELECT f.*, "
                "(SELECT COUNT(*) FROM decks WHERE folder_id=f.id) as deck_count, "
                "(SELECT COALESCE(SUM(card_count), 0) FROM decks WHERE folder_id=f.id) as card_count "
                "FROM folders f ORDER BY f.sort_order, f.name"
            ).fetchall()
        return [dict(r) for r in rows]

    def get_folder(self, folder_id: int) -> Optional[Dict]:
        with closing(self._conn()) as conn:
            row = conn.execute(
                "SELECT f.*, "
                "(SELECT COUNT(*) FROM decks WHERE folder_id=f.id) as deck_count "
                "FROM folders f WHERE f.id=?",
                (folder_id,),
            ).fetchone()
        return dict(row) if row else None

    def update_folder(self, folder_id: int, name: str = None, icon: str = None, color: str = None):
        with closing(self._conn()) as conn:
            parts = []
            vals = []
            if name is not None:
                parts.append("name=?")
                vals.append(name)
            if icon is not None:
                parts.append("icon=?")
                vals.append(icon)
            if color is not None:
                parts.append("color=?")
                vals.append(color)
            if parts:
                vals.append(folder_id)
                conn.execute(f"UPDATE folders SET {', '.join(parts)} WHERE id=?", vals)
                conn.commit()

    def delete_folder(self, folder_id: int):
        with closing(self._conn()) as conn:
            # Decks in this folder get folder_id set to NULL (ON DELETE SET NULL)
            conn.execute("DELETE FROM folders WHERE id=?", (folder_id,))
            conn.commit()

    # ── Decks ─────────────────────────────────────────────────
    def create_deck(self, name: str, subject: str = "", description: str = "",
                    image_path: str = None, folder_id: int = None) -> int:
        with closing(self._conn()) as conn:
            cur = conn.execute(
                "INSERT INTO decks (folder_id, name, subject, description, image_path) VALUES (?, ?, ?, ?, ?)",
                (folder_id, name, subject, description, image_path),
            )
            deck_id = cur.lastrowid
            conn.commit()
        self._check_achievements()
        return deck_id

    def create_deck_with_cards(self, name: str, subject: str = "", description: str = "",
                               image_paths: list = None, folder_id: int = None,
                               cards: List[Dict] = None) -> int:
        image_paths = image_paths or []
        cards = cards or []
        primary_image = image_paths[0] if image_paths else None
        with closing(self._conn()) as conn:
            try:
                cur = conn.execute(
                    "INSERT INTO decks (folder_id, name, subject, description, image_path) VALUES (?, ?, ?, ?, ?)",
                    (folder_id, name, subject, description, primary_image),
                )
                deck_id = cur.lastrowid
                for sort_order, image_path in enumerate(image_paths):
                    conn.execute(
                        "INSERT INTO deck_images (deck_id, image_path, sort_order) VALUES (?, ?, ?)",
                        (deck_id, image_path, sort_order),
                    )
                for card in cards:
                    conn.execute(
                        "INSERT INTO cards (deck_id, question, answer, card_type, options, difficulty) VALUES (?, ?, ?, ?, ?, ?)",
                        (
                            deck_id,
                            card["question"],
                            card["answer"],
                            card.get("type", card.get("card_type", "flashcard")),
                            json.dumps(card.get("options", [])),
                            card.get("difficulty", 3),
                        ),
                    )
                conn.execute("UPDATE decks SET card_count=? WHERE id=?", (len(cards), deck_id))
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        self._check_achievements()
        return deck_id

    def get_decks(self, folder_id: int = None) -> List[Dict]:
        with closing(self._conn()) as conn:
            if folder_id is not None:
                rows = conn.execute(
                    "SELECT d.*, "
                    "d.card_count as card_count, "
                    "(SELECT COUNT(*) FROM cards WHERE deck_id=d.id AND next_review <= datetime('now')) as due_count "
                    "FROM decks d WHERE d.folder_id=? ORDER BY d.created_at DESC",
                    (folder_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT d.*, "
                    "d.card_count as card_count, "
                    "(SELECT COUNT(*) FROM cards WHERE deck_id=d.id AND next_review <= datetime('now')) as due_count "
                    "FROM decks d ORDER BY d.created_at DESC"
                ).fetchall()
        return [dict(r) for r in rows]

    def get_unassigned_decks(self) -> List[Dict]:
        """Get decks not in any folder."""
        with closing(self._conn()) as conn:
            rows = conn.execute(
                "SELECT d.*, "
                "d.card_count as card_count, "
                "(SELECT COUNT(*) FROM cards WHERE deck_id=d.id AND next_review <= datetime('now')) as due_count "
                "FROM decks d WHERE d.folder_id IS NULL ORDER BY d.created_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    def get_deck(self, deck_id: int) -> Optional[Dict]:
        with closing(self._conn()) as conn:
            row = conn.execute(
                "SELECT d.*, "
                "d.card_count as card_count, "
                "(SELECT COUNT(*) FROM cards WHERE deck_id=d.id AND next_review <= datetime('now')) as due_count, "
                "(SELECT COUNT(*) FROM cards WHERE deck_id=d.id AND repetitions >= 3) as mastered_count "
                "FROM decks d WHERE d.id=?",
                (deck_id,),
            ).fetchone()
        return dict(row) if row else None

    def delete_deck(self, deck_id: int):
        with closing(self._conn()) as conn:
            conn.execute("DELETE FROM review_history WHERE deck_id=?", (deck_id,))
            conn.execute("DELETE FROM cards WHERE deck_id=?", (deck_id,))
            conn.execute("DELETE FROM deck_images WHERE deck_id=?", (deck_id,))
            conn.execute("DELETE FROM decks WHERE id=?", (deck_id,))
            conn.commit()

    def add_deck_image(self, deck_id: int, image_path: str, sort_order: int = 0) -> int:
        with closing(self._conn()) as conn:
            cur = conn.execute(
                "INSERT INTO deck_images (deck_id, image_path, sort_order) VALUES (?, ?, ?)",
                (deck_id, image_path, sort_order),
            )
            image_id = cur.lastrowid
            conn.commit()
        return image_id

    def get_deck_images(self, deck_id: int) -> List[Dict]:
        with closing(self._conn()) as conn:
            rows = conn.execute(
                "SELECT * FROM deck_images WHERE deck_id=? ORDER BY sort_order, id",
                (deck_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def update_deck_card_count(self, deck_id: int):
        with closing(self._conn()) as conn:
            count = conn.execute("SELECT COUNT(*) FROM cards WHERE deck_id=?", (deck_id,)).fetchone()[0]
            conn.execute("UPDATE decks SET card_count=? WHERE id=?", (count, deck_id))
            conn.commit()

    def move_deck_to_folder(self, deck_id: int, folder_id: int = None):
        with closing(self._conn()) as conn:
            conn.execute("UPDATE decks SET folder_id=? WHERE id=?", (folder_id, deck_id))
            conn.commit()

    # ── Cards ─────────────────────────────────────────────────
    def add_card(self, deck_id: int, question: str, answer: str, card_type: str = "flashcard",
                 options: list = None, difficulty: int = 3) -> int:
        opts_json = json.dumps(options or [])
        with closing(self._conn()) as conn:
            cur = conn.execute(
                "INSERT INTO cards (deck_id, question, answer, card_type, options, difficulty) VALUES (?, ?, ?, ?, ?, ?)",
                (deck_id, question, answer, card_type, opts_json, difficulty),
            )
            card_id = cur.lastrowid
            count = conn.execute("SELECT COUNT(*) FROM cards WHERE deck_id=?", (deck_id,)).fetchone()[0]
            conn.execute("UPDATE decks SET card_count=? WHERE id=?", (count, deck_id))
            conn.commit()
        self._check_achievements()
        return card_id

    def add_cards(self, deck_id: int, cards: List[Dict]) -> List[int]:
        card_ids = []
        with closing(self._conn()) as conn:
            try:
                for card in cards:
                    cur = conn.execute(
                        "INSERT INTO cards (deck_id, question, answer, card_type, options, difficulty) VALUES (?, ?, ?, ?, ?, ?)",
                        (
                            deck_id,
                            card["question"],
                            card["answer"],
                            card.get("type", card.get("card_type", "flashcard")),
                            json.dumps(card.get("options", [])),
                            card.get("difficulty", 3),
                        ),
                    )
                    card_ids.append(cur.lastrowid)
                count = conn.execute("SELECT COUNT(*) FROM cards WHERE deck_id=?", (deck_id,)).fetchone()[0]
                conn.execute("UPDATE decks SET card_count=? WHERE id=?", (count, deck_id))
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        self._check_achievements()
        return card_ids

    def get_cards_by_deck(self, deck_id: int) -> List[Dict]:
        with closing(self._conn()) as conn:
            rows = conn.execute("SELECT * FROM cards WHERE deck_id=? ORDER BY id", (deck_id,)).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["options"] = json.loads(d["options"])
            result.append(d)
        return result

    def get_cards_for_review(self, deck_id: int, limit: int = 20) -> List[Dict]:
        with closing(self._conn()) as conn:
            rows = conn.execute(
                "SELECT * FROM cards WHERE deck_id=? AND next_review <= datetime('now') ORDER BY next_review LIMIT ?",
                (deck_id, limit),
            ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["options"] = json.loads(d["options"])
            result.append(d)
        return result

    def get_card(self, card_id: int) -> Optional[Dict]:
        with closing(self._conn()) as conn:
            row = conn.execute("SELECT * FROM cards WHERE id=?", (card_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["options"] = json.loads(d["options"])
        return d

    def update_card_review(self, card_id: int, correct: bool) -> Dict:
        with closing(self._conn()) as conn:
            row = conn.execute("SELECT * FROM cards WHERE id=?", (card_id,)).fetchone()
            if not row:
                return {}
            reps = row["repetitions"]
            ease = row["ease_factor"]
            interval = row["interval_days"]
            if correct:
                if reps == 0:
                    interval = 1
                elif reps == 1:
                    interval = 6
                else:
                    interval = round(interval * ease)
                ease = max(1.3, ease + 0.1)
                reps += 1
            else:
                reps = 0
                interval = 1
                ease = max(1.3, ease - 0.2)
            next_review = (datetime.now(UTC) + timedelta(days=interval)).strftime("%Y-%m-%d %H:%M:%S")
            conn.execute(
                "UPDATE cards SET next_review=?, interval_days=?, ease_factor=?, repetitions=? WHERE id=?",
                (next_review, interval, ease, reps, card_id),
            )
            conn.commit()
        return {"next_review": next_review, "interval": interval, "repetitions": reps}

    def delete_card(self, card_id: int):
        with closing(self._conn()) as conn:
            card = conn.execute("SELECT deck_id FROM cards WHERE id=?", (card_id,)).fetchone()
            conn.execute("DELETE FROM review_history WHERE card_id=?", (card_id,))
            conn.execute("DELETE FROM cards WHERE id=?", (card_id,))
            conn.commit()
        if card:
            self.update_deck_card_count(card["deck_id"])

    # ── Progress ──────────────────────────────────────────────
    def get_progress(self) -> Dict:
        with closing(self._conn()) as conn:
            row = conn.execute("SELECT * FROM progress WHERE id=1").fetchone()
        d = dict(row)
        d["level"] = level_from_xp(d["total_xp"])
        d["xp_to_next"] = xp_to_next_level(d["total_xp"])
        d["xp_current_level"] = xp_for_level(d["level"])
        d["xp_next_level"] = xp_for_level(d["level"] + 1)
        return d

    def add_xp(self, amount: int):
        with closing(self._conn()) as conn:
            conn.execute("UPDATE progress SET total_xp = total_xp + ?", (amount,))
            conn.commit()
        self._check_achievements()

    def record_review(self, card_id: int, deck_id: int, correct: bool, time_ms: int = 0):
        with closing(self._conn()) as conn:
            conn.execute(
                "INSERT INTO review_history (card_id, deck_id, correct, time_taken_ms) VALUES (?, ?, ?, ?)",
                (card_id, deck_id, int(correct), time_ms),
            )
            conn.execute("UPDATE progress SET total_cards_reviewed = total_cards_reviewed + 1")
            if correct:
                conn.execute("UPDATE progress SET total_correct = total_correct + 1")
            conn.commit()

    def update_streak(self):
        with closing(self._conn()) as conn:
            row = conn.execute("SELECT last_active FROM progress WHERE id=1").fetchone()
            today = datetime.now(UTC).strftime("%Y-%m-%d")
            last = row["last_active"] if row["last_active"] else ""
            conn.execute("UPDATE progress SET total_sessions = total_sessions + 1")
            if last != today:
                yesterday = (datetime.now(UTC) - timedelta(days=1)).strftime("%Y-%m-%d")
                if last == yesterday:
                    conn.execute("UPDATE progress SET current_streak = current_streak + 1")
                else:
                    conn.execute("UPDATE progress SET current_streak = 1")
                conn.execute(
                    "UPDATE progress SET longest_streak = MAX(longest_streak, current_streak), last_active=?",
                    (today,),
                )
            conn.commit()

    def record_session(self):
        self.update_streak()
        self.check_achievements()

    # ── Achievements ──────────────────────────────────────────
    def get_achievements(self) -> List[Dict]:
        with closing(self._conn()) as conn:
            rows = conn.execute("SELECT * FROM achievements ORDER BY sort_order").fetchall()
        return [dict(r) for r in rows]

    def unlock_achievement(self, name: str) -> bool:
        with closing(self._conn()) as conn:
            row = conn.execute("SELECT id, unlocked_at FROM achievements WHERE name=?", (name,)).fetchone()
            if not row or row["unlocked_at"]:
                return False
            conn.execute("UPDATE achievements SET unlocked_at=datetime('now') WHERE name=?", (name,))
            conn.commit()
        return True

    def check_achievements(self):
        return self._check_achievements()

    def _check_achievements(self):
        progress = self.get_progress()
        total_cards = self._total_card_count()
        deck_count = self._deck_count()
        checks = {
            "First Deck": deck_count >= 1,
            "Card Collector": total_cards >= 25,
            "Card Master": total_cards >= 100,
            "Getting Started": progress["total_sessions"] >= 1,
            "Dedicated Learner": progress["total_cards_reviewed"] >= 50,
            "Study Pro": progress["total_cards_reviewed"] >= 200,
            "On Fire": progress["current_streak"] >= 3,
            "Week Warrior": progress["current_streak"] >= 7,
            "Monthly Master": progress["current_streak"] >= 30,
            "Level 5": progress["level"] >= 5,
            "Level 10": progress["level"] >= 10,
        }
        newly_unlocked = []
        for name, condition in checks.items():
            if condition and self.unlock_achievement(name):
                newly_unlocked.append(name)
        return newly_unlocked

    def _total_card_count(self) -> int:
        with closing(self._conn()) as conn:
            count = conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0]
        return count

    def _deck_count(self) -> int:
        with closing(self._conn()) as conn:
            count = conn.execute("SELECT COUNT(*) FROM decks").fetchone()[0]
        return count
