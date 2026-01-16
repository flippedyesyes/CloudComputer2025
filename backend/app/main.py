# 创建 FastAPI app
# 注册所有 router
# 启动服务

from fastapi import FastAPI
from app.jobs.queue import queue
from app.api import materials, quizzes, attempts, mistakes, tutor

app = FastAPI(title="Learning Evaluation Agent")

app.include_router(materials.router, prefix="/materials")
app.include_router(quizzes.router, prefix="/quizzes")
app.include_router(attempts.router, prefix="/attempts")
app.include_router(mistakes.router, prefix="/mistakes")
app.include_router(tutor.router, prefix="/tutor")

@app.get("/health")
async def health_check():
    return {"status": "ok"}

@app.post("/test-job")
async def test_job():
    job = queue.enqueue("worker.hello_job", "Cloud Native")
    return {
        "job_id": job.id,
        "status": "queued"
    }
