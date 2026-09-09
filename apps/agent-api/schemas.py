"""Pydantic models shared across the agent.

Every structure the LLM produces is defined here as a schema, and every one
of them is enforced with guided decoding rather than hoped for. That is the
direct continuation of Day 1: a model that must emit valid JSON cannot emit a
plan the executor is unable to run.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


# --------------------------------------------------------------------------
# Intent
# --------------------------------------------------------------------------

class IntentLabel(str, Enum):
    """Three outcomes, not two.

    Treating intent as a yes/no question is the most common mistake. A question
    like "what is a router" is neither in scope for a database query nor
    something to refuse - it deserves a plain answer with no tool calls.
    """

    IN_SCOPE = "in_scope"
    GENERAL_KNOWLEDGE = "general_knowledge"
    NEEDS_CLARIFICATION = "needs_clarification"
    OUT_OF_SCOPE = "out_of_scope"


class IntentResult(BaseModel):
    label: IntentLabel
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = Field(description="Why this label, in one sentence")
    missing_information: list[str] = Field(
        default_factory=list,
        description="For needs_clarification: exactly what is missing",
    )
    suggested_options: list[str] = Field(
        default_factory=list,
        description="Concrete choices to offer the user instead of an open question",
    )
    decided_by: str = Field(
        default="llm", description="fast_path or llm - which layer produced this"
    )


# --------------------------------------------------------------------------
# Planning
# --------------------------------------------------------------------------

class PlanStep(BaseModel):
    step: int = Field(ge=1)
    tool: str
    arguments: dict = Field(default_factory=dict)
    purpose: str = Field(description="What this step is meant to establish")
    depends_on: list[int] = Field(
        default_factory=list,
        description="Steps whose results this step needs. Empty means it can run immediately.",
    )
    argument_from: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Arguments filled from an earlier result, as "
            "{argument_name: 'step.N.json_path'}. Used when a value is not "
            "known until a previous step runs."
        ),
    )


class Plan(BaseModel):
    goal: str = Field(description="Restatement of what the user actually wants")
    reasoning: str = Field(description="Why this sequence of steps answers it")
    steps: list[PlanStep]
    expected_sources: list[str] = Field(
        default_factory=list, description="postgres, neo4j and/or opensearch"
    )


# --------------------------------------------------------------------------
# Execution
# --------------------------------------------------------------------------

class StepResult(BaseModel):
    step: int
    tool: str
    ok: bool
    duration_ms: int
    result: dict | list | str | None = None
    error: str | None = None
    skipped_reason: str | None = None


# --------------------------------------------------------------------------
# Grounding
# --------------------------------------------------------------------------

class GroundingVerdict(BaseModel):
    supported: bool = Field(description="Is every factual claim backed by a step result")
    unsupported_claims: list[str] = Field(default_factory=list)
    corrections: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------
# Memory
# --------------------------------------------------------------------------

class TopicState(BaseModel):
    topic_id: str
    label: str = Field(description="Human readable topic, e.g. 'site:NBI intermittent drops'")
    entities: list[str] = Field(default_factory=list)
    turn_started: int


class MemorySnapshot(BaseModel):
    session_id: str
    turn: int
    current_topic: TopicState | None = None
    recent_turns: list[dict] = Field(default_factory=list)
    archived_summaries: list[str] = Field(default_factory=list)
    context_tokens: int = 0
    topic_changes: int = 0


# --------------------------------------------------------------------------
# API
# --------------------------------------------------------------------------

class ChatRequest(BaseModel):
    message: str
    session_id: str = "default"
    stream: bool = True
    model: str | None = Field(
        default=None, description="Override the model, e.g. the fast model during labs"
    )


class Usage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    latency_ms: int = 0
    tokens_per_second: float = 0.0
    llm_calls: int = 0
    tool_calls: int = 0
