import asyncio
from datetime import datetime, timedelta, date
import pytz
import logging
from sqlalchemy import select, and_
from app.config import settings
from app.database import AsyncSessionLocal, Post, PostMetrics, ContentTopic, ScheduleConfig
from app.threads_client import threads_client, ThreadsAPIError
from app.ai_client import ai_client
from typing import Optional

logger = logging.getLogger(__name__)

_scheduler_running = False

async def start_scheduler():
    global _scheduler_running
    _scheduler_running = True
    logger.info("🕐 Scheduler started — BusSing Threads automation active")
    while _scheduler_running:
        try:
            await check_and_run_due_posts()
        except Exception as e:
            logger.error(f"Scheduler loop error: {e}")
        await asyncio.sleep(60)  # Check every minute

async def shutdown_scheduler():
    global _scheduler_running
    _scheduler_running = False
    logger.info("Scheduler stopped")

async def check_and_run_due_posts():
    tz = pytz.timezone(settings.TIMEZONE)
    now = datetime.now(tz)

    async with AsyncSessionLocal() as db:
        # Find posts that are due (within 1 minute window)
        window_start = now.replace(tzinfo=None) - timedelta(minutes=1)
        window_end = now.replace(tzinfo=None) + timedelta(minutes=1)

        result = await db.execute(
            select(Post).where(
                and_(
                    Post.status == "pending",
                    Post.scheduled_at >= window_start,
                    Post.scheduled_at <= window_end,
                )
            )
        )
        due_posts = result.scalars().all()

        for post in due_posts:
            await publish_post(post, db)

async def publish_post(post: Post, db):
    """Publish a single post to Threads."""
    logger.info(f"Publishing post ID {post.id}: {post.content[:50]}...")
    try:
        post_id = await threads_client.post_text(post.content)
        post.threads_post_id = post_id
        post.status = "published"
        post.published_at = datetime.utcnow()
        await db.commit()
        logger.info(f"✅ Post {post.id} published successfully. Threads ID: {post_id}")
    except ThreadsAPIError as e:
        post.status = "failed"
        post.error_message = e.message
        await db.commit()
        logger.error(f"❌ Failed to publish post {post.id}: {e.message}")
    except Exception as e:
        post.status = "failed"
        post.error_message = str(e)
        await db.commit()
        logger.error(f"❌ Unexpected error publishing post {post.id}: {e}")

async def generate_weekly_schedule(week_offset: int = 0) -> dict:
    """
    Generate 21-35 posts for the upcoming week (3-5 posts/day x 7 days).
    Uses configurable time slots from settings.
    """
    tz = pytz.timezone(settings.TIMEZONE)
    today = datetime.now(tz).date()

    # Calculate start of target week (Monday)
    days_until_monday = (7 - today.weekday()) % 7
    if days_until_monday == 0:
        days_until_monday = 7
    week_start = today + timedelta(days=days_until_monday + (week_offset * 7))

    active_slots = settings.get_active_slots()
    posts_per_day = min(len(active_slots), settings.MAX_POSTS_PER_DAY)
    total_posts = posts_per_day * 7

    async with AsyncSessionLocal() as db:
        # Check if already generated
        existing = await db.execute(
            select(ScheduleConfig).where(
                ScheduleConfig.week_start_date == datetime.combine(week_start, datetime.min.time())
            )
        )
        if existing.scalar_one_or_none():
            return {"error": f"Schedule already generated for week starting {week_start}"}

        # Get active topics
        topics_result = await db.execute(
            select(ContentTopic).where(ContentTopic.is_active == True).order_by(ContentTopic.priority.desc())
        )
        topics = topics_result.scalars().all()

        if not topics:
            return {"error": "No active topics found. Please load your content.md file first."}

        # Get last week's analysis for context
        last_analysis = await get_latest_analysis(db)

        # Let AI plan the week
        try:
            schedule_plan = await ai_client.generate_weekly_schedule(topics, last_analysis)
        except Exception as e:
            logger.error(f"Failed to generate AI weekly schedule: {e}")
            schedule_plan = ai_client._fallback_schedule(topics, posts_per_day)

        # Create a topic lookup
        topic_map = {t.id: t for t in topics}

        # Generate actual posts
        created_posts = []
        recent_post_texts = await get_recent_post_texts(db, limit=10)

        # Map content types to time-of-day vibes
        slot_vibes = {
            "morning_commute": "morning",
            "midday": "morning",
            "lunch": "evening",
            "evening_commute": "evening",
            "night": "evening",
        }

        for day_num in range(1, 8):
            # Use up to posts_per_day slots
            day_slots = active_slots[:posts_per_day]

            for slot_idx, slot_config in enumerate(day_slots):
                # Find a matching topic from AI schedule or rotate
                plan_idx = (day_num - 1) * posts_per_day + slot_idx
                if plan_idx < len(schedule_plan):
                    topic_id = schedule_plan[plan_idx].get("topic_id")
                    topic = topic_map.get(topic_id) or topics[plan_idx % len(topics)]
                else:
                    topic = topics[plan_idx % len(topics)]

                # Calculate scheduled datetime
                post_date = week_start + timedelta(days=day_num - 1)
                scheduled_dt = datetime.combine(
                    post_date,
                    datetime.min.time().replace(
                        hour=slot_config["hour"],
                        minute=slot_config["minute"]
                    )
                )
                # Convert from local timezone to UTC for storage
                local_dt = tz.localize(scheduled_dt)
                utc_dt = local_dt.astimezone(pytz.utc).replace(tzinfo=None)

                # Determine post vibe based on slot type
                post_vibe = slot_vibes.get(slot_config["type"], "morning")

                # Generate post content
                try:
                    generated = await ai_client.generate_post(
                        topic=topic,
                        post_type=post_vibe,
                        previous_posts=recent_post_texts,
                    )
                    post_text = generated.get("post_text", "")[:settings.MAX_POST_LENGTH]
                    hashtags = " ".join(generated.get("hashtags", []))
                    recent_post_texts.append(post_text)
                except Exception as e:
                    logger.error(f"AI generation failed for topic {topic.id}: {e}")
                    post_text = f"{topic.title}\n\n{topic.content[:300]}..."
                    hashtags = ""

                post = Post(
                    content=post_text,
                    topic=topic.title,
                    post_type=slot_config["type"],
                    scheduled_at=utc_dt,
                    status="pending",
                    week_number=week_start.isocalendar()[1],
                    hashtags=hashtags,
                )
                db.add(post)
                created_posts.append(post)

                # Update topic usage
                topic.used_count += 1
                topic.last_used = datetime.utcnow()

        # Save schedule config
        config = ScheduleConfig(
            week_start_date=datetime.combine(week_start, datetime.min.time()),
            posts_generated=True,
            total_posts_planned=len(created_posts),
        )
        db.add(config)
        await db.commit()

        logger.info(f"✅ Generated {len(created_posts)} posts for week starting {week_start}")
        return {
            "success": True,
            "week_start": str(week_start),
            "posts_created": len(created_posts),
            "posts_per_day": posts_per_day,
            "slots_used": [s["type"] for s in active_slots[:posts_per_day]],
            "message": f"Generated {len(created_posts)} posts ({posts_per_day}/day) scheduled from {week_start}",
        }

async def refresh_post_metrics(post_id: Optional[int] = None):
    """Fetch and update metrics for all published posts."""
    async with AsyncSessionLocal() as db:
        query = select(Post).where(Post.status == "published", Post.threads_post_id.isnot(None))
        if post_id:
            query = query.where(Post.id == post_id)

        result = await db.execute(query)
        posts = result.scalars().all()

        updated = 0
        for post in posts:
            try:
                metrics_data = await threads_client.get_post_insights(post.threads_post_id)
                total_interactions = (
                    metrics_data["likes"] + metrics_data["replies"] +
                    metrics_data["reposts"] + metrics_data["quotes"]
                )
                engagement_rate = (total_interactions / max(metrics_data["views"], 1)) * 100

                existing = post.metrics
                if existing:
                    existing.likes = metrics_data["likes"]
                    existing.replies = metrics_data["replies"]
                    existing.reposts = metrics_data["reposts"]
                    existing.quotes = metrics_data["quotes"]
                    existing.views = metrics_data["views"]
                    existing.engagement_rate = engagement_rate
                    existing.fetched_at = datetime.utcnow()
                else:
                    metrics = PostMetrics(
                        post_id=post.id,
                        **metrics_data,
                        engagement_rate=engagement_rate,
                    )
                    db.add(metrics)
                updated += 1
            except Exception as e:
                logger.error(f"Failed to fetch metrics for post {post.id}: {e}")

        await db.commit()
        logger.info(f"Updated metrics for {updated} posts")
        return updated

async def get_latest_analysis(db) -> Optional[dict]:
    from app.database import WeeklyAnalysis
    result = await db.execute(
        select(WeeklyAnalysis).order_by(WeeklyAnalysis.created_at.desc()).limit(1)
    )
    analysis = result.scalar_one_or_none()
    if analysis and analysis.ai_analysis:
        import json
        try:
            return json.loads(analysis.ai_analysis)
        except:
            return None
    return None

async def get_recent_post_texts(db, limit: int = 10) -> list[str]:
    result = await db.execute(
        select(Post.content).where(Post.status == "published").order_by(Post.published_at.desc()).limit(limit)
    )
    return [row[0] for row in result.fetchall()]
