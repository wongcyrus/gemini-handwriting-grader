import os
import json
from typing import List
from google.genai import types
from google.adk.agents.llm_agent import Agent
from pydantic import BaseModel, Field
from ..common import setup_agent_environment, run_agent_with_retry

# Setup environment and logging
logger = setup_agent_environment(__file__)

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

    try:
        content = types.Content(role="user", parts=[types.Part(text=prompt)])
        
        result = await run_agent_with_retry(
            agent=moderation_agent,
            user_content=content,
            app_name="grading_moderator",
            output_type=ModerationResponse,
            max_retries=max_retries,
            logger=logger
        )
        
        # Validate items length
        if len(result.items) != len(entries):
            logger.warning(f"Moderation item count mismatch: got {len(result.items)}, expected {len(entries)}")
            raise ValueError("Moderation item count mismatch")
        
        # Sanitize results
        results = []
        for item in result.items:
            item.moderated_mark = max(0.0, min(float(total_marks), item.moderated_mark))
            results.append(item.model_dump())
        return results
            
    except Exception as e:
        logger.error(f"Moderation failed: {e}")
        # Fallback: return original marks
        return [{"moderated_mark": float(e["mark"]), "flag": False, "note": "moderation_error"} for e in entries]