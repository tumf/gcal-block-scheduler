from datetime import datetime, timedelta, timezone
import os
import os.path
import pickle
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/calendar"]
BUFFER_MINUTES = 30


def authenticate_google_api() -> Credentials:
    credentials = None
    access_token = os.getenv("GOOGLE_ACCESS_TOKEN")
    refresh_token = os.getenv("GOOGLE_REFRESH_TOKEN")
    token_uri = "https://oauth2.googleapis.com/token"
    client_id = os.getenv("GOOGLE_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET")

    if access_token:
        credentials = Credentials(
            token=access_token,
            refresh_token=refresh_token,
            token_uri=token_uri,
            client_id=client_id,
            client_secret=client_secret,
        )
    elif os.path.exists(".credentials/token.pickle"):
        with open(".credentials/token.pickle", "rb") as token:
            credentials = pickle.load(token)

    if not credentials or not credentials.valid:
        if credentials and credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                ".credentials/credentials.json", SCOPES
            )
            credentials = flow.run_local_server(port=0)
        with open(".credentials/token.pickle", "wb") as token:
            pickle.dump(credentials, token)
    return credentials


def get_events(
    calendar_id: str,
    credentials: Credentials,
    query: str = None,
    timeMin: datetime = datetime.now(timezone.utc),
    timeMax: datetime = (datetime.now(timezone.utc) + timedelta(days=90)),
) -> list:
    def format_datetime(dt: datetime) -> str:
        if dt == datetime.min:
            return datetime.min.isoformat() + "Z"
        return dt.strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"

    service = build("calendar", "v3", credentials=credentials)
    events_result = (
        service.events()
        .list(
            calendarId=calendar_id,
            timeMin=format_datetime(timeMin),
            timeMax=format_datetime(timeMax),
            maxResults=500,
            singleEvents=True,
            orderBy="startTime",
            q=query,
        )
        .execute()
    )
    events = events_result.get("items", [])
    # Remove all-day events
    filtered_events = [event for event in events if "dateTime" in event["start"]]
    return filtered_events


def check_event_exists(calendar_id: str, event: dict, credentials: Credentials) -> bool:
    """
    Check if an event exists same start and end time and summary
    """
    service = build("calendar", "v3", credentials=credentials)
    # イベントの開始時刻、終了時刻、サマリーを使用してクエリを作成
    start_time = event["start"]["dateTime"]
    end_time = event["end"]["dateTime"]
    summary = event["summary"]

    query = f"startTime = '{start_time}' and endTime = '{end_time}' and summary = '{summary}'"

    # クエリを使用してイベントを検索
    events_result = (
        service.events()
        .list(
            calendarId=calendar_id,
            timeMin=start_time,
            timeMax=end_time,
            q=query,
            singleEvents=True,
            maxResults=1,
        )
        .execute()
    )

    # 一致するイベントが見つかった場合はTrueを返す
    if events_result.get("items", []):
        return True
    else:
        return False


def insert_event(calendar_id: str, event: dict, credentials: Credentials) -> None:
    if check_event_exists(calendar_id, event, credentials):
        print("Event already exists:", event)
        return
    service = build("calendar", "v3", credentials=credentials)
    print("Inserting event:", event)
    event = service.events().insert(calendarId=calendar_id, body=event).execute()
    print(f'Event created: {event.get("htmlLink")}')


def delete_event(calendar_id, event_id, credentials) -> None:
    service = build("calendar", "v3", credentials=credentials)
    service.events().delete(calendarId=calendar_id, eventId=event_id).execute()
    print(f"Event deleted: {event_id}")


def create_block_event(start: datetime, end: datetime, block_title: str = "↕") -> dict:
    return {
        "summary": block_title,
        "start": {
            "dateTime": start.isoformat(),
            "timeZone": "UTC",
        },
        "end": {
            "dateTime": end.isoformat(),
            "timeZone": "UTC",
        },
    }


def remove_duplicate_block_events(
    block_events_b: list,
    calendar_b: str,
    credentials: Credentials,
) -> bool:
    """
    Remove duplicate block events
    Return True if events were removed
    """
    # find duplicate block events
    duplicate_block_events = []
    updated = False
    event_dict = {}
    for event in block_events_b:
        key = (event["start"]["dateTime"], event["end"]["dateTime"], event["summary"])
        if key in event_dict:
            delete_event(calendar_b, event["id"], credentials)
            updated = True
        else:
            event_dict[key] = event
    return updated


def add_block_events(
    events_a: list,
    block_events_b: list,
    calendar_b: str,
    credentials: Credentials,
    buffer_minutes: int = BUFFER_MINUTES,
    block_title: str = "↕",
) -> bool:
    """
    Add block events that correspond to main events
    Return True if events were added
    """
    updated = False
    new_block_events = []
    for event in events_a:
        if "dateTime" not in event["start"] or "dateTime" not in event["end"]:
            continue
        start_time = datetime.fromisoformat(event["start"]["dateTime"])
        end_time = datetime.fromisoformat(event["end"]["dateTime"])

        # skip events that are more than 90 days from now
        now = datetime.now(timezone.utc)
        ninety_days_later = now + timedelta(days=90)
        if start_time <= now or start_time >= ninety_days_later:
            continue

        block_start = start_time - timedelta(minutes=buffer_minutes)
        block_end = end_time + timedelta(minutes=buffer_minutes)

        # pre-block
        existing_blocks = [
            e
            for e in block_events_b + new_block_events
            if datetime.fromisoformat(e["start"]["dateTime"]) == block_start
            and datetime.fromisoformat(e["end"]["dateTime"]) == start_time
        ]

        if not existing_blocks:
            new_event = create_block_event(block_start, start_time, block_title)
            insert_event(calendar_b, new_event, credentials)
            new_block_events.append(new_event)
            updated = True

        # post-block
        existing_blocks = [
            e
            for e in block_events_b + new_block_events
            if datetime.fromisoformat(e["start"]["dateTime"]) == end_time
            and datetime.fromisoformat(e["end"]["dateTime"]) == block_end
        ]
        if not existing_blocks:
            new_event = create_block_event(end_time, block_end, block_title)
            insert_event(calendar_b, new_event, credentials)
            new_block_events.append(new_event)
            updated = True
    return updated


def remove_past_block_events(
    block_events_b: list, calendar_b: str, credentials: Credentials
) -> bool:
    """
    Remove past block events
    Return True if events were removed
    """
    updated = False
    for block_event in block_events_b:
        if (
            "dateTime" not in block_event["start"]
            or "dateTime" not in block_event["end"]
        ):
            continue
        block_end_time = datetime.fromisoformat(block_event["end"]["dateTime"])
        if block_end_time < datetime.now(timezone.utc):
            delete_event(calendar_b, block_event["id"], credentials)
            updated = True
    return updated


def remove_orphaned_block_events(
    events_a: list,
    block_events_b: list,
    calendar_b: str,
    credentials: Credentials,
    buffer_minutes: int = BUFFER_MINUTES,
) -> bool:
    """
    Remove orphaned block events that no longer correspond to any main event
    Return True if events were removed
    """
    updated = False
    for block_event in block_events_b:
        if (
            "dateTime" not in block_event["start"]
            or "dateTime" not in block_event["end"]
        ):
            continue
        block_start_time = datetime.fromisoformat(block_event["start"]["dateTime"])
        block_end_time = datetime.fromisoformat(block_event["end"]["dateTime"])

        if (
            "dateTime" not in block_event["start"]
            or "dateTime" not in block_event["end"]
        ):
            continue

        related_events = [
            e
            for e in events_a
            if (
                (
                    datetime.fromisoformat(e["start"]["dateTime"])
                    - timedelta(minutes=buffer_minutes)
                    == block_start_time
                )
                and (datetime.fromisoformat(e["start"]["dateTime"]) == block_end_time)
            )
            or (
                (
                    datetime.fromisoformat(e["end"]["dateTime"])
                    + timedelta(minutes=buffer_minutes)
                    == block_end_time
                )
                and (datetime.fromisoformat(e["end"]["dateTime"]) == block_start_time)
            )
        ]

        if not related_events:
            delete_event(calendar_b, block_event["id"], credentials)
            updated = True
    return updated


def get_block_events(
    calendar_b: str, credentials: Credentials, block_title: str = "↕"
) -> list:
    return [
        event
        for event in get_events(calendar_b, credentials, query=block_title)
        if event.get("summary") == block_title
    ]


def run(calendar_a, calendar_b, buffer_min=BUFFER_MINUTES, block_title="↕"):
    credentials = authenticate_google_api()

    events_a = [
        event
        for event in get_events(calendar_a, credentials)
        if event.get("summary") != block_title
    ]

    block_events_b = get_block_events(calendar_b, credentials, block_title)

    while remove_duplicate_block_events(block_events_b, calendar_b, credentials):
        block_events_b = get_block_events(calendar_b, credentials, block_title)
        pass

    add_block_events(
        events_a, block_events_b, calendar_b, credentials, buffer_min, block_title
    )
    remove_orphaned_block_events(
        events_a, block_events_b, calendar_b, credentials, buffer_min
    )

    # remove past block events
    block_events_b = [
        event
        for event in get_events(
            calendar_b,
            credentials,
            query=block_title,
            timeMin=datetime.min,
        )
        if event.get("summary") == block_title
    ]
    remove_past_block_events(block_events_b, calendar_b, credentials)
