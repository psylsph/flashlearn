import os
import sys
import json
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ai_service import (
    resize_image,
    normalize_image,
    pdf_to_images,
    iter_pdf_images,
    generate_cards,
    parse_json_response,
    check_ollama_status,
    validate_card,
    env_int,
)


class TestImageResize:
    def test_resize_small_image(self, sample_png_bytes):
        result = resize_image(sample_png_bytes, max_size=512)
        assert isinstance(result, str)
        import base64
        decoded = base64.b64decode(result)
        assert decoded[:2] == b'\xff\xd8'

    def test_resize_returns_jpeg(self, sample_png_bytes):
        import base64
        result = resize_image(sample_png_bytes)
        decoded = base64.b64decode(result)
        assert decoded[:2] == b'\xff\xd8'

    def test_normalize_converts_la_image_to_jpeg(self):
        from io import BytesIO
        from PIL import Image

        img = Image.new("LA", (2, 2), (255, 128))
        buf = BytesIO()
        img.save(buf, format="PNG")
        result = normalize_image(buf.getvalue())
        assert result[:2] == b'\xff\xd8'


class TestEnvParsing:
    def test_env_int_uses_default_for_invalid_value(self, monkeypatch):
        monkeypatch.setenv("PDF_DPI", "not-an-int")
        assert env_int("PDF_DPI", 150) == 150

    def test_env_int_reads_valid_value(self, monkeypatch):
        monkeypatch.setenv("PDF_MAX_PAGES", "7")
        assert env_int("PDF_MAX_PAGES", 10) == 7


class TestPdfImages:
    def test_pdf_to_images_uses_iterator(self, monkeypatch):
        monkeypatch.setattr("ai_service.iter_pdf_images", lambda *args, **kwargs: iter([b"one", b"two"]))
        assert pdf_to_images(b"pdf") == [b"one", b"two"]

    def test_iter_pdf_images_closes_document(self, monkeypatch):
        closed = {"value": False}

        class FakePixmap:
            def tobytes(self, fmt):
                assert fmt == "jpeg"
                return b"jpg"

        class FakePage:
            def get_pixmap(self, matrix, alpha):
                assert alpha is False
                return FakePixmap()

        class FakeDoc:
            def __len__(self):
                return 1

            def __getitem__(self, idx):
                assert idx == 0
                return FakePage()

            def close(self):
                closed["value"] = True

        fake_fitz = MagicMock()
        fake_fitz.open.return_value = FakeDoc()
        fake_fitz.Matrix.return_value = object()
        with patch.dict("sys.modules", {"fitz": fake_fitz}):
            assert list(iter_pdf_images(b"pdf")) == [b"jpg"]
        assert closed["value"] is True


class TestJsonParsing:
    def test_valid_json(self):
        result = parse_json_response('{"subject": "Math", "cards": []}')
        assert result["subject"] == "Math"

    def test_json_in_markdown_fences(self):
        result = parse_json_response('```json\n{"subject": "Math", "cards": []}\n```')
        assert result["subject"] == "Math"

    def test_json_embedded_in_text(self):
        result = parse_json_response('Here: {"subject": "Math", "cards": []} end.')
        assert result["subject"] == "Math"

    def test_garbage_input(self):
        result = parse_json_response("not json")
        assert "error" in result


class TestGenerateCards:
    def test_successful_generation(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "message": {"content": json.dumps({
                "subject": "Biology", "deck_name": "Cells", "description": "Cells",
                "cards": [
                    {"question": "Q?", "answer": "A", "type": "flashcard", "difficulty": 1},
                    {"question": "Q2?", "answer": "A2", "type": "multiple_choice",
                     "options": ["A2", "B", "C", "D"], "difficulty": 2},
                ],
            })}
        }
        mock_response.raise_for_status = MagicMock()
        mock_client = MagicMock()
        mock_client.post.return_value = mock_response
        with patch("ai_service.httpx.Client") as mc:
            mc.return_value.__enter__ = MagicMock(return_value=mock_client)
            mc.return_value.__exit__ = MagicMock(return_value=False)
            result = generate_cards("fake_base64")
        assert result["success"] is True
        assert len(result["cards"]) == 2

    def test_connection_error(self):
        import httpx
        with patch("ai_service.httpx.Client") as mc:
            mc.return_value.__enter__ = MagicMock(side_effect=httpx.ConnectError("fail"))
            mc.return_value.__exit__ = MagicMock(return_value=False)
            result = generate_cards("fake")
        assert result["success"] is False

    def test_empty_cards(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {"message": {"content": json.dumps({"cards": []})}}
        mock_response.raise_for_status = MagicMock()
        mock_client = MagicMock()
        mock_client.post.return_value = mock_response
        with patch("ai_service.httpx.Client") as mc:
            mc.return_value.__enter__ = MagicMock(return_value=mock_client)
            mc.return_value.__exit__ = MagicMock(return_value=False)
            result = generate_cards("fake")
        assert result["success"] is False

    def test_mc_without_options_becomes_flashcard(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {"message": {"content": json.dumps({
            "cards": [{"question": "Q?", "answer": "A", "type": "multiple_choice", "options": []}]
        })}}
        mock_response.raise_for_status = MagicMock()
        mock_client = MagicMock()
        mock_client.post.return_value = mock_response
        with patch("ai_service.httpx.Client") as mc:
            mc.return_value.__enter__ = MagicMock(return_value=mock_client)
            mc.return_value.__exit__ = MagicMock(return_value=False)
            result = generate_cards("fake")
        assert result["cards"][0]["type"] == "flashcard"

    def test_metadata_is_stripped_and_capped(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {"message": {"content": json.dumps({
            "subject": f"  {'s' * 250}  ",
            "deck_name": f"  {'d' * 250}  ",
            "description": f"  {'x' * 2500}  ",
            "cards": [{"question": "Q?", "answer": "A", "type": "flashcard"}],
        })}}
        mock_response.raise_for_status = MagicMock()
        mock_client = MagicMock()
        mock_client.post.return_value = mock_response
        with patch("ai_service.httpx.Client") as mc:
            mc.return_value.__enter__ = MagicMock(return_value=mock_client)
            mc.return_value.__exit__ = MagicMock(return_value=False)
            result = generate_cards("fake")
        assert result["subject"] == "s" * 200
        assert result["deck_name"] == "d" * 200
        assert result["description"] == "x" * 2000


class TestValidateCard:
    def test_invalid_card_type_is_coerced(self):
        card = validate_card({"question": "Q?", "answer": "A", "type": "bad"})
        assert card["type"] == "flashcard"

    def test_invalid_difficulty_is_clamped(self):
        card = validate_card({"question": "Q?", "answer": "A", "difficulty": 99})
        assert card["difficulty"] == 5

    def test_non_string_question_is_rejected(self):
        assert validate_card({"question": 123, "answer": "A"}) is None

    def test_non_string_answer_is_rejected(self):
        assert validate_card({"question": "Q?", "answer": ["A"]}) is None

    def test_malformed_options_handled(self):
        card = validate_card({"question": "Q?", "answer": "A", "type": "multiple_choice", "options": "bad"})
        assert card["type"] == "flashcard"
        assert card["options"] == []

    def test_answer_inserted_into_multiple_choice_options(self):
        card = validate_card({"question": "Q?", "answer": "A", "type": "multiple_choice", "options": ["B", "C"]})
        assert card["type"] == "multiple_choice"
        assert card["options"][0] == "A"


class TestOllamaStatus:
    def test_running(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {"models": [{"name": "gemma4:31b-cloud"}]}
        mock_response.raise_for_status = MagicMock()
        mock_client = MagicMock()
        mock_client.get.return_value = mock_response
        with patch("ai_service.httpx.Client") as mc:
            mc.return_value.__enter__ = MagicMock(return_value=mock_client)
            mc.return_value.__exit__ = MagicMock(return_value=False)
            result = check_ollama_status()
        assert result["running"] is True

    def test_not_running(self):
        with patch("ai_service.httpx.Client") as mc:
            mc.return_value.__enter__ = MagicMock(side_effect=Exception("fail"))
            mc.return_value.__exit__ = MagicMock(return_value=False)
            result = check_ollama_status()
        assert result["running"] is False
