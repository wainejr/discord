from datetime import datetime

from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.widgets import Footer, Header, Static

from acelerado import youtube
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


class MonitorApp(App):
    CSS = """
    Screen { layout: vertical; }
    #token, #published { border: solid $accent; padding: 1 2; margin: 1 2; }
    #token { height: 5; }
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
            seconds = youtube.get_token_time_to_expire()
            expiry = youtube.get_token_expiration_date()
        except Exception as e:
            self.query_one("#token", Static).update(f"[red]Token read error:[/] {e}")
        else:
            self.query_one("#token", Static).update(
                f"[bold]YouTube OAuth token[/]\nExpires in: {_format_expiry(seconds, expiry)}"
            )

        ids = _read_published()
        recent = ids[-15:][::-1]
        body = "\n".join(f"  • https://youtu.be/{vid}" for vid in recent) or "  (none yet)"
        self.query_one("#published", Static).update(
            f"[bold]Published videos[/] ({len(ids)} total — most recent first)\n\n{body}"
        )


def run_monitor() -> None:
    MonitorApp().run()
