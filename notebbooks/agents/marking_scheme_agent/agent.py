import os
from typing import List, Optional, Union
from google.genai import types
from google.adk.agents import Agent, SequentialAgent
from google.adk.tools.google_search_tool import GoogleSearchTool
from google.adk.models.llm_response import LlmResponse
from google.adk.agents.callback_context import CallbackContext
from pydantic import BaseModel, Field
from ..common import setup_agent_environment, run_agent_with_retry
import grading_utils
import hashlib


# Citation retrieval callback
def citation_retrieval_after_model_callback(
    callback_context: CallbackContext,
    llm_response: LlmResponse,
) -> LlmResponse:
    """Adds citations to the response if grounding metadata is present."""
    if llm_response.grounding_metadata and llm_response.grounding_metadata.grounding_chunks:
        # Check if we can append to content
        if llm_response.content and llm_response.content.parts:
            citation_text = "\n\nCitations:\n"
            found_citations = False
            for chunk in llm_response.grounding_metadata.grounding_chunks:
                if chunk.web:
                    found_citations = True
                    citation_text += f"  - {chunk.web.title}: {chunk.web.uri}\n"
            
            if found_citations:
                # Append to the first text part if it exists
                for part in llm_response.content.parts:
                    if part.text:
                        part.text += citation_text
                        break
                else:
                    # If no text part, add a new one
                    llm_response.content.parts.append(types.Part(text=citation_text))
    return llm_response


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


# Robust verification models
class VerificationItem(BaseModel):
    """Result of verifying a single question"""
    question_number: str = Field(description="The question identifier (e.g., 'Q1')")
    is_correct: bool = Field(description="Whether the question and answer are factually correct")
    feedback: str = Field(description="Detailed feedback explaining any issues or confirming correctness")
    suggestion: str = Field(description="Suggestion for improvement if needed, or 'None' if correct")


class VerificationResponse(BaseModel):
    """Structured verification results"""
    items: List[VerificationItem] = Field(description="Verification results for all questions")
    general_feedback: str = Field(description="Overall feedback on the marking scheme quality")


# Define the verification search agent (Grounding with tools, no schema)
marking_scheme_verifier_searcher = Agent(
    model="gemini-3-flash-preview",
    name="marking_scheme_verifier_searcher",
    description="Agent that verifies marking schemes using Google Search grounding.",
    instruction="""You are an expert examiner. Verify the following marking scheme questions and answers for factual correctness using Google Search.

For each question:
1. Check if the question is factually sound.
2. Check if the provided answer key is correct according to real-world facts (use Google Search).
3. Ensure the marking scheme points are relevant and accurate.
4. Provide constructive feedback and suggestions.

Evaluate:
- Whether the facts are accurate.
- Specific feedback citing what you verified.
- A suggestion if the wording or answer can be improved.""",
    tools=[GoogleSearchTool()],
    output_key="verification_draft",
    after_model_callback=citation_retrieval_after_model_callback,
    generate_content_config=types.GenerateContentConfig(
        temperature=0.1,
    ),
)


# Define the verification formatting agent (Structured output, no tools)
marking_scheme_verifier_formatter = Agent(
    model="gemini-3-flash-preview",
    name="marking_scheme_verifier_formatter",
    description="Agent that formats verification results into structured JSON.",
    instruction="""Format the 'verification_draft' provided by the previous agent into a structured JSON response according to the schema.
Ensure all questions are included in the 'items' list.
Provide an overall 'general_feedback' summary.
**IMPORTANT**: If the source text contains citations (starting with "Citations:"), include them in the 'feedback' field for the relevant question or in the 'general_feedback'.""",
    output_schema=VerificationResponse,
    output_key="output",
    generate_content_config=types.GenerateContentConfig(
        temperature=0.1,
        response_mime_type="application/json",
    ),
)

# Define the sequential verification agent
marking_scheme_verifier = SequentialAgent(
    name="marking_scheme_verifier",
    description="Sequential agent for marking scheme verification and formatting.",
    sub_agents=[marking_scheme_verifier_searcher, marking_scheme_verifier_formatter]
)


# Robust AI processing with comprehensive error handling and retry logic
async def extract_marking_scheme_with_ai(markdown_content, max_retries=3):
    """Extract marking scheme using AI with error handling via ADK Runner (Async)"""

    # --- Caching Logic ---
    cache_key = None
    try:
        content_hash = hashlib.sha256(markdown_content.encode("utf-8")).hexdigest()
        cache_key = grading_utils.get_cache_key(
            "marking_scheme_extraction",
            model="gemini-3-flash-preview",
            content_hash=content_hash,
        )
        cached = grading_utils.get_from_cache(cache_key)
        if cached is not None:
            logger.info("Marking scheme cache hit")
            # Cached data is a list of dicts for questions_data and a string for general_guide
            return cached[0], cached[1]
    except Exception as e:
        logger.warning(f"Cache lookup failed: {e}")
    # ---------------------

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
            logger=logger,
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

        # Save to cache
        if cache_key:
            grading_utils.save_to_cache(cache_key, (questions_data, general_guide))

        return questions_data, general_guide

    except Exception as e:
        logger.error(f"AI extraction failed: {e}")
        raise


async def verify_marking_scheme_with_ai(questions_data, max_retries=3):
    """Verify marking scheme correctness using AI with Google Search grounding (Sequential Agent)"""
    
    try:
        logger.info("Starting sequential marking scheme verification...")
        # Prepare content for verification
        questions_text = ""
        for q in questions_data:
            questions_text += f"Question {q.get('question_number')}: {q.get('question_text')}\n"
            questions_text += f"Answer/Marking: {q.get('marking_scheme')}\n\n"
            
        user_prompt = f"""**Marking Scheme to Verify:**

{questions_text}
"""
        content = types.Content(role="user", parts=[types.Part(text=user_prompt)])

        # Run the Sequential Agent
        result = await run_agent_with_retry(
            agent=marking_scheme_verifier,
            user_content=content,
            app_name="marking_scheme_verifier",
            output_type=VerificationResponse,
            max_retries=max_retries,
            logger=logger,
        )

        verification_items = [v.model_dump() for v in result.items]
        general_feedback = result.general_feedback
        
        logger.info(f"✓ Sequential verification completed: {len(verification_items)} items checked")
        
        return verification_items, general_feedback

    except Exception as e:
        logger.error(f"AI verification failed: {e}")
        # Return empty results rather than crashing the whole pipeline if verification fails
        return [], f"Verification failed due to technical error: {str(e)}"