import os
from google.genai import types
from google.adk.agents import Agent, SequentialAgent
from pydantic import BaseModel, Field
from ..common import setup_agent_environment, run_agent_with_retry
from ..ocr_agent.agent import ocr_agent
import grading_utils

# Setup environment and logging
logger = setup_agent_environment(__file__)

# Pydantic Model
class GradingResult(BaseModel):
    """Pydantic model for grading results"""
    extracted_text: str = Field(description="The student's answer text as extracted/read")
    similarity_score: float = Field(description="Similarity score from 0 to 1")
    mark: float = Field(description="Actual mark awarded")
    reasoning: str = Field(description="Brief explanation of the score")

# Define Grading Agent
grading_agent = Agent(
    model="gemini-3-flash-preview",
    name="grading_expert",
    description="Expert grader for evaluating student answers against a marking scheme.",
    instruction="""You are an expert grader. Evaluate the student's answer based on the provided question, marking scheme, and total marks.

If this is part of a sequential process (e.g., following OCR), the student's answer will be the input provided to you. The Question, Marking Scheme, and Total Marks will be found in the conversation history (context).

Ensure you populate the 'extracted_text' field with the student's answer you evaluated.""",
    output_schema=GradingResult,
    output_key="output",
    generate_content_config=types.GenerateContentConfig(
        temperature=0.0,
        top_p=0.3,
        max_output_tokens=8192,
        response_mime_type="application/json",
    ),
)

# Define Sequential Agent for OCR + Grading
ocr_grading_agent = SequentialAgent(
    name="ocr_and_grading",
    description="Sequential agent that first extracts text from an image (OCR) and then grades it.",
    sub_agents=[ocr_agent, grading_agent],
)

async def grade_answer_with_ai(question_text, submitted_answer, marking_scheme_text, total_marks, max_retries=3):
    """Grade a student's answer using the grading agent (Text-only)."""
    
    # --- Caching Logic ---
    cache_key = None
    try:
        cache_key = grading_utils.get_cache_key(
            "grade_answer",
            model="gemini-3-flash-preview",
            question=question_text,
            answer=submitted_answer,
            scheme=marking_scheme_text,
            marks=total_marks
        )
        cached = grading_utils.get_from_cache(cache_key)
        if cached:
            logger.info(f"Grading cache hit")
            return GradingResult(**cached)
    except Exception as e:
        logger.warning(f"Cache lookup failed: {e}")
    # ---------------------
    
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
1. extracted_text: The student answer provided above
2. reasoning: Brief explanation of the scoring
3. similarity_score: Score from 0 to 1
4. mark: Actual mark to award (0 to {total_marks})"""

    try:
        content = types.Content(role="user", parts=[types.Part(text=prompt)])
        
        result = await run_agent_with_retry(
            agent=grading_agent,
            user_content=content,
            app_name="grading_expert",
            output_type=GradingResult,
            max_retries=max_retries,
            logger=logger
        )
        
        # Sanitize results
        result.similarity_score = max(0.0, min(1.0, result.similarity_score))
        result.mark = max(0.0, min(float(total_marks), result.mark))
        
        # Save to cache
        if cache_key:
            grading_utils.save_to_cache(cache_key, result.model_dump())
            
        return result
            
    except Exception as e:
        logger.error(f"Grading failed: {e}")
        return GradingResult(extracted_text=submitted_answer, similarity_score=0, mark=0, reasoning=f"Error: Grading failed - {str(e)}")


async def grade_answer_with_ocr_and_ai(question_text, marking_scheme_text, total_marks, image_data, max_retries=3):
    """
    Grade a student's answer by first performing OCR on the image and then grading the text.
    Uses the SequentialAgent 'ocr_grading_agent'.
    """
    
    # --- Caching Logic ---
    cache_key = None
    try:
        # Create a hash of the image
        import hashlib
        image_hash = hashlib.sha256(image_data).hexdigest()
        
        cache_key = grading_utils.get_cache_key(
            "grade_answer_ocr",
            model="gemini-3-flash-preview",
            question=question_text,
            scheme=marking_scheme_text,
            marks=total_marks,
            image_hash=image_hash
        )
        cached = grading_utils.get_from_cache(cache_key)
        if cached:
            logger.info(f"OCR+Grading cache hit")
            return GradingResult(**cached)
    except Exception as e:
        logger.warning(f"Cache lookup failed: {e}")
    # ---------------------

    # Construct the prompt for the first agent (OCR)
    # We include the grading context so it's available in the history for the second agent (Grading)
    prompt = f"""<CONTEXT_FOR_GRADING>
<QUESTION>
{question_text}
</QUESTION>
<MARKING_SCHEME>
{marking_scheme_text}
</MARKING_SCHEME>
<TOTAL_MARKS>
{total_marks}
</TOTAL_MARKS>
</CONTEXT_FOR_GRADING>

Please extract the handwritten text from the provided image. 
(Note: The context above is for the subsequent grading step, please focus on extracting the text in the image)."""

    try:
        content = types.Content(
            role="user",
            parts=[
                types.Part(inline_data=types.Blob(mime_type="image/jpeg", data=image_data)),
                types.Part(text=prompt)
            ]
        )
        
        # Run the Sequential Agent
        # The result will be the output of the LAST agent (grading_agent), which is a GradingResult
        result = await run_agent_with_retry(
            agent=ocr_grading_agent,
            user_content=content,
            app_name="ocr_and_grading",
            output_type=GradingResult,
            max_retries=max_retries,
            logger=logger
        )
        
        # Sanitize results
        result.similarity_score = max(0.0, min(1.0, result.similarity_score))
        result.mark = max(0.0, min(float(total_marks), result.mark))
        
        # Save to cache
        if cache_key:
            grading_utils.save_to_cache(cache_key, result.model_dump())
            
        return result

    except Exception as e:
        logger.error(f"OCR+Grading failed: {e}")
        return GradingResult(extracted_text="", similarity_score=0, mark=0, reasoning=f"Error: OCR+Grading failed - {str(e)}")
