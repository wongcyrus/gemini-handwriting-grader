import os
import sys
import logging
import json
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

# --- Student Performance Agent ---


class StudentPerformanceResponse(BaseModel):
    """Structured response for student performance report"""

    report_text: str = Field(description="The generated performance report text.")


student_performance_agent = Agent(
    model="gemini-3-flash-preview",
    name="student_performance_generator",
    description="Agent for generating individual student performance reports.",
    instruction="""You are an instructor drafting a concise performance report.

Write:
- 2-3 sentence overall summary of strengths and weaknesses.
- One short bullet per question with actionable feedback tied to the marking scheme.
- 2 concrete next-step study suggestions focused on the weakest skills.
Keep it under 220 words and avoid restating the input verbatim.""",
    output_schema=StudentPerformanceResponse,
    output_key="output",
    generate_content_config=types.GenerateContentConfig(
        temperature=0.35,
        top_p=0.9,
        max_output_tokens=1536,
        response_mime_type="application/json",
    ),
)


async def generate_student_report_with_ai(
    student_id,
    student_name,
    student_class,
    total_score,
    question_details,
    max_retries=3,
):
    """Generate student performance report using AI"""

    session_service = InMemorySessionService()

    for attempt in range(max_retries):
        try:
            session_id = f"session_student_{student_id}_{os.urandom(4).hex()}"
            session = await session_service.create_session(
                app_name="student_performance_generator",
                session_id=session_id,
                user_id="user",
            )

            runner = Runner(
                agent=student_performance_agent,
                app_name="student_performance_generator",
                session_service=session_service,
            )

            user_prompt = f"""Student: {student_id} - {student_name} (Class: {student_class})
Total score: {total_score}

Use the question details, marking schemes, awarded marks, and answers below:
{question_details}
"""
            content = types.Content(role="user", parts=[types.Part(text=user_prompt)])

            async for event in runner.run_async(
                session_id=session_id, user_id="user", new_message=content
            ):
                pass

            session = await session_service.get_session(
                app_name="student_performance_generator",
                session_id=session_id,
                user_id="user",
            )
            structured_output = session.state.get("output")

            if structured_output:
                if isinstance(structured_output, dict):
                    structured_output = StudentPerformanceResponse(**structured_output)
                return structured_output.report_text

            raise ValueError("No valid structured response received")

        except Exception as e:
            logger.error(f"Student report generation failed (Attempt {attempt+1}): {e}")
            if attempt < max_retries - 1:
                continue
            return f"Report generation failed: {e}"


# --- Class Overview Agent ---


class ClassOverviewResponse(BaseModel):
    """Structured response for class overview report"""

    report_text: str = Field(description="The generated class overview report text.")


class_overview_agent = Agent(
    model="gemini-3-flash-preview",
    name="class_overview_generator",
    description="Agent for generating class-level performance overview.",
    instruction="""You are summarizing overall class performance from individual reports.

Write a concise class-level overview (<200 words):
- 4-6 bullets on class strengths and weaknesses
- 3 targeted next-step actions for instruction
- 2 questions/topics to re-teach next
Focus on patterns; do not restate student names or IDs.""",
    output_schema=ClassOverviewResponse,
    output_key="output",
    generate_content_config=types.GenerateContentConfig(
        temperature=0.35,
        top_p=0.9,
        max_output_tokens=1536,
        response_mime_type="application/json",
    ),
)


async def generate_class_overview_with_ai(
    summary_payload, sample_reports, max_retries=3
):
    """Generate class overview report using AI"""

    session_service = InMemorySessionService()

    # Format sample reports
    report_blob = "\n\n---\n\n".join(sample_reports)

    for attempt in range(max_retries):
        try:
            session_id = f"session_class_{os.urandom(4).hex()}"
            session = await session_service.create_session(
                app_name="class_overview_generator",
                session_id=session_id,
                user_id="user",
            )

            runner = Runner(
                agent=class_overview_agent,
                app_name="class_overview_generator",
                session_service=session_service,
            )

            user_prompt = f"""Key metrics (JSON): {json.dumps(summary_payload)}
Number of sampled individual reports: {len(sample_reports)}
Individual reports (separated by ---):
{report_blob}
"""
            content = types.Content(role="user", parts=[types.Part(text=user_prompt)])

            async for event in runner.run_async(
                session_id=session_id, user_id="user", new_message=content
            ):
                pass

            session = await session_service.get_session(
                app_name="class_overview_generator",
                session_id=session_id,
                user_id="user",
            )
            structured_output = session.state.get("output")

            if structured_output:
                if isinstance(structured_output, dict):
                    structured_output = ClassOverviewResponse(**structured_output)
                return structured_output.report_text

            raise ValueError("No valid structured response received")

        except Exception as e:
            logger.error(f"Class overview generation failed (Attempt {attempt+1}): {e}")
            if attempt < max_retries - 1:
                continue
            return (
                "AI-generated class overview temporarily unavailable due to API issues."
            )
