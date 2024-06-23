import click
from main import run


@click.command()
@click.argument("calendar_id")
@click.option(
    "--block-calendar-id", default=None, help="Block calendar ID (default: calendar_id)"
)
@click.option("--buffer-min", default=30, help="Buffer minutes (default: 30)")
@click.option("--block-title", default="↕", help="Block title (default: ↕)")
def main(calendar_id, block_calendar_id, buffer_min, block_title):
    calendar_b = block_calendar_id if block_calendar_id else calendar_id
    run(calendar_id, calendar_b, buffer_min, block_title)


if __name__ == "__main__":
    main()
