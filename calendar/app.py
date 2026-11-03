import os
import sys

current = os.path.dirname(os.path.realpath(__file__))
sys.path.append(current)

from theticketpost.application import Application
from flask import render_template, request, jsonify
from loguru import logger
from markupsafe import escape
from collections import defaultdict
import copy
import datetime
import re
import requests
import icalendar
import recurring_ical_events


class App(Application):
    """Reads the calendars from their secret iCal addresses.

    Google Calendar: Settings > (your calendar) > Integrate calendar > Secret
    address in iCal format. No Google Cloud project or OAuth needed, and it
    works the same with Outlook, iCloud or Nextcloud calendars."""

    def __init__(self, desc, flaskApp):
        Application.__init__(self, __name__, __file__, desc, flaskApp)


    def calendars(self):
        """[{"name", "url"}] from the app settings, in their order."""
        entries = self.get_configuration_value("calendars", [])
        calendars = []
        for index, entry in enumerate(entries if isinstance(entries, list) else [], start=1):
            url = str(entry.get("url", "")).strip()
            if url:
                # webcal:// is how some providers share the same https address
                url = re.sub(r"^webcal://", "https://", url, flags=re.I)
                calendars.append({"name": str(entry.get("name", "")).strip() or f"Calendar {index}", "url": url})
        return calendars


    def get_inspector_json(self):
        """The section options, with the calendars from the settings to choose from."""
        template = copy.deepcopy(self.desc["inspector_template"])
        for item in template:
            if item["name"] == "calendar":
                item["options"] = [{"value": "", "description": "All calendars"}] + \
                    [{"value": calendar["name"], "description": calendar["name"]} for calendar in self.calendars()]
        return jsonify({"refresh_component": self.desc["refresh_component"], "config": template})


    def fetch_calendar(self, url):
        response = requests.get(url, timeout=20)
        response.raise_for_status()
        return icalendar.Calendar.from_ical(response.content)


    def to_local(self, value):
        """Event times as local datetimes. All-day events come as dates.
        astimezone() also takes times without a timezone as local."""
        if not isinstance(value, datetime.datetime):
            value = datetime.datetime.combine(value, datetime.time.min)
        return value.astimezone()


    def to_event(self, component, today, calendar_name):
        start = component.get("dtstart").dt
        end = component.get("dtend").dt if component.get("dtend") else start
        all_day = not isinstance(start, datetime.datetime)
        start, end = self.to_local(start), self.to_local(end)
        return {
            "summary": str(component.get("summary", "")),
            "calendar": calendar_name,
            "location": str(component.get("location", "")),
            "all_day": all_day,
            "start": start,
            "start_time_str": start.strftime("%H:%M"),
            "end_time_str": end.strftime("%H:%M"),
            # an event that started on an earlier day and still goes on shows today
            "date": max(start.date(), today),
        }


    def get_calendar_events(self, calendars, days):
        """Events from now to the end of the last day, grouped by day, and the
        names of the calendars that couldn't be read."""
        now = datetime.datetime.now().astimezone()
        today = now.date()
        until = datetime.datetime.combine(today + datetime.timedelta(days=days), datetime.time.min).astimezone()

        events = []
        failed = []
        for calendar_info in calendars:
            try:
                calendar = self.fetch_calendar(calendar_info["url"])
            except Exception as e:
                # never log the address: it gives access to the calendar
                error = f"HTTP {e.response.status_code}" if isinstance(e, requests.HTTPError) else type(e).__name__
                logger.error(f"Calendar {calendar_info['name']}: could not read it ({error})")
                failed.append(calendar_info["name"])
                continue
            for component in recurring_ical_events.of(calendar).between(now, until):
                events.append(self.to_event(component, today, calendar_info["name"]))

        # per day: all-day events first, then by time
        events.sort(key=lambda event: (event["date"], not event["all_day"], event["start"]))
        events_by_date = defaultdict(list)
        for event in events:
            events_by_date[event["date"]].append(event)
        return events_by_date, failed


    def render_component(self):
        days = 1
        selected = ""
        show_names = True
        content_type = request.headers.get('Content-Type')
        if (content_type == 'application/json'):
            for element in request.json:
                if element["name"] == "days":
                    try:
                        days = max(1, int(element["value"]))
                    except (TypeError, ValueError):
                        pass
                elif element["name"] == "calendar":
                    selected = element["value"] or ""
                elif element["name"] == "show_names":
                    show_names = bool(element["value"])

        calendars = self.calendars()
        if not calendars:
            return '<div style="text-align: center;">Add your calendars in the app settings</div>'
        if selected:
            calendars = [calendar for calendar in calendars if calendar["name"] == selected]
            if not calendars:
                return f'<div style="text-align: center;">There is no calendar called "{escape(selected)}" in the app settings</div>'

        events_by_date, failed = self.get_calendar_events(calendars, days)
        context = {
            'events_by_date': events_by_date,
            'failed': failed,
            # the name only tells something when the events come from several calendars
            'show_names': show_names and len(calendars) > 1,
            'datetime': datetime
        }
        return render_template('calendar/component.html', **context)
