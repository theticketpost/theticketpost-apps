from theticketpost.application import Application
from flask import render_template, request
from markupsafe import escape
from loguru import logger
import json
import requests
import datetime

API_URL = "https://api.openweathermap.org"
FORECAST_ITEMS = 4


class App(Application):

    def __init__(self, desc, flaskApp):
        Application.__init__(self, __name__, __file__, desc, flaskApp)


    def epoch_to_str(self, epoch_time, timezone_offset):
        # Hours shown in the city's local time
        timestamp = datetime.datetime.fromtimestamp(epoch_time + timezone_offset, datetime.timezone.utc)
        return timestamp.strftime("%H:%M")


    def get_json(self, path, params):
        response = requests.get(API_URL + path, params=params, timeout=15)
        response.raise_for_status()
        return response.json()


    def get_forecast(self, lon, lat):
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
        forecast_data = self.get_json("/data/2.5/forecast", {**params, "cnt": FORECAST_ITEMS})

        logger.info("Received forecast data")

        timezone_offset = current.get("timezone", 0)

        forecast = []
        for item in forecast_data["list"][:FORECAST_ITEMS]:
            forecast.append({ "hour": self.epoch_to_str(item["dt"], timezone_offset), "temp": item["main"]["temp"], "weather": item["weather"][0] })

        return {
            "unit": unit["value"],
            "city_name": city_name,
            "current_temp": current["main"]["temp"],
            "current_icon": current["weather"][0]["icon"],
            "current_description": current["weather"][0]["description"],
            "forecast": forecast,
            "sunrise": self.epoch_to_str(current["sys"]["sunrise"], timezone_offset),
            "sunset": self.epoch_to_str(current["sys"]["sunset"], timezone_offset)
        }


    def render_component(self):
        content_type = request.headers.get('Content-Type')
        if (content_type == 'application/json'):
            response = request.json
            lon = lat = None
            for element in response:
                if element["name"] == "lon":
                    lon = element["value"]
                elif element["name"] == "lat":
                    lat = element["value"]
            try:
                weather = self.get_forecast(lon, lat)
            except Exception as e:
                # Don't show requests' message: its url contains the api key
                if isinstance(e, requests.HTTPError):
                    error = f"HTTP {e.response.status_code}"
                else:
                    error = type(e).__name__
                logger.error(f"OpenWeather error: {error}")
                return f'<div style="text-align: center;">Weather not available ({escape(error)})</div>'
            return render_template('openweather/component.html', weather = weather )
