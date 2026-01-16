from fastapi import FastAPI
from app.jobs.queue import queue

app = FastAPI()

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
