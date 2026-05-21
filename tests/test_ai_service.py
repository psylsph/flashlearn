import os
import sys
import json
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ai_service import resize_image, generate_cards, parse_json_response, check_ollama_status


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
        with patch("ai_service.httpx.Client") as mc:
            mc.return_value.__enter__ = MagicMock(return_value=mock_response)
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
        with patch("ai_service.httpx.Client") as mc:
            mc.return_value.__enter__ = MagicMock(return_value=mock_response)
            mc.return_value.__exit__ = MagicMock(return_value=False)
            result = generate_cards("fake")
        assert result["success"] is False

    def test_mc_without_options_becomes_flashcard(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {"message": {"content": json.dumps({
            "cards": [{"question": "Q?", "answer": "A", "type": "multiple_choice", "options": []}]
        })}}
        mock_response.raise_for_status = MagicMock()
        with patch("ai_service.httpx.Client") as mc:
            mc.return_value.__enter__ = MagicMock(return_value=mock_response)
            mc.return_value.__exit__ = MagicMock(return_value=False)
            result = generate_cards("fake")
        assert result["cards"][0]["type"] == "flashcard"


class TestOllamaStatus:
    def test_running(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {"models": [{"name": "gemma4:31b-cloud"}]}
        mock_response.raise_for_status = MagicMock()
        with patch("ai_service.httpx.Client") as mc:
            mc.return_value.__enter__ = MagicMock(return_value=mock_response)
            mc.return_value.__exit__ = MagicMock(return_value=False)
            result = check_ollama_status()
        assert result["running"] is True

    def test_not_running(self):
        with patch("ai_service.httpx.Client") as mc:
            mc.return_value.__enter__ = MagicMock(side_effect=Exception("fail"))
            mc.return_value.__exit__ = MagicMock(return_value=False)
            result = check_ollama_status()
        assert result["running"] is False
