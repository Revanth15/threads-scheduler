from fastapi import APIRouter, Depends, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc
from app.database import get_db, Post, PostMetrics, WeeklyAnalysis
from app.ai_client import ai_client
from app.scheduler import refresh_post_metrics
import json
from datetime import datetime, timedelta
from typing import Optional

router = APIRouter()

@router.get("/overview")
async def get_overview(db: AsyncSession = Depends(get_db)):
    """High-level stats overview."""
    total_posts = await db.execute(select(func.count(Post.id)).where(Post.status == "published"))
    total_likes = await db.execute(select(func.sum(PostMetrics.likes)))
    total_views = await db.execute(select(func.sum(PostMetrics.views)))
    total_replies = await db.execute(select(func.sum(PostMetrics.replies)))
    total_reposts = await db.execute(select(func.sum(PostMetrics.reposts)))
    avg_engagement = await db.execute(select(func.avg(PostMetrics.engagement_rate)))

    pending_count = await db.execute(select(func.count(Post.id)).where(Post.status == "pending"))
    failed_count = await db.execute(select(func.count(Post.id)).where(Post.status == "failed"))

    return {
        "published_posts": total_posts.scalar() or 0,
        "pending_posts": pending_count.scalar() or 0,
        "failed_posts": failed_count.scalar() or 0,
        "total_likes": total_likes.scalar() or 0,
        "total_views": total_views.scalar() or 0,
        "total_replies": total_replies.scalar() or 0,
        "total_reposts": total_reposts.scalar() or 0,
        "avg_engagement_rate": round(float(avg_engagement.scalar() or 0), 2),
    }

@router.get("/weekly")
async def get_weekly_stats(week_number: Optional[int] = None, db: AsyncSession = Depends(get_db)):
    """Get stats for a specific week (defaults to current week)."""
    if week_number is None:
        week_number = datetime.now().isocalendar()[1]

    result = await db.execute(
        select(Post).where(Post.week_number == week_number, Post.status == "published")
    )
    posts = result.scalars().all()

    post_data = []
    for p in posts:
        post_data.append({
            "id": p.id,
            "content": p.content[:100] + "..." if len(p.content) > 100 else p.content,
            "topic": p.topic,
            "post_type": p.post_type,
            "published_at": str(p.published_at),
            "likes": p.metrics.likes if p.metrics else 0,
            "replies": p.metrics.replies if p.metrics else 0,
            "reposts": p.metrics.reposts if p.metrics else 0,
            "views": p.metrics.views if p.metrics else 0,
            "engagement_rate": p.metrics.engagement_rate if p.metrics else 0,
        })

    return {
        "week_number": week_number,
        "total_posts": len(post_data),
        "posts": post_data,
    }

@router.post("/analyze-week")
async def analyze_week(week_number: Optional[int] = None, db: AsyncSession = Depends(get_db)):
    """Run AI analysis on a week's performance. Saves results to DB."""
    if week_number is None:
        week_number = datetime.now().isocalendar()[1]

    # Refresh metrics first
    await refresh_post_metrics()

    # Get week's posts with metrics
    result = await db.execute(
        select(Post).where(Post.week_number == week_number).order_by(Post.scheduled_at)
    )
    posts = result.scalars().all()

    if not posts:
        return {"error": f"No posts found for week {week_number}"}

    posts_data = []
    for p in posts:
        posts_data.append({
            "id": p.id,
            "content": p.content,
            "topic": p.topic,
            "post_type": p.post_type,
            "published_at": str(p.published_at),
            "status": p.status,
            "hashtags": p.hashtags,
            "metrics": {
                "likes": p.metrics.likes if p.metrics else 0,
                "replies": p.metrics.replies if p.metrics else 0,
                "reposts": p.metrics.reposts if p.metrics else 0,
                "quotes": p.metrics.quotes if p.metrics else 0,
                "views": p.metrics.views if p.metrics else 0,
                "engagement_rate": p.metrics.engagement_rate if p.metrics else 0,
            } if p.metrics else {},
        })

    # Run AI analysis
    analysis = await ai_client.analyze_weekly_performance(posts_data)

    # Calculate aggregate stats
    total_likes = sum(p.get("metrics", {}).get("likes", 0) for p in posts_data)
    total_views = sum(p.get("metrics", {}).get("views", 0) for p in posts_data)
    total_replies = sum(p.get("metrics", {}).get("replies", 0) for p in posts_data)
    total_reposts = sum(p.get("metrics", {}).get("reposts", 0) for p in posts_data)
    avg_engagement = sum(p.get("metrics", {}).get("engagement_rate", 0) for p in posts_data) / max(len(posts_data), 1)

    best_post = max(posts_data, key=lambda x: x.get("metrics", {}).get("engagement_rate", 0), default=None)

    year = datetime.now().year

    # Save to DB
    weekly_analysis = WeeklyAnalysis(
        week_number=week_number,
        year=year,
        total_posts=len(posts_data),
        total_likes=total_likes,
        total_replies=total_replies,
        total_reposts=total_reposts,
        total_views=total_views,
        avg_engagement_rate=avg_engagement,
        best_performing_post_id=best_post["id"] if best_post else None,
        best_time=analysis.get("best_time_to_post"),
        ai_analysis=json.dumps(analysis),
        ai_recommendations=json.dumps(analysis.get("content_recommendations", [])),
        top_topics=analysis.get("topic_performance", {}).get("top_topics", []),
    )
    db.add(weekly_analysis)
    await db.commit()

    return {
        "week_number": week_number,
        "stats": {
            "total_posts": len(posts_data),
            "total_likes": total_likes,
            "total_views": total_views,
            "total_replies": total_replies,
            "total_reposts": total_reposts,
            "avg_engagement_rate": round(avg_engagement, 2),
        },
        "ai_analysis": analysis,
        "best_post": best_post,
    }

@router.get("/history")
async def get_analysis_history(db: AsyncSession = Depends(get_db)):
    """Get all past weekly analyses."""
    result = await db.execute(
        select(WeeklyAnalysis).order_by(desc(WeeklyAnalysis.created_at)).limit(12)
    )
    analyses = result.scalars().all()

    return [
        {
            "id": a.id,
            "week_number": a.week_number,
            "year": a.year,
            "total_posts": a.total_posts,
            "total_likes": a.total_likes,
            "total_views": a.total_views,
            "avg_engagement_rate": a.avg_engagement_rate,
            "best_time": a.best_time,
            "ai_analysis": json.loads(a.ai_analysis) if a.ai_analysis else None,
            "top_topics": a.top_topics,
            "created_at": str(a.created_at),
        }
        for a in analyses
    ]

@router.get("/top-posts")
async def get_top_posts(limit: int = 10, db: AsyncSession = Depends(get_db)):
    """Get top performing posts by engagement rate."""
    result = await db.execute(
        select(Post, PostMetrics)
        .join(PostMetrics, Post.id == PostMetrics.post_id)
        .order_by(desc(PostMetrics.engagement_rate))
        .limit(limit)
    )
    rows = result.all()

    return [
        {
            "id": post.id,
            "content": post.content,
            "topic": post.topic,
            "post_type": post.post_type,
            "published_at": str(post.published_at),
            "likes": metrics.likes,
            "replies": metrics.replies,
            "reposts": metrics.reposts,
            "views": metrics.views,
            "engagement_rate": metrics.engagement_rate,
        }
        for post, metrics in rows
    ]
