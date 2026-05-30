from pydantic import BaseModel, Field
from typing import List, Dict

class ResumeEvaluation(BaseModel):
    passed: bool = Field(description="True if resume meets the bar")
    is_hallucinated: bool = Field(description="True if fabricated facts exist")
    feedback: str = Field(description="Specific, actionable feedback for the generator. Use newlines to separate multiple points.")
    ats_score: int = Field(description="Score for ATS parsing and keyword optimization (0-100)")
    manual_score: int = Field(description="Score for human recruiter impact and readability (0-100)")

class ResumeEdit(BaseModel):
    search_string: str = Field(description="The exact contiguous text block in the current HTML to be replaced. Must be unique and match the existing HTML exactly including whitespace.")
    replacement_string: str = Field(description="The new text/HTML to replace it with.")

class ResumeRevisions(BaseModel):
    edits: List[ResumeEdit] = Field(description="List of targeted edits to apply to the HTML.")

class Phase1Research(BaseModel):
    research_markdown: str = Field(description="Full markdown for Sections 1, 2, 3, 4, and 6.")
    company_type: str = Field(description="The determined company type: 'product_startup', 'it_services', or 'gcc'.")

class Phase2FinalGuide(BaseModel):
    guide_markdown: str = Field(description="Complete markdown guide with all 7 sections assembled.")
    summary: str = Field(description="2-3 sentences max: the single most important insight, top skills to emphasize, and callback confidence level.")
