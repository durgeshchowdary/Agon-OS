import os
import pytest
import httpx
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock
from pydantic import BaseModel
from typing import List, Optional

from app.llm.providers.gemini import GeminiProvider, pydantic_to_gemini_schema

class MockSubModel(BaseModel):
    name: str
    value: int

class MockModel(BaseModel):
    title: str
    scores: List[float]
    nested: List[MockSubModel]
    flag: Optional[bool] = None

@pytest.mark.asyncio
async def test_pydantic_to_gemini_schema():
    schema = pydantic_to_gemini_schema(MockModel)
    
    assert schema["type"] == "OBJECT"
    assert "title" in schema["properties"]
    assert schema["properties"]["title"]["type"] == "STRING"
    assert schema["properties"]["scores"]["type"] == "ARRAY"
    assert schema["properties"]["scores"]["items"]["type"] == "NUMBER"
    assert schema["properties"]["nested"]["type"] == "ARRAY"
    assert schema["properties"]["nested"]["items"]["type"] == "OBJECT"
    assert schema["properties"]["nested"]["items"]["properties"]["name"]["type"] == "STRING"
    assert schema["properties"]["nested"]["items"]["properties"]["value"]["type"] == "INTEGER"

@pytest.mark.asyncio
async def test_gemini_provider_success():
    provider = GeminiProvider(api_key="test-key", model="gemini-1.5-flash")
    
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {"text": '{"title": "Test response", "scores": [1.0, 2.0], "nested": [], "flag": true}'}
                    ]
                }
            }
        ]
    }
    mock_response.raise_for_status = MagicMock()
    
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response
        
        response_str = await provider.generate(
            system_prompt="Test System Prompt",
            user_prompt="Test User Prompt",
            response_schema=MockModel
        )
        
        assert "Test response" in response_str
        # Verify schema was passed in payload
        args, kwargs = mock_post.call_args
        payload = kwargs["json"]
        assert "generationConfig" in payload
        assert payload["generationConfig"]["responseMimeType"] == "application/json"
        assert "responseSchema" in payload["generationConfig"]

@pytest.mark.asyncio
async def test_gemini_provider_rate_limit_retry():
    # Make retries fast by mocking asyncio.sleep
    provider = GeminiProvider(api_key="test-key")
    
    mock_429 = MagicMock()
    mock_429.status_code = 429
    mock_429.raise_for_status = MagicMock(side_effect=httpx.HTTPStatusError("429", request=None, response=mock_429))
    
    mock_200 = MagicMock()
    mock_200.status_code = 200
    mock_200.json.return_value = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {"text": "Success after rate limit"}
                    ]
                }
            }
        ]
    }
    
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post, \
         patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        # First two calls return 429, third returns 200
        mock_post.side_effect = [mock_429, mock_429, mock_200]
        
        response_str = await provider.generate(
            system_prompt="Test",
            user_prompt="Test"
        )
        
        assert response_str == "Success after rate limit"
        assert mock_post.call_count == 3
        assert mock_sleep.call_count == 2

@pytest.mark.asyncio
async def test_gemini_provider_timeout_retry():
    provider = GeminiProvider(api_key="test-key")
    
    mock_200 = MagicMock()
    mock_200.status_code = 200
    mock_200.json.return_value = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {"text": "Success after timeout"}
                    ]
                }
            }
        ]
    }
    
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post, \
         patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        # First call timeouts, second succeeds
        mock_post.side_effect = [asyncio.TimeoutError("Connection timeout"), mock_200]
        
        response_str = await provider.generate(
            system_prompt="Test",
            user_prompt="Test"
        )
        
        assert response_str == "Success after timeout"
        assert mock_post.call_count == 2
        assert mock_sleep.call_count == 1

@pytest.mark.asyncio
async def test_gemini_provider_max_retries_fail():
    provider = GeminiProvider(api_key="test-key")
    
    mock_500 = MagicMock()
    mock_500.status_code = 500
    mock_500.raise_for_status = MagicMock(side_effect=httpx.HTTPStatusError("500 Internal Server Error", request=None, response=mock_500))
    
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post, \
         patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        mock_post.return_value = mock_500
        
        with pytest.raises(httpx.HTTPStatusError):
            await provider.generate(
                system_prompt="Test",
                user_prompt="Test"
            )
            
        assert mock_post.call_count == 3
