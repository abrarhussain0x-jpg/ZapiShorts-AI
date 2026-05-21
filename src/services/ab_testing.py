"""Auto A/B testing helpers for variants and winner selection."""

import logging
from typing import List, Optional

from sqlalchemy.orm import Session

from src.database.models import FacebookUpload
from src.services.metadata_generator import MetadataGenerator

logger = logging.getLogger(__name__)


class ABTestingEngine:
    """Tracks A/B variants and picks winner by weighted engagement."""

    def __init__(self):
        self.meta_gen = MetadataGenerator()

    @staticmethod
    def performance_score(upload: FacebookUpload) -> float:
        watch_time_proxy = float(upload.views or 0)
        engagement = float(upload.engagement_rate or 0)
        shares = float(upload.shares or 0)
        return (0.5 * watch_time_proxy) + (0.35 * engagement) + (0.15 * shares)

    def pick_winner(
        self, db: Session, variant_group_id: str
    ) -> Optional[FacebookUpload]:
        variants: List[FacebookUpload] = (
            db.query(FacebookUpload)
            .filter(FacebookUpload.variant_group_id == variant_group_id)
            .all()
        )

        if not variants:
            return None

        winner = max(variants, key=self.performance_score)
        for v in variants:
            v.is_winner = v.id == winner.id

        if winner.cta_style:
            self.meta_gen.record_winner_style(winner.cta_style)

        db.commit()
        logger.info("A/B winner selected for group %s: %s", variant_group_id, winner.id)
        return winner
