from theticketpost.application import Application
from flask import render_template, request
from loguru import logger
import json
import requests


class App(Application):

    def __init__(self, desc):
        Application.__init__(self, __name__, __file__, desc)


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

        return {"city_name": city_name, "current_temp": data["current"]["temp"]}


    def render_component(self):
        forecast = self.get_forecast()
        return render_template('openweather/component.html', city_name = forecast["city_name"], current_temp=forecast["current_temp"])
