"""Command-line entry points."""

import hashlib
import logging
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import typer

from panorama_calendar.ics import render_calendar
from panorama_calendar.models import (
    Alarm,
    CalendarKind,
    EventKind,
    EventRecord,
    ResultStatus,
    SessionKind,
)
from panorama_calendar.models.f1 import F1GridEntry, F1RaceReport, F1Session
from panorama_calendar.pipelines import (
    F1ReportError,
    build_f1_report_events,
    build_f1_schedule_events,
    build_holiday_events,
    build_memorial_events,
)
from panorama_calendar.publishing import CalendarArtifact, write_calendar
from panorama_calendar.services.audit import append_publish_record
from panorama_calendar.services.event_state import (
    EventStateError,
    load_event_state,
    save_event_state,
)
from panorama_calendar.services.feed_snapshot import (
    FeedSnapshotError,
    read_published_sequences,
)
from panorama_calendar.services.guardrails import PublishGuardError
from panorama_calendar.services.revision import reconcile_events
from panorama_calendar.services.rollback import RollbackError, rollback_to_snapshot
from panorama_calendar.sources.datasets import (
    DatasetError,
    load_anniversary_registry,
    load_holiday_dataset,
)
from panorama_calendar.sources.f1_official import F1OfficialClient, F1SourceError
from panorama_calendar.sources.f1_results import F1ResultsClient, F1ResultsError
from panorama_calendar.sources.fia_documents import (
    FiaDocumentsClient,
    FiaDocumentsError,
    load_fia_event_registry,
    race_classification_status,
)
from panorama_calendar.sources.jolpica import (
    JolpicaClient,
    load_official_schedule_with_optional_cross_check,
)

logger = logging.getLogger(__name__)

app = typer.Typer(help="Personal panorama calendar tools")

CALENDAR_SPECS: dict[str, tuple[CalendarKind, str, str]] = {
    "cn": (
        CalendarKind.CN_HOLIDAY,
        "全国假期｜法定节假日与调休",
        "cn-holidays-{year}.ics",
    ),
    "gx": (CalendarKind.GX_HOLIDAY, "广西假期", "guangxi-holidays-{year}.ics"),
    "memorial": (CalendarKind.MEMORIAL, "国家纪念日", "memorial-days-{year}.ics"),
}


@app.callback()
def main() -> None:
    """Root callback keeps the app a command group.

    Without it Typer collapses a single-command app into the root command,
    which breaks the documented ``python -m panorama_calendar demo`` form.
    """


@app.command()
def demo(
    output: Path = typer.Option(Path("dist/valarm-ios-test.ics"), help="Output ICS path"),
    workday: str | None = typer.Option(None, help="Adjusted workday in YYYY-MM-DD format"),
    in_days: list[int] = typer.Option(
        [],
        "--in-days",
        help="Offset in days from today; repeat the flag for several chances to hear the alarm",
    ),
) -> None:
    """Generate future all-day events for real iPhone VALARM verification."""
    if workday and in_days:
        raise typer.BadParameter("use either --workday or --in-days, not both")
    if any(offset < 1 for offset in in_days):
        raise typer.BadParameter("--in-days must be 1 or more; the alarm fires the evening before")
    try:
        if in_days:
            event_dates = sorted({date.today() + timedelta(days=offset) for offset in in_days})
        elif workday:
            event_dates = [date.fromisoformat(workday)]
        else:
            event_dates = [date.today() + timedelta(days=7)]
    except ValueError as error:
        raise typer.BadParameter("workday must use YYYY-MM-DD") from error

    events = [_demo_event(event_date) for event_date in event_dates]
    data = render_calendar(events, "全国假期｜VALARM 验证")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(data)
    typer.echo(f"Generated: {output.resolve()} ({len(events)} event(s))")
    for event_date in event_dates:
        alarm_date = event_date - timedelta(days=1)
        typer.echo(f"Workday: {event_date.isoformat()}; alarm: {alarm_date} 20:00")


def _demo_event(event_date: date) -> EventRecord:
    """Build one self-describing verification event with a prior-evening alarm."""
    alarm = Alarm(
        description="明天调休上班：这是 iPhone 订阅日历提醒验证事件。",
        purpose="adjusted-workday-evening",
    )
    return EventRecord(
        event_key=f"demo:adjusted-workday:{event_date.isoformat()}",
        calendar_kind=CalendarKind.CN_HOLIDAY,
        event_kind=EventKind.ADJUSTED_WORKDAY,
        summary="调休上班｜iOS VALARM 验证",
        description=(
            "此事件用于验证 VALARM 内的独立 UID 与 X-WR-ALARMUID。"
            "提醒应在设备本地时间的前一晚20:00出现；同时验证中文、逗号、分号、"
            "反斜杠\\和长文本的UTF-8字节折行。"
        ),
        start_date=event_date,
        end_date_exclusive=event_date + timedelta(days=1),
        alarms=[alarm],
        categories=["调休上班", "兼容性验证"],
        dtstamp=datetime.now(UTC),
    )


def _events_for(kind: CalendarKind, year: int) -> list[EventRecord]:
    """Load the dataset for one calendar and turn it into events."""
    if kind is CalendarKind.MEMORIAL:
        return build_memorial_events(load_anniversary_registry(), year)
    return build_holiday_events(load_holiday_dataset(kind, year))


@app.command()
def build(
    calendar: str = typer.Option(
        "all",
        "--calendar",
        "-c",
        help="Which feed to build: cn | gx | memorial | all",
    ),
    year: int | None = typer.Option(
        None,
        "--year",
        "-y",
        help="Calendar year to build; defaults to the current year",
    ),
    out: Path = typer.Option(Path("dist"), "--out", "-o", help="Output directory"),
) -> None:
    """Build one or more subscription feeds from the packaged datasets."""
    target_year = year or date.today().year
    selected = list(CALENDAR_SPECS) if calendar == "all" else [calendar]
    unknown = [name for name in selected if name not in CALENDAR_SPECS]
    if unknown:
        raise typer.BadParameter(
            f"unknown calendar {unknown[0]!r}; choose from {', '.join(CALENDAR_SPECS)} or all"
        )

    failures = 0
    for name in selected:
        kind, calendar_name, pattern = CALENDAR_SPECS[name]
        feed = pattern.removesuffix("{year}.ics").rstrip("-") or name
        output = out / pattern.format(year=target_year)
        state_path = out / f"{feed}-{target_year}.state.json"
        try:
            previous = load_event_state(state_path)
            events = reconcile_events(
                previous,
                _events_for(kind, target_year),
                minimum_sequences=read_published_sequences(output),
            )
            artifact = write_calendar(
                events,
                calendar_name,
                output,
                calendar_kind=kind,
            )
            save_event_state(state_path, events)
            _record_publication(out, feed, target_year, "build", events, artifact)
        except (
            DatasetError,
            PublishGuardError,
            EventStateError,
            FeedSnapshotError,
        ) as error:
            failures += 1
            typer.echo(f"[FAILED] {name}: {error}", err=True)
            continue
        typer.echo(
            f"{artifact.path.name}: {artifact.event_count} events, {artifact.byte_count} bytes"
        )

    if failures:
        raise typer.Exit(code=1)


def _record_publication(
    out: Path,
    feed: str,
    year: int,
    action: str,
    events: list[EventRecord],
    artifact: CalendarArtifact,
) -> None:
    """Append one line to the feed's audit trail after a successful write.

    A build that reproduces the exact bytes already published adds no line: the
    audit trail records revisions, not heartbeats. Without this the state branch
    would gain a commit every scheduled run and say nothing new.
    """
    sequences = [event.sequence for event in events]
    append_publish_record(
        out / f"{feed}-{year}.revisions.jsonl",
        {
            "action": action,
            "feed": feed,
            "events": len(events),
            "sequence_min": min(sequences) if sequences else None,
            "sequence_max": max(sequences) if sequences else None,
            "ics_sha256": hashlib.sha256(artifact.path.read_bytes()).hexdigest(),
        },
        skip_if_unchanged=True,
    )


@app.command("f1-schedule")
def f1_schedule(
    year: int = typer.Option(..., "--year", "-y", help="F1 championship season"),
    out: Path = typer.Option(Path("dist"), "--out", "-o", help="Output directory"),
) -> None:
    """Build the F1 schedule from official pages with optional Jolpica checks."""
    official = F1OfficialClient()
    jolpica = JolpicaClient()
    output = out / f"f1-schedule-{year}.ics"
    state_path = out / f"f1-schedule-{year}.state.json"
    try:
        sessions = load_official_schedule_with_optional_cross_check(
            year,
            official.fetch_schedule,
            jolpica,
        )
        previous = load_event_state(state_path)
        events = build_f1_schedule_events(
            sessions,
            previous=previous,
            minimum_sequences=read_published_sequences(output),
        )
        artifact = write_calendar(
            events,
            "F1 赛历｜排位赛、冲刺赛与正赛",
            output,
            calendar_kind=CalendarKind.F1_SCHEDULE,
        )
        save_event_state(state_path, events)
        _record_publication(out, "f1-schedule", year, "build", events, artifact)
    except (
        F1SourceError,
        httpx.HTTPError,
        PublishGuardError,
        EventStateError,
        FeedSnapshotError,
    ) as error:
        typer.echo(f"[FAILED] f1-schedule: {error}", err=True)
        raise typer.Exit(code=1) from error
    finally:
        official.close()
        jolpica.close()
    typer.echo(f"{artifact.path.name}: {artifact.event_count} events, {artifact.byte_count} bytes")


def _race_local_date(session: F1Session) -> date:
    """Return the date the Grand Prix is held at the circuit, not in UTC."""
    return session.start_at_utc.astimezone(ZoneInfo(session.circuit_timezone)).date()


@app.command("f1-report")
def f1_report(
    year: int = typer.Option(..., "--year", "-y", help="F1 championship season"),
    event: list[str] = typer.Option(
        [],
        "--event",
        "-e",
        help="Event slug to refresh; repeatable. Defaults to every completed round.",
    ),
    out: Path = typer.Option(Path("dist"), "--out", "-o", help="Output directory"),
) -> None:
    """Build alarm-free race reports backed by FIA finality evidence."""
    official = F1OfficialClient()
    results = F1ResultsClient()
    fia = FiaDocumentsClient()
    output = out / f"f1-reports-{year}.ics"
    state_path = out / f"f1-reports-{year}.state.json"
    failures: list[str] = []
    reports: list[F1RaceReport] = []
    try:
        registry = load_fia_event_registry(year)
        races = {
            session.event_id: session
            for session in official.fetch_schedule(year)
            if session.session_kind is SessionKind.RACE
        }
        links = {link.event_id: link for link in results.fetch_round_links(year)}
        if event:
            unknown = [slug for slug in event if slug not in races]
            if unknown:
                raise typer.BadParameter(
                    f"unknown event {unknown[0]!r}; known rounds: {', '.join(sorted(races))}"
                )
            targets = [races[slug] for slug in event]
        else:
            targets = sorted(races.values(), key=lambda session: session.start_at_utc)

        previous = load_event_state(state_path)
        today = datetime.now(UTC).date()

        for session in targets:
            slug = session.event_id
            race_date = _race_local_date(session)
            if race_date > today:
                typer.echo(f"[SKIP] {slug}: race on {race_date} has not run yet")
                continue
            link = links.get(slug) or links.get(registry.aliases.get(slug, ""))
            if link is None:
                failures.append(slug)
                typer.echo(f"[FAILED] {slug}: no official results page", err=True)
                continue
            try:
                fetched = results.fetch_race_result(link)
            except (F1ResultsError, httpx.HTTPError) as error:
                failures.append(slug)
                typer.echo(f"[FAILED] {slug}: {error}", err=True)
                continue
            if fetched is None:
                typer.echo(f"[SKIP] {slug}: classification not published yet")
                continue
            entries, result_source = fetched

            grid: list[F1GridEntry] = []
            grid_source = None
            try:
                grid_fetched = results.fetch_starting_grid(link)
            except (F1ResultsError, httpx.HTTPError) as error:
                logger.warning("starting grid unavailable for %s: %s", slug, error)
                grid_fetched = None
            if grid_fetched is not None:
                grid, grid_source = grid_fetched

            fia_title = registry.title_for(slug)
            if fia_title is None:
                failures.append(slug)
                typer.echo(f"[FAILED] {slug}: no reviewed FIA event title", err=True)
                continue
            try:
                status, fia_url = race_classification_status(
                    fia.fetch_event_documents(year, fia_title)
                )
            except (FiaDocumentsError, httpx.HTTPError) as error:
                failures.append(slug)
                typer.echo(f"[FAILED] {slug}: FIA documents unavailable: {error}", err=True)
                continue
            if status is ResultStatus.NOT_AVAILABLE:
                status, fia_url = ResultStatus.PROVISIONAL, None

            report = F1RaceReport(
                season=year,
                event_id=slug,
                grand_prix_name=fia_title,
                official_name=session.grand_prix_name,
                race_date=race_date,
                status=status,
                results=entries,
                grid=grid,
                result_source=result_source,
                grid_source=grid_source,
                fia_classification_url=fia_url,
            )
            reports.append(report)
            typer.echo(
                f"{slug}: {report.status.value}, {report.classified_count} classified, "
                f"{len(report.grid)} on grid, {report.race_date}"
            )

        if not reports and not previous:
            if failures:
                typer.echo(f"rounds with failures: {', '.join(failures)}", err=True)
                raise typer.Exit(code=1)
            typer.echo("[SKIP] no completed round has a published classification yet")
            return

        events = build_f1_report_events(
            reports,
            previous=previous,
            minimum_sequences=read_published_sequences(output),
        )
        artifact = write_calendar(
            events,
            "F1 战报｜正赛成绩",
            output,
            calendar_kind=CalendarKind.F1_REPORT,
        )
        save_event_state(state_path, events)
        _record_publication(out, "f1-reports", year, "build", events, artifact)
    except (
        F1SourceError,
        F1ResultsError,
        FiaDocumentsError,
        F1ReportError,
        EventStateError,
        FeedSnapshotError,
        PublishGuardError,
        httpx.HTTPError,
    ) as error:
        typer.echo(f"[FAILED] f1-report: {error}", err=True)
        raise typer.Exit(code=1) from error
    finally:
        official.close()
        results.close()
        fia.close()

    typer.echo(f"{artifact.path.name}: {artifact.event_count} events, {artifact.byte_count} bytes")
    if failures:
        typer.echo(f"rounds with failures: {', '.join(failures)}", err=True)
        raise typer.Exit(code=1)


ROLLBACK_FEEDS: dict[str, tuple[CalendarKind, str, str]] = {
    "f1-reports": (
        CalendarKind.F1_REPORT,
        "f1-reports-{year}",
        "F1 战报｜正赛成绩",
    ),
    "f1-schedule": (
        CalendarKind.F1_SCHEDULE,
        "f1-schedule-{year}",
        "F1 赛历｜排位赛、冲刺赛与正赛",
    ),
}


@app.command("rollback")
def rollback(
    feed: str = typer.Option(..., "--feed", help="Feed to roll back; run --help to see choices"),
    year: int = typer.Option(..., "--year", "-y", help="Season being rolled back"),
    from_state: Path = typer.Option(
        ...,
        "--from-state",
        help="Older state snapshot, e.g. written by 'git show <sha>:dist/...state.json'",
    ),
    out: Path = typer.Option(Path("dist"), "--out", "-o", help="Output directory"),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Print the planned revision numbers without writing"
    ),
) -> None:
    """Republish an older snapshot as a new revision instead of rewinding SEQUENCE."""
    spec = ROLLBACK_FEEDS.get(feed)
    if spec is None:
        raise typer.BadParameter(
            f"unknown feed {feed!r}; choose from {', '.join(ROLLBACK_FEEDS)}"
        )
    if not from_state.is_file():
        raise typer.BadParameter(f"snapshot not found: {from_state}")
    kind, pattern, calendar_name = spec
    stem = pattern.format(year=year)
    output = out / f"{stem}.ics"
    state_path = out / f"{stem}.state.json"

    try:
        current = load_event_state(state_path)
        snapshot = load_event_state(from_state)
        events = rollback_to_snapshot(
            snapshot,
            current,
            calendar_kind=kind,
            minimum_sequences=read_published_sequences(output),
        )
        if dry_run:
            current_by_key = {event.event_key: event for event in current}
            for event in events:
                old = current_by_key.get(event.event_key)
                before = old.sequence if old is not None else "new"
                typer.echo(f"[DRY] {event.event_key}: SEQUENCE {before} -> {event.sequence}")
            return
        artifact = write_calendar(events, calendar_name, output, calendar_kind=kind)
        save_event_state(state_path, events)
        _record_publication(out, feed, year, "rollback", events, artifact)
    except (
        EventStateError,
        FeedSnapshotError,
        RollbackError,
        PublishGuardError,
    ) as error:
        typer.echo(f"[FAILED] rollback: {error}", err=True)
        raise typer.Exit(code=1) from error

    typer.echo(
        f"{artifact.path.name}: rolled back to {from_state.name}, "
        f"{artifact.event_count} events, {artifact.byte_count} bytes"
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    app()
