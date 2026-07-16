from datetime import datetime

from pydantic import BaseModel, Field


class QuizGenerateRequest(BaseModel):
    stage: str = Field(default="当前学习阶段", min_length=1, max_length=128)
    focus: str = Field(default="", max_length=256)
    question_count: int = Field(default=5, ge=3, le=10)


class QuizQuestionOut(BaseModel):
    id: int
    prompt: str
    options: list[str]
    topic: str


class QuizAttemptBrief(BaseModel):
    id: int
    score: float
    correct_count: int
    total_count: int
    created_at: datetime


class QuizOut(BaseModel):
    id: int
    course_id: int
    title: str
    stage: str
    focus: str
    question_count: int
    questions: list[QuizQuestionOut]
    agent_mode: str
    created_at: datetime
    latest_attempt: QuizAttemptBrief | None = None


class QuizSubmitRequest(BaseModel):
    answers: list[int] = Field(min_length=1, max_length=10)


class QuizQuestionResult(BaseModel):
    question_id: int
    prompt: str
    submitted_index: int
    correct_index: int
    correct: bool
    explanation: str
    topic: str
    source: dict


class QuizAttemptOut(QuizAttemptBrief):
    quiz_id: int
    results: list[QuizQuestionResult]
    weak_topics: list[str]


class LearningProgressOut(BaseModel):
    course_id: int
    attempts: int
    latest_score: float | None
    best_score: float | None
    average_score: float | None
    mastery_level: str
    task_completion_rate: float | None
    combined_progress: float
    weak_topics: list[str]
    trend: list[QuizAttemptBrief]


class PriorityMetrics(BaseModel):
    pending_tasks: int
    overdue_tasks: int
    due_today: int
    due_in_3_days: int
    due_in_7_days: int
    task_completion_rate: float | None
    latest_quiz_score: float | None
    next_deadline: str | None


class PriorityComponents(BaseModel):
    urgency: float
    workload: float
    plan_pressure: float
    completion_gap: float
    mastery_gap: float


class CoursePriorityOut(BaseModel):
    course_id: int
    course_name: str
    rank: int
    score: float
    level: str
    level_label: str
    progress: float
    reasons: list[str]
    metrics: PriorityMetrics
    components: PriorityComponents
