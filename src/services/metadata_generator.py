"""Metadata generator — UCB1-based A/B style selection, OpenAI GPT metadata, emoji enrichment."""

import json
import logging
import math
import os
import random
import re
from dataclasses import dataclass
from typing import Dict, List, Optional

from src.config.settings import settings
from src.services.multi_platform import (is_supported_platform,
                                         normalize_platform_name)

logger = logging.getLogger(__name__)


@dataclass
class MetadataVariant:
    variant_label: str
    cta_style: str
    hook_line: str
    title: str
    caption: str
    hashtags: List[str]


_EMOJI_MAP = {
    "action": "🔥💪✅",
    "follow": "🔔👆❤️",
    "curiosity": "👀🤔😱",
    "engagement": "💬🙌👇",
}


class MetadataGenerator:
    """Generate social-optimised metadata with UCB1 A/B selection and optional GPT enrichment."""

    CTA_STYLES = {
        "engagement": [
            "Comment your take",
            "Drop your opinion",
            "Tag a friend who needs this",
        ],
        "follow": ["Follow for more", "Save for later", "Turn on notifications 🔔"],
        "action": [
            "Try this today",
            "Use this strategy now",
            "Apply this in your next post",
        ],
        "curiosity": [
            "Wait for the ending",
            "You will not expect this",
            "The last part changes everything",
        ],
    }

    PLATFORM_TAGS = {
        "facebook_reels": "#facebookreels",
        "instagram_reels": "#instagramreels",
        "tiktok": "#tiktok #fyp",
        "youtube_shorts": "#youtubeshorts #shorts",
    }

    def __init__(self):
        self.memory_path = os.path.join(settings.data_dir, "ab_style_memory.json")
        os.makedirs(settings.data_dir, exist_ok=True)

    # ── Persistent A/B memory ─────────────────────────────────────────────────

    def _load_memory(self) -> Dict:
        if not os.path.exists(self.memory_path):
            return {"wins": {}, "plays": {}}
        try:
            with open(self.memory_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {"wins": {}, "plays": {}}

    def _save_memory(self, mem: Dict) -> None:
        with open(self.memory_path, "w", encoding="utf-8") as f:
            json.dump(mem, f, indent=2)

    def _ucb1_best_style(self) -> str:
        """UCB1 bandit — balances exploitation of winners with exploration of untried styles."""
        mem = self._load_memory()
        wins = mem.get("wins", {})
        plays = mem.get("plays", {})
        total_plays = sum(plays.get(s, 0) for s in self.CTA_STYLES)

        best_style, best_score = "curiosity", -1.0
        for style in self.CTA_STYLES:
            n = plays.get(style, 0)
            w = wins.get(style, 0)
            if n == 0:
                return style  # always try untried styles first
            mean = w / n
            explore = math.sqrt(2 * math.log(max(total_plays, 1)) / n)
            score = mean + explore
            if score > best_score:
                best_style, best_score = style, score
        return best_style

    def record_winner_style(self, cta_style: str) -> None:
        mem = self._load_memory()
        mem.setdefault("wins", {})[cta_style] = (
            mem.get("wins", {}).get(cta_style, 0) + 1
        )
        mem.setdefault("plays", {})[cta_style] = (
            mem.get("plays", {}).get(cta_style, 0) + 1
        )
        self._save_memory(mem)

    def record_play_style(self, cta_style: str) -> None:
        mem = self._load_memory()
        mem.setdefault("plays", {})[cta_style] = (
            mem.get("plays", {}).get(cta_style, 0) + 1
        )
        self._save_memory(mem)

    def export_ab_report(self) -> Dict:
        """Return win-rate table for all CTA styles."""
        mem = self._load_memory()
        report = {}
        for style in self.CTA_STYLES:
            plays = mem.get("plays", {}).get(style, 0)
            wins = mem.get("wins", {}).get(style, 0)
            report[style] = {
                "plays": plays,
                "wins": wins,
                "win_rate": round(wins / plays, 4) if plays > 0 else 0.0,
            }
        return report

    # ── Keyword extraction ────────────────────────────────────────────────────

    def _extract_keywords(self, title: str, description: str) -> List[str]:
        text = f"{title} {description}".lower()
        words = re.findall(r"[a-zA-Z][a-zA-Z0-9_]{3,}", text)
        stop = {
            "this",
            "that",
            "with",
            "from",
            "your",
            "have",
            "will",
            "about",
            "what",
            "when",
            "where",
            "there",
            "which",
            "they",
            "them",
            "then",
        }
        freq: Dict[str, int] = {}
        for w in words:
            if w not in stop:
                freq[w] = freq.get(w, 0) + 1
        return [
            w for w, _ in sorted(freq.items(), key=lambda x: x[1], reverse=True)[:6]
        ]

    # ── GPT metadata (optional) ───────────────────────────────────────────────

    def _generate_with_gpt(
        self, title: str, description: str, platform: str
    ) -> Optional[Dict]:
        if not (settings.enable_ai_metadata and settings.openai_api_key):
            return None
        try:
            from openai import OpenAI

            client = OpenAI(api_key=settings.openai_api_key)
            prompt = (
                f"You are a viral social media content strategist. "
                f"Given a video titled '{title}' with description '{description[:300]}', "
                f"targeting {platform}, generate a JSON object with keys: "
                "'hook' (max 80 chars), 'title' (max 60 chars), 'caption' (max 150 chars), "
                "'hashtags' (list of 6 strings without #). "
                "Make it punchy, curiosity-driven, and platform-optimised."
            )
            resp = client.chat.completions.create(
                model=settings.openai_model,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                max_tokens=300,
                temperature=0.85,
            )
            return json.loads(resp.choices[0].message.content)
        except Exception as exc:
            logger.warning("GPT metadata generation failed: %s", exc)
            return None

    # ── Emoji enrichment ──────────────────────────────────────────────────────

    @staticmethod
    def emoji_enrich(text: str, style: str) -> str:
        emojis = _EMOJI_MAP.get(style, "")
        if emojis and not any(e in text for e in emojis):
            text = text.rstrip(".") + " " + emojis[0]
        return text

    # ── Variant generation ────────────────────────────────────────────────────

    def generate_variants(
        self,
        source_title: str,
        source_description: str,
        variant_count: int = 3,
        platform: str = "facebook",
    ) -> List[MetadataVariant]:
        variant_count = max(2, min(4, variant_count))
        platform = normalize_platform_name(platform)
        if not is_supported_platform(platform):
            platform = "facebook_reels"

        keywords = self._extract_keywords(source_title, source_description)
        if not keywords:
            keywords = ["viral", "shorts", "creator"]

        # Try GPT first for the first variant
        gpt_data = self._generate_with_gpt(source_title, source_description, platform)

        best_style = self._ucb1_best_style()
        styles = [best_style] + [s for s in self.CTA_STYLES if s != best_style]
        base_topic = keywords[0].replace("_", " ").title()
        variants: List[MetadataVariant] = []

        for i in range(variant_count):
            style = styles[i % len(styles)]
            cta = random.choice(self.CTA_STYLES[style])

            if i == 0 and gpt_data:
                hook = gpt_data.get("hook", f"{base_topic}: watch this first")
                title = gpt_data.get("title", f"{base_topic} #{i+1}")
                caption = self.emoji_enrich(
                    f"{gpt_data.get('caption', hook)}. {cta}.", style
                )
                gpt_tags = [f"#{t.lstrip('#')}" for t in gpt_data.get("hashtags", [])]
                hashtags = list(
                    dict.fromkeys(gpt_tags + [self.PLATFORM_TAGS.get(platform, "")])
                )[:8]
            else:
                hook = self._make_hook(base_topic, style, platform)
                title = f"{base_topic} Strategy #{i + 1}"
                caption = self.emoji_enrich(f"{hook}. {cta}.", style)
                tag_pool = [f"#{k}" for k in keywords[:4]] + [
                    "#shorts",
                    "#viral",
                    "#content",
                ]
                pt = self.PLATFORM_TAGS.get(platform)
                if pt:
                    tag_pool.extend(pt.split())
                hashtags = list(dict.fromkeys(tag_pool))[:8]

            self.record_play_style(style)
            variants.append(
                MetadataVariant(
                    variant_label=f"V{i+1}",
                    cta_style=style,
                    hook_line=hook,
                    title=title,
                    caption=caption,
                    hashtags=hashtags,
                )
            )
        return variants

    def _make_hook(self, topic: str, style: str, platform: str) -> str:
        hooks = {
            "tiktok": f"{topic}: this is the fast version",
            "youtube_shorts": f"{topic}: quick breakdown",
            "instagram_reels": f"{topic}: reel-ready strategy",
        }
        if platform in hooks:
            return hooks[platform]
        if style in {"action", "follow"}:
            return f"{topic} in 60 seconds"
        return f"{topic}: watch this before your next post"
