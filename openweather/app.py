from theticketpost.application import Application
from flask import render_template, request
from loguru import logger
import json
import requests
import datetime


class App(Application):

    def __init__(self, desc, flaskApp):
        Application.__init__(self, __name__, __file__, desc, flaskApp)


    def epoch_to_str(self, epoch_time):
        timestamp = datetime.datetime.fromtimestamp(  epoch_time )
        return timestamp.strftime("%H:%M")

    def get_forecast(self, lon, lat):
        # get app configuration parameters
        response = self.get_configuration_json()
        json_object = json.loads(response.data)
        api_key = next((item for item in json_object if item["name"] == "api_key"), None)
        unit = next((item for item in json_object if item["name"] == "unit"), None)

        # request city name from lat & lon
        url = "http://api.openweathermap.org/geo/1.0/reverse?lat=%s&lon=%s&limit=1&appid=%s" % (lat, lon, api_key["value"])
        response = requests.get(url)
        data = json.loads(response.text)
        city_name = data[0]["name"]

        # request data forecast to openweather
        url = "https://api.openweathermap.org/data/2.5/onecall?lat=%s&lon=%s&appid=%s&units=%s" % (lat, lon, api_key["value"], unit["value"])
        response = requests.get(url)
        data = json.loads(response.text)

        logger.info("Received forecast data")

        current_temp = data["current"]["temp"]
        current_icon = data["current"]["weather"][0]["icon"]
        current_description = data["current"]["weather"][0]["description"]

        hourly = data["hourly"]
        forecast = []
        for i in range(1, 11, 3):
            forecast.append({ "hour": self.epoch_to_str(hourly[i]["dt"]), "temp": hourly[i]["temp"], "weather": hourly[i]["weather"][0] })


        sunset = self.epoch_to_str(data["current"]["sunset"])
        sunrise = self.epoch_to_str(data["current"]["sunrise"])

        return {"unit": unit["value"], "city_name": city_name, "current_temp": current_temp, "current_icon": current_icon, "current_description": current_description, "forecast": forecast, "sunrise": sunrise, "sunset": sunset }


    def render_component(self):
        content_type = request.headers.get('Content-Type')
        if (content_type == 'application/json'):
            response = request.json
            img_filename = ""
            for element in response:
                if element["name"] == "lon":
                    lon = element["value"]
                elif element["name"] == "lat":
                    lat = element["value"]
            weather = self.get_forecast(lon, lat)
            return render_template('openweather/component.html', weather = weather )
