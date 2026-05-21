"""Smart scheduler — generates optimal publishing slots based on engagement history."""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class PublishSlot:
    publish_at: datetime
    hour: int
    score: float


class SmartScheduler:
    """Predictive scheduler for optimal social media posting times."""

    def __init__(self):
        self.default_peak_hours = [11, 14, 18, 20]  # 11am, 2pm, 6pm, 8pm

    def infer_best_hours(self, history_uploads: List[Any], top_n: int = 3) -> List[int]:
        """Analyse past engagement to find the hours with the highest average engagement."""
        if not history_uploads:
            return self.default_peak_hours[:top_n]

        hour_stats = {}
        for upload in history_uploads:
            if not upload.uploaded_at or not upload.views:
                continue
            h = upload.uploaded_at.hour
            if h not in hour_stats:
                hour_stats[h] = {"views": 0, "count": 0}
            hour_stats[h]["views"] += upload.views
            hour_stats[h]["count"] += 1

        averages = []
        for h, stats in hour_stats.items():
            if stats["count"] >= 3:  # Only trust hours with at least 3 historical posts
                averages.append((h, stats["views"] / stats["count"]))

        if not averages:
            return self.default_peak_hours[:top_n]

        # Sort by highest average views
        averages.sort(key=lambda x: x[1], reverse=True)
        return [h for h, _ in averages[:top_n]]

    def avoid_duplicate_slots(
        self, existing_slots: List[datetime], candidate: datetime, gap_hours: int = 2
    ) -> bool:
        """Return False if candidate is within `gap_hours` of any existing slot."""
        for ex in existing_slots:
            if abs((ex - candidate).total_seconds()) < gap_hours * 3600:
                return False
        return True

    def recommend_slots(
        self,
        count: int = 3,
        days_ahead: int = 7,
        preferred_hours: Optional[List[int]] = None,
        history_uploads: Optional[List[Any]] = None,
        timezone_offset_minutes: int = 0,
        gap_hours: int = 2,
    ) -> List[PublishSlot]:
        """Generate a list of future publishing slots ranked by predicted engagement score."""
        now = datetime.utcnow()
        if timezone_offset_minutes:
            now += timedelta(minutes=timezone_offset_minutes)

        if preferred_hours:
            target_hours = preferred_hours
        elif history_uploads:
            target_hours = self.infer_best_hours(history_uploads)
        else:
            target_hours = self.default_peak_hours

        candidates = []
        # Generate all possible hour slots in the lookahead window
        for day in range(days_ahead):
            d = now.date() + timedelta(days=day)
            for h in range(24):
                dt = datetime(d.year, d.month, d.day, h, 0, 0)
                if dt > now + timedelta(hours=1):
                    # Base score starts high if it's a target hour
                    score = 1.0 if h in target_hours else 0.2
                    # Small penalty for slots too far in the future (decay)
                    score *= 1.0 - (day * 0.05)
                    candidates.append(PublishSlot(dt, h, score))

        # Sort candidates by score
        candidates.sort(key=lambda x: x.score, reverse=True)

        selected = []
        selected_dts = []
        for c in candidates:
            if len(selected) >= count:
                break
            if self.avoid_duplicate_slots(selected_dts, c.publish_at, gap_hours):
                selected.append(c)
                selected_dts.append(c.publish_at)

        # Sort chronological
        selected.sort(key=lambda x: x.publish_at)

        # Revert to UTC if offset was applied
        if timezone_offset_minutes:
            for s in selected:
                s.publish_at -= timedelta(minutes=timezone_offset_minutes)

        return selected
