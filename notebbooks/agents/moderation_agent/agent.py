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

# Setup path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

# Robust logging setup
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Initialize environment
try:
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../"))
    env_path = os.path.join(project_root, ".env")
    load_dotenv(env_path)
    
    genai_key = os.getenv("GOOGLE_GENAI_API_KEY")
    api_key = os.getenv("GOOGLE_API_KEY")
    if genai_key and not api_key:
        os.environ["GOOGLE_API_KEY"] = genai_key
    elif not api_key:
        logger.error("No API key found!")
except Exception as e:
    logger.error(f"Failed to initialize environment: {e}")

# Pydantic Models
class ModerationItem(BaseModel):
    """Individual moderation result"""
    moderated_mark: float = Field(description="Final moderated mark")
    flag: bool = Field(description="True if adjusted or needs review")
    note: str = Field(description="Short reason for moderation")

class ModerationResponse(BaseModel):
    """Response containing all moderation items"""
    items: List[ModerationItem] = Field(description="List of moderation items")

# Define Moderation Agent
moderation_agent = Agent(
    model="gemini-3-pro-preview", # Use pro for complex moderation reasoning if available/preferred
    name="grading_moderator",
    description="Agent to moderate grading results for consistency.",
    instruction="You are a grading moderator ensuring fairness and consistency. Review the student responses and marks.",
    output_schema=ModerationResponse,
    output_key="output",
    generate_content_config=types.GenerateContentConfig(
        temperature=0.0,
        top_p=0.3,
        max_output_tokens=65535,
        response_mime_type="application/json",
    ),
)

async def moderate_grades_with_ai(question_text, marking_scheme_text, total_marks, entries: List[dict], max_retries=3):
    """Moderate grades using the moderation agent."""
    
    session_service = InMemorySessionService()
    
    entries_json = json.dumps(entries, ensure_ascii=False)
    
    prompt = f"""Question: {question_text}
Marking scheme: {marking_scheme_text}
Total marks: {total_marks}

Review {len(entries)} student responses and ensure similar answers receive similar marks.

Return JSON with "items" array of {len(entries)} objects:
- "moderated_mark": number (0 to {total_marks})
- "flag": boolean (true if adjusted or needs review)
- "note": string (max 120 chars, reference peers by row number)

Responses:
{entries_json}"""

    for attempt in range(max_retries):
        try:
            session_id = f"session_{os.urandom(4).hex()}"
            session = await session_service.create_session(
                app_name="grading_moderator", session_id=session_id, user_id="user"
            )
            
            runner = Runner(
                agent=moderation_agent, app_name="grading_moderator", session_service=session_service
            )
            
            content = types.Content(role="user", parts=[types.Part(text=prompt)])
            
            async for event in runner.run_async(session_id=session_id, user_id="user", new_message=content):
                pass
                
            session = await session_service.get_session(
                app_name="grading_moderator", session_id=session_id, user_id="user"
            )
            structured_output = session.state.get("output")
            
            if structured_output and isinstance(structured_output, dict):
                structured_output = ModerationResponse(**structured_output)
                
            if structured_output and isinstance(structured_output, ModerationResponse):
                # Validate items length
                if len(structured_output.items) != len(entries):
                    logger.warning(f"Moderation item count mismatch: got {len(structured_output.items)}, expected {len(entries)}")
                    # If mismatch, fallback or handle error? For now return what we have or error
                    # Better to error and retry if count is wrong
                    raise ValueError("Moderation item count mismatch")
                
                # Sanitize results
                results = []
                for item in structured_output.items:
                    item.moderated_mark = max(0.0, min(float(total_marks), item.moderated_mark))
                    results.append(item.model_dump())
                return results
                
            logger.warning("Structured moderation output not found or invalid.")
            
        except Exception as e:
            logger.error(f"Moderation attempt {attempt + 1} failed: {e}")
            if attempt < max_retries - 1:
                import time
                time.sleep(2 ** attempt)
                continue
                
    # Fallback: return original marks
    logger.error("Moderation failed, returning original marks")
    return [{"moderated_mark": float(e["mark"]), "flag": False, "note": "moderation_error"} for e in entries]
