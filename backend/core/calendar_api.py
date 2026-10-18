import os
import zoneinfo
from datetime import datetime, timedelta
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from .tool_events import notify_tool_execution

SCOPES = [
    'https://www.googleapis.com/auth/calendar',
    'https://www.googleapis.com/auth/tasks'
]

MIAMI_TZ = zoneinfo.ZoneInfo("America/New_York")

def get_calendar_service():
    """Initializes and returns the authenticated Google Calendar API service."""
    creds = None
    token_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'token.json')
    
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                with open(token_path, 'w') as token_file:
                    token_file.write(creds.to_json())
            except Exception as e:
                print(f"⚠️ [CalendarAPI] Token refresh warning: {e}")
    else:
        raise FileNotFoundError(f"token.json not found at {token_path}. Authentication required.")
        
    return build('calendar', 'v3', credentials=creds)

def get_calendar_events(time_window: str = "today", max_results: int = 10) -> str:
    """
    Retrieves events from Fab's primary Google Calendar.
    
    Args:
        time_window: The time range to inspect. Can be "today", "tomorrow", "this_week", 
                     or an ISO 8601 date string (e.g., "2026-10-19"). Defaults to "today".
        max_results: Maximum number of events to return (default 10).
    
    Returns:
        A concise, natural language summary of scheduled calendar events suited for spoken delivery.
    """
    notify_tool_execution("calendar")
    try:
        service = get_calendar_service()
        now = datetime.now(MIAMI_TZ)
        
        # Calculate time_min and time_max based on window
        window_clean = (time_window or "today").lower().strip()
        if window_clean in ["today", "now"]:
            start_dt = now.replace(hour=0, minute=0, second=0, microsecond=0)
            end_dt = start_dt + timedelta(days=1)
            period_label = "today"
        elif window_clean == "tomorrow":
            start_dt = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
            end_dt = start_dt + timedelta(days=1)
            period_label = "tomorrow"
        elif window_clean in ["this_week", "week"]:
            start_dt = now.replace(hour=0, minute=0, second=0, microsecond=0)
            end_dt = start_dt + timedelta(days=7)
            period_label = "this week"
        else:
            # Try parsing custom date
            try:
                parsed = datetime.fromisoformat(window_clean)
                start_dt = parsed.replace(tzinfo=MIAMI_TZ, hour=0, minute=0, second=0)
                end_dt = start_dt + timedelta(days=1)
                period_label = start_dt.strftime("%A, %B %d")
            except Exception:
                start_dt = now.replace(hour=0, minute=0, second=0, microsecond=0)
                end_dt = start_dt + timedelta(days=1)
                period_label = "today"

        events_result = service.events().list(
            calendarId='primary',
            timeMin=start_dt.isoformat(),
            timeMax=end_dt.isoformat(),
            maxResults=max_results,
            singleEvents=True,
            orderBy='startTime'
        ).execute()
        
        events = events_result.get('items', [])
        if not events:
            return f"Fab, your calendar is completely clear for {period_label}."
            
        event_descriptions = []
        for event in events:
            summary = event.get('summary', 'Untitled Event')
            start = event.get('start', {})
            location = event.get('location', '')
            
            # Format time
            if 'dateTime' in start:
                dt = datetime.fromisoformat(start['dateTime']).astimezone(MIAMI_TZ)
                time_str = dt.strftime("%I:%M %p").lstrip('0')
            elif 'date' in start:
                time_str = "All day"
            else:
                time_str = "Time unspecified"
                
            desc = f"{summary} at {time_str}"
            if location:
                desc += f" (at {location})"
            event_descriptions.append(desc)
            
        count = len(event_descriptions)
        header = f"You have {count} event{'s' if count > 1 else ''} scheduled for {period_label}: "
        return header + "; ".join(event_descriptions) + "."

    except Exception as e:
        print(f"❌ [CalendarAPI] Error fetching calendar events: {e}")
        return f"I encountered an error accessing your Google Calendar: {str(e)}"

def create_calendar_event(summary: str, start_time: str, end_time: str = None, description: str = None, location: str = None) -> str:
    """
    Creates a new event on Fab's primary Google Calendar.
    
    Args:
        summary: Title/name of the event (e.g., "Lunch with Marc", "Design Review").
        start_time: ISO 8601 string or natural time format (e.g. "2026-10-19T13:00:00").
        end_time: Optional end time. If omitted, defaults to 1 hour after start_time.
        description: Optional notes or description.
        location: Optional location (e.g., "Joe's Stone Crab", "Miami Design District").
        
    Returns:
        Confirmation message suitable for voice delivery.
    """
    notify_tool_execution("calendar")
    try:
        service = get_calendar_service()
        
        # Parse start_time
        try:
            start_dt = datetime.fromisoformat(start_time)
            if start_dt.tzinfo is None:
                start_dt = start_dt.replace(tzinfo=MIAMI_TZ)
        except Exception:
            return f"Unable to parse event start time '{start_time}'. Please provide a valid date/time."
            
        if end_time:
            try:
                end_dt = datetime.fromisoformat(end_time)
                if end_dt.tzinfo is None:
                    end_dt = end_dt.replace(tzinfo=MIAMI_TZ)
            except Exception:
                end_dt = start_dt + timedelta(hours=1)
        else:
            end_dt = start_dt + timedelta(hours=1)
            
        event_body = {
            'summary': summary,
            'start': {'dateTime': start_dt.isoformat(), 'timeZone': 'America/New_York'},
            'end': {'dateTime': end_dt.isoformat(), 'timeZone': 'America/New_York'},
        }
        if description:
            event_body['description'] = description
        if location:
            event_body['location'] = location
            
        created = service.events().insert(calendarId='primary', body=event_body).execute()
        time_formatted = start_dt.strftime("%A, %B %d at %I:%M %p").replace(" 0", " ")
        return f"Successfully scheduled '{summary}' on your Google Calendar for {time_formatted}."
        
    except Exception as e:
        print(f"❌ [CalendarAPI] Error creating event: {e}")
        return f"I was unable to schedule '{summary}' on your calendar: {str(e)}"
