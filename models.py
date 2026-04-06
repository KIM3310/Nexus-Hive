"""
Pydantic request models for Nexus-Hive API endpoints.
"""

from pydantic import BaseModel

from config import DEFAULT_ROLE


class AskRequest(BaseModel):
    question: str


class ReviewerQueryDemoRequest(BaseModel):
    question_id: str


class PolicyCheckRequest(BaseModel):
    sql: str
    role: str = DEFAULT_ROLE
