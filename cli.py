"""Command-line interface for ZAPI."""

from __future__ import annotations

import builtins
import json
import logging
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
import shutil

stdout_encoding = getattr(sys.stdout, "encoding", None)
if not stdout_encoding or stdout_encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError, OSError):
        pass


def _remove_shadowing_src_path() -> None:
    repo_src = os.path.normcase(
        str((Path(__file__).resolve().parent / "src").resolve())
    )
    cleaned_paths = []
    for entry in sys.path:
        if not entry:
            cleaned_paths.append(entry)
            continue
        try:
            entry_path = os.path.normcase(str(Path(entry).resolve()))
        except Exception:
            cleaned_paths.append(entry)
            continue
        if entry_path != repo_src:
            cleaned_paths.append(entry)
    sys.path[:] = cleaned_paths


_remove_shadowing_src_path()

import queue as _stdlib_queue  # noqa: F401

import click
from dotenv import load_dotenv
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.progress import (BarColumn, Progress, SpinnerColumn, TextColumn,
                           TimeElapsedColumn)
from rich.table import Table
from rich.text import Text
from sqlalchemy.exc import OperationalError

from src.api.scheduling import (build_schedule_preview,
                                execute_publish_scheduled_short)
from src.config.settings import Settings, settings
from src.database.database import SessionLocal
from src.database.database import init_db as init_database
from src.database.models import (FacebookUpload, ProcessedShort, SourceVideo,
                                 VideoStatusEnum)
from src.job_queue.job_queue import get_worker_stats
from src.services.facebook_uploader import FacebookUploader
from src.services.smart_scheduler import SmartScheduler
from src.services.video_editor import VideoEditor

logger = logging.getLogger(__name__)
console = Console()


def _configure_logging(verbosity: int, quietness: int) -> None:
    level = logging.INFO
    if verbosity > 0:
        level = logging.DEBUG
    if quietness > 0:
        level = logging.WARNING
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )


def _load_environment(env_file: Path) -> None:
    load_dotenv(dotenv_path=env_file, override=False)


def _echo_json(payload: Dict[str, Any]) -> None:
    click.echo(json.dumps(payload, indent=2, default=str))


def _unwrap_quotes(value: Optional[str]) -> Optional[str]:
    """Remove surrounding single/double quotes and trim whitespace from input."""
    if value is None:
        return None
    v = value.strip()
    if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
        v = v[1:-1].strip()
    return v


def _safe_int(value: Optional[str], default: int) -> int:
    try:
        return int(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def _parse_iso_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    normalized = value.strip().replace("Z", "+00:00")
    return datetime.fromisoformat(normalized)


def _format_count_line(label: str, value: Any) -> str:
    return f"{label:<24} {value}"


def _rich_enabled() -> bool:
    return True


def _section_title(title: str, subtitle: str = "") -> Text:
    text = Text(title, style="bold cyan")
    if subtitle:
        text.append(f"  {subtitle}", style="dim")
    return text


def _print_panel(title: str, body: str, subtitle: str = "") -> None:
    console.print(
        Panel(
            body,
            title=title,
            subtitle=subtitle or None,
            border_style="cyan",
            box=box.ROUNDED,
            padding=(1, 2),
        )
    )


def _print_kv_table(title: str, rows: List[tuple[str, Any]]) -> None:
    table = Table(
        title=title,
        box=box.ROUNDED,
        border_style="cyan",
        show_header=False,
        pad_edge=False,
    )
    table.add_column("Label", style="bold white")
    table.add_column("Value", style="green")
    for label, value in rows:
        table.add_row(label, str(value))
    console.print(table)


def _print_banner() -> None:
    body = (
        "[bold white]ZAPI[/bold white]\n"
        "[dim]YouTube → Shorts → Facebook[/dim]\n\n"
        "[bold cyan]Fast lane[/bold cyan]\n"
        "• [green]process[/green]  Create shorts from a YouTube URL\n"
        "• [green]shorts[/green]  Quick Shorts Generator\n"
        "• [green]exit[/green]  Exit interactive menu"
    )
    _print_panel(
        "Claude-style terminal", body, subtitle="Built for fast operator workflow"
    )


def _print_command_hint() -> None:
    console.print(
        "[dim]Tip:[/dim] run [bold]zapi --help[/bold] for the full command list or [bold]zapi <command> --help[/bold] for details."
    )


def _print_helpful_header() -> None:
    click.echo("ZAPI CLI")
    click.echo(
        "One command surface for setup, scheduling, processing, and diagnostics.\n"
    )


@click.group(
    context_settings={"help_option_names": ["-h", "--help"]},
    invoke_without_command=True,
)
@click.option(
    "--env-file",
    type=click.Path(path_type=Path),
    default=Path(".env"),
    show_default=True,
    help="Load variables from a custom .env file",
)
@click.option("-v", "--verbose", count=True, help="Increase log verbosity")
@click.option("-q", "--quiet", count=True, help="Reduce log verbosity")
@click.option(
    "--beginner/--no-beginner",
    default=False,
    help="Show beginner help panel in interactive mode",
)
@click.pass_context
def cli(
    ctx: click.Context, env_file: Path, verbose: int, quiet: int, beginner: bool
) -> None:
    """ZAPI - YouTube to Facebook automation CLI."""
    _load_environment(env_file)
    _configure_logging(verbose, quiet)
    ctx.ensure_object(dict)
    ctx.obj.update(
        {"env_file": env_file, "verbose": verbose, "quiet": quiet, "beginner": beginner}
    )

    if ctx.invoked_subcommand is None:
        _print_banner()
        console.print("\n[bold cyan]Interactive Menu[/bold cyan]")
        if ctx.obj.get("beginner"):
            help_body = (
                "How it works:\n"
                "1) process: download YouTube URL → processor creates shorts\n"
                "2) shorts: local file / URL / browse downloads → editor extracts + renders\n\n"
                "Flow:\n"
                "  YouTube URL → [YouTubeDownloader] → downloaded file → [VideoProcessor/VideoEditor] → shorts\n"
                "  Local file  → [VideoEditor.extract_short_segments] → render shorts → output folder\n"
            )
            _print_panel(
                "Beginner Guide", help_body, subtitle="Quick workflow overview"
            )
        console.print(
            "  [bold green]1.[/bold green] 🎬 Process YouTube Video (process)"
        )
        console.print(
            "  [bold green]2.[/bold green] ⚡ Quick Shorts Generator (shorts)"
        )
        console.print("  [bold green]3.[/bold green] ❌ Exit")

        from rich.prompt import Prompt

        choice = Prompt.ask(
            "\n[bold cyan]Select an option[/bold cyan]",
            choices=["1", "2", "3"],
            default="3",
            show_choices=False,
        )

        if choice == "1":
            url = Prompt.ask("[cyan]Enter YouTube URL[/cyan]")
            url = _unwrap_quotes(url)
            ctx.invoke(
                process, url=url, shorts=3, platforms="", upload=False, no_shorts=False
            )
        elif choice == "2":
            input_val = Prompt.ask(
                "[cyan]Enter local video file path, YouTube URL, or type 'browse' to choose from downloads[/cyan]"
            )
            input_val = _unwrap_quotes(input_val) or ""
            count = _safe_int(
                Prompt.ask("[cyan]How many shorts[/cyan]", default="3"), 3
            )
            duration_input = Prompt.ask(
                "[cyan]Choose short duration (seconds) or 'default'/'45'/'25'[/cyan]",
                default="default",
                show_choices=False,
            )
            duration_input = (duration_input or "").strip().lower()
            if duration_input.isdigit():
                duration = int(duration_input)
            elif duration_input == "45":
                duration = 45
            elif duration_input == "25":
                duration = 25
            else:
                duration = settings.short_video_duration

            low = input_val.strip().lower()
            if low in ("browse", "choose", "downloads"):
                downloads_dir = Path(settings.downloads_dir)
                candidates = [
                    p
                    for p in downloads_dir.iterdir()
                    if p.is_file()
                    and p.suffix.lower() in {".mp4", ".mov", ".mkv", ".webm", ".m4v"}
                ]
                selected = _select_available_video(candidates)
                if not selected:
                    console.print("[red]FAIL[/red] No video selected")
                    raise SystemExit(1)
                video_file = selected
                ctx.invoke(
                    shorts,
                    video_file=video_file,
                    url=None,
                    count=count,
                    duration=duration,
                    output_dir=None,
                )
            elif low.startswith("http"):
                ctx.invoke(
                    shorts,
                    video_file=None,
                    url=_unwrap_quotes(input_val),
                    count=count,
                    duration=duration,
                    output_dir=None,
                )
            else:
                video_file = Path(input_val)
                ctx.invoke(
                    shorts,
                    video_file=video_file,
                    url=None,
                    count=count,
                    duration=duration,
                    output_dir=None,
                )
        else:
            console.print("[dim]Goodbye![/dim]")


@cli.command()
@click.option("--json-output", is_flag=True, help="Emit machine-readable output")
def doctor(json_output: bool) -> None:
    """Run a deep local readiness check."""
    from setup import (check_dependencies, check_directories, check_env_file,
                       check_env_variables, check_python_version,
                       check_system_tools)

    checks = [
        ("python", check_python_version),
        ("dependencies", check_dependencies),
        ("system_tools", check_system_tools),
        ("env_file", check_env_file),
        ("env_variables", check_env_variables),
        ("directories", check_directories),
    ]

    results: List[Dict[str, Any]] = []
    for name, check in checks:
        try:
            result = bool(check())
            results.append({"check": name, "passed": result})
        except Exception as exc:
            results.append({"check": name, "passed": False, "error": str(exc)})

    passed = builtins.all(item["passed"] for item in results)

    if json_output:
        _echo_json({"passed": passed, "checks": results})
    else:
        _print_panel(
            "Doctor",
            "Readiness check for Python, dependencies, tools, environment, and directories.",
            subtitle="Fast terminal diagnostics",
        )
        table = Table(box=box.ROUNDED, border_style="cyan", title="Readiness checks")
        table.add_column("Check", style="bold white")
        table.add_column("Status", style="white")
        table.add_column("Details", style="dim")
        for item in results:
            status_text = "[green]PASS[/green]" if item["passed"] else "[red]FAIL[/red]"
            table.add_row(item["check"], status_text, item.get("error", ""))
        console.print(table)
        console.print(f"[bold]{'Overall: PASS' if passed else 'Overall: FAIL'}[/bold]")

    raise SystemExit(0 if passed else 1)


@cli.command()
@click.option("--host", default=settings.api_host, show_default=True, help="Bind host")
@click.option(
    "--port", default=settings.api_port, show_default=True, type=int, help="Bind port"
)
@click.option(
    "--reload/--no-reload",
    default=settings.debug,
    show_default=True,
    help="Enable code reload",
)
@click.option("--workers", default=1, type=int, show_default=True, help="Worker count")
def serve(host: str, port: int, reload: bool, workers: int) -> None:
    """Start the FastAPI app with uvicorn."""
    import uvicorn

    uvicorn.run(
        "src.api.main:app",
        host=host,
        port=port,
        reload=reload,
        workers=workers if not reload else 1,
    )


@cli.command()
@click.option("--prefix", default="", help="Only show routes starting with this prefix")
def routes(prefix: str) -> None:
    """List the registered API routes."""
    from src.api.main import app

    _print_panel(
        "Routes",
        "Registered API routes with methods and paths.",
        subtitle="API surface",
    )
    table = Table(box=box.ROUNDED, border_style="cyan")
    table.add_column("Methods", style="cyan", no_wrap=True)
    table.add_column("Path", style="bold white")
    table.add_column("Description", style="dim")
    count = 0
    for route in app.routes:
        path = getattr(route, "path", "")
        if prefix and not path.startswith(prefix):
            continue
        methods = ",".join(sorted(getattr(route, "methods", []) or []))
        if not methods:
            continue
        count += 1
        table.add_row(methods, path, "")
    console.print(table)
    console.print(f"[bold]Total:[/bold] {count}")


@cli.command()
@click.option("--json-output", is_flag=True, help="Emit machine-readable output")
@click.option(
    "--days",
    default=30,
    type=int,
    show_default=True,
    help="History window for scheduling preview",
)
def status(json_output: bool, days: int) -> None:
    """Show an operator-friendly system status snapshot."""
    db = SessionLocal()
    try:
        try:
            total_videos = db.query(SourceVideo).count()
            processed_videos = (
                db.query(SourceVideo)
                .filter(SourceVideo.status == VideoStatusEnum.PROCESSED)
                .count()
            )
            failed_videos = (
                db.query(SourceVideo)
                .filter(SourceVideo.status == VideoStatusEnum.FAILED)
                .count()
            )
            total_shorts = db.query(ProcessedShort).count()
            total_uploads = db.query(FacebookUpload).count()
            uploaded = (
                db.query(FacebookUpload)
                .filter(FacebookUpload.status == VideoStatusEnum.UPLOADED)
                .count()
            )
            scheduled = (
                db.query(FacebookUpload)
                .filter(FacebookUpload.scheduled_for != None)
                .count()
            )
            schedule_preview = build_schedule_preview(
                db=db, count=3, days_ahead=7, history_days=days
            )
        except OperationalError:
            total_videos = processed_videos = failed_videos = 0
            total_shorts = total_uploads = uploaded = scheduled = 0
            schedule_preview = {
                "status": "success",
                "source": "default",
                "count": 0,
                "history_samples": 0,
                "best_hours": [],
                "recommended_slots": [],
            }

        try:
            queue_stats = get_worker_stats()
            queue_tasks: int = queue_stats.get("tasks", 0)
        except Exception:
            queue_tasks = 0

        payload = {
            "videos": {
                "total": total_videos,
                "processed": processed_videos,
                "failed": failed_videos,
            },
            "shorts": {"total": total_shorts},
            "uploads": {
                "total": total_uploads,
                "uploaded": uploaded,
                "scheduled": scheduled,
            },
            "queue": {"active_jobs": queue_tasks},
            "scheduling": schedule_preview,
        }

        if json_output:
            _echo_json(payload)
        else:
            _print_panel(
                "Status",
                "Current system snapshot with video, short, upload, queue, and scheduling counts.",
                subtitle="Operator view",
            )
            _print_kv_table(
                "Summary",
                [
                    ("Source videos", total_videos),
                    ("Processed videos", processed_videos),
                    ("Failed videos", failed_videos),
                    ("Processed shorts", total_shorts),
                    ("Facebook uploads", total_uploads),
                    ("Uploaded", uploaded),
                    ("Scheduled", scheduled),
                    ("Active queue jobs", queue_tasks),
                ],
            )
            console.print("[bold cyan]Top schedule slots[/bold cyan]")
            for slot in schedule_preview.get("recommended_slots", []):
                console.print(
                    f"  • {slot['publish_at']}  [green]score={slot['score']}[/green]"
                )
    finally:
        db.close()


@cli.command()
@click.option("--url", prompt="YouTube URL", help="YouTube video URL to process")
@click.option(
    "--shorts",
    type=int,
    default=3,
    show_default=True,
    help="Number of shorts to create",
)
@click.option(
    "--platforms",
    default="",
    help="Comma-separated platform targets, like facebook,instagram",
)
@click.option(
    "--upload/--no-upload",
    default=True,
    show_default=True,
    help="Upload to Facebook after processing",
)
@click.option("--no-shorts", is_flag=True, help="Download only, skip short creation")
def process(
    url: str, shorts: int, platforms: str, upload: bool, no_shorts: bool
) -> None:
    """Process a YouTube video into shorts."""
    try:
        from src.core.processor import VideoProcessor

        target_platforms = [
            item.strip() for item in platforms.split(",") if item.strip()
        ] or None
        db = SessionLocal()
        try:
            processor = VideoProcessor()
            source_id = processor.process_youtube_url(
                url,
                db,
                create_shorts=not no_shorts,
                upload_to_facebook=upload,
                num_shorts=shorts,
                platforms=target_platforms,
            )
        finally:
            db.close()

        if source_id:
            console.print(
                f"[green]PASS[/green] Processing started: [bold]{source_id}[/bold]"
            )
        else:
            console.print("[red]FAIL[/red] Processing did not start")
            raise SystemExit(1)
    except Exception as exc:
        console.print(f"[red]FAIL[/red] Error: {exc}")
        raise SystemExit(1)


@cli.command()
@click.argument(
    "video_file", required=False, type=click.Path(exists=True, path_type=Path)
)
@click.option("--url", default=None, help="YouTube URL to download and process")
@click.option(
    "--count", default=3, type=int, show_default=True, help="Number of shorts to create"
)
@click.option(
    "--duration",
    default=210,
    type=int,
    show_default=True,
    help="Target short duration in seconds",
)
@click.option(
    "--output-dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Output directory (default: data/output)",
)
def shorts(
    video_file: Optional[Path],
    url: Optional[str],
    count: int,
    duration: int,
    output_dir: Optional[Path],
) -> None:
    """Generate shorts from a video file - one-click operation."""
    try:
        # If a YouTube URL is provided, download it first and use the downloaded file.
        if url:
            url = _unwrap_quotes(url)
            from src.services.youtube_downloader import YouTubeDownloader

            console.print(f"[dim]Downloading video from URL:[/dim] {url}")
            ytd = YouTubeDownloader()
            meta = ytd.download_video(url)
            if not meta or not meta.get("local_path"):
                console.print(
                    f"[red]FAIL[/red] Failed to download video from URL: {url}"
                )
                raise SystemExit(1)
            video_file = Path(meta.get("local_path"))

        if not video_file:
            console.print(
                "[red]FAIL[/red] No input video provided. Supply a local path or use --url."
            )
            raise SystemExit(1)

        editor = VideoEditor()

        _print_panel(
            "Quick Shorts Generator",
            f"Generating {count} shorts from video",
            subtitle="One-click operation",
        )

        console.print(f"[cyan]Video:[/cyan] {video_file.name}")

        # Extract segments
        console.print("[bold cyan]Detecting scenes...[/bold cyan]")
        # Automatically use deeper scoring for short, attention-focused presets
        if duration in (25, 45):
            sel_mode = "best"
            console.print(f"[dim]Using deep selection mode:[/dim] {sel_mode}")
        else:
            sel_mode = "easy_best"

        segments = editor.extract_short_segments(
            str(video_file),
            short_duration=duration,
            num_segments=count,
            selection_mode=sel_mode,
        )

        if not segments:
            console.print("[red]FAIL[/red] No clip segments were found")
            raise SystemExit(1)

        console.print(f"[green]✓[/green] Found {len(segments)} segments")

        # Show preview
        preview_table = Table(
            title="Selected clips", box=box.ROUNDED, border_style="cyan"
        )
        preview_table.add_column("#", style="bold white", no_wrap=True)
        preview_table.add_column("Start", style="cyan")
        preview_table.add_column("Duration", style="green")
        for index, (start_time, end_time) in enumerate(segments[:count], start=1):
            dur = max(0.1, end_time - start_time)
            preview_table.add_row(str(index), f"{start_time:.1f}s", f"{dur:.1f}s")
        console.print(preview_table)

        # Render shorts
        console.print("[bold cyan]Rendering shorts...[/bold cyan]")
        out_dir = output_dir or Path(settings.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        rendered = []
        progress = Progress(
            SpinnerColumn(style="cyan"),
            TextColumn("[bold]{task.description}[/bold]"),
            BarColumn(bar_width=None),
            TextColumn("{task.completed}/{task.total}"),
            TimeElapsedColumn(),
            console=console,
        )

        with progress:
            task = progress.add_task("Rendering", total=len(segments[:count]))
            # Prepare metadata generator for hook lines
            try:
                from src.services.metadata_generator import MetadataGenerator
            except Exception:
                MetadataGenerator = None

            for index, (start_time, end_time) in enumerate(segments[:count], start=1):
                # Use a single folder per source video (clean stem) to group shorts together
                folder_name = clean_filename(video_file.stem)
                short_folder = out_dir / folder_name
                short_folder.mkdir(parents=True, exist_ok=True)
                filename = _make_short_name(video_file.stem, index, tag="shorts")
                output_path = short_folder / filename
                # Generate hook line using metadata generator when available
                hook_srt = None
                try:
                    source_title = None
                    source_description = ""
                    if url and meta:
                        source_title = meta.get("title")
                        source_description = meta.get("description", "")
                    else:
                        source_title = video_file.stem
                    if MetadataGenerator:
                        mg = MetadataGenerator()
                        variants = mg.generate_variants(
                            source_title or video_file.stem,
                            source_description or "",
                            variant_count=1,
                            platform="youtube_shorts",
                        )
                        hook = (
                            variants[0].hook_line
                            if variants
                            else f"{video_file.stem}: watch this"
                        )
                        hook_srt = _write_hook_srt(short_folder, video_file.stem, index, hook)
                except Exception:
                    hook_srt = None

                success = editor.create_short(
                    str(video_file),
                    str(output_path),
                    start_time=start_time,
                    duration=min(duration, max(1, int(end_time - start_time))),
                    add_captions=bool(hook_srt),
                    caption_file=hook_srt or None,
                )
                if success:
                    rendered.append(output_path)
                    # Create a legacy flat-copy in the root output dir for backwards compatibility/tests
                    try:
                        timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
                        legacy_name = f"{clean_filename(video_file.stem)}__shorts_{index:02d}__{timestamp}.mp4"
                        legacy_path = out_dir / legacy_name
                        shutil.copy(str(output_path), str(legacy_path))
                    except Exception:
                        pass
                progress.advance(task)

        # Summary
        summary = Table(
            title="Generation complete", box=box.ROUNDED, border_style="cyan"
        )
        summary.add_column("Item", style="bold white")
        summary.add_column("Value", style="green")
        summary.add_row("Input video", video_file.name)
        summary.add_row("Segments found", str(len(segments)))
        summary.add_row("Shorts rendered", str(len(rendered)))
        summary.add_row("Output directory", str(out_dir))
        console.print(summary)

        if rendered:
            console.print("\n[green]✓ PASS[/green] Shorts generated successfully!")
            for idx, path in enumerate(rendered, 1):
                console.print(f"  {idx}. [cyan]{path.name}[/cyan]")
        else:
            console.print("[red]✗ FAIL[/red] No shorts were generated")
            raise SystemExit(1)

    except Exception as exc:
        logger.error("Error generating shorts: %s", exc, exc_info=True)
        console.print(f"[red]FAIL[/red] Error: {exc}")
        raise SystemExit(1)


def _find_latest_downloaded_video(downloads_dir: Path) -> Optional[Path]:
    candidates = [
        path
        for path in downloads_dir.iterdir()
        if path.is_file()
        and path.suffix.lower() in {".mp4", ".mov", ".mkv", ".webm", ".m4v"}
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


def _select_available_video(candidates: List[Path]) -> Optional[Path]:
    """Interactive video selection from available downloads."""
    if not candidates:
        return None

    # If only one video, return it directly
    if len(candidates) == 1:
        return candidates[0]

    # Show selection table
    from rich.prompt import Prompt

    table = Table(title="Available videos", box=box.ROUNDED, border_style="cyan")
    table.add_column("#", style="bold white", no_wrap=True)
    table.add_column("Filename", style="cyan")
    table.add_column("Size", style="green")
    table.add_column("Modified", style="dim")

    for idx, path in enumerate(candidates, start=1):
        try:
            size_mb = path.stat().st_size / 1_048_576
            mod_time = datetime.fromtimestamp(path.stat().st_mtime).strftime(
                "%Y-%m-%d %H:%M"
            )
            table.add_row(str(idx), path.name, f"{size_mb:.1f}MB", mod_time)
        except Exception as exc:
            logger.warning("Error getting file stats for %s: %s", path.name, exc)
            continue

    console.print(table)

    try:
        choice = Prompt.ask(
            "[cyan]Select video[/cyan]",
            choices=[str(i) for i in range(1, len(candidates) + 1)],
            default="1",
            show_choices=False,
        )
        return candidates[int(choice) - 1]
    except (ValueError, IndexError, KeyboardInterrupt) as exc:
        logger.warning("Video selection cancelled or invalid: %s", exc)
        return None


def _run_readiness_checks() -> Dict[str, Any]:
    from setup import (check_dependencies, check_directories, check_env_file,
                       check_env_variables, check_python_version,
                       check_system_tools)

    checks = [
        ("python", check_python_version),
        ("dependencies", check_dependencies),
        ("system_tools", check_system_tools),
        ("env_file", check_env_file),
        ("env_variables", check_env_variables),
        ("directories", check_directories),
    ]

    results: List[Dict[str, Any]] = []
    for name, check in checks:
        try:
            result = bool(check())
            results.append({"check": name, "passed": result})
        except Exception as exc:
            results.append({"check": name, "passed": False, "error": str(exc)})

    return {
        "passed": builtins.all(item["passed"] for item in results),
        "checks": results,
    }


def _record_stage(stage_timings: List[Dict[str, Any]], name: str, start: float) -> None:
    stage_timings.append(
        {"stage": name, "seconds": round(time.perf_counter() - start, 3)}
    )


def _make_short_name(stem: str, index: int, tag: str = "short") -> str:
    """Return a clean, timestamped filename for a generated short.

    Format: ``<stem>__<tag>_<NN>__<YYYYMMDD-HHMMSS>.mp4``

    Example: ``my_video__short_01__20260519-105600.mp4``
    """
    # Sanitize stem and produce compact, human-friendly filenames.
    # Use hyphens and keep names short to avoid messy outputs.
    clean = re.sub(r"[^A-Za-z0-9]+", "-", stem).strip("-").lower()
    timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    return f"{clean}-{tag}-{index:02d}-{timestamp}.mp4"


def _write_hook_srt(out_dir: Path, stem: str, index: int, hook_text: str) -> str:
    """Write a small SRT file containing the hook text for the start of the short."""
    out_dir.mkdir(parents=True, exist_ok=True)
    # Use a short, predictable filename inside the video's output folder
    srt_path = out_dir / f"hook_{index:02d}.srt"
    # Basic SRT entry: show hook for first 3 seconds
    content = "1\n00:00:00,000 --> 00:00:03,000\n" + hook_text.strip() + "\n"
    try:
        with open(srt_path, "w", encoding="utf-8") as fh:
            fh.write(content)
        return str(srt_path)
    except Exception:
        return ""


def clean_filename(name: str) -> str:
    return re.sub(r"[^\w]+", "_", name).strip("_").lower()


def _upload_rendered_shorts(
    rendered_outputs: List[Path], base_title: str, max_attempts: int = 3
) -> List[Dict[str, Any]]:
    uploader = FacebookUploader()
    uploaded: List[Dict[str, Any]] = []
    for index, output_path in enumerate(rendered_outputs, start=1):
        video_title = f"{base_title} #{index}"
        video_id = None
        for attempt in range(1, max_attempts + 1):
            video_id = uploader.upload_video(
                str(output_path),
                video_title,
                description="Generated by ZAPI deep workflow",
                is_reels=True,
            )
            if video_id:
                break
            if attempt < max_attempts:
                time.sleep(min(2 ** (attempt - 1), 3))
        uploaded.append(
            {
                "path": str(output_path),
                "title": video_title,
                "video_id": video_id,
                "uploaded": bool(video_id),
            }
        )
    return uploaded


@cli.command()
@click.option(
    "--video-path",
    type=click.Path(path_type=Path),
    default=None,
    help="Local video file to clip",
)
@click.option(
    "--latest-download",
    is_flag=True,
    help="Use the newest file from the downloads folder",
)
@click.option(
    "--count", default=3, type=int, show_default=True, help="How many shorts to create"
)
@click.option(
    "--duration",
    default=settings.short_video_duration,
    type=int,
    show_default=True,
    help="Target short duration in seconds",
)
@click.option(
    "--selection-mode",
    default=settings.clip_selection_preset,
    show_default=True,
    type=click.Choice(["easy_best", "best", "balanced"], case_sensitive=False),
    help="Clip scoring preset",
)
@click.option(
    "--context-text",
    default="",
    help="Optional title/description context for better clip scoring",
)
@click.option("--no-captions", is_flag=True, default=True, help="Skip caption burn-in")
@click.option(
    "--preview", is_flag=True, help="Show the chosen segments before rendering"
)
@click.option(
    "--watermark",
    default="ZAPI",
    show_default=True,
    help="Watermark text to place on each short",
)
def clip(
    video_path: Optional[Path],
    latest_download: bool,
    count: int,
    duration: int,
    selection_mode: str,
    context_text: str,
    no_captions: bool,
    preview: bool,
    watermark: str,
) -> None:
    """Clip a local video into one or more shorts."""
    try:
        resolved_video_path: Optional[Path] = video_path
        if latest_download:
            resolved_video_path = _find_latest_downloaded_video(
                Path(settings.downloads_dir)
            )
            if resolved_video_path:
                console.print(f"[dim]Latest download:[/dim] {resolved_video_path}")
        if not resolved_video_path:
            console.print(
                "[red]FAIL[/red] Provide --video-path or use --latest-download"
            )
            raise SystemExit(1)
        if not resolved_video_path.exists():
            console.print(
                f"[red]FAIL[/red] Video file not found: {resolved_video_path}"
            )
            raise SystemExit(1)

        editor = VideoEditor()
        console.print("[bold cyan]Clipping video[/bold cyan]")
        console.print(f"[dim]Input:[/dim] {resolved_video_path}")
        console.print(
            f"[dim]Preset:[/dim] {selection_mode}  [dim]Count:[/dim] {count}  [dim]Duration:[/dim] {duration}s"
        )

        segments = editor.extract_short_segments(
            str(resolved_video_path),
            short_duration=duration,
            num_segments=count,
            context_text=context_text,
            selection_mode=selection_mode,
        )

        if not segments:
            console.print("[red]FAIL[/red] No clip segments were found")
            raise SystemExit(1)

        if preview:
            preview_table = Table(
                title="Clip preview", box=box.ROUNDED, border_style="cyan"
            )
            preview_table.add_column("#", style="bold white", no_wrap=True)
            preview_table.add_column("Start", style="cyan")
            preview_table.add_column("End", style="cyan")
            preview_table.add_column("Length", style="green")
            for index, (start_time, end_time) in enumerate(segments[:count], start=1):
                preview_table.add_row(
                    str(index),
                    f"{start_time:.1f}s",
                    f"{end_time:.1f}s",
                    f"{max(0.1, end_time - start_time):.1f}s",
                )
            console.print(preview_table)

        output_dir = Path(settings.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        table = Table(title="Generated shorts", box=box.ROUNDED, border_style="cyan")
        table.add_column("#", style="bold white", no_wrap=True)
        table.add_column("Start", style="cyan")
        table.add_column("End", style="cyan")
        table.add_column("Output", style="green")
        table.add_column("Status", style="white")

        created = 0
        from src.services.caption_generator import CaptionGenerator

        caption_gen = CaptionGenerator()
        stem = resolved_video_path.stem

        for index, (start_time, end_time) in enumerate(segments[:count], start=1):
            # Group clip outputs by source video stem
            folder_name = clean_filename(stem)
            short_folder = output_dir / folder_name
            short_folder.mkdir(parents=True, exist_ok=True)
            filename = _make_short_name(stem, index, tag="clip")
            output_path = short_folder / filename

            caption_file = None
            hook_srt = None
            try:
                from src.services.metadata_generator import MetadataGenerator
            except Exception:
                MetadataGenerator = None

            if not no_captions:
                cap_filename = _make_short_name(stem, index, tag="clip").replace(
                    ".mp4", ".srt"
                )
                cap_path = short_folder / cap_filename
                clip_duration = min(duration, max(1, int(end_time - start_time)))
                console.print(
                    f"[dim]Transcribing exact subtitles for clip {index}...[/dim]"
                )
                caption_gen.generate_best_captions(
                    str(resolved_video_path),
                    str(cap_path),
                    hook_text=f"Clip {index} of {stem}",
                    start_time=start_time,
                    duration=clip_duration,
                )
                if cap_path.exists():
                    # Generate a hook and prepend to the existing captions in a merged file
                    try:
                        hook = None
                        if MetadataGenerator:
                            mg = MetadataGenerator()
                            variants = mg.generate_variants(
                                stem, "", variant_count=1, platform="youtube_shorts"
                            )
                            hook = variants[0].hook_line if variants else None
                        if hook:
                            merged = short_folder / (cap_path.stem + "__withhook.srt")
                            with open(merged, "w", encoding="utf-8") as outfh:
                                outfh.write(
                                    "1\n00:00:00,000 --> 00:00:03,000\n"
                                    + hook.strip()
                                    + "\n\n"
                                )
                                with open(cap_path, "r", encoding="utf-8") as infh:
                                    outfh.write(infh.read())
                            caption_file = str(merged)
                        else:
                            caption_file = str(cap_path)
                    except Exception:
                        caption_file = str(cap_path)
            else:
                # no_captions == True means captions are skipped; do not add hook
                caption_file = None

            success = editor.create_short(
                str(resolved_video_path),
                str(output_path),
                start_time=start_time,
                duration=min(duration, max(1, int(end_time - start_time))),
                add_captions=not no_captions and bool(caption_file),
                caption_file=caption_file,
                watermark_text=watermark,
            )
            status_text = "[green]done[/green]" if success else "[red]failed[/red]"
            if success:
                created += 1
                try:
                    timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
                    legacy_name = f"{clean_filename(stem)}__clip_{index:02d}__{timestamp}.mp4"
                    legacy_path = output_dir / legacy_name
                    shutil.copy(str(output_path), str(legacy_path))
                except Exception:
                    pass
            table.add_row(
                str(index),
                f"{start_time:.1f}s",
                f"{end_time:.1f}s",
                str(output_path),
                status_text,
            )

        console.print(table)
        if created == 0:
            raise SystemExit(1)
        console.print(
            f"[green]PASS[/green] Created {created} short(s) from {resolved_video_path.name}"
        )
    except Exception as exc:
        if isinstance(exc, SystemExit):
            raise
        console.print(f"[red]FAIL[/red] Error: {exc}")
        raise SystemExit(1)


@cli.command()
@click.option(
    "--video-path",
    type=click.Path(path_type=Path),
    default=None,
    help="Local video file to use",
)
@click.option(
    "--latest-download/--no-latest-download",
    default=True,
    show_default=True,
    help="Auto-use the newest downloaded video",
)
@click.option(
    "--interactive/--no-interactive",
    default=True,
    show_default=True,
    help="Interactively select from available videos",
)
@click.option(
    "--count", default=3, type=int, show_default=True, help="How many shorts to create"
)
@click.option(
    "--duration",
    default=settings.short_video_duration,
    type=int,
    show_default=True,
    help="Target short duration in seconds",
)
@click.option(
    "--selection-mode",
    default=settings.clip_selection_preset,
    show_default=True,
    type=click.Choice(["easy_best", "best", "balanced"], case_sensitive=False),
    help="Clip scoring preset",
)
@click.option(
    "--context-text",
    default="",
    help="Optional title/description context for better clip scoring",
)
@click.option(
    "--preview/--no-preview",
    default=True,
    show_default=True,
    help="Show clip selection before rendering",
)
@click.option(
    "--render/--no-render",
    default=True,
    show_default=True,
    help="Render shorts after previewing",
)
@click.option(
    "--upload/--no-upload",
    default=False,
    show_default=True,
    help="Upload rendered shorts to Facebook",
)
def deep(
    video_path: Optional[Path],
    latest_download: bool,
    interactive: bool,
    count: int,
    duration: int,
    selection_mode: str,
    context_text: str,
    preview: bool,
    render: bool,
    upload: bool,
) -> None:
    """Run a deep end-to-end local workflow."""
    workflow_start = time.perf_counter()
    stage_timings: List[Dict[str, Any]] = []
    editor = VideoEditor()

    _print_panel(
        "Deep workflow",
        "Ready check, latest download selection, preview, render, and final summary in one terminal flow.",
        subtitle="One command, one result",
    )

    stage_start = time.perf_counter()
    readiness = _run_readiness_checks()
    _record_stage(stage_timings, "readiness", stage_start)
    table = Table(title="Readiness", box=box.ROUNDED, border_style="cyan")
    table.add_column("Check", style="bold white")
    table.add_column("Status", style="white")
    for item in readiness["checks"]:
        table.add_row(
            item["check"],
            "[green]PASS[/green]" if item["passed"] else "[red]FAIL[/red]",
        )
    console.print(table)

    resolved_video_path = video_path
    if not resolved_video_path and latest_download:
        # Try to find available videos; offer interactive selection if multiple exist and interactive mode is enabled
        try:
            downloads_path = Path(settings.downloads_dir)
            if not downloads_path.exists():
                console.print(
                    f"[red]FAIL[/red] Downloads directory not found: {downloads_path}"
                )
                raise SystemExit(1)

            available = [
                p
                for p in downloads_path.iterdir()
                if p.is_file()
                and p.suffix.lower() in {".mp4", ".mov", ".mkv", ".webm", ".m4v"}
            ]

            if not available:
                console.print(
                    f"[red]FAIL[/red] No video files found in {downloads_path}"
                )
                raise SystemExit(1)

            # Sort by modification time (newest first)
            available.sort(key=lambda p: p.stat().st_mtime, reverse=True)

            if len(available) > 1 and interactive:
                # Multiple videos with interactive mode: offer selection
                resolved_video_path = _select_available_video(available)
                if not resolved_video_path:
                    console.print("[red]FAIL[/red] No video selected")
                    raise SystemExit(1)
            else:
                # Single video or non-interactive: use latest
                resolved_video_path = available[0]
        except SystemExit:
            raise
        except Exception as exc:
            logger.error("Error selecting video: %s", exc)
            console.print(f"[red]FAIL[/red] Error selecting video: {exc}")
            raise SystemExit(1)

    if not resolved_video_path:
        console.print(
            "[red]FAIL[/red] Provide --video-path or enable --latest-download"
        )
        raise SystemExit(1)

    if not resolved_video_path.exists():
        console.print(f"[red]FAIL[/red] Video file not found: {resolved_video_path}")
        raise SystemExit(1)

    stage_start = time.perf_counter()
    segments = editor.extract_short_segments(
        str(resolved_video_path),
        short_duration=duration,
        num_segments=count,
        context_text=context_text,
        selection_mode=selection_mode,
    )
    _record_stage(stage_timings, "clip selection", stage_start)

    if not segments:
        console.print("[red]FAIL[/red] No clip segments were found")
        raise SystemExit(1)

    preview_table = Table(title="Selected clips", box=box.ROUNDED, border_style="cyan")
    preview_table.add_column("#", style="bold white", no_wrap=True)
    preview_table.add_column("Start", style="cyan")
    preview_table.add_column("End", style="cyan")
    preview_table.add_column("Length", style="green")
    for index, (start_time, end_time) in enumerate(segments[:count], start=1):
        preview_table.add_row(
            str(index),
            f"{start_time:.1f}s",
            f"{end_time:.1f}s",
            f"{max(0.1, end_time - start_time):.1f}s",
        )
    if preview:
        console.print(preview_table)

    rendered_outputs: List[Path] = []
    progress = Progress(
        SpinnerColumn(style="cyan"),
        TextColumn("[bold]{task.description}[/bold]"),
        BarColumn(bar_width=None),
        TextColumn("{task.completed}/{task.total}"),
        TimeElapsedColumn(),
        console=console,
        transient=False,
    )
    if render:
        stage_start = time.perf_counter()
        output_dir = Path(settings.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        with progress:
            render_task = progress.add_task(
                "Rendering shorts", total=len(segments[:count])
            )
            for index, (start_time, end_time) in enumerate(segments[:count], start=1):
                # Group deep outputs by source video stem
                folder_name = clean_filename(resolved_video_path.stem)
                short_folder = output_dir / folder_name
                short_folder.mkdir(parents=True, exist_ok=True)
                filename = _make_short_name(resolved_video_path.stem, index, tag="deep")
                output_path = short_folder / filename
                # Optionally generate a hook SRT for burn-in when auto-subtitles are enabled
                hook_srt = None
                if settings.enable_auto_subtitles:
                    try:
                        from src.services.metadata_generator import \
                            MetadataGenerator

                        mg = MetadataGenerator()
                        variants = mg.generate_variants(
                            resolved_video_path.stem,
                            "",
                            variant_count=1,
                            platform="youtube_shorts",
                        )
                        hook = variants[0].hook_line if variants else None
                        if hook:
                            hook_srt = _write_hook_srt(
                                short_folder, resolved_video_path.stem, index, hook
                            )
                    except Exception:
                        hook_srt = None

                success = editor.create_short(
                    str(resolved_video_path),
                    str(output_path),
                    start_time=start_time,
                    duration=min(duration, max(1, int(end_time - start_time))),
                    add_captions=bool(hook_srt),
                    caption_file=hook_srt or None,
                    watermark_text="ZAPI DEEP",
                )
                if success:
                    rendered_outputs.append(output_path)
                    # also create legacy flat copy for compatibility/tests
                    try:
                        timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
                        legacy_name = f"{clean_filename(resolved_video_path.stem)}__deep_{index:02d}__{timestamp}.mp4"
                        legacy_path = output_dir / legacy_name
                        shutil.copy(str(output_path), str(legacy_path))
                    except Exception:
                        pass
                progress.advance(render_task)
        _record_stage(stage_timings, "render", stage_start)

    uploaded_outputs: List[Dict[str, Any]] = []
    if upload and rendered_outputs:
        stage_start = time.perf_counter()
        with progress:
            upload_task = progress.add_task(
                "Uploading shorts", total=len(rendered_outputs)
            )
            # Delegate to the shared helper — same retry logic, no duplication.
            uploaded_outputs = _upload_rendered_shorts(
                rendered_outputs, base_title=resolved_video_path.stem
            )
            progress.advance(upload_task, advance=len(rendered_outputs))
        _record_stage(stage_timings, "upload", stage_start)

    summary = Table(title="Deep workflow summary", box=box.ROUNDED, border_style="cyan")
    summary.add_column("Item", style="bold white")
    summary.add_column("Value", style="green")
    summary.add_row("Video", str(resolved_video_path))
    summary.add_row("Preset", selection_mode)
    summary.add_row("Selected clips", str(min(count, len(segments))))
    summary.add_row("Rendered shorts", str(len(rendered_outputs)))
    summary.add_row(
        "Uploaded shorts", str(sum(1 for item in uploaded_outputs if item["uploaded"]))
    )
    summary.add_row("Readiness", "PASS" if readiness["passed"] else "FAIL")
    console.print(summary)

    timing_table = Table(title="Stage timings", box=box.ROUNDED, border_style="cyan")
    timing_table.add_column("Stage", style="bold white")
    timing_table.add_column("Seconds", style="green")
    for item in stage_timings:
        timing_table.add_row(item["stage"], f"{item['seconds']:.3f}")
    timing_table.add_row("total", f"{time.perf_counter() - workflow_start:.3f}")
    console.print(timing_table)

    if readiness["passed"] and (not render or rendered_outputs):
        console.print("[green]PASS[/green] Deep workflow complete")
    else:
        console.print("[yellow]WARN[/yellow] Deep workflow completed with warnings")


@cli.command("schedule-preview")
@click.option(
    "--count", default=3, type=int, show_default=True, help="How many slots to show"
)
@click.option(
    "--days-ahead",
    default=7,
    type=int,
    show_default=True,
    help="How far into the future to look",
)
@click.option(
    "--history-days",
    default=30,
    type=int,
    show_default=True,
    help="How many history days to use",
)
@click.option(
    "--preferred-hours", default="", help="Comma-separated preferred publish hours"
)
@click.option(
    "--timezone-offset-minutes",
    default=0,
    type=int,
    show_default=True,
    help="Local timezone offset from UTC",
)
def schedule_preview(
    count: int,
    days_ahead: int,
    history_days: int,
    preferred_hours: str,
    timezone_offset_minutes: int,
) -> None:
    """Preview recommended publish slots."""
    db = SessionLocal()
    try:
        hours = (
            [
                _safe_int(value.strip(), -1)
                for value in preferred_hours.split(",")
                if value.strip()
            ]
            if preferred_hours
            else None
        )
        if hours is not None:
            hours = [value for value in hours if 0 <= value <= 23]
            if not hours:
                hours = None

        result = build_schedule_preview(
            db=db,
            count=count,
            days_ahead=days_ahead,
            history_days=history_days,
            preferred_hours=hours,
            timezone_offset_minutes=timezone_offset_minutes,
        )
    finally:
        db.close()

    _print_panel(
        "Schedule Preview",
        "Recommended publish slots optimized for simple, operator-friendly scheduling.",
        subtitle="Use these times as a default",
    )
    console.print(f"[bold]Source:[/bold] {result['source']}")
    console.print(f"[bold]History samples:[/bold] {result['history_samples']}")
    for slot in result["recommended_slots"]:
        console.print(
            f"  • {slot['publish_at']}  hour={slot['hour']}  [green]score={slot['score']}[/green]"
        )


@cli.command("schedule-publish")
@click.option(
    "--processed-short-id", required=True, help="Processed short ID to publish"
)
@click.option(
    "--when", default=None, help="Schedule time in ISO 8601, e.g. 2026-05-18T18:00:00"
)
@click.option(
    "--in-hours", default=None, type=int, help="Schedule relative to now in hours"
)
@click.option(
    "--platform", default="facebook", show_default=True, help="Target platform"
)
@click.option("--title", default=None, help="Override post title")
@click.option("--description", default=None, help="Override post description")
@click.option(
    "--hashtag", "hashtags", multiple=True, help="Append a hashtag; repeatable"
)
def schedule_publish(
    processed_short_id: str,
    when: Optional[str],
    in_hours: Optional[int],
    platform: str,
    title: Optional[str],
    description: Optional[str],
    hashtags: Iterable[str],
) -> None:
    """Schedule a processed short for publishing."""
    schedule_time = _parse_iso_datetime(when) if when else None
    if schedule_time is None and in_hours is not None:
        schedule_time = datetime.utcnow() + timedelta(hours=in_hours)

    db = SessionLocal()
    try:
        result = execute_publish_scheduled_short(
            db=db,
            processed_short_id=processed_short_id,
            schedule_time=schedule_time,
            platform=platform,
            title=title,
            description=description,
            hashtags=list(hashtags),
        )
    finally:
        db.close()

    _print_panel(
        "Schedule Publish",
        "Queued post for a target platform.",
        subtitle="Publishing workflow",
    )
    _print_kv_table(
        "Publish result",
        [
            ("Upload ID", result["upload_id"]),
            ("Platform", result["platform"]),
            ("Scheduled for", result["scheduled_for"]),
            ("Facebook video ID", result.get("facebook_video_id")),
        ],
    )


@cli.command()
def init_db() -> None:
    """Initialize the database."""
    console.print("[bold cyan]Initializing database...[/bold cyan]")
    init_database()
    console.print("[green]PASS[/green] Database initialized")


@cli.command()
def stats() -> None:
    """Show summary statistics."""
    db = SessionLocal()
    try:
        total_videos = db.query(SourceVideo).count()
        processed = (
            db.query(SourceVideo)
            .filter(SourceVideo.status == VideoStatusEnum.PROCESSED)
            .count()
        )
        failed = (
            db.query(SourceVideo)
            .filter(SourceVideo.status == VideoStatusEnum.FAILED)
            .count()
        )
        total_shorts = db.query(ProcessedShort).count()
        total_uploads = db.query(FacebookUpload).count()
        successful = (
            db.query(FacebookUpload)
            .filter(FacebookUpload.status == VideoStatusEnum.UPLOADED)
            .count()
        )

        _print_panel(
            "Stats",
            "Repository-level summary of the processing pipeline.",
            subtitle="Fast snapshot",
        )
        _print_kv_table(
            "Processing statistics",
            [
                ("Source videos", total_videos),
                ("Processed", processed),
                ("Failed", failed),
                ("Processed shorts", total_shorts),
                ("Facebook uploads", total_uploads),
                ("Successful uploads", successful),
                ("Failed uploads", total_uploads - successful),
            ],
        )
        if total_uploads > 0:
            console.print(
                _format_count_line(
                    "Success rate", f"{(successful / total_uploads) * 100:.1f}%"
                )
            )
    finally:
        db.close()


@cli.command()
def routes_json() -> None:
    """Emit routes as JSON for scripting."""
    from src.api.main import app

    payload = []
    for route in app.routes:
        path = getattr(route, "path", "")
        methods = sorted(getattr(route, "methods", []) or [])
        if methods:
            payload.append({"path": path, "methods": methods})
    _echo_json({"routes": payload})


@cli.command()
@click.option(
    "--hours", default=24, type=int, show_default=True, help="Hours to inspect"
)
def test_ffmpeg(hours: int) -> None:
    """Test FFmpeg availability."""
    click.echo("Testing FFmpeg...")
    result = subprocess.run(
        ["ffmpeg", "-version"], capture_output=True, text=True, timeout=5
    )
    if result.returncode == 0:
        click.secho(result.stdout.splitlines()[0], fg="green")
    else:
        click.secho("FAIL FFmpeg not found", fg="red")
        raise SystemExit(1)


@cli.command()
def test_youtube() -> None:
    """Test YouTube API connection."""
    from src.services.youtube_downloader import YouTubeDownloader

    click.echo("Testing YouTube API...")
    downloader = YouTubeDownloader()
    info = downloader.get_video_info("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    if info:
        click.secho("PASS YouTube API connected", fg="green")
        click.echo(f"Title: {info['title']}")
        click.echo(f"Duration: {info['duration_seconds']}s")
    else:
        click.secho("FAIL YouTube API test failed", fg="red")
        raise SystemExit(1)


@cli.command()
def test_facebook() -> None:
    """Test Facebook API connection."""
    from src.services.facebook_uploader import FacebookUploader

    click.echo("Testing Facebook API...")
    if not os.getenv("FACEBOOK_PAGE_ID"):
        click.secho("FAIL FACEBOOK_PAGE_ID not set", fg="red")
        raise SystemExit(1)
    uploader = FacebookUploader()
    insights = uploader.get_page_insights()
    if insights:
        click.secho("PASS Facebook API connected", fg="green")
        for key, value in insights.items():
            click.echo(f"{key}: {value}")
    else:
        click.secho("FAIL Facebook API test failed", fg="red")
        raise SystemExit(1)


@cli.group()
def test() -> None:
    """Run system tests."""
    pass


@test.command(name="all")
def test_all() -> None:
    """Run all system tests."""
    click.echo("Running all system tests...\n")
    ctx = click.get_current_context()
    for cmd in [test_ffmpeg, test_youtube, test_facebook]:
        click.echo("=" * 40)
        ctx.invoke(cmd)
    click.echo("\nPASS All tests completed")


if __name__ == "__main__":
    cli()
