from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class StageQuiz(Base):
    """基于课程资料生成的阶段性测验。题目答案仅保存在服务端 JSON 中。"""

    __tablename__ = "stage_quizzes"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), index=True)
    title: Mapped[str] = mapped_column(String(256))
    stage: Mapped[str] = mapped_column(String(128), default="当前学习阶段")
    focus: Mapped[str] = mapped_column(String(256), default="")
    questions_json: Mapped[str] = mapped_column(Text, default="[]")
    agent_mode: Mapped[str] = mapped_column(String(16), default="fallback")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class QuizAttempt(Base):
    """一次测验提交，用于成绩趋势与学习进度检测。"""

    __tablename__ = "quiz_attempts"

    id: Mapped[int] = mapped_column(primary_key=True)
    quiz_id: Mapped[int] = mapped_column(ForeignKey("stage_quizzes.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    answers_json: Mapped[str] = mapped_column(Text, default="[]")
    feedback_json: Mapped[str] = mapped_column(Text, default="[]")
    score: Mapped[float] = mapped_column(Float, default=0.0)
    correct_count: Mapped[int] = mapped_column(Integer, default=0)
    total_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
