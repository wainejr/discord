from datetime import datetime, timedelta

from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.widgets import Footer, Header, Static

from acelerado import metrics, youtube
from acelerado.state import FILENAME_PUBLISHED


def _format_expiry(seconds: float | None, expiry: datetime | None) -> str:
    if seconds is None or expiry is None:
        return "[yellow]No token cached[/]"
    if seconds <= 0:
        return f"[red bold]EXPIRED[/] (was {expiry:%Y-%m-%d %H:%M:%S})"
    days, rem = divmod(int(seconds), 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    color = "red" if seconds < 3600 * 24 else "green"
    return (
        f"[{color}]{days}d {hours:02d}h {minutes:02d}m {secs:02d}s[/] "
        f"(at {expiry:%Y-%m-%d %H:%M:%S})"
    )


def _read_published() -> list[str]:
    if not FILENAME_PUBLISHED.exists():
        return []
    return [line for line in FILENAME_PUBLISHED.read_text().splitlines() if line.strip()]


def _render_metrics_panel() -> str:
    m = metrics.load()

    def line(label: str, entries):
        total_24h = metrics.window_total(entries, timedelta(hours=24))
        total_7d = metrics.window_total(entries, timedelta(days=7))
        total_all = metrics.total(entries)
        return f"  {label:<22} {total_24h:>4} (24h) · {total_7d:>4} (7d) · {total_all:>5} (total)"

    last_tick_str = (
        m.last_successful_tick.strftime("%Y-%m-%d %H:%M:%S")
        if m.last_successful_tick is not None
        else "— nunca"
    )
    return (
        "[bold]Métricas[/]\n"
        f"  Último tick OK:        {last_tick_str}\n"
        f"{line('Vídeos anunciados', m.videos_announced)}\n"
        f"{line('Membros sincronizados', m.members_synced)}\n"
        f"{line('Erros reportados', m.errors)}"
    )


class MonitorApp(App):
    CSS = """
    Screen { layout: vertical; }
    #token, #metrics, #published { border: solid $accent; padding: 1 2; margin: 1 2; }
    #token { height: 5; }
    #metrics { height: 9; }
    #published { height: 1fr; }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("r", "refresh", "Refresh"),
    ]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Vertical(
            Static(id="token"),
            Static(id="metrics"),
            Static(id="published"),
        )
        yield Footer()

    def on_mount(self) -> None:
        self.title = "Acelerado Monitor"
        self.refresh_data()
        self.set_interval(1.0, self.refresh_data)

    def action_refresh(self) -> None:
        self.refresh_data()

    def refresh_data(self) -> None:
        try:
            from acelerado.env import get_env

            ttl_days = get_env().ACELERADO_REFRESH_TOKEN_TTL_DAYS
            seconds = youtube.get_refresh_token_time_to_expire(ttl_days)
            issued = youtube.get_refresh_token_issued_at()
            deadline = issued + timedelta(days=ttl_days) if issued else None
        except Exception as e:
            self.query_one("#token", Static).update(f"[red]Token read error:[/] {e}")
        else:
            self.query_one("#token", Static).update(
                f"[bold]YouTube refresh token[/]\nExpires in: {_format_expiry(seconds, deadline)}"
            )

        self.query_one("#metrics", Static).update(_render_metrics_panel())

        ids = _read_published()
        recent = ids[-15:][::-1]
        body = "\n".join(f"  • https://youtu.be/{vid}" for vid in recent) or "  (none yet)"
        self.query_one("#published", Static).update(
            f"[bold]Published videos[/] ({len(ids)} total — most recent first)\n\n{body}"
        )


def run_monitor() -> None:
    MonitorApp().run()
