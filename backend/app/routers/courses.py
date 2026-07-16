"""课程管理 CRUD 与知识点整理。"""
import json
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import (
    Conversation,
    Course,
    Material,
    MaterialChunk,
    Message,
    QuizAttempt,
    StageQuiz,
    StudyPlan,
    Task,
    User,
)
from ..schemas.chat import KnowledgeSummaryOut
from ..schemas.course import CourseCreate, CourseOut, CourseUpdate
from ..schemas.assessment import CoursePriorityOut
from ..services import agent
from ..services.priority import calculate_course_priorities
from ..services.retrieval import ordered_course_chunks
from ..services.security import get_current_user

router = APIRouter(prefix="/api/courses", tags=["courses"])
logger = logging.getLogger(__name__)


def get_owned_course(
    course_id: int,
    current: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Course:
    course = db.get(Course, course_id)
    if course is None or course.owner_id != current.id:
        raise HTTPException(status_code=404, detail="课程不存在")
    return course


@router.post("", response_model=CourseOut, status_code=status.HTTP_201_CREATED)
def create_course(
    payload: CourseCreate,
    current: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    course = Course(owner_id=current.id, **payload.model_dump())
    db.add(course)
    db.commit()
    db.refresh(course)
    return course


@router.get("", response_model=list[CourseOut])
def list_courses(
    current: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    return (
        db.execute(
            select(Course)
            .where(Course.owner_id == current.id)
            .order_by(Course.created_at.desc())
        )
        .scalars()
        .all()
    )


@router.get("/priorities", response_model=list[CoursePriorityOut])
def list_course_priorities(
    current: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    """根据任务、计划与最近测验结果实时计算课程学习优先级。"""
    return calculate_course_priorities(db, current.id)


@router.get("/{course_id}", response_model=CourseOut)
def get_course(course: Course = Depends(get_owned_course)):
    return course


@router.put("/{course_id}", response_model=CourseOut)
def update_course(
    payload: CourseUpdate,
    course: Course = Depends(get_owned_course),
    db: Session = Depends(get_db),
):
    for key, value in payload.model_dump(exclude_none=True).items():
        setattr(course, key, value)
    db.commit()
    db.refresh(course)
    return course


@router.delete("/{course_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_course(
    course: Course = Depends(get_owned_course), db: Session = Depends(get_db)
):
    # 资料与对话属于课程本身，随课程删除；计划和任务属于用户，保留但解除课程关联。
    stored_paths = db.execute(
        select(Material.stored_path).where(Material.course_id == course.id)
    ).scalars().all()
    conv_ids = db.execute(
        select(Conversation.id).where(Conversation.course_id == course.id)
    ).scalars().all()
    quiz_ids = db.execute(
        select(StageQuiz.id).where(StageQuiz.course_id == course.id)
    ).scalars().all()
    if quiz_ids:
        db.query(QuizAttempt).filter(QuizAttempt.quiz_id.in_(quiz_ids)).delete(
            synchronize_session=False
        )
        db.query(StageQuiz).filter(StageQuiz.id.in_(quiz_ids)).delete(
            synchronize_session=False
        )
    if conv_ids:
        db.query(Message).filter(Message.conversation_id.in_(conv_ids)).delete(
            synchronize_session=False
        )
        db.query(Conversation).filter(Conversation.id.in_(conv_ids)).delete(
            synchronize_session=False
        )
    db.query(MaterialChunk).filter(MaterialChunk.course_id == course.id).delete(
        synchronize_session=False
    )
    db.query(Material).filter(Material.course_id == course.id).delete(
        synchronize_session=False
    )
    db.query(Task).filter(Task.course_id == course.id).update(
        {Task.course_id: None}, synchronize_session=False
    )
    db.query(StudyPlan).filter(StudyPlan.course_id == course.id).update(
        {StudyPlan.course_id: None}, synchronize_session=False
    )
    db.delete(course)
    db.commit()
    for stored_path in stored_paths:
        try:
            Path(stored_path).unlink(missing_ok=True)
        except OSError as exc:
            logger.warning("课程删除后清理上传文件失败 %s: %s", stored_path, exc)


@router.post("/{course_id}/knowledge-summary", response_model=KnowledgeSummaryOut)
def knowledge_summary(
    course: Course = Depends(get_owned_course), db: Session = Depends(get_db)
):
    """根据课程资料自动提取重点知识点，生成复习提纲（高级功能）。"""
    chunks = ordered_course_chunks(db, course.id)
    result = agent.summarize_knowledge(course.name, chunks)
    return KnowledgeSummaryOut(
        course_id=course.id,
        summary=result["summary"],
        agent_mode=result["agent_mode"],
        sources=result["sources"],
    )


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("/{course_id}/knowledge-summary/stream")
def knowledge_summary_stream(
    course: Course = Depends(get_owned_course), db: Session = Depends(get_db)
):
    """流式整理全部资料：立即返回批次数，并持续报告并行处理进度。"""
    chunks = ordered_course_chunks(db, course.id)
    course_name = course.name

    def event_stream():
        for event, data in agent.summarize_knowledge_events(course_name, chunks):
            yield _sse(event, data)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
