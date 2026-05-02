# BusSing Threads Scheduler

Automated Threads posting for [BusSing](https://bfrfrr.com) — Singapore's #1 bus timing & transport app.

Posts 3–5 times daily with AI-generated content: commuter jokes, product flexes, founder updates, polls, and local transport commentary. Built specifically for the Singapore commuter audience on Threads.

## Features

- **AI Content Generation** — generates authentic, Singlish-flavored Threads posts using OpenRouter
- **5 Daily Time Slots** — morning commute (7:30am), midday (10am), lunch (12:30pm), evening commute (5:30pm), night (9pm) SGT
- **Content Type Rotation** — automatically rotates between jokes, product flexes, founder updates, polls, and commentary
- **Weekly Schedule Generation** — one-click generation of a full week's content (21–35 posts)
- **Analytics Dashboard** — track likes, replies, reposts, views, and engagement rate
- **AI Weekly Analysis** — get strategic insights on what's working
- **Content Library** — markdown-based content management with categories and priorities

## Quick Start

```bash
# Clone
git clone https://github.com/Revanth15/threads-scheduler.git
cd threads-scheduler

# Setup
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Configure
cp .env.example .env
# Edit .env with your Threads API + OpenRouter keys
# Recommended model for post/schedule generation: openai/gpt-4o-mini

# Run
python -m app.main
```

Dashboard: `http://localhost:8000`

## Deployment (Free)

### Option 1: Render (Recommended)
1. Push to GitHub
2. Go to [render.com](https://render.com) → New Web Service → connect your repo
3. Render auto-detects `render.yaml` and configures everything
4. Add your env vars (Threads API keys, OpenRouter key) in the Render dashboard
5. **Important**: Use [cron-job.org](https://cron-job.org) to ping `https://your-app.onrender.com/health` every 14 minutes to keep the free tier alive

### Option 2: Railway
1. Push to GitHub
2. Go to [railway.app](https://railway.app) → New Project → Deploy from GitHub
3. Add env vars in Railway dashboard
4. Free $5/month credit — enough to run 24/7

### Option 3: Fly.io
```bash
fly launch
fly secrets set THREADS_ACCESS_TOKEN=xxx OPENROUTER_API_KEY=xxx ...
fly deploy
```

## Content Library

Edit `content.md` to manage your posting topics. Format:

```markdown
## Category Name

### Topic Title
Post content and context here.

Tags: #BusSing #Singapore
Priority: high
```

Categories: Commuter Jokes, Product Flex, Founder Updates, Polls, Local Transport Commentary, Reply Engagement

## Posting Schedule

| Slot | Time (SGT) | Best Content Type |
|------|-----------|-------------------|
| Morning Commute | 7:30am | Commuter jokes, commentary |
| Midday | 10:00am | Product flex, tips |
| Lunch | 12:30pm | Polls, product flex |
| Evening Commute | 5:30pm | Commuter jokes, polls |
| Night | 9:00pm | Founder updates, reply bait |

## Weekly Workflow

1. **Update content.md** (optional) — add fresh topics
2. **Reload content** — Dashboard → Content → Reload from disk
3. **Generate schedule** — Dashboard → Generate Week (AI plans 21–35 posts)
4. **Review & edit** — tweak any posts you want
5. **Let it run** — scheduler auto-publishes at each time slot
6. **Analyze** — end of week, run AI analysis for next week's strategy

## API Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/` | GET | Dashboard |
| `/health` | GET | Health check |
| `/api/posts/` | GET | List all posts |
| `/api/posts/generate-schedule` | POST | Generate weekly schedule |
| `/api/posts/manual` | POST | Create manual post |
| `/api/posts/{id}/publish-now` | POST | Publish immediately |
| `/api/content/topics` | GET | List content topics |
| `/api/content/reload-markdown` | POST | Reload content.md |
| `/api/analytics/overview` | GET | Stats overview |
| `/api/analytics/analyze-week` | POST | Run AI analysis |

## Environment Variables

See `.env.example` for all configuration options including:
- Threads API credentials
- OpenRouter AI model selection (`openai/gpt-4o-mini` recommended for structured text generation)
- 5 configurable daily posting slots (disable any by setting hour to -1)
- Timezone, post length limits, and more

## Refreshing Your Threads Token

Threads access tokens expire after 60 days. To refresh:
1. Use the Threads API token refresh endpoint
2. Update `THREADS_ACCESS_TOKEN` in your `.env` (or in Render/Railway dashboard)
3. Restart the app

Set a reminder every 50 days to refresh!
