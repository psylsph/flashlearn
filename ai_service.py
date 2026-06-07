import base64
import json
import re
from io import BytesIO
from typing import Dict, List

import httpx
from PIL import Image

OLLAMA_URL = "http://localhost:11434"

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


def resize_image(image_bytes: bytes, max_size: int = 1024) -> str:
    """Resize image and return base64 encoded string."""
    img = Image.open(BytesIO(image_bytes))
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")
    img.thumbnail((max_size, max_size), Image.LANCZOS)
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def pdf_to_images(pdf_bytes: bytes, max_pages: int = 20, dpi: int = 200) -> List[bytes]:
    """Convert PDF pages to JPEG image bytes (one per page)."""
    import fitz  # PyMuPDF

    images = []
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    pages = min(len(doc), max_pages)
    for i in range(pages):
        page = doc[i]
        zoom = dpi / 72  # 72 is default PDF DPI
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat)
        img_bytes = pix.tobytes("jpeg")
        images.append(img_bytes)
    doc.close()
    return images


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
            if "question" in card and "answer" in card:
                card.setdefault("type", "flashcard")
                card.setdefault("difficulty", 3)
                if card["type"] == "multiple_choice":
                    card.setdefault("options", [])
                    if not card["options"]:
                        card["type"] = "flashcard"
                valid_cards.append(card)

        if not valid_cards:
            return {"success": False, "error": "No valid cards could be generated"}

        result["cards"] = valid_cards
        result["success"] = True
        return result

    except httpx.ConnectError:
        return {"success": False, "error": "Cannot connect to Ollama. Is it running?"}
    except httpx.TimeoutException:
        return {"success": False, "error": "AI request timed out. Try again."}
    except Exception as e:
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
