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


@app.get("/api/status")
async def get_status():
    return check_ollama_status()


@app.get("/api/progress")
async def get_progress():
    return db.get_progress()


@app.get("/api/settings")
async def get_settings():
    return {"model": db.get_model()}


@app.put("/api/settings")
async def update_settings(model: str = None):
    if model:
        db.set_setting("model", model)
    return {"status": "ok"}


@app.get("/api/decks")
async def list_decks():
    return {"decks": db.get_decks()}


@app.get("/api/decks/{deck_id}")
async def get_deck(deck_id: int):
    deck = db.get_deck(deck_id)
    if not deck:
        raise HTTPException(404, "Deck not found")
    cards = db.get_cards_by_deck(deck_id)
    return {"deck": deck, "cards": cards}


@app.post("/api/decks")
async def create_deck(name: str = Form(...), subject: str = Form("")):
    deck_id = db.create_deck(name=name, subject=subject)
    return {"id": deck_id, "status": "ok"}


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


@app.post("/api/upload")
async def upload_and_process(
    photo: UploadFile = File(...),
    deck_name: str = Form(""),
    model: str = Form(""),
):
    if not model:
        model = db.get_model()

    image_bytes = await photo.read()
    if len(image_bytes) > 20_000_000:
        raise HTTPException(400, "Image too large (max 20MB)")

    try:
        Image.open(BytesIO(image_bytes))
    except Exception:
        raise HTTPException(400, "Invalid image file")

    ext = Path(photo.filename or "photo.jpg").suffix or ".jpg"
    photo_filename = f"{uuid.uuid4().hex}{ext}"
    photo_path = PHOTO_DIR / photo_filename
    with open(photo_path, "wb") as f:
        f.write(image_bytes)

    image_base64 = resize_image(image_bytes)
    result = generate_cards(image_base64, model)

    if not result.get("success"):
        photo_path.unlink(missing_ok=True)
        return JSONResponse(500, {"error": result.get("error", "AI processing failed")})

    name = deck_name or result.get("deck_name", "Untitled Deck")
    subject = result.get("subject", "")
    description = result.get("description", "")

    deck_id = db.create_deck(
        name=name, subject=subject, description=description, image_path=photo_filename,
    )

    for card_data in result.get("cards", []):
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
    return {"success": True, "deck": deck, "cards": cards}


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


@app.delete("/api/cards/{card_id}")
async def delete_card(card_id: int):
    card = db.get_card(card_id)
    if not card:
        raise HTTPException(404, "Card not found")
    db.delete_card(card_id)
    return {"status": "ok"}


@app.get("/api/achievements")
async def get_achievements():
    return {"achievements": db.get_achievements()}


if __name__ == "__main__":
    import uvicorn
    import os
    port = int(os.environ.get("PORT", 5050))
    uvicorn.run(app, host="0.0.0.0", port=port)
