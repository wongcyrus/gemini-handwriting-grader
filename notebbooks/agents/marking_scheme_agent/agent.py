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
from grading_utils import init_gemini_client

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

    # We call init_gemini_client primarily to load the .env file and validate the key exists
    try:
        _ = init_gemini_client(env_path=env_path)
    except Exception as e:
        logger.warning(
            f"init_gemini_client failed: {e}. Proceeding with manual env check."
        )

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


# Robust Pydantic models with comprehensive validation
class Question(BaseModel):
    """Robust question model with comprehensive validation"""

    question_number: str = Field(
        description="The question number (e.g., '1', '2', '22a', '22b', 'Q1','Q2')"
    )
    question_text: str = Field(description="The full question text")
    marking_scheme: str = Field(
        description="Well-formatted marking scheme using markdown. Use bullet points (-), numbered lists (1., 2.), bold (**text**) for key terms, and clear line breaks. Include point allocations in parentheses (e.g., '- Key concept explained (2 marks)'). Structure should be clear and scannable."
    )
    marks: int = Field(description="Total marks available for this question")


class MarkingSchemeResponse(BaseModel):
    """Robust wrapper class with validation"""

    general_grading_guide: str = Field(
        default="",
        description="General grading guide for partial marks applicable to all questions, formatted in markdown",
    )
    questions: List[Question] = Field(
        description="List of questions with marking schemes and marks"
    )


# Define the specialized agent
marking_scheme_agent = Agent(
    model="gemini-3-flash-preview",
    name="marking_scheme_extractor",
    description="Specialized agent for extracting structured marking schemes from documents.",
    instruction="""Please analyze this marking scheme document and extract structured, well-formatted data.

**FORMATTING REQUIREMENTS for marking_scheme:**
- Use markdown formatting (bullet points -, numbered lists 1., 2., bold **text**)
- Each marking criterion should be on its own line
- Show point allocations clearly (e.g., "- Correct formula (2 marks)")
- Use clear hierarchy with proper indentation for sub-points
- Add line breaks between major sections
- Bold important terms or key concepts
- Make it scannable and easy to read

**EXTRACT:**

1. **GENERAL GRADING GUIDE**: Extract any general grading guide or guidance for partial marks that applies to all/multiple questions (use markdown formatting)

2. **FOR EACH QUESTION**: Extract:
   - Question number (normalize to consistent format)
   - Question text (complete question statement)
   - **Marking scheme** (well-formatted with markdown, bullets, numbering, clear point allocation)
   - Total marks available (must be a positive integer)

**Important Guidelines:**
- When extracting the marking_scheme for each question, incorporate any general grading principles that apply to that question's scoring
- Ensure all questions have non-empty marking schemes
- Validate that mark totals are reasonable (1-100 marks per question)
- Use consistent formatting throughout""",
    output_schema=MarkingSchemeResponse,
    output_key="output",
    generate_content_config=types.GenerateContentConfig(
        temperature=0.1,
        top_p=0.5,
        max_output_tokens=8192,
        response_mime_type="application/json",
    ),
)


# Robust AI processing with comprehensive error handling and retry logic
async def extract_marking_scheme_with_ai(markdown_content, max_retries=3):
    """Extract marking scheme using AI with error handling via ADK Runner (Async)"""

    # Initialize session service once
    session_service = InMemorySessionService()

    for attempt in range(max_retries):
        try:
            logger.info(f"AI extraction attempt {attempt + 1}/{max_retries}")

            # Create a unique session for this attempt
            session_id = f"session_{os.urandom(4).hex()}"
            session = await session_service.create_session(
                app_name="marking_scheme_extractor",
                session_id=session_id,
                user_id="user",
            )

            # Initialize Runner
            runner = Runner(
                agent=marking_scheme_agent,
                app_name="marking_scheme_extractor",
                session_service=session_service,
            )

            # Create user prompt combining the document content
            user_prompt = f"""**Document Content:**

{markdown_content}
"""
            content = types.Content(role="user", parts=[types.Part(text=user_prompt)])

            # Run the agent and capture the final text response as fallback
            final_response_text = None
            async for event in runner.run_async(
                session_id=session_id, user_id="user", new_message=content
            ):
                if event.is_final_response() and event.content and event.content.parts:
                    final_response_text = event.content.parts[0].text

            # Retrieve structured output from session state (primary method)
            # ADK stores the parsed output in the session state under the output_key (default "output")
            session = await session_service.get_session(
                app_name="marking_scheme_extractor",
                session_id=session_id,
                user_id="user",
            )
            structured_output = session.state.get("output")

            if structured_output and isinstance(structured_output, dict):
                # If stored as dict, convert to model
                structured_output = MarkingSchemeResponse(**structured_output)

            if structured_output and isinstance(
                structured_output, MarkingSchemeResponse
            ):
                result = structured_output
                general_guide = result.general_grading_guide
                questions_data = [q.model_dump() for q in result.questions]

                logger.info(
                    f"✓ Successfully extracted {len(questions_data)} questions via ADK output state!"
                )
                if general_guide:
                    logger.info(
                        f"✓ General grading guide extracted ({len(general_guide)} characters)"
                    )
                return questions_data, general_guide
            raise ValueError("No valid response received from Agent runner")

        except Exception as e:
            logger.error(f"AI extraction attempt {attempt + 1} failed: {e}")
            if attempt < max_retries - 1:
                logger.info("Retrying...")
                continue
            else:
                raise
