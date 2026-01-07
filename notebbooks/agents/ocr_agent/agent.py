import os
import asyncio
import time
import hashlib
from google.genai import types
from google.adk.agents.llm_agent import Agent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from ..common import setup_agent_environment
import grading_utils

# Setup environment and logging
logger = setup_agent_environment(__file__)

# Define the OCR agent
ocr_agent = Agent(
    model="gemini-3-flash-preview",
    name="ocr_extractor",
    description="Agent for extracting text from images based on specific instructions.",
    instruction="You are an expert OCR assistant. Your task is to extract text from images exactly as requested.",
    generate_content_config=types.GenerateContentConfig(
        temperature=0.0,
        top_p=0.5,
        max_output_tokens=4096,
    ),
)

async def perform_ocr_with_ai(prompt: str, image_path: str = None, image_data: bytes = None, max_retries: int = 3) -> str:
    """
    Perform OCR using the OCR agent with caching.
    Accepts either image_path or image_data.
    """
    
    # Initialize session service once
    session_service = InMemorySessionService()
    
    # Load image data if path is provided
    if image_path and not image_data:
        try:
            with open(image_path, "rb") as f:
                image_data = f.read()
        except Exception as e:
            logger.error(f"Failed to read image file {image_path}: {e}")
            return ""
            
    if not image_data:
        logger.error("No image data provided for OCR")
        return ""

    # --- Caching Logic ---
    cache_key = None
    try:
        image_hash = hashlib.sha256(image_data).hexdigest()
        cache_key = grading_utils.get_cache_key(
            "ocr", 
            model="gemini-3-flash-preview", 
            prompt=prompt, 
            image_hash=image_hash
        )
        cached_result = grading_utils.get_from_cache(cache_key)
        if cached_result is not None:
             if isinstance(cached_result, dict) and "result" in cached_result:
                 logger.info(f"OCR cache hit for hash {image_hash[:8]}")
                 return cached_result["result"]
    except Exception as e:
        logger.warning(f"Cache lookup failed: {e}")
    # ---------------------

    for attempt in range(max_retries):
        try:
            # Create a unique session
            session_id = f"session_{os.urandom(4).hex()}"
            session = await session_service.create_session(
                app_name="ocr_extractor",
                session_id=session_id,
                user_id="user",
            )

            # Initialize Runner
            runner = Runner(
                agent=ocr_agent,
                app_name="ocr_extractor",
                session_service=session_service,
            )

            # Create content with image and prompt
            content = types.Content(
                role="user",
                parts=[
                    types.Part(inline_data=types.Blob(mime_type="image/jpeg", data=image_data)), # Assuming JPEG/PNG, API usually handles generic image types well or we could detect
                    types.Part(text=prompt)
                ]
            )

            # Run the agent
            final_text = ""
            async for event in runner.run_async(
                session_id=session_id, user_id="user", new_message=content
            ):
                if event.is_final_response() and event.content and event.content.parts:
                    final_text = event.content.parts[0].text

            if final_text:
                result_text = final_text.strip()
                # Save to cache
                if cache_key:
                    grading_utils.save_to_cache(cache_key, {"result": result_text})
                return result_text
            
            logger.warning(f"Empty OCR response on attempt {attempt + 1}")

        except Exception as e:
            logger.error(f"OCR attempt {attempt + 1} failed: {e}")
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
                continue
            else:
                logger.error("All OCR attempts failed")
                return ""
    
    return ""
