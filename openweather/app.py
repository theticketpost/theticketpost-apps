from theticketpost.application import Application
from flask import render_template, request
from loguru import logger
import json
import requests
import datetime


class App(Application):

    def __init__(self, desc):
        Application.__init__(self, __name__, __file__, desc)


    def epoch_to_str(self, epoch_time):
        timestamp = datetime.datetime.fromtimestamp(  epoch_time )
        return timestamp.strftime("%H:%M")

    def get_forecast(self):
        # get app configuration parameters
        response = self.get_configuration_json()
        json_object = json.loads(response.data)
        api_key = next((item for item in json_object if item["name"] == "api_key"), None)
        lat = next((item for item in json_object if item["name"] == "lat"), None)
        lon = next((item for item in json_object if item["name"] == "lon"), None)
        unit = next((item for item in json_object if item["name"] == "unit"), None)

        # request city name from lat & lon
        url = "http://api.openweathermap.org/geo/1.0/reverse?lat=%s&lon=%s&limit=1&appid=%s" % (lat["value"], lon["value"], api_key["value"])
        response = requests.get(url)
        data = json.loads(response.text)
        city_name = data[0]["name"]

        # request data forecast to openweather
        url = "https://api.openweathermap.org/data/2.5/onecall?lat=%s&lon=%s&appid=%s&units=%s" % (lat["value"], lon["value"], api_key["value"], unit["value"])
        response = requests.get(url)
        data = json.loads(response.text)

        logger.info("Received forecast data")

        current_temp = data["current"]["temp"]
        current_icon = data["current"]["weather"][0]["icon"]
        current_description = data["current"]["weather"][0]["description"]

        hourly = data["hourly"]
        forecast = []
        logger.info("current hour" + self.epoch_to_str(data["current"]["dt"]))
        for i in range(1, 11, 3):
            forecast.append({ "hour": self.epoch_to_str(hourly[i]["dt"]), "temp": hourly[i]["temp"], "weather": hourly[i]["weather"][0] })


        sunset = self.epoch_to_str(data["current"]["sunset"])
        sunrise = self.epoch_to_str(data["current"]["sunrise"])

        return {"unit": unit["value"], "city_name": city_name, "current_temp": current_temp, "current_icon": current_icon, "current_description": current_description, "forecast": forecast, "sunrise": sunrise, "sunset": sunset }


    def render_component(self):
        weather = self.get_forecast()
        return render_template('openweather/component.html', weather = weather )
