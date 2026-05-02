import re
from pathlib import Path
from typing import Optional
from app.config import settings
import logging

logger = logging.getLogger(__name__)

class ContentParser:
    """Parses a structured markdown file into topics for posting."""

    def parse_file(self, filepath: Optional[str] = None) -> list[dict]:
        """Parse the content markdown file and return list of topics."""
        path = Path(filepath or settings.CONTENT_FILE)
        if not path.exists():
            logger.warning(f"Content file not found: {path}")
            return []

        with open(path, "r", encoding="utf-8") as f:
            content = f.read()

        return self.parse_content(content)

    def parse_content(self, content: str) -> list[dict]:
        """
        Parses markdown with the following format:

        # App Name / Overview (H1 = global metadata, ignored as topic)

        ## Category Name (H2 = category grouping)

        ### Topic Title (H3 = individual post topic)
        Content of the topic...

        Tags: #tag1 #tag2
        Priority: high|medium|low
        """
        topics = []
        current_category = "General"
        current_topic = None
        current_lines = []

        lines = content.split("\n")

        for line in lines:
            h2_match = re.match(r"^## (.+)$", line.strip())
            h3_match = re.match(r"^### (.+)$", line.strip())

            if h2_match:
                # Save previous topic
                if current_topic:
                    topics.append(self._finalize_topic(current_topic, current_lines, current_category))
                current_category = h2_match.group(1).strip()
                current_topic = None
                current_lines = []

            elif h3_match:
                # Save previous topic
                if current_topic:
                    topics.append(self._finalize_topic(current_topic, current_lines, current_category))
                current_topic = h3_match.group(1).strip()
                current_lines = []

            elif current_topic is not None:
                current_lines.append(line)

        # Save last topic
        if current_topic:
            topics.append(self._finalize_topic(current_topic, current_lines, current_category))

        logger.info(f"Parsed {len(topics)} topics from content file")
        return topics

    def _finalize_topic(self, title: str, lines: list[str], category: str) -> dict:
        """Parse topic body, extract metadata, and return structured dict."""
        priority = 1
        tags = []
        content_lines = []

        for line in lines:
            if line.strip().lower().startswith("priority:"):
                val = line.split(":", 1)[1].strip().lower()
                priority = {"high": 3, "medium": 2, "low": 1}.get(val, 1)
            elif line.strip().lower().startswith("tags:"):
                tag_str = line.split(":", 1)[1].strip()
                tags = [t.strip() for t in tag_str.split() if t.startswith("#")]
            else:
                content_lines.append(line)

        content = "\n".join(content_lines).strip()

        return {
            "title": title,
            "content": content,
            "category": category,
            "priority": priority,
            "suggested_tags": tags,
        }

content_parser = ContentParser()
