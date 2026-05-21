import uuid
from pathlib import Path
from io import BytesIO

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from PIL import Image

from database import Database
from ai_service import resize_image, generate_cards, check_ollama_status

app = FastAPI(title="FlashLearn")
db = Database()

DATA_DIR = Path(__file__).parent / "data"
PHOTO_DIR = DATA_DIR / "photos"
PHOTO_DIR.mkdir(parents=True, exist_ok=True)

STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
async def index():
    return FileResponse(str(STATIC_DIR / "index.html"))


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
    if model:
        db.set_setting("model", model)
    return {"status": "ok"}


# ── Folders ───────────────────────────────────────────────────
@app.get("/api/folders")
async def list_folders():
    return {"folders": db.get_folders()}


@app.post("/api/folders")
async def create_folder(name: str = Form(...), icon: str = Form("📁"), color: str = Form("")):
    folder_id = db.create_folder(name=name, icon=icon, color=color)
    return {"id": folder_id, "status": "ok"}


@app.put("/api/folders/{folder_id}")
async def update_folder(folder_id: int, name: str = None, icon: str = None, color: str = None):
    folder = db.get_folder(folder_id)
    if not folder:
        raise HTTPException(404, "Folder not found")
    db.update_folder(folder_id, name=name, icon=icon, color=color)
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
    deck_id = db.create_deck(name=name, subject=subject, folder_id=folder_id)
    return {"id": deck_id, "status": "ok"}


@app.put("/api/decks/{deck_id}/move")
async def move_deck(deck_id: int, folder_id: int = None):
    deck = db.get_deck(deck_id)
    if not deck:
        raise HTTPException(404, "Deck not found")
    db.move_deck_to_folder(deck_id, folder_id)
    return {"status": "ok"}


@app.delete("/api/decks/{deck_id}")
async def delete_deck(deck_id: int):
    deck = db.get_deck(deck_id)
    if not deck:
        raise HTTPException(404, "Deck not found")
    if deck.get("image_path"):
        photo_path = PHOTO_DIR / deck["image_path"]
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
    if not model:
        model = db.get_model()

    if not photos or len(photos) == 0:
        raise HTTPException(400, "No images provided")

    all_cards = []
    detected_subject = ""
    detected_deck_name = ""
    detected_description = ""
    saved_photos = []
    total_images = len(photos)
    errors = []

    for idx, photo in enumerate(photos):
        image_bytes = await photo.read()

        if len(image_bytes) > 20_000_000:
            errors.append(f"Image {idx+1} too large, skipped")
            continue

        try:
            Image.open(BytesIO(image_bytes))
        except Exception:
            errors.append(f"Image {idx+1} is not a valid image, skipped")
            continue

        # Save photo
        ext = Path(photo.filename or "photo.jpg").suffix or ".jpg"
        photo_filename = f"{uuid.uuid4().hex}{ext}"
        photo_path = PHOTO_DIR / photo_filename
        with open(photo_path, "wb") as f:
            f.write(image_bytes)
        saved_photos.append(photo_filename)

        # Resize and encode for AI
        image_base64 = resize_image(image_bytes)

        # Call AI
        result = generate_cards(image_base64, model)

        if result.get("success"):
            all_cards.extend(result.get("cards", []))
            if not detected_subject and result.get("subject"):
                detected_subject = result["subject"]
            if not detected_deck_name and result.get("deck_name"):
                detected_deck_name = result["deck_name"]
            if not detected_description and result.get("description"):
                detected_description = result["description"]
        else:
            errors.append(f"Image {idx+1}: {result.get('error', 'AI failed')}")

    if not all_cards:
        # Clean up saved photos
        for p in saved_photos:
            (PHOTO_DIR / p).unlink(missing_ok=True)
        error_msg = "; ".join(errors) if errors else "No cards could be generated from any image"
        return JSONResponse(500, {"error": error_msg})

    # Create deck
    name = deck_name or detected_deck_name or "Untitled Deck"
    primary_photo = saved_photos[0] if saved_photos else None

    deck_id = db.create_deck(
        name=name,
        subject=detected_subject,
        description=detected_description,
        image_path=primary_photo,
        folder_id=folder_id,
    )

    # Create cards
    for card_data in all_cards:
        db.add_card(
            deck_id=deck_id,
            question=card_data["question"],
            answer=card_data["answer"],
            card_type=card_data.get("type", "flashcard"),
            options=card_data.get("options", []),
            difficulty=card_data.get("difficulty", 3),
        )

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
    cards = db.get_cards_for_review(deck_id, limit)
    if not cards:
        cards = db.get_cards_by_deck(deck_id)
    return {"cards": cards}


@app.post("/api/cards/{card_id}/review")
async def review_card(card_id: int, correct: bool = True, time_ms: int = 0):
    card = db.get_card(card_id)
    if not card:
        raise HTTPException(404, "Card not found")

    db.update_card_review(card_id, correct)
    db.record_review(card_id, card["deck_id"], correct, time_ms)

    xp = 5
    if correct:
        xp += 10
    db.add_xp(xp)

    progress = db.get_progress()
    return {"xp_earned": xp, "total_xp": progress["total_xp"], "level": progress["level"]}


@app.post("/api/session/complete")
async def complete_session(deck_id: int, correct_count: int = 0, total_count: int = 0):
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

    if bonus > 0:
        db.add_xp(bonus)

    db._check_achievements()
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
