import os
import sys
import datetime

current = os.path.dirname(os.path.realpath(__file__))
sys.path.append(current)

from theticketpost.application import Application
from flask import render_template, request
from loguru import logger
import json
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from google.auth.transport.requests import Request
import datetime
from collections import defaultdict

class App(Application):

    def __init__(self, desc):
        Application.__init__(self, __name__, __file__, desc)



    # Function to format the date in a more readable format
    def format_date(self, date_string):
        date_obj = datetime.datetime.fromisoformat(date_string)
        return date_obj.strftime("%H:%M")
    


    def format_event_dates(self, event):
        start = event['start'].get('dateTime', event['start'].get('date'))
        end = event['end'].get('dateTime', event['end'].get('date'))
        
        if 'T' in start:
            formatted_start = datetime.datetime.fromisoformat(start)
            formatted_end = datetime.datetime.fromisoformat(end)
            all_day = False
            start_time_str = formatted_start.strftime('%H:%M')
            end_time_str = formatted_end.strftime('%H:%M')
        else:
            formatted_start = datetime.datetime.fromisoformat(start)
            formatted_end = datetime.datetime.fromisoformat(end)
            all_day = True
            start_time_str = datetime.datetime.strptime(start, '%Y-%m-%d').date()
            end_time_str = datetime.datetime.strptime(end, '%Y-%m-%d').date()

        event['formatted_start'] = formatted_start
        event['formatted_end'] = formatted_end
        event['all_day'] = all_day
        event['start_time_str'] = self.format_date(start)
        event['end_time_str'] = self.format_date(end)



    # Function to get the start time of an event
    def get_event_start_time(self, event):
        start_time = event['start'].get('dateTime', event['start'].get('date'))
        return start_time



    def get_calendar_events(self, days):
        response = self.get_configuration_json()
        json_object = json.loads(response.data)
        credentials = next((item for item in json_object if item["name"] == "google-credentials"), None)

        for credential in credentials["value"]:
            creds = Credentials.from_authorized_user_info(info=credential["token"])
            if creds:
                if creds.expired and creds.refresh_token:
                    creds.refresh(Request())

                service = build('calendar', 'v3', credentials=creds)    

                # List all calendars
                calendar_list = service.calendarList().list().execute()
                all_events = []

                for calendar in calendar_list['items']:
                    if not calendar.get('hidden', False):
                        calendar_id = calendar['id']

                        # Get events from the current calendar
                        now = datetime.datetime.utcnow().isoformat() + 'Z'  # 'Z' indicates UTC time
                        if days == 0:
                            end_of_day = datetime.datetime.combine(datetime.date.today(), datetime.time.max)
                            future = now
                        else:
                            end_of_day = datetime.datetime.combine(datetime.date.today() + datetime.timedelta(days=days), datetime.time.min)
                                            

                        future = end_of_day.isoformat() + 'Z'
                        events_result = service.events().list(calendarId=calendar_id, timeMin=now, timeMax=future, singleEvents=True, orderBy='startTime').execute()
                        events = events_result.get('items', [])

                        # Iterate through all events
                        for event in events:
                            self.format_event_dates(event)

                        # Combine events from all calendars
                        all_events.extend(events)

                sorted_events = sorted(all_events, key=self.get_event_start_time)

                events_by_date = defaultdict(list)
                for event in sorted_events:
                    date_key = event['formatted_start'].date()  # Utiliza solo la parte de la fecha (sin la hora)
                    events_by_date[date_key].append(event)

                return events_by_date
            
        return []



    def render_component(self):
        content_type = request.headers.get('Content-Type')
        if (content_type == 'application/json'):
            response = request.json
            days = 1
            for element in response:
                if element["name"] == "days":
                    days = int(element["value"]) - 1
        events = self.get_calendar_events(days)
        logger.info(events)

        context = {
            'events_by_date': events,
            'datetime': datetime
        }
        return render_template('google-calendar/component.html', **context)
