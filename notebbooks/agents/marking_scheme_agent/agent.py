import os
from typing import List
from google.genai import types
from google.adk.agents.llm_agent import Agent
from pydantic import BaseModel, Field
from ..common import setup_agent_environment, run_agent_with_retry

# Setup environment and logging
logger = setup_agent_environment(__file__)

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

    try:
        # Create user prompt combining the document content
        user_prompt = f"""**Document Content:**

{markdown_content}
"""
        content = types.Content(role="user", parts=[types.Part(text=user_prompt)])

        result = await run_agent_with_retry(
            agent=marking_scheme_agent,
            user_content=content,
            app_name="marking_scheme_extractor",
            output_type=MarkingSchemeResponse,
            max_retries=max_retries,
            logger=logger
        )

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

    except Exception as e:
        logger.error(f"AI extraction failed: {e}")
        raise