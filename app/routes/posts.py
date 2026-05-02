from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from app.database import get_db, Post, PostMetrics
from app.scheduler import generate_weekly_schedule, refresh_post_metrics, publish_post
from app.threads_client import threads_client

router = APIRouter()

class GenerateScheduleRequest(BaseModel):
    week_offset: int = 0

class ManualPostRequest(BaseModel):
    content: str
    scheduled_at: Optional[datetime] = None

class UpdatePostRequest(BaseModel):
    content: Optional[str] = None
    scheduled_at: Optional[datetime] = None
    status: Optional[str] = None

@router.get("/")
async def list_posts(
    status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db)
):
    query = select(Post).order_by(desc(Post.scheduled_at)).limit(limit).offset(offset)
    if status:
        query = query.where(Post.status == status)
    result = await db.execute(query)
    posts = result.scalars().all()

    return [
        {
            "id": p.id,
            "content": p.content,
            "topic": p.topic,
            "post_type": p.post_type,
            "scheduled_at": p.scheduled_at,
            "published_at": p.published_at,
            "status": p.status,
            "threads_post_id": p.threads_post_id,
            "error_message": p.error_message,
            "week_number": p.week_number,
            "hashtags": p.hashtags,
            "metrics": {
                "likes": p.metrics.likes if p.metrics else 0,
                "replies": p.metrics.replies if p.metrics else 0,
                "reposts": p.metrics.reposts if p.metrics else 0,
                "quotes": p.metrics.quotes if p.metrics else 0,
                "views": p.metrics.views if p.metrics else 0,
                "engagement_rate": p.metrics.engagement_rate if p.metrics else 0,
            } if p.metrics else None,
        }
        for p in posts
    ]

@router.post("/generate-schedule")
async def generate_schedule(request: GenerateScheduleRequest, background_tasks: BackgroundTasks):
    """Generate posts for the upcoming week. Run this once per week."""
    background_tasks.add_task(generate_weekly_schedule, request.week_offset)
    return {"message": "Schedule generation started in background", "week_offset": request.week_offset}

@router.post("/generate-schedule/sync")
async def generate_schedule_sync(request: GenerateScheduleRequest):
    """Generate posts synchronously (may be slow)."""
    result = await generate_weekly_schedule(request.week_offset)
    return result

@router.post("/manual")
async def create_manual_post(request: ManualPostRequest, db: AsyncSession = Depends(get_db)):
    """Create a one-off manual post."""
    if len(request.content) > 500:
        raise HTTPException(400, f"Post too long: {len(request.content)} chars (max 500)")

    post = Post(
        content=request.content,
        topic="Manual Post",
        post_type="manual",
        scheduled_at=request.scheduled_at or datetime.utcnow(),
        status="pending" if request.scheduled_at else "pending",
    )
    db.add(post)
    await db.commit()
    await db.refresh(post)
    return {"id": post.id, "message": "Manual post created", "scheduled_at": post.scheduled_at}

@router.post("/{post_id}/publish-now")
async def publish_now(post_id: int, db: AsyncSession = Depends(get_db)):
    """Immediately publish a pending post."""
    result = await db.execute(select(Post).where(Post.id == post_id))
    post = result.scalar_one_or_none()
    if not post:
        raise HTTPException(404, "Post not found")
    if post.status == "published":
        raise HTTPException(400, "Post already published")

    await publish_post(post, db)
    return {"message": "Post published", "threads_post_id": post.threads_post_id, "status": post.status}

@router.patch("/{post_id}")
async def update_post(post_id: int, request: UpdatePostRequest, db: AsyncSession = Depends(get_db)):
    """Update a pending post's content or schedule."""
    result = await db.execute(select(Post).where(Post.id == post_id))
    post = result.scalar_one_or_none()
    if not post:
        raise HTTPException(404, "Post not found")
    if post.status == "published":
        raise HTTPException(400, "Cannot edit published posts")

    if request.content:
        if len(request.content) > 500:
            raise HTTPException(400, "Post too long")
        post.content = request.content
    if request.scheduled_at:
        post.scheduled_at = request.scheduled_at
    if request.status:
        post.status = request.status

    await db.commit()
    return {"message": "Post updated", "id": post.id}

@router.delete("/{post_id}")
async def delete_post(post_id: int, db: AsyncSession = Depends(get_db)):
    """Delete a pending post."""
    result = await db.execute(select(Post).where(Post.id == post_id))
    post = result.scalar_one_or_none()
    if not post:
        raise HTTPException(404, "Post not found")
    if post.status == "published":
        raise HTTPException(400, "Cannot delete published posts")

    await db.delete(post)
    await db.commit()
    return {"message": "Post deleted"}

@router.post("/refresh-metrics")
async def refresh_metrics(background_tasks: BackgroundTasks):
    """Fetch latest metrics from Threads for all published posts."""
    background_tasks.add_task(refresh_post_metrics)
    return {"message": "Metrics refresh started in background"}

@router.get("/test-connection")
async def test_threads_connection():
    """Test if Threads API credentials are valid."""
    ok = await threads_client.test_connection()
    return {"connected": ok, "user_id": threads_client.user_id if ok else None}
