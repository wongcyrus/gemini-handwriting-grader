import os
from google.genai import types
from google.adk.agents.llm_agent import Agent
from pydantic import BaseModel, Field
from ..common import setup_agent_environment, run_agent_with_retry

# Setup environment and logging
logger = setup_agent_environment(__file__)

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
        return result
            
    except Exception as e:
        logger.error(f"Grading failed: {e}")
        return GradingResult(similarity_score=0, mark=0, reasoning="Error: Grading failed")