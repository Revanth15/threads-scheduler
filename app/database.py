from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy import String, Integer, DateTime, Text, Float, Boolean, ForeignKey, JSON
from datetime import datetime
from typing import Optional, List
from app.config import settings

engine = create_async_engine(settings.DATABASE_URL, echo=settings.DEBUG)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)

class Base(DeclarativeBase):
    pass

class Post(Base):
    __tablename__ = "posts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    threads_post_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    content: Mapped[str] = mapped_column(Text)
    topic: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    post_type: Mapped[str] = mapped_column(String(50), default="morning")  # morning/evening
    scheduled_at: Mapped[datetime] = mapped_column(DateTime)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending/published/failed/skipped
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    week_number: Mapped[int] = mapped_column(Integer, default=0)
    hashtags: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    metrics: Mapped[Optional["PostMetrics"]] = relationship("PostMetrics", back_populates="post", uselist=False, lazy="selectin")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class PostMetrics(Base):
    __tablename__ = "post_metrics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("posts.id"))
    likes: Mapped[int] = mapped_column(Integer, default=0)
    replies: Mapped[int] = mapped_column(Integer, default=0)
    reposts: Mapped[int] = mapped_column(Integer, default=0)
    quotes: Mapped[int] = mapped_column(Integer, default=0)
    views: Mapped[int] = mapped_column(Integer, default=0)
    engagement_rate: Mapped[float] = mapped_column(Float, default=0.0)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    post: Mapped["Post"] = relationship("Post", back_populates="metrics", lazy="selectin")

class ContentTopic(Base):
    __tablename__ = "content_topics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    content: Mapped[str] = mapped_column(Text)
    category: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    used_count: Mapped[int] = mapped_column(Integer, default=0)
    last_used: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    priority: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class WeeklyAnalysis(Base):
    __tablename__ = "weekly_analyses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    week_number: Mapped[int] = mapped_column(Integer)
    year: Mapped[int] = mapped_column(Integer)
    total_posts: Mapped[int] = mapped_column(Integer, default=0)
    total_likes: Mapped[int] = mapped_column(Integer, default=0)
    total_replies: Mapped[int] = mapped_column(Integer, default=0)
    total_reposts: Mapped[int] = mapped_column(Integer, default=0)
    total_views: Mapped[int] = mapped_column(Integer, default=0)
    avg_engagement_rate: Mapped[float] = mapped_column(Float, default=0.0)
    best_performing_post_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    best_time: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    ai_analysis: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ai_recommendations: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    top_topics: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class ScheduleConfig(Base):
    __tablename__ = "schedule_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    week_start_date: Mapped[datetime] = mapped_column(DateTime)
    posts_generated: Mapped[bool] = mapped_column(Boolean, default=False)
    total_posts_planned: Mapped[int] = mapped_column(Integer, default=14)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

async def get_db():
    async with AsyncSessionLocal() as session:
        yield session