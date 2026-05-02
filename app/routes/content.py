from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from pydantic import BaseModel
from typing import Optional
from app.database import get_db, ContentTopic
from app.content_parser import content_parser
import aiofiles

router = APIRouter()

class TopicCreate(BaseModel):
    title: str
    content: str
    category: Optional[str] = "General"
    priority: int = 1
    suggested_tags: list[str] = []

class TopicUpdate(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    category: Optional[str] = None
    priority: Optional[int] = None
    is_active: Optional[bool] = None

@router.get("/topics")
async def list_topics(
    category: Optional[str] = None,
    active_only: bool = True,
    db: AsyncSession = Depends(get_db)
):
    query = select(ContentTopic).order_by(ContentTopic.priority.desc(), ContentTopic.created_at.desc())
    if active_only:
        query = query.where(ContentTopic.is_active == True)
    if category:
        query = query.where(ContentTopic.category == category)

    result = await db.execute(query)
    topics = result.scalars().all()

    return [
        {
            "id": t.id,
            "title": t.title,
            "content": t.content[:200] + "..." if len(t.content) > 200 else t.content,
            "category": t.category,
            "priority": t.priority,
            "used_count": t.used_count,
            "last_used": str(t.last_used) if t.last_used else None,
            "is_active": t.is_active,
        }
        for t in topics
    ]

@router.post("/topics")
async def create_topic(topic: TopicCreate, db: AsyncSession = Depends(get_db)):
    db_topic = ContentTopic(
        title=topic.title,
        content=topic.content,
        category=topic.category,
        priority=topic.priority,
    )
    db.add(db_topic)
    await db.commit()
    await db.refresh(db_topic)
    return {"id": db_topic.id, "message": "Topic created"}

@router.patch("/topics/{topic_id}")
async def update_topic(topic_id: int, update: TopicUpdate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ContentTopic).where(ContentTopic.id == topic_id))
    topic = result.scalar_one_or_none()
    if not topic:
        raise HTTPException(404, "Topic not found")

    if update.title is not None:
        topic.title = update.title
    if update.content is not None:
        topic.content = update.content
    if update.category is not None:
        topic.category = update.category
    if update.priority is not None:
        topic.priority = update.priority
    if update.is_active is not None:
        topic.is_active = update.is_active

    await db.commit()
    return {"message": "Topic updated"}

@router.delete("/topics/{topic_id}")
async def delete_topic(topic_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ContentTopic).where(ContentTopic.id == topic_id))
    topic = result.scalar_one_or_none()
    if not topic:
        raise HTTPException(404, "Topic not found")
    await db.delete(topic)
    await db.commit()
    return {"message": "Topic deleted"}

@router.post("/upload-markdown")
async def upload_markdown(file: UploadFile = File(...), db: AsyncSession = Depends(get_db)):
    """Upload and parse a markdown content file. Replaces all existing topics."""
    if not file.filename.endswith(".md"):
        raise HTTPException(400, "File must be a .md markdown file")

    contents = await file.read()
    text = contents.decode("utf-8")

    topics = content_parser.parse_content(text)
    if not topics:
        raise HTTPException(400, "No topics found in the file. Check the format.")

    # Save to content.md
    async with aiofiles.open("content.md", "w") as f:
        await f.write(text)

    # Deactivate all existing topics
    existing = await db.execute(select(ContentTopic))
    for topic in existing.scalars().all():
        topic.is_active = False

    # Create new topics
    created = 0
    for t in topics:
        db_topic = ContentTopic(
            title=t["title"],
            content=t["content"],
            category=t["category"],
            priority=t["priority"],
            is_active=True,
        )
        db.add(db_topic)
        created += 1

    await db.commit()
    return {
        "message": f"Imported {created} topics from {file.filename}",
        "topics_created": created,
        "categories": list(set(t["category"] for t in topics)),
    }

@router.post("/reload-markdown")
async def reload_markdown(db: AsyncSession = Depends(get_db)):
    """Re-parse the content.md file already on disk."""
    topics = content_parser.parse_file()
    if not topics:
        raise HTTPException(400, "No topics found or content.md not found")

    existing = await db.execute(select(ContentTopic))
    for topic in existing.scalars().all():
        topic.is_active = False

    created = 0
    for t in topics:
        db_topic = ContentTopic(
            title=t["title"],
            content=t["content"],
            category=t["category"],
            priority=t["priority"],
            is_active=True,
        )
        db.add(db_topic)
        created += 1

    await db.commit()
    return {"message": f"Reloaded {created} topics from content.md"}

@router.get("/categories")
async def list_categories(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(ContentTopic.category).where(ContentTopic.is_active == True).distinct()
    )
    return [row[0] for row in result.fetchall() if row[0]]
