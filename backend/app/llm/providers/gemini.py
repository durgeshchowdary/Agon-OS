import os
import httpx
import asyncio
import logging
from typing import Optional
from pydantic import BaseModel
from app.llm.base import LLMProvider

logger = logging.getLogger(__name__)

def clean_schema(schema: dict, defs: dict = None) -> dict:
    if defs is None:
        defs = schema.get("$defs", {})
    
    if isinstance(schema, dict):
        if "$ref" in schema:
            ref_path = schema["$ref"]
            ref_name = ref_path.split("/")[-1]
            ref_schema = defs.get(ref_name, {})
            return clean_schema(ref_schema, defs)
            
        cleaned = {}
        if "type" in schema:
            t = schema["type"]
            type_mapping = {
                "string": "STRING",
                "object": "OBJECT",
                "array": "ARRAY",
                "number": "NUMBER",
                "integer": "INTEGER",
                "boolean": "BOOLEAN"
            }
            cleaned["type"] = type_mapping.get(t, t.upper())
            
        for key in ["properties", "items", "required", "description", "enum"]:
            if key in schema:
                val = schema[key]
                if key == "properties":
                    cleaned["properties"] = {k: clean_schema(v, defs) for k, v in val.items()}
                elif key == "items":
                    cleaned["items"] = clean_schema(val, defs)
                elif key == "required":
                    cleaned["required"] = val
                else:
                    cleaned[key] = val
        return cleaned
    elif isinstance(schema, list):
        return [clean_schema(item, defs) for item in schema]
    return schema

def pydantic_to_gemini_schema(model: type[BaseModel]) -> dict:
    raw_schema = model.model_json_schema()
    return clean_schema(raw_schema)

class GeminiProvider(LLMProvider):
    def __init__(self, api_key: str = None, model: str = "gemini-1.5-flash"):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        self.model = model
        self.api_url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"

    async def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        response_schema: Optional[type[BaseModel]] = None
    ) -> str:
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY environment variable is not set.")

        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": user_prompt}
                    ]
                }
            ],
            "systemInstruction": {
                "parts": [
                    {"text": system_prompt}
                ]
            }
        }

        generation_config = {}
        if response_schema:
            generation_config["responseMimeType"] = "application/json"
            generation_config["responseSchema"] = pydantic_to_gemini_schema(response_schema)
            
        if generation_config:
            payload["generationConfig"] = generation_config

        headers = {
            "Content-Type": "application/json"
        }

        url_with_key = f"{self.api_url}?key={self.api_key}"

        # Timeout protection: 15 seconds
        timeout = httpx.Timeout(15.0, connect=5.0)

        # Retry logic for transient failures (e.g. 429, 5xx, network errors)
        max_retries = 3
        backoff_factor = 1.0

        async with httpx.AsyncClient(timeout=timeout) as client:
            for attempt in range(max_retries):
                try:
                    logger.info("Gemini API call (attempt %d/%d) model=%s", attempt + 1, max_retries, self.model)
                    response = await client.post(url_with_key, json=payload, headers=headers)

                    # If rate limited or server error, retry with exponential backoff
                    if response.status_code in [429, 500, 502, 503, 504]:
                        logger.warning(f"Gemini API returned status code {response.status_code}. Retrying...")
                        if attempt == max_retries - 1:
                            response.raise_for_status()
                        await asyncio.sleep(backoff_factor * (2 ** attempt))
                        continue

                    response.raise_for_status()
                    result = response.json()

                    # Extract response text
                    try:
                        return result["candidates"][0]["content"]["parts"][0]["text"]
                    except (KeyError, IndexError) as e:
                        raise ValueError(f"Unexpected response structure from Gemini API: {result}") from e

                except (httpx.HTTPError, asyncio.TimeoutError) as e:
                    logger.error(f"Gemini API attempt {attempt + 1} failed: {e}")
                    if attempt == max_retries - 1:
                        raise e
                    await asyncio.sleep(backoff_factor * (2 ** attempt))

        raise ValueError("Failed to generate content from Gemini API.")
