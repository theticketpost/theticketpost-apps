from theticketpost.application import Application
from flask import render_template, request
from markupsafe import escape
from loguru import logger
import json
import requests
import datetime

API_URL = "https://api.openweathermap.org"
# The free forecast comes in 3 hour steps: 16 steps cover today and tomorrow
FORECAST_STEPS = 16
# Sections saved before the hour range existed show the next slots
DEFAULT_ITEMS = 4


class App(Application):

    def __init__(self, desc, flaskApp):
        Application.__init__(self, __name__, __file__, desc, flaskApp)


    def epoch_to_str(self, epoch_time, timezone_offset):
        # Hours shown in the city's local time
        timestamp = datetime.datetime.fromtimestamp(epoch_time + timezone_offset, datetime.timezone.utc)
        return timestamp.strftime("%H:%M")


    def forecast_title(self, tomorrow):
        # only worth saying when the slots aren't today's
        return "Tomorrow" if tomorrow else ""


    def get_json(self, path, params):
        response = requests.get(API_URL + path, params=params, timeout=15)
        response.raise_for_status()
        return response.json()


    def pick_slots(self, items, timezone_offset, hour_from, hour_to):
        """Forecast slots between hour_from and hour_to (local time, inclusive) of
        the first day that still has some: today, or tomorrow once today's range
        is over. When part of today's range has already passed, the forecast no
        longer has those slots: fill the row with the slots that come after it.
        Returns (slots, is_tomorrow)."""
        if hour_from is None or hour_to is None:
            return items[:DEFAULT_ITEMS], False

        today = None
        days = {}
        for item in items:
            local = datetime.datetime.fromtimestamp(item["dt"] + timezone_offset, datetime.timezone.utc)
            today = today or local.date()
            if hour_from <= local.hour <= hour_to:
                days.setdefault(local.date(), []).append(item)

        if not days:
            return [], False

        day = min(days)
        slots = days[day]
        if day == today:
            # a full day of the range (tomorrow's) tells how many slots fit in it
            wanted = min(DEFAULT_ITEMS, max(len(s) for s in days.values()))
            start = items.index(slots[-1]) + 1
            slots = slots + items[start:start + wanted - len(slots)]
        return slots, day != today


    def get_forecast(self, lon, lat, hour_from=None, hour_to=None):
        # get app configuration parameters
        response = self.get_configuration_json()
        json_object = json.loads(response.data)
        api_key = next((item for item in json_object if item["name"] == "api_key"), None)
        unit = next((item for item in json_object if item["name"] == "unit"), None)

        params = {"lat": lat, "lon": lon, "appid": api_key["value"], "units": unit["value"]}

        # request city name from lat & lon
        data = self.get_json("/geo/1.0/reverse", {**params, "limit": 1})
        city_name = data[0]["name"] if data else ""

        # One Call API 2.5 was shut down in June 2024 and 3.0 needs a paid subscription:
        # use the free current weather and 5 day / 3 hour forecast APIs
        current = self.get_json("/data/2.5/weather", params)
        forecast_data = self.get_json("/data/2.5/forecast", {**params, "cnt": FORECAST_STEPS})

        logger.info("Received forecast data")

        timezone_offset = current.get("timezone", 0)

        slots, tomorrow = self.pick_slots(forecast_data["list"], timezone_offset, hour_from, hour_to)

        forecast = []
        for item in slots:
            forecast.append({ "hour": self.epoch_to_str(item["dt"], timezone_offset), "temp": item["main"]["temp"], "weather": item["weather"][0] })

        return {
            "unit": unit["value"],
            "city_name": city_name,
            "current_temp": current["main"]["temp"],
            "current_icon": current["weather"][0]["icon"],
            "current_description": current["weather"][0]["description"],
            "forecast": forecast,
            "forecast_title": self.forecast_title(tomorrow),
            "sunrise": self.epoch_to_str(current["sys"]["sunrise"], timezone_offset),
            "sunset": self.epoch_to_str(current["sys"]["sunset"], timezone_offset)
        }


    def parse_hour(self, value, default):
        try:
            return min(23, max(0, int(value)))
        except (TypeError, ValueError):
            return default


    def render_component(self):
        content_type = request.headers.get('Content-Type')
        if (content_type == 'application/json'):
            response = request.json
            lon = lat = hour_from = hour_to = None
            for element in response:
                if element["name"] == "lon":
                    lon = element["value"]
                elif element["name"] == "lat":
                    lat = element["value"]
                elif element["name"] == "hour_from":
                    hour_from = self.parse_hour(element["value"], 0)
                elif element["name"] == "hour_to":
                    hour_to = self.parse_hour(element["value"], 23)
            if hour_from is not None and hour_to is not None and hour_from > hour_to:
                hour_from, hour_to = hour_to, hour_from
            try:
                weather = self.get_forecast(lon, lat, hour_from, hour_to)
            except Exception as e:
                # Don't show requests' message: its url contains the api key
                if isinstance(e, requests.HTTPError):
                    error = f"HTTP {e.response.status_code}"
                else:
                    error = type(e).__name__
                logger.error(f"OpenWeather error: {error}")
                return f'<div style="text-align: center;">Weather not available ({escape(error)})</div>'
            return render_template('openweather/component.html', weather = weather )
