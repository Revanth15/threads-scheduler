import httpx
import json
import re
from typing import Optional
from app.config import settings
from app.database import ContentTopic
import logging

logger = logging.getLogger(__name__)

OPENROUTER_BASE = "https://openrouter.ai/api/v1"

class AIClient:
    def __init__(self):
        self.api_key = settings.OPENROUTER_API_KEY
        self.model = settings.OPENROUTER_MODEL
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://threads-scheduler.app",
            "X-Title": "Threads Scheduler",
        }

    async def _call(self, messages: list, max_tokens: int = 1000, temperature: float = 0.8) -> str:
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{OPENROUTER_BASE}/chat/completions",
                headers=self.headers,
                json={
                    "model": self.model,
                    "messages": messages,
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                }
            )
            data = response.json()
            if response.status_code != 200:
                raise Exception(f"OpenRouter API error: {data}")

            choices = data.get("choices")
            if not choices:
                logger.error(f"OpenRouter returned no choices: {data}")
                raise Exception(f"OpenRouter returned no choices: {json.dumps(data)[:500]}")

            message = choices[0].get("message", {})
            content = message.get("content")

            # Some models (e.g. DeepSeek) return reasoning in a separate field
            # with content set to null. Fall back to reasoning_content if available.
            if content is None:
                content = message.get("reasoning_content")
                logger.warning(f"OpenRouter content was null, fell back to reasoning_content")

            if content is None:
                logger.error(f"OpenRouter returned null content. Full response: {json.dumps(data)[:500]}")
                raise Exception(
                    f"OpenRouter returned null content for model {self.model}. "
                    f"Finish reason: {choices[0].get('finish_reason', 'unknown')}. "
                    f"This can happen with reasoning models — try a different model."
                )

            return content

    async def generate_post(
        self,
        topic: ContentTopic,
        post_type: str,
        previous_posts: list[str] = [],
        best_performing_topics: list[str] = [],
    ) -> dict:
        """Generate a Threads post from a content topic."""
        time_context = "morning" if post_type == "morning" else "evening"
        time_vibe = (
            "energetic, motivating, and inspirational — people are starting their day"
            if post_type == "morning"
            else "reflective, insightful, and thought-provoking — people are winding down"
        )

        prev_context = ""
        if previous_posts:
            prev_context = f"\n\nAvoid repeating these recent posts:\n" + "\n---\n".join(previous_posts[-5:])

        performance_hint = ""
        if best_performing_topics:
            performance_hint = f"\n\nThese topics have performed best recently: {', '.join(best_performing_topics)}"

        system_prompt = """You are the social media voice for BusSing — the #1 bus timing & transport app in Singapore.

IDENTITY & TONE:
- You are a Singaporean commuter who also built the app. You speak like a real Singaporean — casual, relatable, sometimes funny.
- You use Singlish naturally when it fits (lah, sia, walao, confirm, sian, shiok) but don't overdo it.
- You write in first person. You're the founder sharing product updates, commuter jokes, and local transport takes.
- You are NOT a brand account. You're a person who happens to build BusSing.

BUSSING FEATURES YOU CAN REFERENCE:
- Real-time bus arrival timings (LTA DataMall powered)
- Lock Screen widget — see bus timings without unlocking your phone
- Home Screen widget — favourite stops, one glance
- Apple Watch app — check timings from your wrist
- Dynamic Island / Live Activities — track your bus live
- Offline MRT map — works underground, no signal needed
- Real-time bus tracking on map
- Causeway traffic cameras — check JB traffic before heading out
- Bus route explorer — full routes & stops
- Traffic incident alerts

CONTENT TYPES (rotate between these):
1. Commuter jokes — relatable Singapore commuting moments
2. Product flex — highlight a feature naturally, not like an ad
3. Founder updates — "working on X", building in public
4. Polls — ask users what to improve next
5. Local transport commentary — react to MRT delays, rain, bus life
6. Reply bait — posts that make people want to reply with their own stories

THREADS-SPECIFIC RULES:
- Threads is text-first. No images needed.
- Short posts (1-4 lines) perform best. Use line breaks.
- 1-2 emojis max. Don't overdo it.
- End with something that invites replies: a question, a hot take, or a "what's yours?"
- 2-3 hashtags MAX at the end. Use: #BusSing #Singapore #SingaporeTransport #SGCommute
- NEVER sound like a press release or corporate announcement.
- DO NOT spam links. Mention "BusSing" naturally, not as a CTA.

SINGAPORE CONTEXT:
- Threads has ~464k users in Singapore (7.9% of population) — it's a secondary channel, not the main acquisition engine.
- Your existing Threads messaging highlights "bus timings right on your Lock Screen" and offline MRT maps.
- Peak commute: 7-9am, 5-7pm. Rain = bus delays. MRT breakdowns = goldmine for relatable content.
- JB (Johor Bahru) traffic is a constant topic. Causeway jams = engagement.
- Singaporeans love complaining about transport — lean into that energy."""

        user_prompt = f"""Write a {time_context} Threads post for BusSing.

POST TYPE: {topic.category or 'General'}
TOPIC: {topic.title}
CONTENT BRIEF:
{topic.content}

VIBE: {time_vibe}

REQUIREMENTS:
- Max {settings.MAX_POST_LENGTH} characters
- Sound like a real Singaporean, not a brand
- Short, punchy, max 4 lines with line breaks
- End with a hook that invites replies
- 2-3 hashtags at the end (from: #BusSing #Singapore #SGCommute #SingaporeTransport)
- If it's a commuter joke, make it genuinely funny
- If it's a product flex, make it feel like a casual flex, not an ad
- If it's a founder update, be authentic and vulnerable
- If it's a poll, use the format "Which X?" with clear options
{prev_context}{performance_hint}

Respond with ONLY a JSON object like this:
{{
  "post_text": "Your full post text here including hashtags",
  "hashtags": ["#tag1", "#tag2"],
  "hook_type": "question|cta|statement|joke|poll",
  "estimated_engagement": "low|medium|high"
}}"""

        raw = await self._call([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ])

        # Parse JSON from response
        if not raw:
            logger.error("AI returned empty content for post generation")
            return {
                "post_text": f"{topic.title}\n\n#BusSing #Singapore",
                "hashtags": ["#BusSing", "#Singapore"],
                "hook_type": "statement",
                "estimated_engagement": "low"
            }

        try:
            cleaned = re.sub(r"```json|```", "", raw).strip()
            return json.loads(cleaned)
        except json.JSONDecodeError:
            # Fallback: extract just the text
            return {
                "post_text": raw[:settings.MAX_POST_LENGTH],
                "hashtags": [],
                "hook_type": "statement",
                "estimated_engagement": "medium"
            }

    async def analyze_weekly_performance(self, posts_data: list[dict]) -> dict:
        """Run AI analysis on a week's worth of posts and metrics."""
        posts_summary = json.dumps(posts_data, indent=2, default=str)

        system_prompt = """You are a social media strategist analyzing Threads performance data.
You provide actionable, specific insights — not vague advice.
You look for patterns in what works and what doesn't.
Your recommendations are concrete and implementable."""

        user_prompt = f"""Analyze this week's Threads performance data and provide strategic insights:

{posts_summary}

Provide a comprehensive analysis as JSON with this structure:
{{
  "executive_summary": "2-3 sentence overview of the week",
  "key_wins": ["win1", "win2", "win3"],
  "key_issues": ["issue1", "issue2"],
  "best_time_to_post": "morning|evening|both",
  "best_performing_content_types": ["type1", "type2"],
  "engagement_patterns": {{
    "morning_avg_engagement": "observation",
    "evening_avg_engagement": "observation",
    "best_day": "observation"
  }},
  "topic_performance": {{
    "top_topics": ["topic1", "topic2"],
    "underperforming_topics": ["topic1"]
  }},
  "content_recommendations": [
    "Specific actionable recommendation 1",
    "Specific actionable recommendation 2",
    "Specific actionable recommendation 3"
  ],
  "hashtag_analysis": "observations about hashtag performance",
  "next_week_strategy": "Concrete 3-5 sentence strategy for next week",
  "predicted_best_post_style": "Description of the ideal post style based on data"
}}"""

        raw = await self._call(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            max_tokens=2000,
            temperature=0.3
        )

        if not raw:
            return {"executive_summary": "AI returned empty response", "error": "No content from AI model"}

        try:
            cleaned = re.sub(r"```json|```", "", raw).strip()
            return json.loads(cleaned)
        except json.JSONDecodeError:
            return {"executive_summary": raw, "error": "Could not parse structured analysis"}

    async def generate_weekly_schedule(
        self,
        topics: list[ContentTopic],
        previous_analysis: Optional[dict] = None
    ) -> list[dict]:
        """Plan the optimal post order for the week based on topics and past performance."""
        topics_list = [
            {"id": t.id, "title": t.title, "category": t.category, "priority": t.priority}
            for t in topics
        ]

        analysis_context = ""
        if previous_analysis:
            analysis_context = f"\n\nLast week's strategy insights:\n{json.dumps(previous_analysis, indent=2)}"

        posts_per_day = getattr(settings, 'MAX_POSTS_PER_DAY', 5)
        total_posts = posts_per_day * 7

        user_prompt = f"""Plan a {total_posts}-post schedule for BusSing on Threads ({posts_per_day} posts/day x 7 days).

Available topics:
{json.dumps(topics_list, indent=2)}
{analysis_context}

Content type rotation (must mix daily):
- Commuter Jokes: 1-2 per day (high engagement)
- Product Flex: 1 per day (subtle, not salesy)
- Founder Updates: 2-3 per week
- Polls: 1-2 per week
- Local Transport Commentary: 1 per day
- Reply Engagement: 1-2 per day

Slot types per day: morning_commute (7:30am), midday (10am), lunch (12:30pm), evening_commute (5:30pm), night (9pm)

Rules:
- Never repeat the same content type in consecutive slots
- Commuter jokes perform best at morning_commute and evening_commute
- Product flex performs best at midday and lunch
- Founder updates perform best at night
- Polls perform best at lunch and evening_commute
- Put high-priority topics on Tue-Thu (highest engagement days)
- Space similar topics at least 2 days apart

Return a JSON array of {total_posts} objects:
[
  {{"day": 1, "slot": "morning_commute", "topic_id": 123, "rationale": "why this topic for this slot"}},
  ...
]"""

        raw = await self._call(
            [{"role": "user", "content": user_prompt}],
            max_tokens=4000,
            temperature=0.4
        )

        if not raw:
            logger.warning("AI returned empty response for weekly schedule, using fallback rotation")
            return self._fallback_schedule(topics, posts_per_day)

        try:
            cleaned = re.sub(r"```json|```", "", raw).strip()
            # Handle case where response contains text before/after JSON array
            bracket_start = cleaned.find("[")
            bracket_end = cleaned.rfind("]")
            if bracket_start != -1 and bracket_end != -1:
                cleaned = cleaned[bracket_start:bracket_end + 1]
            return json.loads(cleaned)
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(f"Failed to parse AI schedule response: {e}. Using fallback rotation.")
            return self._fallback_schedule(topics, posts_per_day)

    def _fallback_schedule(self, topics: list[ContentTopic], posts_per_day: int = 5) -> list[dict]:
        """Generate a simple rotation schedule when AI fails."""
        slot_types = ["morning_commute", "midday", "lunch", "evening_commute", "night"]
        schedule = []
        for day in range(1, 8):
            for slot_idx in range(posts_per_day):
                idx = ((day - 1) * posts_per_day + slot_idx) % len(topics)
                schedule.append({
                    "day": day,
                    "slot": slot_types[slot_idx % len(slot_types)],
                    "topic_id": topics[idx].id,
                    "rationale": "Auto-assigned (fallback)"
                })
        return schedule

ai_client = AIClient()
