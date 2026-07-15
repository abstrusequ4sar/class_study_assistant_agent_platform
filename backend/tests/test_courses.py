import re
import threading
import time

from .conftest import create_course, register_and_login


def test_course_crud(client, auth_headers):
    course_id = create_course(client, auth_headers, "数据结构")

    resp = client.get("/api/courses", headers=auth_headers)
    assert resp.status_code == 200
    assert any(c["id"] == course_id for c in resp.json())

    resp = client.put(
        f"/api/courses/{course_id}",
        json={"teacher": "李老师"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["teacher"] == "李老师"

    assert (
        client.delete(f"/api/courses/{course_id}", headers=auth_headers).status_code
        == 204
    )
    assert (
        client.get(f"/api/courses/{course_id}", headers=auth_headers).status_code
        == 404
    )


def test_course_isolated_between_users(client):
    headers_a = register_and_login(client, "owner")
    headers_b = register_and_login(client, "intruder")
    course_id = create_course(client, headers_a)
    assert (
        client.get(f"/api/courses/{course_id}", headers=headers_b).status_code == 404
    )


def test_knowledge_summary_without_materials(client, auth_headers):
    course_id = create_course(client, auth_headers)
    resp = client.post(
        f"/api/courses/{course_id}/knowledge-summary", headers=auth_headers
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["agent_mode"] == "fallback"
    assert body["summary"]

    streamed = client.post(
        f"/api/courses/{course_id}/knowledge-summary/stream", headers=auth_headers
    )
    assert streamed.status_code == 200
    assert "event: meta" in streamed.text
    assert "event: done" in streamed.text


def test_knowledge_summary_covers_all_chunks_in_natural_chapter_order(
    client, auth_headers
):
    """不能只取前 30 个切片；即使后上传第一章，也应排在第十章前。"""
    course_id = create_course(client, auth_headers)
    chapter10 = "\n".join(
        f"第十章 知识点 {index}：" + "后续章节内容" * 70 for index in range(36)
    )
    uploads = (
        ("Chap10.txt", chapter10),
        ("Chap1.txt", "第一章 基础概念。" + "基础内容" * 180),
    )
    for filename, content in uploads:
        resp = client.post(
            f"/api/courses/{course_id}/materials",
            files={"file": (filename, content.encode(), "text/plain")},
            headers=auth_headers,
        )
        assert resp.status_code == 201, resp.text

    resp = client.post(
        f"/api/courses/{course_id}/knowledge-summary", headers=auth_headers
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["sources"]) > 30
    assert body["summary"].index("《Chap1.txt》") < body["summary"].index("《Chap10.txt》")
    assert body["sources"][0]["material_name"] == "Chap1.txt"
    assert body["sources"][-1]["material_name"] == "Chap10.txt"


def test_knowledge_summary_batches_every_chunk_with_stable_global_citations(monkeypatch):
    from app.services import agent
    from app.services.retrieval import RetrievedChunk

    chunks = [
        RetrievedChunk(1, 1, "Chap1.txt", "第一章-A", 0),
        RetrievedChunk(2, 1, "Chap1.txt", "第一章-B", 0),
        RetrievedChunk(3, 1, "Chap1.txt", "第一章-C", 0),
        RetrievedChunk(4, 2, "Chap2.txt", "第二章-D", 0),
    ]
    calls = []

    def fake_complete(system, user_content, **kwargs):
        del system, kwargs
        calls.append(user_content)
        return f"## 小节{len(calls)}\n- 已整理"

    monkeypatch.setattr(agent, "complete", fake_complete)
    monkeypatch.setattr(agent, "_SUMMARY_BATCH_CHARS", 12)
    monkeypatch.setattr(agent, "_SUMMARY_BATCH_CHUNKS", 2)
    monkeypatch.setattr(agent, "_SUMMARY_MAX_WORKERS", 1)

    result = agent.summarize_knowledge("测试课程", chunks)
    combined_context = "\n".join(calls)
    assert result["agent_mode"] == "llm"
    assert len(calls) == 3
    assert all(chunk.content in combined_context for chunk in chunks)
    assert [source["index"] for source in result["sources"]] == [1, 2, 3, 4]
    assert [int(value) for value in re.findall(r"\[(\d+)\] 来源", combined_context)] == [
        1,
        2,
        3,
        4,
    ]
    assert (
        result["summary"].index("小节1")
        < result["summary"].index("小节2")
        < result["summary"].index("小节3")
    )


def test_knowledge_summary_batches_run_concurrently_and_report_progress(monkeypatch):
    from app.services import agent
    from app.services.retrieval import RetrievedChunk

    chunks = [
        RetrievedChunk(index, index, f"Chap{index}.txt", f"第{index}章", 0)
        for index in range(1, 4)
    ]
    lock = threading.Lock()
    active = 0
    max_active = 0

    def fake_complete(system, user_content, **kwargs):
        nonlocal active, max_active
        del system, kwargs
        with lock:
            active += 1
            max_active = max(max_active, active)
        time.sleep(0.05)
        with lock:
            active -= 1
        chapter = re.search(r"第(\d+)章", user_content).group(1)
        return f"### 第{chapter}章\n- 已整理"

    monkeypatch.setattr(agent, "complete", fake_complete)
    monkeypatch.setattr(agent, "_SUMMARY_MAX_WORKERS", 3)

    events = list(agent.summarize_knowledge_events("测试课程", chunks))
    assert max_active == 3
    assert events[0] == (
        "meta",
        {"total": 3, "materials": 3, "fragments": 3},
    )
    progress = [data for event, data in events if event == "progress"]
    assert [item["completed"] for item in progress] == [1, 2, 3]
    done = next(data for event, data in events if event == "done")
    assert done["summary"].index("《Chap1.txt》") < done["summary"].index("《Chap2.txt》")
    assert done["summary"].index("《Chap2.txt》") < done["summary"].index("《Chap3.txt》")


def test_delete_course_cleans_files_and_detaches_user_data(client, auth_headers):
    """删除课程应清理专属资源，但保留并解除计划/任务的课程关联。"""
    from datetime import date, timedelta
    from pathlib import Path

    from app.database import SessionLocal
    from app.models import Material

    course_id = create_course(client, auth_headers, "待删除课程")
    uploaded = client.post(
        f"/api/courses/{course_id}/materials",
        files={"file": ("cleanup.txt", "应随课程删除".encode(), "text/plain")},
        headers=auth_headers,
    ).json()
    db = SessionLocal()
    try:
        stored_path = Path(db.get(Material, uploaded["id"]).stored_path)
    finally:
        db.close()
    assert stored_path.exists()

    plan = client.post(
        "/api/plans",
        json={
            "course_id": course_id,
            "goal": "保留这份计划",
            "deadline": (date.today() + timedelta(days=2)).isoformat(),
            "daily_hours": 1,
        },
        headers=auth_headers,
    ).json()
    manual_task = client.post(
        "/api/tasks",
        json={"course_id": course_id, "title": "保留这条任务"},
        headers=auth_headers,
    ).json()

    assert client.delete(f"/api/courses/{course_id}", headers=auth_headers).status_code == 204
    assert not stored_path.exists()

    plans = client.get("/api/plans", headers=auth_headers).json()
    assert next(item for item in plans if item["id"] == plan["id"])["course_id"] is None
    tasks = client.get("/api/tasks", headers=auth_headers).json()
    assert next(item for item in tasks if item["id"] == manual_task["id"])["course_id"] is None
    assert all(task["course_id"] is None for task in tasks if task["plan_id"] == plan["id"])
