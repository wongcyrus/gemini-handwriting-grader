import os
import json
import hashlib
from google.genai import types
from google.adk.agents.llm_agent import Agent
from pydantic import BaseModel, Field
from ..common import setup_agent_environment, run_agent_with_retry
import grading_utils

# Setup environment and logging
logger = setup_agent_environment(__file__)

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
    
    # --- Caching Logic ---
    cache_key = None
    try:
        # Use hash of the question details as payload hash
        payload_hash = hashlib.sha256(question_details.encode("utf-8")).hexdigest()
        cache_key = grading_utils.get_cache_key(
            "performance_report",
            model="gemini-3-flash-preview",
            student_id=str(student_id),
            payload_hash=payload_hash,
        )
        cached = grading_utils.get_from_cache(cache_key)
        if cached is not None and isinstance(cached, dict) and "report" in cached:
            logger.info(f"Performance report cache hit for {student_id}")
            return cached["report"]
    except Exception as e:
        logger.warning(f"Cache lookup failed: {e}")
    # ---------------------

    try:
        user_prompt = f"""Student: {student_id} - {student_name} (Class: {student_class})
Total score: {total_score}

Use the question details, marking schemes, awarded marks, and answers below:
{question_details}
"""
        content = types.Content(role="user", parts=[types.Part(text=user_prompt)])

        result = await run_agent_with_retry(
            agent=student_performance_agent,
            user_content=content,
            app_name="student_performance_generator",
            output_type=StudentPerformanceResponse,
            max_retries=max_retries,
            logger=logger
        )
        
        # Save to cache
        if cache_key:
            grading_utils.save_to_cache(cache_key, {"report": result.report_text})

        return result.report_text

    except Exception as e:
        logger.error(f"Student report generation failed: {e}")
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
    # Format sample reports
    report_blob = "\n\n---\n\n".join(sample_reports)

    # --- Caching Logic ---
    cache_key = None
    try:
        # Cache-aware Gemini call
        payload_hash = hashlib.sha256(
            (json.dumps(summary_payload, sort_keys=True) + report_blob).encode("utf-8")
        ).hexdigest()
        cache_key = grading_utils.get_cache_key(
            "class_overview_report",
            model="gemini-3-flash-preview",
            payload_hash=payload_hash,
        )
        cached = grading_utils.get_from_cache(cache_key)
        if cached is not None and isinstance(cached, dict) and "report" in cached:
            logger.info("Class overview cache hit")
            return cached["report"]
    except Exception as e:
        logger.warning(f"Cache lookup failed: {e}")
    # ---------------------

    try:
        user_prompt = f"""Key metrics (JSON): {json.dumps(summary_payload)}
Number of sampled individual reports: {len(sample_reports)}
Individual reports (separated by ---):
{report_blob}
"""
        content = types.Content(role="user", parts=[types.Part(text=user_prompt)])

        result = await run_agent_with_retry(
            agent=class_overview_agent,
            user_content=content,
            app_name="class_overview_generator",
            output_type=ClassOverviewResponse,
            max_retries=max_retries,
            logger=logger
        )

        # Save to cache
        if cache_key:
            grading_utils.save_to_cache(cache_key, {"report": result.report_text})

        return result.report_text

    except Exception as e:
        logger.error(f"Class overview generation failed: {e}")
        return "AI-generated class overview temporarily unavailable due to API issues."
