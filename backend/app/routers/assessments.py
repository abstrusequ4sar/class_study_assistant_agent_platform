"""阶段性测验：资料命题、自动批改、学习进度与薄弱点分析。"""
import json
from collections import Counter

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Course, QuizAttempt, StageQuiz, Task, User
from ..schemas.assessment import (
    LearningProgressOut,
    QuizAttemptBrief,
    QuizAttemptOut,
    QuizGenerateRequest,
    QuizOut,
    QuizQuestionOut,
    QuizSubmitRequest,
)
from ..services import agent
from ..services.retrieval import ordered_course_chunks
from ..services.security import get_current_user

router = APIRouter(prefix="/api", tags=["assessments"])


def _owned_course(course_id: int, user_id: int, db: Session) -> Course:
    course = db.get(Course, course_id)
    if course is None or course.owner_id != user_id:
        raise HTTPException(status_code=404, detail="课程不存在")
    return course


def _owned_quiz(quiz_id: int, user_id: int, db: Session) -> StageQuiz:
    quiz = db.get(StageQuiz, quiz_id)
    if quiz is None or quiz.user_id != user_id:
        raise HTTPException(status_code=404, detail="测验不存在")
    return quiz


def _load_list(raw: str) -> list:
    try:
        value = json.loads(raw or "[]")
    except json.JSONDecodeError:
        return []
    return value if isinstance(value, list) else []


def _attempt_brief(attempt: QuizAttempt) -> QuizAttemptBrief:
    return QuizAttemptBrief(
        id=attempt.id,
        score=round(attempt.score, 1),
        correct_count=attempt.correct_count,
        total_count=attempt.total_count,
        created_at=attempt.created_at,
    )


def _quiz_out(quiz: StageQuiz, db: Session) -> QuizOut:
    questions = _load_list(quiz.questions_json)
    latest = db.execute(
        select(QuizAttempt)
        .where(QuizAttempt.quiz_id == quiz.id, QuizAttempt.user_id == quiz.user_id)
        .order_by(QuizAttempt.created_at.desc(), QuizAttempt.id.desc())
        .limit(1)
    ).scalar_one_or_none()
    return QuizOut(
        id=quiz.id,
        course_id=quiz.course_id,
        title=quiz.title,
        stage=quiz.stage,
        focus=quiz.focus,
        question_count=len(questions),
        questions=[
            QuizQuestionOut(
                id=int(item.get("id", index)),
                prompt=str(item.get("prompt", "")),
                options=[str(option) for option in item.get("options", [])],
                topic=str(item.get("topic", "综合知识")),
            )
            for index, item in enumerate(questions, start=1)
        ],
        agent_mode=quiz.agent_mode,
        created_at=quiz.created_at,
        latest_attempt=_attempt_brief(latest) if latest else None,
    )


@router.post(
    "/courses/{course_id}/quizzes",
    response_model=QuizOut,
    status_code=status.HTTP_201_CREATED,
)
def generate_quiz(
    course_id: int,
    payload: QuizGenerateRequest,
    current: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    course = _owned_course(course_id, current.id, db)
    chunks = ordered_course_chunks(db, course.id)
    if not chunks:
        raise HTTPException(
            status_code=422,
            detail="课程暂无可命题的文本资料，请先上传课件、笔记或教材内容",
        )
    result = agent.generate_stage_quiz(
        course.name,
        payload.stage.strip(),
        payload.focus.strip(),
        chunks,
        payload.question_count,
    )
    quiz = StageQuiz(
        user_id=current.id,
        course_id=course.id,
        title=f"{payload.stage.strip()}测验"[:256],
        stage=payload.stage.strip(),
        focus=payload.focus.strip(),
        questions_json=json.dumps(result["questions"], ensure_ascii=False),
        agent_mode=result["agent_mode"],
    )
    db.add(quiz)
    db.commit()
    db.refresh(quiz)
    return _quiz_out(quiz, db)


@router.get("/courses/{course_id}/quizzes", response_model=list[QuizOut])
def list_quizzes(
    course_id: int,
    current: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _owned_course(course_id, current.id, db)
    quizzes = db.execute(
        select(StageQuiz)
        .where(StageQuiz.course_id == course_id, StageQuiz.user_id == current.id)
        .order_by(StageQuiz.created_at.desc(), StageQuiz.id.desc())
    ).scalars().all()
    return [_quiz_out(quiz, db) for quiz in quizzes]


@router.get("/quizzes/{quiz_id}", response_model=QuizOut)
def get_quiz(
    quiz_id: int,
    current: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _quiz_out(_owned_quiz(quiz_id, current.id, db), db)


@router.post("/quizzes/{quiz_id}/submit", response_model=QuizAttemptOut)
def submit_quiz(
    quiz_id: int,
    payload: QuizSubmitRequest,
    current: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    quiz = _owned_quiz(quiz_id, current.id, db)
    questions = _load_list(quiz.questions_json)
    if len(payload.answers) != len(questions):
        raise HTTPException(status_code=422, detail="请完成全部题目后再提交")
    if any(answer < 0 or answer > 3 for answer in payload.answers):
        raise HTTPException(status_code=422, detail="答案选项超出有效范围")

    results = []
    correct_count = 0
    weak_topics = []
    for question, submitted in zip(questions, payload.answers, strict=True):
        correct_index = int(question.get("correct_index", -1))
        is_correct = submitted == correct_index
        correct_count += int(is_correct)
        topic = str(question.get("topic", "综合知识"))
        if not is_correct and topic not in weak_topics:
            weak_topics.append(topic)
        results.append(
            {
                "question_id": int(question.get("id", len(results) + 1)),
                "prompt": str(question.get("prompt", "")),
                "submitted_index": submitted,
                "correct_index": correct_index,
                "correct": is_correct,
                "explanation": str(question.get("explanation", "")),
                "topic": topic,
                "source": question.get("source", {}),
            }
        )
    total = len(questions)
    score = round(100.0 * correct_count / total, 1) if total else 0.0
    attempt = QuizAttempt(
        quiz_id=quiz.id,
        user_id=current.id,
        answers_json=json.dumps(payload.answers),
        feedback_json=json.dumps(results, ensure_ascii=False),
        score=score,
        correct_count=correct_count,
        total_count=total,
    )
    db.add(attempt)
    db.commit()
    db.refresh(attempt)
    return QuizAttemptOut(
        **_attempt_brief(attempt).model_dump(),
        quiz_id=quiz.id,
        results=results,
        weak_topics=weak_topics,
    )


@router.get(
    "/courses/{course_id}/learning-progress", response_model=LearningProgressOut
)
def learning_progress(
    course_id: int,
    current: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _owned_course(course_id, current.id, db)
    quiz_ids = db.execute(
        select(StageQuiz.id).where(
            StageQuiz.course_id == course_id, StageQuiz.user_id == current.id
        )
    ).scalars().all()
    attempts = []
    if quiz_ids:
        attempts = db.execute(
            select(QuizAttempt)
            .where(
                QuizAttempt.quiz_id.in_(quiz_ids),
                QuizAttempt.user_id == current.id,
            )
            .order_by(QuizAttempt.created_at, QuizAttempt.id)
        ).scalars().all()

    scores = [attempt.score for attempt in attempts]
    latest_score = round(scores[-1], 1) if scores else None
    if latest_score is None:
        mastery_level = "待检测"
    elif latest_score >= 90:
        mastery_level = "掌握优秀"
    elif latest_score >= 75:
        mastery_level = "掌握良好"
    elif latest_score >= 60:
        mastery_level = "需要巩固"
    else:
        mastery_level = "基础薄弱"

    tasks = db.execute(
        select(Task).where(Task.user_id == current.id, Task.course_id == course_id)
    ).scalars().all()
    task_completion_rate = (
        round(100.0 * sum(1 for task in tasks if task.completed) / len(tasks), 1)
        if tasks
        else None
    )
    progress_values = [value for value in (latest_score, task_completion_rate) if value is not None]
    combined_progress = (
        round(sum(progress_values) / len(progress_values), 1)
        if progress_values
        else 0.0
    )

    weak_counter = Counter()
    for attempt in attempts[-10:]:
        for item in _load_list(attempt.feedback_json):
            if not item.get("correct"):
                weak_counter[str(item.get("topic", "综合知识"))] += 1

    return LearningProgressOut(
        course_id=course_id,
        attempts=len(attempts),
        latest_score=latest_score,
        best_score=round(max(scores), 1) if scores else None,
        average_score=round(sum(scores) / len(scores), 1) if scores else None,
        mastery_level=mastery_level,
        task_completion_rate=task_completion_rate,
        combined_progress=combined_progress,
        weak_topics=[topic for topic, _ in weak_counter.most_common(5)],
        trend=[_attempt_brief(attempt) for attempt in attempts[-10:]],
    )


@router.delete("/quizzes/{quiz_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_quiz(
    quiz_id: int,
    current: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    quiz = _owned_quiz(quiz_id, current.id, db)
    db.query(QuizAttempt).filter(QuizAttempt.quiz_id == quiz.id).delete(
        synchronize_session=False
    )
    db.delete(quiz)
    db.commit()
