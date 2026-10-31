"""临时验证 app 层路由的端到端行为（用 TestClient，不依赖真实 LLM）。"""

from fastapi.testclient import TestClient

from deerflow_simple.app.app import create_app
from deerflow_simple.config import SimpleConfig

# 最小配置：关闭所有可选子系统，避免 build_agent 时引入重依赖
config = SimpleConfig(
    sandbox_enabled=False,
    subagents_enabled=False,
    summarization_enabled=False,
    memory_enabled=False,
)
app = create_app(config)
client = TestClient(app)


def test_health() -> None:
    r = client.get("/health")
    print("GET /health ->", r.status_code, r.json())
    assert r.status_code == 200


def test_openapi_has_runs() -> None:
    paths = app.openapi()["paths"]
    expected = [
        "/api/runs",
        "/api/runs/wait",
        "/api/runs/stream",
        "/api/threads/{thread_id}/runs",
        "/api/threads/{thread_id}/runs/{run_id}",
        "/api/threads/{thread_id}/runs/{run_id}/cancel",
    ]
    for p in expected:
        assert p in paths, f"missing {p}"
    print("openapi 包含全部 6 个 run 路由")


def test_create_and_cancel() -> None:
    # 创建后台 run（立即返回）
    r = client.post("/api/runs", json={"message": "你好", "thread_id": "t1"})
    print("POST /api/runs ->", r.status_code, r.json())
    assert r.status_code == 200
    run_id = r.json()["run_id"]

    # 查询 run
    r2 = client.get(f"/api/threads/t1/runs/{run_id}")
    print("GET run ->", r2.status_code, r2.json())
    assert r2.status_code == 200

    # 取消 run
    r3 = client.post(f"/api/threads/t1/runs/{run_id}/cancel")
    print("POST cancel ->", r3.status_code, r3.json())


def test_reject_conflict() -> None:
    # 同线程并发：第一个 pending，第二个应 409
    r1 = client.post("/api/runs", json={"message": "任务A", "thread_id": "t2"})
    r2 = client.post("/api/runs", json={"message": "任务B", "thread_id": "t2"})
    print("第一个 ->", r1.status_code, "第二个 ->", r2.status_code, r2.json())
    assert r1.status_code == 200
    assert r2.status_code == 409


test_health()
test_openapi_has_runs()
test_create_and_cancel()
test_reject_conflict()
print("ALL APP TESTS OK")
