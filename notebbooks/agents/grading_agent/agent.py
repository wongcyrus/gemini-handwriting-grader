import os
import sys
import json
import logging
import asyncio
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

# Pydantic Model
class GradingResult(BaseModel):
    """Pydantic model for grading results"""
    similarity_score: float = Field(description="Similarity score from 0 to 1")
    mark: float = Field(description="Actual mark awarded")
    reasoning: str = Field(description="Brief explanation of the score")

# Define Grading Agent
grading_agent = Agent(
    model="gemini-3-flash-preview",
    name="grading_expert",
    description="Expert grader for evaluating student answers against a marking scheme.",
    instruction="You are an expert grader. Evaluate the student's answer based on the provided question, marking scheme, and total marks.",
    output_schema=GradingResult,
    output_key="output",
    generate_content_config=types.GenerateContentConfig(
        temperature=0.0,
        top_p=0.3,
        max_output_tokens=8192,
        response_mime_type="application/json",
    ),
)

async def grade_answer_with_ai(question_text, submitted_answer, marking_scheme_text, total_marks, max_retries=3):
    """Grade a student's answer using the grading agent."""
    
    session_service = InMemorySessionService()
    
    prompt = f"""<QUESTION>
{question_text}
</QUESTION>

<MARKING_SCHEME>
{marking_scheme_text}
</MARKING_SCHEME>

<TOTAL_MARKS>
{total_marks}
</TOTAL_MARKS>

<STUDENT_ANSWER>
{submitted_answer}
</STUDENT_ANSWER>

Provide:
1. reasoning: Brief explanation of the scoring
2. similarity_score: Score from 0 to 1
3. mark: Actual mark to award (0 to {total_marks})"""

    for attempt in range(max_retries):
        try:
            session_id = f"session_{os.urandom(4).hex()}"
            session = await session_service.create_session(
                app_name="grading_expert", session_id=session_id, user_id="user"
            )
            
            runner = Runner(
                agent=grading_agent, app_name="grading_expert", session_service=session_service
            )
            
            content = types.Content(role="user", parts=[types.Part(text=prompt)])
            
            async for event in runner.run_async(session_id=session_id, user_id="user", new_message=content):
                pass
                
            session = await session_service.get_session(
                app_name="grading_expert", session_id=session_id, user_id="user"
            )
            structured_output = session.state.get("output")
            
            if structured_output and isinstance(structured_output, dict):
                structured_output = GradingResult(**structured_output)
                
            if structured_output and isinstance(structured_output, GradingResult):
                # Sanitize results
                result = structured_output
                result.similarity_score = max(0.0, min(1.0, result.similarity_score))
                result.mark = max(0.0, min(float(total_marks), result.mark))
                return result
                
            logger.warning("Structured grading output not found or invalid.")
            
        except Exception as e:
            logger.error(f"Grading attempt {attempt + 1} failed: {e}")
            if attempt < max_retries - 1:
                import time
                time.sleep(2 ** attempt)
                continue
                
    return GradingResult(similarity_score=0, mark=0, reasoning="Error: Grading failed")
