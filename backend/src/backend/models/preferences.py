"""User preference schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field


class GoalRequest(BaseModel):
    goal: str = Field(min_length=1, max_length=500, description="A preset label or free text")
