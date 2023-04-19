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

class App(Application):

    def __init__(self, desc):
        Application.__init__(self, __name__, __file__, desc)


    def get_calendar_events(self):
        days = 1
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
                    calendar_id = calendar['id']

                    # Get events from the current calendar
                    now = datetime.datetime.utcnow().isoformat() + 'Z'  # 'Z' indicates UTC time
                    future = (datetime.datetime.utcnow() + datetime.timedelta(days=days)).isoformat() + 'Z'
                    events_result = service.events().list(calendarId=calendar_id, timeMin=now, timeMax=future, singleEvents=True, orderBy='startTime').execute()
                    events = events_result.get('items', [])

                    # Combine events from all calendars
                    all_events.extend(events)

                return all_events
            
        return []



    def render_component(self):
        events = self.get_calendar_events()
        logger.info(events)
        #content_type = request.headers.get('Content-Type')
        #if (content_type == 'application/json'):
        #    response = request.json
        #    variable_value = ""
        #    for element in response:
        #        if element["name"] == "variable_name":
        #            variable_value = element["value"]
        #            break
        #     return render_template('google-calendar/component.html', variable_name=variable_value)
        return render_template('google-calendar/component.html', events=events)
