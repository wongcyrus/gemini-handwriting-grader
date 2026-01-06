import os
import sys
import logging
import asyncio
from dotenv import load_dotenv
from google.genai import types
from google.adk.agents.llm_agent import Agent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService

# Setup path to import grading_utils
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

# Robust logging setup
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Initialize environment and credentials
try:
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../"))
    env_path = os.path.join(project_root, ".env")

    # Load env vars explicitly as a fallback
    load_dotenv(env_path)

    # Ensure GOOGLE_API_KEY is set for ADK's internal client initialization
    genai_key = os.getenv("GOOGLE_GENAI_API_KEY")
    api_key = os.getenv("GOOGLE_API_KEY")

    if genai_key and not api_key:
        os.environ["GOOGLE_API_KEY"] = genai_key
        logger.info("Mapped GOOGLE_GENAI_API_KEY to GOOGLE_API_KEY for ADK")
    elif api_key:
        logger.info("GOOGLE_API_KEY found in environment")
    else:
        logger.error("No API key found in environment! ADK execution will likely fail.")

except Exception as e:
    logger.error(f"Failed to initialize environment: {e}")

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
    Perform OCR using the OCR agent.
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
                return final_text.strip()
            
            logger.warning(f"Empty OCR response on attempt {attempt + 1}")

        except Exception as e:
            logger.error(f"OCR attempt {attempt + 1} failed: {e}")
            if attempt < max_retries - 1:
                import time
                time.sleep(2 ** attempt)
                continue
            else:
                logger.error("All OCR attempts failed")
                return ""
    
    return ""
