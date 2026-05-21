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
        # Should be valid base64
        import base64
        decoded = base64.b64decode(result)
        assert len(decoded) > 0
        assert decoded[:2] == b'\xff\xd8'  # JPEG magic bytes

    def test_resize_returns_jpeg(self, sample_png_bytes):
        import base64
        result = resize_image(sample_png_bytes)
        decoded = base64.b64decode(result)
        assert decoded[:2] == b'\xff\xd8'


class TestJsonParsing:
    def test_valid_json(self):
        text = '{"subject": "Math", "cards": []}'
        result = parse_json_response(text)
        assert result["subject"] == "Math"

    def test_json_in_markdown_fences(self):
        text = '```json\n{"subject": "Math", "cards": []}\n```'
        result = parse_json_response(text)
        assert result["subject"] == "Math"

    def test_json_in_plain_fences(self):
        text = '```\n{"subject": "Math", "cards": []}\n```'
        result = parse_json_response(text)
        assert result["subject"] == "Math"

    def test_json_embedded_in_text(self):
        text = 'Here are the cards:\n{"subject": "Math", "cards": []}\nEnd.'
        result = parse_json_response(text)
        assert result["subject"] == "Math"

    def test_garbage_input(self):
        text = "This is not JSON at all"
        result = parse_json_response(text)
        assert "error" in result

    def test_partial_json(self):
        text = "{broken json"
        result = parse_json_response(text)
        assert "error" in result


class TestGenerateCards:
    def test_successful_generation(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "message": {
                "content": json.dumps({
                    "subject": "Biology",
                    "deck_name": "Cell Biology",
                    "description": "Cell structures",
                    "cards": [
                        {"question": "What is a cell?", "answer": "Basic unit of life", "type": "flashcard", "difficulty": 1},
                        {
                            "question": "Powerhouse of cell?",
                            "answer": "Mitochondria",
                            "type": "multiple_choice",
                            "options": ["Mitochondria", "Nucleus", "Ribosome", "Golgi"],
                            "difficulty": 2,
                        },
                    ],
                })
            }
        }
        mock_response.raise_for_status = MagicMock()

        with patch("ai_service.httpx.Client") as mock_client:
            mock_client.return_value.__enter__ = MagicMock(return_value=mock_response)
            mock_client.return_value.__exit__ = MagicMock(return_value=False)
            result = generate_cards("fake_base64", "test-model")

        assert result["success"] is True
        assert len(result["cards"]) == 2
        assert result["subject"] == "Biology"

    def test_connection_error(self):
        import httpx
        with patch("ai_service.httpx.Client") as mock_client:
            mock_client.return_value.__enter__ = MagicMock(side_effect=httpx.ConnectError("No connection"))
            mock_client.return_value.__exit__ = MagicMock(return_value=False)
            result = generate_cards("fake_base64")
        assert result["success"] is False
        assert "connect" in result["error"].lower()

    def test_timeout_error(self):
        import httpx
        with patch("ai_service.httpx.Client") as mock_client:
            mock_client.return_value.__enter__ = MagicMock(side_effect=httpx.TimeoutException("Timeout"))
            mock_client.return_value.__exit__ = MagicMock(return_value=False)
            result = generate_cards("fake_base64")
        assert result["success"] is False
        assert "timed out" in result["error"].lower()

    def test_invalid_response_no_cards(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {"message": {"content": json.dumps({"subject": "Math"})}}
        mock_response.raise_for_status = MagicMock()

        with patch("ai_service.httpx.Client") as mock_client:
            mock_client.return_value.__enter__ = MagicMock(return_value=mock_response)
            mock_client.return_value.__exit__ = MagicMock(return_value=False)
            result = generate_cards("fake_base64")
        assert result["success"] is False

    def test_empty_cards(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {"message": {"content": json.dumps({"cards": []})}}
        mock_response.raise_for_status = MagicMock()

        with patch("ai_service.httpx.Client") as mock_client:
            mock_client.return_value.__enter__ = MagicMock(return_value=mock_response)
            mock_client.return_value.__exit__ = MagicMock(return_value=False)
            result = generate_cards("fake_base64")
        assert result["success"] is False

    def test_mc_card_without_options_becomes_flashcard(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "message": {
                "content": json.dumps({
                    "cards": [
                        {"question": "Q?", "answer": "A", "type": "multiple_choice", "options": []},
                    ],
                })
            }
        }
        mock_response.raise_for_status = MagicMock()

        with patch("ai_service.httpx.Client") as mock_client:
            mock_client.return_value.__enter__ = MagicMock(return_value=mock_response)
            mock_client.return_value.__exit__ = MagicMock(return_value=False)
            result = generate_cards("fake_base64")
        assert result["success"] is True
        assert result["cards"][0]["type"] == "flashcard"


class TestOllamaStatus:
    def test_ollama_running(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {"models": [{"name": "gemma4:31b-cloud"}, {"name": "gemma3:4b"}]}
        mock_response.raise_for_status = MagicMock()

        with patch("ai_service.httpx.Client") as mock_client:
            mock_client.return_value.__enter__ = MagicMock(return_value=mock_response)
            mock_client.return_value.__exit__ = MagicMock(return_value=False)
            result = check_ollama_status()
        assert result["running"] is True
        assert len(result["models"]) == 2

    def test_ollama_not_running(self):
        with patch("ai_service.httpx.Client") as mock_client:
            mock_client.return_value.__enter__ = MagicMock(side_effect=Exception("No connection"))
            mock_client.return_value.__exit__ = MagicMock(return_value=False)
            result = check_ollama_status()
        assert result["running"] is False
        assert result["models"] == []
