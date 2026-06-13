import base64
import json
import logging
import os
import re
import warnings
from io import BytesIO
from typing import Dict, List

import httpx
from PIL import Image, ImageOps

logger = logging.getLogger(__name__)

Image.MAX_IMAGE_PIXELS = 25_000_000
warnings.simplefilter("error", Image.DecompressionBombWarning)

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434").rstrip("/")
MAX_TEXT_LENGTH = 2000
MAX_METADATA_LENGTH = 200
VALID_CARD_TYPES = {"flashcard", "multiple_choice", "fill_blank"}


def env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default


DEFAULT_PDF_MAX_PAGES = env_int("PDF_MAX_PAGES", 10)
DEFAULT_PDF_DPI = env_int("PDF_DPI", 150)

EXTRACTION_PROMPT = """You are a study assistant for a student. The user has uploaded a photo of their study notes, worksheet, or textbook page.

Analyze the image carefully. Extract all key information that would be useful for studying.

Generate quiz flashcards in JSON format with EXACTLY this structure:
{
  "subject": "detected subject area",
  "deck_name": "short descriptive name for this deck",
  "description": "brief 1-sentence description",
  "cards": [
    {
      "question": "the question text",
      "answer": "the correct answer",
      "type": "flashcard",
      "difficulty": 3
    },
    {
      "question": "the question text?",
      "answer": "correct answer",
      "type": "multiple_choice",
      "options": ["correct answer", "plausible wrong 1", "plausible wrong 2", "plausible wrong 3"],
      "difficulty": 2
    },
    {
      "question": "sentence with _____ missing",
      "answer": "the missing word or phrase",
      "type": "fill_blank",
      "difficulty": 3
    }
  ]
}

Rules:
- Generate 8 to 15 cards from the image content
- Mix of types: roughly 40% flashcard, 40% multiple_choice, 20% fill_blank
- Difficulty ranges from 1 (easy recall) to 5 (complex analysis)
- Multiple choice wrong options must be plausible but clearly incorrect
- Fill in the blank should test key terms or definitions
- Questions must be clear and unambiguous
- Answers must be concise and accurate
- Return ONLY valid JSON, no markdown fences, no extra text
- If the image is unclear or not study material, return: {"error": "Could not detect study material in this image"}
"""


def normalize_image(image_bytes: bytes, max_size: int = 1024) -> bytes:
    """Validate, resize, and return normalized JPEG bytes."""
    img = Image.open(BytesIO(image_bytes))
    img.load()
    img = ImageOps.exif_transpose(img)
    if img.mode != "RGB":
        img = img.convert("RGB")
    img.thumbnail((max_size, max_size), Image.LANCZOS)
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def resize_image(image_bytes: bytes, max_size: int = 1024) -> str:
    """Resize image and return base64 encoded string."""
    return base64.b64encode(normalize_image(image_bytes, max_size)).decode("utf-8")


def pdf_to_images(pdf_bytes: bytes, max_pages: int = DEFAULT_PDF_MAX_PAGES,
                  dpi: int = DEFAULT_PDF_DPI) -> List[bytes]:
    """Convert PDF pages to JPEG image bytes (one per page)."""
    return list(iter_pdf_images(pdf_bytes, max_pages, dpi))


def iter_pdf_images(pdf_bytes: bytes, max_pages: int = DEFAULT_PDF_MAX_PAGES,
                    dpi: int = DEFAULT_PDF_DPI):
    """Yield PDF pages as JPEG image bytes without retaining all pages in memory."""
    import fitz  # PyMuPDF

    max_pages = max(1, min(max_pages, 50))
    dpi = max(72, min(dpi, 200))
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        pages = min(len(doc), max_pages)
        for i in range(pages):
            page = doc[i]
            zoom = dpi / 72  # 72 is default PDF DPI
            mat = fitz.Matrix(zoom, zoom)
            pix = page.get_pixmap(matrix=mat, alpha=False)
            img_bytes = pix.tobytes("jpeg")
            yield img_bytes
    finally:
        doc.close()


def _clean_text(value, max_length: int = MAX_TEXT_LENGTH) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip()[:max_length]


def _clean_difficulty(value) -> int:
    try:
        difficulty = int(value)
    except (TypeError, ValueError):
        difficulty = 3
    return max(1, min(5, difficulty))


def validate_card(card) -> Dict | None:
    """Validate and normalize a single AI-generated card."""
    if not isinstance(card, dict):
        return None

    question = _clean_text(card.get("question"))
    answer = _clean_text(card.get("answer"))
    if not question or not answer:
        return None

    card_type = card.get("type") or card.get("card_type") or "flashcard"
    if card_type not in VALID_CARD_TYPES:
        card_type = "flashcard"

    options = card.get("options", [])
    if not isinstance(options, list):
        options = []
    options = [_clean_text(option, 500) for option in options]
    options = [option for option in options if option]

    if card_type == "multiple_choice":
        if not options:
            card_type = "flashcard"
        else:
            if answer not in options:
                options.insert(0, answer)
            # Keep order while removing duplicates.
            options = list(dict.fromkeys(options))[:6]
            if len(options) < 2:
                card_type = "flashcard"

    if card_type != "multiple_choice":
        options = []

    return {
        "question": question,
        "answer": answer,
        "type": card_type,
        "options": options,
        "difficulty": _clean_difficulty(card.get("difficulty", 3)),
    }


def generate_cards(image_base64: str, model: str = "gemma4:31b-cloud") -> Dict:
    """Send image to Ollama and get structured quiz cards back."""
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": EXTRACTION_PROMPT,
                "images": [image_base64],
            }
        ],
        "stream": False,
        "format": "json",
        "options": {
            "temperature": 0.3,
            "num_predict": 2048,
        },
    }

    try:
        with httpx.Client(timeout=120.0) as client:
            response = client.post(f"{OLLAMA_URL}/api/chat", json=payload)
            response.raise_for_status()

        data = response.json()
        content = data.get("message", {}).get("content", "")
        result = parse_json_response(content)

        if "error" in result:
            return {"success": False, "error": result["error"]}

        if "cards" not in result or not isinstance(result["cards"], list):
            return {"success": False, "error": "AI did not return valid card data"}

        valid_cards = []
        for card in result["cards"]:
            validated = validate_card(card)
            if validated:
                valid_cards.append(validated)

        if not valid_cards:
            return {"success": False, "error": "No valid cards could be generated"}

        result["cards"] = valid_cards
        result["subject"] = _clean_text(result.get("subject"), MAX_METADATA_LENGTH)
        result["deck_name"] = _clean_text(result.get("deck_name"), MAX_METADATA_LENGTH)
        result["description"] = _clean_text(result.get("description"), MAX_TEXT_LENGTH)
        result["success"] = True
        return result

    except httpx.ConnectError:
        return {"success": False, "error": "Cannot connect to Ollama. Is it running?"}
    except httpx.TimeoutException:
        return {"success": False, "error": "AI request timed out. Try again."}
    except Exception as e:
        logger.exception("Unexpected AI card generation error")
        return {"success": False, "error": f"AI error: {str(e)}"}


def parse_json_response(text: str) -> Dict:
    """Try to parse JSON from AI response, handling common issues."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    json_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if json_match:
        try:
            return json.loads(json_match.group(1).strip())
        except json.JSONDecodeError:
            pass

    brace_start = text.find("{")
    brace_end = text.rfind("}") + 1
    if brace_start >= 0 and brace_end > brace_start:
        try:
            return json.loads(text[brace_start:brace_end])
        except json.JSONDecodeError:
            pass

    return {"error": "Could not parse AI response as JSON"}


def check_ollama_status() -> Dict:
    """Check if Ollama is running and list available models."""
    try:
        with httpx.Client(timeout=5.0) as client:
            response = client.get(f"{OLLAMA_URL}/api/tags")
            response.raise_for_status()
            data = response.json()
            models = [m["name"] for m in data.get("models", [])]
            return {"running": True, "models": models}
    except Exception:
        return {"running": False, "models": []}
