import os
import sys
import json
import logging
import asyncio
from typing import List
from dotenv import load_dotenv
from google.genai import types
from google.adk.agents.llm_agent import Agent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from pydantic import BaseModel, Field

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


# Robust Pydantic models with validation
class BoundingBox(BaseModel):
    """Represents a single bounding box annotation with validation."""
    x: int = Field(description="X coordinate of the top-left corner")
    y: int = Field(description="Y coordinate of the top-left corner")
    width: int = Field(description="Width of the bounding box")
    height: int = Field(description="Height of the bounding box")
    label: str = Field(description="Question number (e.g., '1', '2', '3')")

class BoundingBoxResponse(BaseModel):
    """Wrapper class for list of bounding boxes with validation."""
    boxes: List[BoundingBox] = Field(description="List of bounding boxes for question cells")


# Define the specialized agent
annotation_agent = Agent(
    model="gemini-3-flash-preview",
    name="annotation_extractor",
    description="Specialized agent for extracting bounding boxes for question/answer cells from exam images.",
    instruction="""Extract the coordinates of bounding boxes for each question/answer cell from the table in the image.

Instructions:
- Identify all table cells that contain question numbers (like "1", "2", "3", "4", "5", etc.)
- Question IDs may appear in formats such as "Q1", "Q2", "q.1", "q.2" (case-insensitive); capture the full alphanumeric label (without the trailing period)
- Question numbers are typically located in the top-left corner or top area of each cell
- Each bounding box should cover the entire cell area where a student would write their answer
- Include cells with sub-questions (like 22a, 22b, 22c, etc.) as separate bounding boxes
- Do NOT include cells that only contain "XXXXXXX" or are marked as non-answer areas
- Bounding boxes may be adjacent but should not overlap
- For merged cells spanning multiple rows/columns, create one bounding box covering the entire merged area
- Also identify and mark special fields: NAME, ID, CLASS (student information fields)
- Do NOT draw a bounding box if the question label is not placed inside a clear table cell/answer cell

For each bounding box, provide:
- x: X coordinate of the top-left corner of the cell
- y: Y coordinate of the top-left corner of the cell
- width: Width of the entire cell (including answer space)
- height: Height of the entire cell (including answer space)
- label: The question number or field name (e.g., "1", "2", "3", "Q1", "q.1", "NAME", "ID", "CLASS")

Important: 
- Extract the question number text exactly as shown (including letters like "a", "b", "c" for sub-questions)
- Do not include the period after the question number in the label
- Focus on cells where students write answers, not header cells or instruction text
- Ensure NAME, ID, and CLASS fields are properly identified for student information""",
    output_schema=BoundingBoxResponse,
    output_key="output",
    generate_content_config=types.GenerateContentConfig(
        temperature=0.0,
        top_p=0.5,
        max_output_tokens=65535,
        response_mime_type="application/json",
    ),
)


# Robust AI processing with comprehensive error handling and retry logic
async def extract_annotations_with_ai(image_path, max_retries=3):
    """Extract annotations using AI with error handling via ADK Runner (Async)"""

    # Initialize session service once
    session_service = InMemorySessionService()

    # Read image data
    try:
        with open(image_path, "rb") as f:
            image_data = f.read()
    except Exception as e:
        logger.error(f"Failed to read image file {image_path}: {e}")
        return BoundingBoxResponse(boxes=[])

    for attempt in range(max_retries):
        try:
            logger.info(f"AI extraction attempt {attempt + 1}/{max_retries} for {image_path}")

            # Create a unique session for this attempt
            session_id = f"session_{os.urandom(4).hex()}"
            session = await session_service.create_session(
                app_name="annotation_extractor",
                session_id=session_id,
                user_id="user",
            )

            # Initialize Runner
            runner = Runner(
                agent=annotation_agent,
                app_name="annotation_extractor",
                session_service=session_service,
            )

            # Create user prompt with image
            content = types.Content(
                role="user",
                parts=[
                    types.Part(inline_data=types.Blob(mime_type="image/jpeg", data=image_data)),
                    types.Part(text="Extract bounding boxes from this image.")
                ]
            )

            # Run the agent
            async for event in runner.run_async(
                session_id=session_id, user_id="user", new_message=content
            ):
                pass

            # Retrieve structured output from session state (primary method)
            # ADK stores the parsed output in the session state under the output_key (default "output")
            session = await session_service.get_session(
                app_name="annotation_extractor",
                session_id=session_id,
                user_id="user",
            )
            structured_output = session.state.get("output")

            if structured_output and isinstance(structured_output, dict):
                # If stored as dict, convert to model
                structured_output = BoundingBoxResponse(**structured_output)

            if structured_output and isinstance(
                structured_output, BoundingBoxResponse
            ):
                result = structured_output
                boxes_data = [box.model_dump() for box in result.boxes]

                logger.info(
                    f"✓ Successfully extracted {len(boxes_data)} boxes via ADK output state!"
                )
                return result
            
            raise ValueError("No valid structured response received from Agent runner")

        except Exception as e:
            logger.error(f"AI extraction attempt {attempt + 1} failed for {image_path}: {e}")
            if attempt < max_retries - 1:
                import time
                time.sleep(2 ** attempt) # Exponential backoff
                logger.info("Retrying...")
                continue
            else:
                logger.error(f"All extraction attempts failed for {image_path}")
                # Return empty response instead of raising to allow partial success in batch processing
                return BoundingBoxResponse(boxes=[])
