"""Unit tests for ZAPI"""

import os
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

# Force testing environment before any app imports
os.environ["ENVIRONMENT"] = "testing"
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.api.main import app
from src.database.database import Base, get_db

# Setup test database
engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base.metadata.create_all(bind=engine)


def override_get_db():
    try:
        db = TestingSessionLocal()
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db


# Test fixtures
@pytest.fixture
def test_data_dir(tmp_path):
    """Create test data directory"""
    return tmp_path / "test_data"


@pytest.fixture
def mock_settings(monkeypatch):
    """Mock settings"""
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setenv("YOUTUBE_API_KEY", "test_key")
    monkeypatch.setenv("FACEBOOK_ACCESS_TOKEN", "test_token")
    monkeypatch.setenv("FACEBOOK_PAGE_ID", "test_page")


# Test YouTube Downloader
class TestYouTubeDownloader:
    def test_initialization(self):
        """Test downloader initialization"""
        from src.services.youtube_downloader import YouTubeDownloader

        downloader = YouTubeDownloader()
        assert downloader.output_dir is not None

    @patch("yt_dlp.YoutubeDL")
    def test_get_video_info(self, mock_ydl, mock_settings):
        """Test getting video info"""
        from src.services.youtube_downloader import YouTubeDownloader

        mock_instance = MagicMock()
        mock_instance.extract_info.return_value = {
            "id": "test123",
            "title": "Test Video",
            "description": "Test description",
            "duration": 300,
            "thumbnail": "http://thumb.jpg",
            "channel_id": "UCtest",
        }
        mock_ydl.return_value.__enter__.return_value = mock_instance

        downloader = YouTubeDownloader()
        info = downloader.get_video_info("https://youtube.com/watch?v=test123")

        assert info is not None
        assert info["youtube_id"] == "test123"
        assert info["title"] == "Test Video"


# Test Video Editor
class TestVideoEditor:
    def test_initialization(self):
        """Test editor initialization"""
        from src.services.video_editor import VideoEditor

        editor = VideoEditor()
        assert editor.output_dir is not None

    def test_extract_short_segments(self):
        """Test segment extraction"""
        from src.services.video_editor import VideoEditor

        editor = VideoEditor()
        # This would normally process a real video
        # For testing, we just verify the method exists
        assert hasattr(editor, "extract_short_segments")

    @patch(
        "src.services.video_editor.VideoEditor.detect_scenes", return_value=[10.0, 40.0]
    )
    @patch(
        "src.services.video_editor.VideoEditor.get_video_info",
        return_value={"duration": 120.0},
    )
    @patch("src.services.clip_scorer.AIClipScoringEngine.rank_segments")
    def test_extract_short_segments_uses_easy_best_default(
        self, mock_rank_segments, mock_get_info, mock_detect_scenes
    ):
        from src.services.video_editor import VideoEditor

        mock_rank_segments.return_value = [
            Mock(start=0.0, end=30.0),
        ]

        editor = VideoEditor()
        editor.extract_short_segments(
            "/tmp/video.mp4", short_duration=30, num_segments=1, context_text=""
        )

        assert mock_rank_segments.called
        _, kwargs = mock_rank_segments.call_args
        assert kwargs.get("selection_mode") == "easy_best"


# Test Caption Generator
class TestCaptionGenerator:
    def test_initialization(self):
        """Test caption generator initialization"""
        from src.services.caption_generator import CaptionGenerator

        gen = CaptionGenerator()
        assert gen.output_dir is not None

    def test_time_to_srt_format(self):
        """Test time format conversion"""
        from src.services.caption_generator import CaptionGenerator

        gen = CaptionGenerator()
        result = gen.time_to_srt_format(3665.5)  # 1h 1m 5.5s

        assert "01:01:05" in result
        assert "500" in result  # milliseconds


# Test Database Models
class TestDatabaseModels:
    def test_source_video_model(self):
        """Test SourceVideo model"""
        from src.database.models import SourceVideo, VideoStatusEnum

        video = SourceVideo(
            id="test_id",
            youtube_id="yt_123",
            title="Test",
            channel_id="ch_123",
            status=VideoStatusEnum.PENDING,
        )

        assert video.id == "test_id"
        assert video.status == VideoStatusEnum.PENDING

    def test_processed_short_model(self):
        """Test ProcessedShort model"""
        from src.database.models import ProcessedShort, VideoStatusEnum

        short = ProcessedShort(
            id="short_id",
            source_video_id="src_id",
            output_path="/path/to/short.mp4",
            status=VideoStatusEnum.PROCESSED,
        )

        assert short.id == "short_id"
        assert short.status == VideoStatusEnum.PROCESSED


# Test API endpoints
class TestVideoAPI:
    @pytest.mark.asyncio
    async def test_health_endpoint(self):
        """Test health endpoint"""
        from fastapi.testclient import TestClient

        from src.api.main import app

        client = TestClient(app)
        response = client.get("/health")

        assert response.status_code == 200
        assert response.json()["status"] == "healthy"

    @pytest.mark.asyncio
    async def test_root_endpoint(self):
        """Test root endpoint"""
        from fastapi.testclient import TestClient

        from src.api.main import app

        client = TestClient(app)
        response = client.get("/")

        assert response.status_code == 200
        assert "status" in response.json()

    def test_demo_endpoint(self):
        """Test ad-free demo endpoint"""
        from fastapi.testclient import TestClient

        from src.api.main import app

        client = TestClient(app)
        response = client.get("/demo")

        assert response.status_code == 200
        assert "ad-free demo" in response.text.lower()
        assert "open api docs" in response.text.lower()

    def test_advanced_platforms_endpoint(self):
        """Test platform profile listing"""
        from fastapi.testclient import TestClient

        from src.api.main import app

        client = TestClient(app)
        response = client.get("/api/advanced/platforms")

        assert response.status_code == 200
        assert response.json()["status"] == "success"
        assert response.json()["profiles"]

    def test_advanced_metadata_variants_endpoint(self):
        """Test metadata variant generation"""
        from fastapi.testclient import TestClient

        from src.api.main import app

        client = TestClient(app)
        response = client.post(
            "/api/advanced/metadata/variants",
            json={
                "source_title": "How to Grow on Facebook",
                "source_description": "A simple creator growth guide",
                "variant_count": 2,
                "platform": "facebook",
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "success"
        assert len(body["variants"]) == 2
        assert body["platform"] == "facebook_reels"
        assert "#facebookreels" in body["variants"][0]["hashtags"]

    def test_advanced_metadata_variants_rejects_invalid_platform(self):
        """Test metadata variant generation rejects invalid platform names"""
        from fastapi.testclient import TestClient

        from src.api.main import app

        client = TestClient(app)
        response = client.post(
            "/api/advanced/metadata/variants",
            json={
                "source_title": "How to Grow on Facebook",
                "source_description": "A simple creator growth guide",
                "variant_count": 2,
                "platform": "invalid_platform",
            },
        )

        assert response.status_code == 422
        assert response.json()["error"]["code"] == "HTTP_422"

    @patch("src.api.advanced.FileValidator.validate_video_path")
    @patch("src.api.advanced.AIClipScoringEngine.rank_segments")
    def test_advanced_clip_score_endpoint(self, mock_rank_segments, mock_validate_path):
        """Test clip scoring endpoint"""
        from fastapi.testclient import TestClient

        from src.api.main import app
        from src.services.clip_scorer import ClipScore

        mock_rank_segments.return_value = [
            ClipScore(
                start=0.0,
                end=12.0,
                hook_strength=0.8,
                motion=0.7,
                speech_density=0.6,
                sentiment=0.5,
                face_presence=0.5,
                audio_energy=0.5,
                total=0.69,
            )
        ]

        client = TestClient(app)
        response = client.post(
            "/api/advanced/clip-score",
            json={
                "video_path": "C:/tmp/video.mp4",
                "context_text": "Watch this before your next post",
                "candidates": [{"start": 0, "end": 12}],
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "success"
        assert body["count"] == 1
        assert body["scores"][0]["total"] == 0.69
        mock_validate_path.assert_called_once()
        mock_rank_segments.assert_called_once()

    @patch("src.api.advanced.ABTestingEngine.pick_winner")
    def test_advanced_ab_winner_endpoint(self, mock_pick_winner):
        """Test A/B winner endpoint"""
        from types import SimpleNamespace

        from fastapi.testclient import TestClient

        from src.api.main import app

        mock_pick_winner.return_value = SimpleNamespace(
            id="upload_1",
            facebook_video_id="fb_1",
            title="Winning Variant",
            cta_style="curiosity",
            variant_group_id="group_123",
            is_winner=True,
        )

        client = TestClient(app)
        response = client.post(
            "/api/advanced/ab/pick-winner",
            json={"variant_group_id": "group_123"},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "success"
        assert body["winner"]["id"] == "upload_1"
        assert body["winner"]["is_winner"] is True
        mock_pick_winner.assert_called_once()

    @patch(
        "src.api.advanced.VideoProcessor.process_youtube_url", return_value="source_123"
    )
    def test_advanced_process_with_platforms_endpoint(self, mock_process):
        """Test advanced processing endpoint with platform routing"""
        from fastapi.testclient import TestClient

        from src.api.main import app

        client = TestClient(app)
        response = client.post(
            "/api/advanced/process-with-platforms",
            json={
                "youtube_url": "https://youtube.com/watch?v=test123",
                "platforms": ["facebook", "instagram"],
                "num_shorts": 2,
                "create_shorts": True,
                "upload_to_facebook": True,
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "success"
        assert body["source_id"] == "source_123"
        mock_process.assert_called_once()

    def test_advanced_process_with_platforms_rejects_invalid_platform(self):
        """Test advanced processing endpoint rejects unsupported platforms"""
        from fastapi.testclient import TestClient

        from src.api.main import app

        client = TestClient(app)
        response = client.post(
            "/api/advanced/process-with-platforms",
            json={
                "youtube_url": "https://youtube.com/watch?v=test123",
                "platforms": ["facebook", "unknown_platform"],
                "num_shorts": 2,
                "create_shorts": True,
                "upload_to_facebook": True,
            },
        )

        assert response.status_code == 422
        body = response.json()
        assert body["error"]["code"] == "HTTP_422"

    def test_analytics_dashboard_endpoint(self):
        """Test consolidated analytics dashboard endpoint"""
        from fastapi.testclient import TestClient

        from src.api.main import app

        client = TestClient(app)
        response = client.get("/api/analytics/dashboard")

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "success"
        assert "pipeline" in body
        assert "source_videos" in body["pipeline"]
        assert "processed_shorts" in body["pipeline"]
        assert "successful_uploads" in body["pipeline"]
        assert "total_source_hours" in body["pipeline"]
        assert "engagement" in body
        assert "total_views" in body["engagement"]
        assert "total_likes" in body["engagement"]
        assert "avg_views_per_video" in body["engagement"]
        assert "avg_engagement_rate" in body["engagement"]

    def test_scheduling_preview_endpoint(self):
        """Test smart scheduling preview endpoint"""
        from fastapi.testclient import TestClient

        from src.api.main import app

        client = TestClient(app)
        response = client.post(
            "/api/scheduling/preview",
            json={
                "count": 3,
                "days_ahead": 7,
                "history_days": 30,
                "preferred_hours": [9, 18],
                "timezone_offset_minutes": 0,
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "success"
        assert body["count"] == 3
        assert len(body["recommended_slots"]) == 3
        assert all("publish_at" in slot for slot in body["recommended_slots"])

    @patch(
        "src.api.scheduling.FacebookUploader.upload_video", return_value="fb_sched_123"
    )
    def test_scheduling_publish_endpoint(self, mock_upload_video):
        """Test scheduled publishing of a processed short"""
        from datetime import datetime, timedelta
        from types import SimpleNamespace

        from fastapi.testclient import TestClient

        from src.api.main import app
        from src.database.database import get_db
        from src.database.models import VideoStatusEnum

        future_time = datetime.utcnow() + timedelta(hours=5)
        source_video = SimpleNamespace(
            title="Scheduled Source Title", description="Scheduled source description"
        )
        processed_short = SimpleNamespace(
            id="short_sched_1",
            output_path="C:/tmp/short.mp4",
            output_filename="short_sched_1.mp4",
            status=VideoStatusEnum.PROCESSED,
            variant_group_id="vg_sched_1",
            source_video=source_video,
        )

        class FakeQuery:
            def __init__(self, model):
                self.model = model

            def filter(self, *args, **kwargs):
                return self

            def first(self):
                if getattr(self.model, "__name__", "") == "ProcessedShort":
                    return processed_short
                return None

        class FakeDB:
            def query(self, model):
                return FakeQuery(model)

            def add(self, obj):
                self.added = obj

            def commit(self):
                self.committed = True

            def refresh(self, obj):
                self.refreshed = obj

        fake_db = FakeDB()
        app.dependency_overrides[get_db] = lambda: fake_db

        try:
            client = TestClient(app)
            response = client.post(
                "/api/scheduling/publish",
                json={
                    "processed_short_id": "short_sched_1",
                    "schedule_time": future_time.isoformat(),
                    "platform": "facebook",
                    "title": "Scheduled Hook",
                    "description": "Scheduled description",
                    "hashtags": ["#schedule", "creator"],
                },
            )

            assert response.status_code == 200
            body = response.json()
            assert body["status"] == "success"
            assert body["facebook_video_id"] == "fb_sched_123"
            assert body["platform"] == "facebook_reels"
            assert body["scheduled_for"].endswith("Z")
            mock_upload_video.assert_called_once()
        finally:
            app.dependency_overrides.pop(get_db, None)


# Test utilities
class TestUtilities:
    def test_settings_loading(self, mock_settings):
        """Test settings are loaded correctly"""
        from src.config.settings import Settings

        settings = Settings()

        assert settings.database_url is not None
        assert settings.youtube_api_key == "test_key"

    def test_default_youtube_channel_is_configured(self):
        """Test the permanent default YouTube channel is configured"""
        from src.config.settings import Settings

        settings = Settings()

        assert any(
            channel == "https://youtube.com/@storylinemovie?si=N7XMWqmBXBSYn9Yw"
            for channel in settings.youtube_channel_ids
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
