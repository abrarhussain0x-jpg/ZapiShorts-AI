"""CLI tests for ZAPI."""

from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from click.testing import CliRunner

from cli import cli


class TestCLI:
    def test_help_includes_key_commands(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])

        assert result.exit_code == 0
        assert "doctor" in result.output
        assert "serve" in result.output
        assert "routes" in result.output
        assert "schedule-preview" in result.output
        assert "schedule-publish" in result.output

    def test_routes_lists_api_paths(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["routes"])

        assert result.exit_code == 0
        assert "/health" in result.output
        assert "/api/advanced/platforms" in result.output
        assert "/api/scheduling/preview" in result.output

    def test_doctor_json_output(self, monkeypatch):
        import setup as setup_checks

        monkeypatch.setattr(setup_checks, "check_python_version", lambda: True)
        monkeypatch.setattr(setup_checks, "check_dependencies", lambda: True)
        monkeypatch.setattr(setup_checks, "check_system_tools", lambda: True)
        monkeypatch.setattr(setup_checks, "check_env_file", lambda: True)
        monkeypatch.setattr(setup_checks, "check_env_variables", lambda: True)
        monkeypatch.setattr(setup_checks, "check_directories", lambda: True)

        runner = CliRunner()
        result = runner.invoke(cli, ["doctor", "--json-output"])

        assert result.exit_code == 0
        assert '"passed": true' in result.output.lower()
        assert '"check": "python"' in result.output.lower()

    def test_schedule_preview_command(self):
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "schedule-preview",
                "--count",
                "2",
                "--days-ahead",
                "7",
                "--history-days",
                "30",
                "--preferred-hours",
                "9,18",
            ],
        )

        assert result.exit_code == 0
        assert "Schedule Preview" in result.output
        assert "hour=" in result.output

    def test_schedule_publish_command(self, monkeypatch):
        import cli as cli_module
        from src.database.models import VideoStatusEnum

        future_time = datetime.utcnow() + timedelta(hours=4)
        source_video = SimpleNamespace(title="CLI Title", description="CLI Description")
        processed_short = SimpleNamespace(
            id="short_cli_1",
            output_path="C:/tmp/short.mp4",
            output_filename="short_cli_1.mp4",
            status=VideoStatusEnum.PROCESSED,
            variant_group_id="vg_cli_1",
            source_video=source_video,
        )

        class FakeQuery:
            def __init__(self, model):
                self.model = model

            def filter(self, *args, **kwargs):
                return self

            def first(self):
                return (
                    processed_short
                    if getattr(self.model, "__name__", "") == "ProcessedShort"
                    else None
                )

        class FakeDB:
            def query(self, model):
                return FakeQuery(model)

            def add(self, obj):
                self.added = obj

            def commit(self):
                self.committed = True

            def refresh(self, obj):
                self.refreshed = obj

            def close(self):
                pass

        monkeypatch.setattr(cli_module, "SessionLocal", lambda: FakeDB())
        monkeypatch.setattr(
            cli_module,
            "execute_publish_scheduled_short",
            lambda **kwargs: {
                "status": "success",
                "upload_id": "upload_123",
                "facebook_video_id": "fb_123",
                "scheduled_for": future_time.isoformat() + "Z",
                "platform": "facebook_reels",
                "idempotency_key": "abc123",
                "message": "Short scheduled for Facebook upload",
            },
        )

        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "schedule-publish",
                "--processed-short-id",
                "short_cli_1",
                "--when",
                future_time.isoformat(),
                "--platform",
                "facebook",
                "--title",
                "CLI Scheduled Title",
                "--description",
                "CLI Scheduled Description",
                "--hashtag",
                "creator",
                "--hashtag",
                "zapi",
            ],
        )

        assert result.exit_code == 0
        assert "Schedule Publish" in result.output
        assert "upload_123" in result.output
        assert "facebook_reels" in result.output

    def test_clip_command_creates_shorts(self, monkeypatch, tmp_path):
        import cli as cli_module

        video_path = tmp_path / "sample.mp4"
        video_path.write_bytes(b"fake video")

        class FakeEditor:
            def extract_short_segments(
                self,
                video_path,
                short_duration=60,
                num_segments=3,
                context_text="",
                selection_mode=None,
            ):
                return [(0.0, 12.0), (20.0, 32.0)]

            def create_short(
                self,
                video_path,
                output_path,
                start_time=0,
                duration=60,
                add_captions=False,
                caption_file=None,
                target_width=None,
                target_height=None,
                target_fps=None,
                target_bitrate=None,
                watermark_text=None,
            ):
                Path(output_path).write_bytes(b"short")
                return True

        monkeypatch.setattr(cli_module, "VideoEditor", lambda: FakeEditor())
        monkeypatch.setattr(cli_module.settings, "output_dir", str(tmp_path / "output"))

        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "clip",
                "--video-path",
                str(video_path),
                "--count",
                "2",
                "--duration",
                "12",
                "--selection-mode",
                "easy_best",
                "--context-text",
                "make it easy best",
            ],
        )

        assert result.exit_code == 0
        assert "Clipping video" in result.output
        assert "Created 2 short(s)" in result.output
        assert any((tmp_path / "output").glob("sample__clip_01__*.mp4"))
        assert any((tmp_path / "output").glob("sample__clip_02__*.mp4"))

    def test_clip_command_latest_download_preview(self, monkeypatch, tmp_path):
        import cli as cli_module

        downloads_dir = tmp_path / "downloads"
        downloads_dir.mkdir()
        old_file = downloads_dir / "old.mp4"
        new_file = downloads_dir / "new.mp4"
        old_file.write_bytes(b"old")
        new_file.write_bytes(b"new")

        old_mtime = datetime.utcnow().timestamp() - 100
        new_mtime = datetime.utcnow().timestamp()
        old_file.touch()
        new_file.touch()
        Path(old_file).touch()
        Path(new_file).touch()
        os = __import__("os")
        os.utime(old_file, (old_mtime, old_mtime))
        os.utime(new_file, (new_mtime, new_mtime))

        class FakeEditor:
            def extract_short_segments(
                self,
                video_path,
                short_duration=60,
                num_segments=3,
                context_text="",
                selection_mode=None,
            ):
                assert Path(video_path).name == "new.mp4"
                return [(2.0, 14.0)]

            def create_short(
                self,
                video_path,
                output_path,
                start_time=0,
                duration=60,
                add_captions=False,
                caption_file=None,
                target_width=None,
                target_height=None,
                target_fps=None,
                target_bitrate=None,
                watermark_text=None,
            ):
                Path(output_path).write_bytes(b"short")
                return True

        monkeypatch.setattr(cli_module, "VideoEditor", lambda: FakeEditor())
        monkeypatch.setattr(cli_module.settings, "downloads_dir", str(downloads_dir))
        monkeypatch.setattr(cli_module.settings, "output_dir", str(tmp_path / "output"))

        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "clip",
                "--latest-download",
                "--preview",
                "--count",
                "1",
                "--duration",
                "12",
            ],
        )

        assert result.exit_code == 0
        assert "Latest download" in result.output
        assert "Clip preview" in result.output
        assert "Created 1 short(s)" in result.output
        assert any((tmp_path / "output").glob("new__clip_01__*.mp4"))

    def test_shorts_command_creates_outputs(self, monkeypatch, tmp_path):
        import cli as cli_module

        video_path = tmp_path / "source.mp4"
        video_path.write_bytes(b"fake video")

        class FakeEditor:
            def extract_short_segments(
                self,
                video_path,
                short_duration=60,
                num_segments=3,
                context_text="",
                selection_mode=None,
            ):
                assert Path(video_path).name == "source.mp4"
                return [(0.0, 10.0), (15.0, 27.0), (30.0, 42.0)]

            def create_short(
                self,
                video_path,
                output_path,
                start_time=0,
                duration=60,
                add_captions=False,
                caption_file=None,
                target_width=None,
                target_height=None,
                target_fps=None,
                target_bitrate=None,
                watermark_text=None,
            ):
                Path(output_path).write_bytes(b"short")
                return True

        monkeypatch.setattr(cli_module, "VideoEditor", lambda: FakeEditor())
        monkeypatch.setattr(cli_module.settings, "output_dir", str(tmp_path / "output"))

        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "shorts",
                str(video_path),
                "--count",
                "3",
                "--duration",
                "12",
            ],
        )

        assert result.exit_code == 0
        assert "Quick Shorts Generator" in result.output
        assert "Shorts generated successfully" in result.output
        assert any((tmp_path / "output").glob("source__shorts_01__*.mp4"))
        assert any((tmp_path / "output").glob("source__shorts_02__*.mp4"))
        assert any((tmp_path / "output").glob("source__shorts_03__*.mp4"))

    def test_deep_command_runs_end_to_end(self, monkeypatch, tmp_path):
        import cli as cli_module

        downloads_dir = tmp_path / "downloads"
        downloads_dir.mkdir()
        video_path = downloads_dir / "latest.mp4"
        video_path.write_bytes(b"latest")

        class FakeEditor:
            def extract_short_segments(
                self,
                video_path,
                short_duration=60,
                num_segments=3,
                context_text="",
                selection_mode=None,
            ):
                assert Path(video_path).name == "latest.mp4"
                return [(1.0, 11.0), (20.0, 30.0)]

            def create_short(
                self,
                video_path,
                output_path,
                start_time=0,
                duration=60,
                add_captions=False,
                caption_file=None,
                target_width=None,
                target_height=None,
                target_fps=None,
                target_bitrate=None,
                watermark_text=None,
            ):
                Path(output_path).write_bytes(b"rendered")
                return True

        monkeypatch.setattr(cli_module, "VideoEditor", lambda: FakeEditor())
        monkeypatch.setattr(cli_module.settings, "downloads_dir", str(downloads_dir))
        monkeypatch.setattr(cli_module.settings, "output_dir", str(tmp_path / "output"))
        monkeypatch.setattr(
            cli_module,
            "_run_readiness_checks",
            lambda: {"passed": True, "checks": [{"check": "python", "passed": True}]},
        )

        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "deep",
                "--latest-download",
                "--count",
                "2",
                "--duration",
                "10",
                "--selection-mode",
                "easy_best",
                "--preview",
                "--render",
            ],
        )

        assert result.exit_code == 0
        assert "Deep workflow" in result.output
        assert "Deep workflow summary" in result.output
        assert "Stage timings" in result.output
        assert "PASS" in result.output
        assert any((tmp_path / "output").glob("latest__deep_01__*.mp4"))
        assert any((tmp_path / "output").glob("latest__deep_02__*.mp4"))

    def test_deep_command_can_upload(self, monkeypatch, tmp_path):
        import cli as cli_module

        downloads_dir = tmp_path / "downloads"
        downloads_dir.mkdir()
        video_path = downloads_dir / "latest.mp4"
        video_path.write_bytes(b"latest")

        class FakeEditor:
            def extract_short_segments(
                self,
                video_path,
                short_duration=60,
                num_segments=3,
                context_text="",
                selection_mode=None,
            ):
                return [(1.0, 11.0)]

            def create_short(
                self,
                video_path,
                output_path,
                start_time=0,
                duration=60,
                add_captions=False,
                caption_file=None,
                target_width=None,
                target_height=None,
                target_fps=None,
                target_bitrate=None,
                watermark_text=None,
            ):
                Path(output_path).write_bytes(b"rendered")
                return True

        class FakeUploader:
            def upload_video(
                self,
                video_path,
                title,
                description="",
                schedule_time=None,
                is_reels=True,
            ):
                assert Path(video_path).exists()
                return "fb_video_123"

        monkeypatch.setattr(cli_module, "VideoEditor", lambda: FakeEditor())
        monkeypatch.setattr(cli_module, "FacebookUploader", lambda: FakeUploader())
        monkeypatch.setattr(cli_module.settings, "downloads_dir", str(downloads_dir))
        monkeypatch.setattr(cli_module.settings, "output_dir", str(tmp_path / "output"))
        monkeypatch.setattr(
            cli_module,
            "_run_readiness_checks",
            lambda: {"passed": True, "checks": [{"check": "python", "passed": True}]},
        )

        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "deep",
                "--latest-download",
                "--count",
                "1",
                "--duration",
                "10",
                "--selection-mode",
                "easy_best",
                "--upload",
                "--no-preview",
                "--render",
            ],
        )

        assert result.exit_code == 0
        assert "Uploaded shorts" in result.output
        assert "Stage timings" in result.output
        assert "PASS" in result.output
        assert any((tmp_path / "output").glob("latest__deep_01__*.mp4"))
