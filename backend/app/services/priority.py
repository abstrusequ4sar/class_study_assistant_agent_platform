"""课程动态优先级：把任务、计划与测验结果汇总为可解释的实时评分。"""
from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Course, QuizAttempt, StageQuiz, StudyPlan, Task


def _deadline_pressure(days: int | None) -> float:
    if days is None:
        return 0.0
    if days <= 0:
        return 15.0
    if days <= 3:
        return 12.0
    if days <= 7:
        return 9.0
    if days <= 14:
        return 5.0
    return 2.0


def calculate_course_priorities(db: Session, user_id: int) -> list[dict]:
    """每次请求都从最新任务/计划/测验记录重算，不持久化易过期的分数。"""
    courses = db.execute(
        select(Course)
        .where(Course.owner_id == user_id)
        .order_by(Course.created_at.desc(), Course.id.desc())
    ).scalars().all()
    if not courses:
        return []

    course_ids = {course.id for course in courses}
    tasks_by_course: dict[int, list[Task]] = defaultdict(list)
    tasks = db.execute(
        select(Task).where(Task.user_id == user_id, Task.course_id.in_(course_ids))
    ).scalars().all()
    for task in tasks:
        if task.course_id is not None:
            tasks_by_course[task.course_id].append(task)

    plans_by_course: dict[int, list[StudyPlan]] = defaultdict(list)
    plans = db.execute(
        select(StudyPlan).where(
            StudyPlan.user_id == user_id, StudyPlan.course_id.in_(course_ids)
        )
    ).scalars().all()
    for plan in plans:
        if plan.course_id is not None:
            plans_by_course[plan.course_id].append(plan)

    quizzes = db.execute(
        select(StageQuiz).where(
            StageQuiz.user_id == user_id, StageQuiz.course_id.in_(course_ids)
        )
    ).scalars().all()
    quiz_course = {quiz.id: quiz.course_id for quiz in quizzes}
    latest_attempt_by_course: dict[int, QuizAttempt] = {}
    if quiz_course:
        attempts = db.execute(
            select(QuizAttempt)
            .where(
                QuizAttempt.user_id == user_id,
                QuizAttempt.quiz_id.in_(quiz_course),
            )
            .order_by(QuizAttempt.created_at, QuizAttempt.id)
        ).scalars().all()
        for attempt in attempts:
            latest_attempt_by_course[quiz_course[attempt.quiz_id]] = attempt

    today = date.today()
    rows = []
    for course in courses:
        course_tasks = tasks_by_course[course.id]
        pending = [task for task in course_tasks if not task.completed]
        dated_pending = [task for task in pending if task.due_date is not None]
        overdue = [task for task in dated_pending if task.due_date < today]
        due_today = [task for task in dated_pending if task.due_date == today]
        due_3 = [
            task
            for task in dated_pending
            if today < task.due_date <= today + timedelta(days=3)
        ]
        due_7 = [
            task
            for task in dated_pending
            if today + timedelta(days=3) < task.due_date <= today + timedelta(days=7)
        ]

        urgency = min(
            45.0,
            len(overdue) * 12.0
            + len(due_today) * 10.0
            + len(due_3) * 6.0
            + len(due_7) * 3.0,
        )
        workload = min(20.0, len(pending) * 4.0)
        completion_rate = (
            round(
                100.0
                * sum(1 for task in course_tasks if task.completed)
                / len(course_tasks),
                1,
            )
            if course_tasks
            else None
        )
        completion_gap = (
            round((100.0 - completion_rate) * 0.1, 1)
            if completion_rate is not None
            else 4.0
        )

        latest_attempt = latest_attempt_by_course.get(course.id)
        latest_score = round(latest_attempt.score, 1) if latest_attempt else None
        mastery_gap = (
            round((100.0 - latest_score) * 0.2, 1)
            if latest_score is not None
            else 8.0
        )

        plan_deadlines = [plan.deadline for plan in plans_by_course[course.id]]
        nearest_plan = min(plan_deadlines) if plan_deadlines else None
        plan_pressure = _deadline_pressure(
            (nearest_plan - today).days if nearest_plan is not None else None
        )
        all_deadlines = [task.due_date for task in dated_pending] + plan_deadlines
        next_deadline = min(all_deadlines) if all_deadlines else None

        score = round(
            min(
                100.0,
                urgency + workload + plan_pressure + completion_gap + mastery_gap,
            ),
            1,
        )
        if score >= 60:
            level, level_label = "high", "优先处理"
        elif score >= 30:
            level, level_label = "medium", "重点关注"
        else:
            level, level_label = "low", "常规推进"

        reasons = []
        if overdue:
            reasons.append(f"{len(overdue)} 项任务已逾期")
        if due_today:
            reasons.append(f"{len(due_today)} 项任务今天到期")
        if due_3:
            reasons.append(f"{len(due_3)} 项任务将在 3 天内到期")
        if latest_score is None:
            reasons.append("尚未测验，掌握度待检测")
        elif latest_score < 60:
            reasons.append(f"最近测验 {latest_score:g} 分，需要补强")
        elif latest_score < 80:
            reasons.append(f"最近测验 {latest_score:g} 分，仍有提升空间")
        if pending and len(reasons) < 3:
            reasons.append(f"还有 {len(pending)} 项未完成任务")
        if not reasons:
            reasons.append("暂无临期压力，保持常规学习节奏")

        progress_values = []
        if completion_rate is not None:
            progress_values.append(completion_rate)
        if latest_score is not None:
            progress_values.append(latest_score)
        progress = round(sum(progress_values) / len(progress_values), 1) if progress_values else 0.0

        rows.append(
            {
                "course_id": course.id,
                "course_name": course.name,
                "score": score,
                "level": level,
                "level_label": level_label,
                "progress": progress,
                "reasons": reasons[:3],
                "metrics": {
                    "pending_tasks": len(pending),
                    "overdue_tasks": len(overdue),
                    "due_today": len(due_today),
                    "due_in_3_days": len(due_3),
                    "due_in_7_days": len(due_7),
                    "task_completion_rate": completion_rate,
                    "latest_quiz_score": latest_score,
                    "next_deadline": next_deadline.isoformat() if next_deadline else None,
                },
                "components": {
                    "urgency": urgency,
                    "workload": workload,
                    "plan_pressure": plan_pressure,
                    "completion_gap": completion_gap,
                    "mastery_gap": mastery_gap,
                },
            }
        )

    rows.sort(
        key=lambda row: (
            -row["score"],
            row["metrics"]["next_deadline"] or "9999-12-31",
            row["course_id"],
        )
    )
    for rank, row in enumerate(rows, start=1):
        row["rank"] = rank
    return rows
