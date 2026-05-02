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

    def _extract_message_text(self, content) -> Optional[str]:
        """Normalize OpenRouter message payloads into plain text."""
        if content is None:
            return None
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    text = item.get("text")
                    if isinstance(text, str):
                        parts.append(text)
            normalized = "\n".join(part for part in parts if part).strip()
            return normalized or None
        if isinstance(content, dict):
            text = content.get("text")
            if isinstance(text, str):
                return text
            try:
                return json.dumps(content)
            except TypeError:
                return str(content)
        return str(content)

    def _strip_code_fences(self, raw: Optional[str]) -> str:
        """Remove markdown code fences from model output safely."""
        if not raw:
            return ""
        return re.sub(r"```json|```", "", raw).strip()

    def _is_reasoning_model(self) -> bool:
        model = (self.model or "").lower()
        return any(name in model for name in ("deepseek", "o1", "o3", "gpt-5", "reason"))

    def _compact_text(self, value: Optional[str], limit: int) -> str:
        if not value:
            return ""
        normalized = re.sub(r"\s+", " ", value).strip()
        if len(normalized) <= limit:
            return normalized
        return normalized[: limit - 3].rstrip() + "..."

    async def _call(self, messages: list, max_tokens: int = 1000, temperature: float = 0.8) -> str:
        request_body = {
            "model": self.model,
            "messages": messages,
            "max_completion_tokens": max_tokens,
            "temperature": temperature,
        }

        # Reasoning models can spend the entire output budget thinking and return null content.
        # Keep the reasoning budget small and exclude it from the visible response path.
        if self._is_reasoning_model():
            request_body["reasoning"] = {
                "exclude": True,
                "max_tokens": settings.OPENROUTER_REASONING_MAX_TOKENS,
            }

        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{OPENROUTER_BASE}/chat/completions",
                headers=self.headers,
                json=request_body
            )
            data = response.json()
            if response.status_code != 200:
                raise Exception(f"OpenRouter API error: {data}")

            choices = data.get("choices")
            if not choices:
                logger.error(f"OpenRouter returned no choices: {data}")
                raise Exception(f"OpenRouter returned no choices: {json.dumps(data)[:500]}")

            message = choices[0].get("message", {})
            content = self._extract_message_text(message.get("content"))
            reasoning = self._extract_message_text(message.get("reasoning"))
            reasoning_content = self._extract_message_text(message.get("reasoning_content"))

            if content is None:
                finish_reason = choices[0].get("finish_reason", "unknown")
                if reasoning or reasoning_content:
                    logger.warning(
                        "OpenRouter returned reasoning without assistant content "
                        f"(finish_reason={finish_reason}, model={self.model})"
                    )
                logger.error(f"OpenRouter returned null content. Full response: {json.dumps(data)[:500]}")
                raise Exception(
                    f"OpenRouter returned null content for model {self.model}. "
                    f"Finish reason: {finish_reason}. "
                    "The provider returned thinking output but no assistant text."
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
            recent_samples = [
                self._compact_text(post, 160)
                for post in previous_posts[-3:]
                if post
            ]
            if recent_samples:
                prev_context = "\n\nAvoid sounding too similar to these recent posts:\n- " + "\n- ".join(recent_samples)

        performance_hint = ""
        if best_performing_topics:
            performance_hint = f"\n\nThese topics have performed best recently: {', '.join(best_performing_topics)}"

        system_prompt = """You write Threads posts for BusSing like a real Singaporean founder who actually takes buses and trains.

Voice:
- first person, warm, specific, a bit tired or amused when the topic calls for it
- sound like a person talking to other commuters, not a copywriter
- natural Singaporean phrasing is good; forced slang is bad
- use Singlish lightly and only where it sounds natural
- reflect real commuter feelings: rushing, sweating, rain, packed buses, MRT delays, just-missed bus anger, long waits, JB jam dread, standing all the way home

Style rules:
- 2 to 5 short lines
- emotionally honest beats polished
- use concrete moments, not generic observations
- do not sound motivational, inspirational, or "social media optimized"
- do not sound like an ad even when mentioning a BusSing feature
- at most 1 emoji, and only if it genuinely fits
- 1 or 2 hashtags max
- no links
- end naturally; only ask a question when it feels earned"""

        user_prompt = f"""Write a {time_context} Threads post for BusSing.

POST TYPE: {topic.category or 'General'}
TOPIC: {topic.title}
CONTENT BRIEF:
{self._compact_text(topic.content, 600)}

VIBE: {time_vibe}

REQUIREMENTS:
- Max {settings.MAX_POST_LENGTH} characters
- Sound like a real Singaporean, not a brand
- Short, punchy, with line breaks
- Focus on one relatable commuter feeling or one lived observation
- Prefer specificity over polish
- Do not use corporate phrasing, launch-copy wording, or generic engagement bait
- Keep emojis to 0 or 1
- Use only 1-2 hashtags at the end, and only if they fit naturally
- If it's a commuter joke, make it sound like an actual complaint or observation people in Singapore will instantly recognise
- If it's a product flex, make it feel like "I built this because I was damn annoyed by this problem", not an ad
- If it's a founder update, be authentic and vulnerable
- If it's a poll, make the options sound like actual commuter choices or pain points
- Good references: missing the bus by 10 seconds, standing in a hot queue, rain making everything slower, checking bus timing every 20 seconds, squeezing into a packed MRT, waiting for the lift with everyone else
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
            cleaned = self._strip_code_fences(raw)
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
            {
                "id": t.id,
                "title": self._compact_text(t.title, 80) or f"Topic {t.id}",
                "category": t.category or "General",
                "priority": t.priority or 1,
            }
            for t in topics
        ]

        analysis_context = ""
        if previous_analysis:
            analysis_context = (
                f"\n\nLast week's strategy insights:\n"
                f"{json.dumps(previous_analysis, indent=2, default=str)}"
            )

        posts_per_day = getattr(settings, 'MAX_POSTS_PER_DAY', 5)
        total_posts = posts_per_day * 7

        user_prompt = f"""Plan a {total_posts}-post schedule for BusSing on Threads.

Available topics:
{json.dumps(topics_list, separators=(",", ":"))}
{analysis_context}

Slots each day: morning_commute, midday, lunch, evening_commute, night

Rules:
- Never repeat the same content type in consecutive slots
- Commuter jokes perform best at morning_commute and evening_commute
- Product flex performs best at midday and lunch
- Founder updates perform best at night
- Polls perform best at lunch and evening_commute
- Put high-priority topics on Tue-Thu (highest engagement days)
- Space similar topics at least 2 days apart
- Keep rationale under 8 words

Return a JSON array of {total_posts} objects:
[
  {{"day":1,"slot":"morning_commute","topic_id":123,"rationale":"short reason"}},
  ...
]"""

        try:
            raw = await self._call(
                [{"role": "user", "content": user_prompt}],
                max_tokens=4000,
                temperature=0.4
            )
        except Exception as e:
            logger.warning(f"AI schedule generation failed before parsing: {e}. Using fallback rotation.")
            return self._fallback_schedule(topics, posts_per_day)

        if not raw:
            logger.warning("AI returned empty response for weekly schedule, using fallback rotation")
            return self._fallback_schedule(topics, posts_per_day)

        try:
            cleaned = self._strip_code_fences(raw)
            # Handle case where response contains text before/after JSON array
            bracket_start = cleaned.find("[")
            bracket_end = cleaned.rfind("]")
            if bracket_start != -1 and bracket_end != -1:
                cleaned = cleaned[bracket_start:bracket_end + 1]
            schedule_plan = json.loads(cleaned)
            return self._normalize_schedule_plan(schedule_plan, topics, posts_per_day, total_posts)
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

    def _normalize_schedule_plan(
        self,
        schedule_plan,
        topics: list[ContentTopic],
        posts_per_day: int,
        total_posts: int,
    ) -> list[dict]:
        if not isinstance(schedule_plan, list):
            return self._fallback_schedule(topics, posts_per_day)

        normalized = []
        allowed_slots = {"morning_commute", "midday", "lunch", "evening_commute", "night"}
        valid_topic_ids = {topic.id for topic in topics}

        for item in schedule_plan:
            if not isinstance(item, dict):
                continue
            day = item.get("day")
            slot = item.get("slot")
            topic_id = item.get("topic_id")
            if day not in range(1, 8):
                continue
            if slot not in allowed_slots:
                continue
            if topic_id not in valid_topic_ids:
                continue
            normalized.append({
                "day": day,
                "slot": slot,
                "topic_id": topic_id,
                "rationale": self._compact_text(item.get("rationale"), 80) or "AI-assigned",
            })
            if len(normalized) >= total_posts:
                break

        if len(normalized) < total_posts:
            fallback = self._fallback_schedule(topics, posts_per_day)
            normalized.extend(fallback[len(normalized):total_posts])

        return normalized[:total_posts]

ai_client = AIClient()
