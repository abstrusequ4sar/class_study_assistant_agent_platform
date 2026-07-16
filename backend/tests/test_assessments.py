from datetime import date, timedelta

from .conftest import create_course, register_and_login


def _upload_text(client, headers, course_id):
    content = (
        "第一章 数据结构基础。线性表是具有相同数据类型的有限序列。\n"
        "第二章 栈与队列。栈遵循后进先出原则，队列遵循先进先出原则。\n"
        "第三章 树结构。二叉树的每个结点最多有两个孩子。\n"
    )
    response = client.post(
        f"/api/courses/{course_id}/materials",
        files={"file": ("阶段复习.txt", content.encode(), "text/plain")},
        headers=headers,
    )
    assert response.status_code == 201, response.text


def test_dynamic_course_priority_reacts_to_task_state(client, auth_headers):
    urgent_id = create_course(client, auth_headers, "临近期末课程")
    normal_id = create_course(client, auth_headers, "常规课程")
    task = client.post(
        "/api/tasks",
        json={
            "course_id": urgent_id,
            "title": "已逾期复习任务",
            "due_date": (date.today() - timedelta(days=1)).isoformat(),
        },
        headers=auth_headers,
    ).json()

    priorities = client.get("/api/courses/priorities", headers=auth_headers)
    assert priorities.status_code == 200, priorities.text
    rows = priorities.json()
    urgent = next(item for item in rows if item["course_id"] == urgent_id)
    normal = next(item for item in rows if item["course_id"] == normal_id)
    assert urgent["rank"] == 1
    assert urgent["score"] > normal["score"]
    assert urgent["metrics"]["overdue_tasks"] == 1
    assert any("逾期" in reason for reason in urgent["reasons"])
    before = urgent["score"]

    client.put(
        f"/api/tasks/{task['id']}",
        json={"completed": True},
        headers=auth_headers,
    )
    refreshed = client.get("/api/courses/priorities", headers=auth_headers).json()
    urgent_after = next(item for item in refreshed if item["course_id"] == urgent_id)
    assert urgent_after["score"] < before
    assert urgent_after["metrics"]["overdue_tasks"] == 0
    assert urgent_after["metrics"]["task_completion_rate"] == 100.0


def test_stage_quiz_submission_updates_learning_progress(client, auth_headers):
    course_id = create_course(client, auth_headers, "数据结构测验")
    _upload_text(client, auth_headers, course_id)

    created = client.post(
        f"/api/courses/{course_id}/quizzes",
        json={"stage": "第一阶段", "focus": "栈、队列与树", "question_count": 3},
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    quiz = created.json()
    assert quiz["agent_mode"] == "fallback"
    assert quiz["question_count"] == 3
    assert len(quiz["questions"]) == 3
    assert "correct_index" not in created.text

    incomplete = client.post(
        f"/api/quizzes/{quiz['id']}/submit",
        json={"answers": [0]},
        headers=auth_headers,
    )
    assert incomplete.status_code == 422

    submitted = client.post(
        f"/api/quizzes/{quiz['id']}/submit",
        json={"answers": [0, 1, 2]},
        headers=auth_headers,
    )
    assert submitted.status_code == 200, submitted.text
    result = submitted.json()
    assert result["score"] == 100.0
    assert result["correct_count"] == 3
    assert all(item["source"]["material_id"] for item in result["results"])
    assert all(item["source"]["excerpt"] for item in result["results"])

    progress = client.get(
        f"/api/courses/{course_id}/learning-progress", headers=auth_headers
    )
    assert progress.status_code == 200
    body = progress.json()
    assert body["attempts"] == 1
    assert body["latest_score"] == 100.0
    assert body["best_score"] == 100.0
    assert body["mastery_level"] == "掌握优秀"
    assert len(body["trend"]) == 1

    priorities = client.get("/api/courses/priorities", headers=auth_headers).json()
    priority = next(item for item in priorities if item["course_id"] == course_id)
    assert priority["metrics"]["latest_quiz_score"] == 100.0


def test_quiz_requires_material_and_is_isolated(client):
    owner = register_and_login(client, "quiz_owner")
    intruder = register_and_login(client, "quiz_intruder")
    empty_course = create_course(client, owner, "暂无资料")
    response = client.post(
        f"/api/courses/{empty_course}/quizzes",
        json={"stage": "第一阶段", "question_count": 3},
        headers=owner,
    )
    assert response.status_code == 422

    course_id = create_course(client, owner, "有资料课程")
    _upload_text(client, owner, course_id)
    quiz = client.post(
        f"/api/courses/{course_id}/quizzes",
        json={"stage": "章节检查", "question_count": 3},
        headers=owner,
    ).json()
    assert client.get(f"/api/quizzes/{quiz['id']}", headers=intruder).status_code == 404
    assert (
        client.post(
            f"/api/quizzes/{quiz['id']}/submit",
            json={"answers": [0, 1, 2]},
            headers=intruder,
        ).status_code
        == 404
    )
    assert client.delete(f"/api/quizzes/{quiz['id']}", headers=owner).status_code == 204


def test_priority_only_returns_owned_courses(client):
    user_a = register_and_login(client, "priority_a")
    user_b = register_and_login(client, "priority_b")
    course_a = create_course(client, user_a, "A 的课程")
    create_course(client, user_b, "B 的课程")
    rows = client.get("/api/courses/priorities", headers=user_a).json()
    assert [row["course_id"] for row in rows] == [course_a]
