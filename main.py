import re
import time
import uuid
from threading import Lock
from pathlib import Path
from io import BytesIO

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from PIL import Image
from starlette.concurrency import run_in_threadpool

from database import Database
from ai_service import resize_image, normalize_image, generate_cards, iter_pdf_images, check_ollama_status

app = FastAPI(title="FlashLearn")
db = Database()

SESSION_TTL_SECONDS = 4 * 60 * 60
study_sessions = {}
study_sessions_lock = Lock()
MAX_MODEL_LENGTH = 200
MAX_DECK_NAME_LENGTH = 200
MAX_METADATA_LENGTH = 200
MAX_DESCRIPTION_LENGTH = 2000


def _cleanup_study_sessions():
    now = time.time()
    with study_sessions_lock:
        expired = [sid for sid, session in study_sessions.items() if now - session["created_at"] > SESSION_TTL_SECONDS]
        for sid in expired:
            study_sessions.pop(sid, None)


def _get_study_session(session_id: str):
    _cleanup_study_sessions()
    with study_sessions_lock:
        return study_sessions.get(session_id)


def _validate_folder(folder_id: int | None):
    if folder_id is not None and not db.get_folder(folder_id):
        raise HTTPException(400, "Folder not found")


def _validate_folder_fields(name: str | None = None, icon: str | None = None, color: str | None = None):
    if name is not None and not name.strip():
        raise HTTPException(400, "Folder name is required")
    if icon is not None and len(icon) > 8:
        raise HTTPException(400, "Folder icon is too long")
    if color and not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
        raise HTTPException(400, "Folder color must be a hex color like #6c63ff")


def _clean_required_text(value: str, label: str, max_length: int) -> str:
    cleaned = (value or "").strip()
    if not cleaned:
        raise HTTPException(400, f"{label} is required")
    return cleaned[:max_length]


def _clean_optional_text(value: str, max_length: int) -> str:
    return (value or "").strip()[:max_length]


def _clean_model_name(model: str | None) -> str | None:
    if model is None:
        return None
    cleaned = model.strip()
    if not cleaned:
        raise HTTPException(400, "Model name is required")
    if len(cleaned) > MAX_MODEL_LENGTH:
        raise HTTPException(400, "Model name is too long")
    return cleaned


def _verify_image(image_bytes: bytes):
    Image.open(BytesIO(image_bytes)).verify()


def _normalize_image(image_bytes: bytes) -> bytes:
    return normalize_image(image_bytes)

DATA_DIR = Path(__file__).parent / "data"
PHOTO_DIR = DATA_DIR / "photos"
PHOTO_DIR.mkdir(parents=True, exist_ok=True)

STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
async def index():
    return FileResponse(str(STATIC_DIR / "index.html"))


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return FileResponse(str(STATIC_DIR / "favicon.ico"))


# ── Ollama Status ─────────────────────────────────────────────
@app.get("/api/status")
async def get_status():
    return check_ollama_status()


# ── Progress ──────────────────────────────────────────────────
@app.get("/api/progress")
async def get_progress():
    return db.get_progress()


# ── Settings ──────────────────────────────────────────────────
@app.get("/api/settings")
async def get_settings():
    return {"model": db.get_model()}


@app.put("/api/settings")
async def update_settings(model: str = None):
    if model is not None:
        db.set_setting("model", _clean_model_name(model))
    return {"status": "ok"}


# ── Folders ───────────────────────────────────────────────────
@app.get("/api/folders")
async def list_folders():
    return {"folders": db.get_folders()}


@app.post("/api/folders")
async def create_folder(name: str = Form(...), icon: str = Form("📁"), color: str = Form("")):
    _validate_folder_fields(name=name, icon=icon, color=color)
    folder_id = db.create_folder(name=name.strip(), icon=icon, color=color)
    return {"id": folder_id, "status": "ok"}


@app.put("/api/folders/{folder_id}")
async def update_folder(folder_id: int, name: str = None, icon: str = None, color: str = None):
    folder = db.get_folder(folder_id)
    if not folder:
        raise HTTPException(404, "Folder not found")
    _validate_folder_fields(name=name, icon=icon, color=color)
    db.update_folder(folder_id, name=name.strip() if name is not None else None, icon=icon, color=color)
    return {"status": "ok"}


@app.delete("/api/folders/{folder_id}")
async def delete_folder(folder_id: int):
    folder = db.get_folder(folder_id)
    if not folder:
        raise HTTPException(404, "Folder not found")
    db.delete_folder(folder_id)
    return {"status": "ok"}


# ── Decks ─────────────────────────────────────────────────────
@app.get("/api/decks")
async def list_decks(folder_id: int = None):
    if folder_id is not None:
        return {"decks": db.get_decks(folder_id)}
    return {"decks": db.get_decks()}


@app.get("/api/decks/unassigned")
async def list_unassigned_decks():
    return {"decks": db.get_unassigned_decks()}


@app.get("/api/decks/{deck_id}")
async def get_deck(deck_id: int):
    deck = db.get_deck(deck_id)
    if not deck:
        raise HTTPException(404, "Deck not found")
    cards = db.get_cards_by_deck(deck_id)
    return {"deck": deck, "cards": cards}


@app.post("/api/decks")
async def create_deck(name: str = Form(...), subject: str = Form(""), folder_id: int = Form(None)):
    _validate_folder(folder_id)
    deck_id = db.create_deck(
        name=_clean_required_text(name, "Deck name", MAX_DECK_NAME_LENGTH),
        subject=_clean_optional_text(subject, MAX_METADATA_LENGTH),
        folder_id=folder_id,
    )
    return {"id": deck_id, "status": "ok"}


@app.put("/api/decks/{deck_id}/move")
async def move_deck(deck_id: int, folder_id: int = None):
    deck = db.get_deck(deck_id)
    if not deck:
        raise HTTPException(404, "Deck not found")
    _validate_folder(folder_id)
    db.move_deck_to_folder(deck_id, folder_id)
    return {"status": "ok"}


@app.delete("/api/decks/{deck_id}")
async def delete_deck(deck_id: int):
    deck = db.get_deck(deck_id)
    if not deck:
        raise HTTPException(404, "Deck not found")
    image_paths = {img["image_path"] for img in db.get_deck_images(deck_id)}
    if deck.get("image_path"):
        image_paths.add(deck["image_path"])
    for image_path in image_paths:
        photo_path = PHOTO_DIR / image_path
        if photo_path.exists():
            photo_path.unlink()
    db.delete_deck(deck_id)
    return {"status": "ok"}


# ── Multi-Image Upload & AI Processing ───────────────────────
@app.post("/api/upload")
async def upload_and_process(
    photos: list[UploadFile] = File(...),
    deck_name: str = Form(""),
    folder_id: int = Form(None),
    model: str = Form(""),
):
    if model:
        model = _clean_model_name(model)
    else:
        model = db.get_model()

    _validate_folder(folder_id)

    if not photos or len(photos) == 0:
        raise HTTPException(400, "No images provided")

    all_cards = []
    detected_subject = ""
    detected_deck_name = ""
    detected_description = ""
    saved_photos = []
    total_images = len(photos)
    errors = []

    try:
        for idx, photo in enumerate(photos):
            file_bytes = await photo.read()

            if len(file_bytes) > 20_000_000:
                errors.append(f"File {idx+1} too large, skipped")
                continue

            filename = photo.filename or ""
            content_type = photo.content_type or ""
            is_pdf = content_type == "application/pdf" or filename.lower().endswith(".pdf")

            if is_pdf:
                page_count = 0
                try:
                    page_images = iter_pdf_images(file_bytes)
                    for page_idx, page_bytes in enumerate(page_images):
                        page_count += 1
                        photo_filename = f"{uuid.uuid4().hex}_p{page_idx+1}.jpg"
                        photo_path = PHOTO_DIR / photo_filename
                        with open(photo_path, "wb") as f:
                            f.write(page_bytes)
                        saved_photos.append(photo_filename)

                        image_base64 = await run_in_threadpool(resize_image, page_bytes)
                        result = await run_in_threadpool(generate_cards, image_base64, model)

                        if result.get("success"):
                            all_cards.extend(result.get("cards", []))
                            if not detected_subject and result.get("subject"):
                                detected_subject = _clean_optional_text(result["subject"], MAX_METADATA_LENGTH)
                            if not detected_deck_name and result.get("deck_name"):
                                detected_deck_name = _clean_optional_text(result["deck_name"], MAX_DECK_NAME_LENGTH)
                            if not detected_description and result.get("description"):
                                detected_description = _clean_optional_text(result["description"], MAX_DESCRIPTION_LENGTH)
                        else:
                            errors.append(f"PDF {idx+1} page {page_idx+1}: {result.get('error', 'AI failed')}")
                except Exception as e:
                    errors.append(f"PDF {idx+1} could not be read: {str(e)}")
                    continue
                if page_count == 0:
                    errors.append(f"PDF {idx+1} has no pages, skipped")
                    continue
                continue

            # Image file
            try:
                await run_in_threadpool(_verify_image, file_bytes)
            except Exception:
                errors.append(f"File {idx+1} is not a valid image, skipped")
                continue

            # Normalize and save photo as JPEG
            normalized_bytes = await run_in_threadpool(_normalize_image, file_bytes)
            photo_filename = f"{uuid.uuid4().hex}.jpg"
            photo_path = PHOTO_DIR / photo_filename
            with open(photo_path, "wb") as f:
                f.write(normalized_bytes)
            saved_photos.append(photo_filename)

            # Encode for AI
            image_base64 = await run_in_threadpool(resize_image, normalized_bytes)

            # Call AI
            result = await run_in_threadpool(generate_cards, image_base64, model)

            if result.get("success"):
                all_cards.extend(result.get("cards", []))
                if not detected_subject and result.get("subject"):
                    detected_subject = _clean_optional_text(result["subject"], MAX_METADATA_LENGTH)
                if not detected_deck_name and result.get("deck_name"):
                    detected_deck_name = _clean_optional_text(result["deck_name"], MAX_DECK_NAME_LENGTH)
                if not detected_description and result.get("description"):
                    detected_description = _clean_optional_text(result["description"], MAX_DESCRIPTION_LENGTH)
            else:
                errors.append(f"Image {idx+1}: {result.get('error', 'AI failed')}")
    except HTTPException:
        for p in saved_photos:
            (PHOTO_DIR / p).unlink(missing_ok=True)
        raise
    except Exception:
        for p in saved_photos:
            (PHOTO_DIR / p).unlink(missing_ok=True)
        raise

    if not all_cards:
        # Clean up saved photos
        for p in saved_photos:
            (PHOTO_DIR / p).unlink(missing_ok=True)
        error_msg = "; ".join(errors) if errors else "No cards could be generated from any image"
        status_code = 400 if errors and all("not a valid image" in e or "too large" in e or "could not be read" in e or "has no pages" in e for e in errors) else 502
        return JSONResponse(status_code=status_code, content={"error": error_msg})

    # Create deck
    name = _clean_optional_text(deck_name, MAX_DECK_NAME_LENGTH) or detected_deck_name or "Untitled Deck"
    try:
        deck_id = db.create_deck_with_cards(
            name=name,
            subject=detected_subject,
            description=detected_description,
            image_paths=saved_photos,
            folder_id=folder_id,
            cards=all_cards,
        )
    except Exception:
        for p in saved_photos:
            (PHOTO_DIR / p).unlink(missing_ok=True)
        raise

    deck = db.get_deck(deck_id)
    cards = db.get_cards_by_deck(deck_id)

    return {
        "success": True,
        "deck": deck,
        "cards": cards,
        "images_processed": len(saved_photos),
        "total_images": total_images,
        "errors": errors if errors else None,
    }


# ── Study / Review ────────────────────────────────────────────
@app.get("/api/decks/{deck_id}/study")
async def get_study_cards(deck_id: int, limit: int = Query(20, ge=1, le=50)):
    _cleanup_study_sessions()
    deck = db.get_deck(deck_id)
    if not deck:
        raise HTTPException(404, "Deck not found")

    cards = db.get_cards_for_review(deck_id, limit)
    if not cards:
        cards = db.get_cards_by_deck(deck_id)

    session_id = uuid.uuid4().hex
    with study_sessions_lock:
        study_sessions[session_id] = {
            "deck_id": deck_id,
            "card_ids": {card["id"] for card in cards},
            "reviewed": {},
            "created_at": time.time(),
            "completed": False,
        }
    return {"session_id": session_id, "cards": cards}


@app.post("/api/cards/{card_id}/review")
async def review_card(card_id: int, correct: bool = True, time_ms: int = 0, session_id: str = ""):
    _cleanup_study_sessions()
    with study_sessions_lock:
        session = study_sessions.get(session_id)
        if not session:
            raise HTTPException(400, "Invalid or expired study session")
        if session["completed"]:
            raise HTTPException(400, "Study session is already complete")
        if card_id not in session["card_ids"]:
            raise HTTPException(400, "Card is not part of this study session")
        if card_id in session["reviewed"]:
            raise HTTPException(409, "Card was already reviewed in this session")
        session["reviewed"][card_id] = {"correct": bool(correct), "time_ms": None}

    card = db.get_card(card_id)
    if not card:
        raise HTTPException(404, "Card not found")
    if card["deck_id"] != session["deck_id"]:
        raise HTTPException(400, "Card does not belong to this session deck")

    time_ms = max(0, min(time_ms, 60 * 60 * 1000))
    try:
        db.update_card_review(card_id, correct)
        db.record_review(card_id, card["deck_id"], correct, time_ms)
    except Exception:
        with study_sessions_lock:
            session = study_sessions.get(session_id)
            if session:
                session["reviewed"].pop(card_id, None)
        raise
    with study_sessions_lock:
        session = study_sessions.get(session_id)
        if session:
            session["reviewed"][card_id] = {"correct": bool(correct), "time_ms": time_ms}

    xp = 5
    if correct:
        xp += 10
    db.add_xp(xp)

    progress = db.get_progress()
    return {"xp_earned": xp, "total_xp": progress["total_xp"], "level": progress["level"]}


@app.post("/api/session/complete")
async def complete_session(deck_id: int, session_id: str = ""):
    deck = db.get_deck(deck_id)
    if not deck:
        raise HTTPException(404, "Deck not found")

    _cleanup_study_sessions()
    with study_sessions_lock:
        session = study_sessions.get(session_id)
        if not session:
            raise HTTPException(400, "Invalid or expired study session")
        if session["completed"]:
            raise HTTPException(400, "Study session is already complete")
        if session["deck_id"] != deck_id:
            raise HTTPException(400, "Study session does not belong to this deck")

        reviewed = list(session["reviewed"].values())
        total_count = len(reviewed)
        if total_count == 0:
            raise HTTPException(400, "Cannot complete an empty study session")
        if any(review["time_ms"] is None for review in reviewed) or total_count != len(session["card_ids"]):
            raise HTTPException(400, "Study session still has unreviewed cards")
        session["completed"] = True
    correct_count = sum(1 for review in reviewed if review["correct"])
    total_time_ms = sum(review["time_ms"] for review in reviewed)

    db.record_session()

    bonus = 0
    if total_count > 0:
        ratio = correct_count / total_count
        if ratio >= 0.9:
            bonus = 50
        elif ratio >= 0.7:
            bonus = 25
        else:
            bonus = 10
        if ratio == 1.0 and total_count >= 3:
            db.unlock_achievement("Perfectionist")
        if total_count >= 3 and total_time_ms <= total_count * 5000:
            db.unlock_achievement("Speed Demon")

    if bonus > 0:
        db.add_xp(bonus)

    with study_sessions_lock:
        study_sessions.pop(session_id, None)
    db.check_achievements()
    progress = db.get_progress()
    return {
        "bonus_xp": bonus,
        "total_xp": progress["total_xp"],
        "level": progress["level"],
        "streak": progress["current_streak"],
    }


# ── Cards ─────────────────────────────────────────────────────
@app.delete("/api/cards/{card_id}")
async def delete_card(card_id: int):
    card = db.get_card(card_id)
    if not card:
        raise HTTPException(404, "Card not found")
    db.delete_card(card_id)
    return {"status": "ok"}


# ── Achievements ──────────────────────────────────────────────
@app.get("/api/achievements")
async def get_achievements():
    return {"achievements": db.get_achievements()}


if __name__ == "__main__":
    import uvicorn
    import os
    port = int(os.environ.get("PORT", 5050))
    uvicorn.run(app, host="0.0.0.0", port=port)
