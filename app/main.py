from fastapi import FastAPI, BackgroundTasks, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from contextlib import asynccontextmanager
import asyncio
import uvicorn
from app.scheduler import start_scheduler, shutdown_scheduler
from app.routes import posts, analytics, content
from app.database import init_db

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    scheduler_task = asyncio.create_task(start_scheduler())
    yield
    await shutdown_scheduler()
    scheduler_task.cancel()

app = FastAPI(
    title="Threads Scheduler",
    description="Automated Threads post scheduler with AI analytics",
    version="1.0.0",
    lifespan=lifespan
)

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

app.include_router(posts.router, prefix="/api/posts", tags=["posts"])
app.include_router(analytics.router, prefix="/api/analytics", tags=["analytics"])
app.include_router(content.router, prefix="/api/content", tags=["content"])

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    return templates.TemplateResponse("dashboard.html", {"request": request})

@app.get("/health")
async def health():
    return {"status": "ok", "message": "Threads Scheduler is running"}

if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("app.main:app", host="0.0.0.0", port=port, reload=True)
