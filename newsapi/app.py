import os
import sys

current = os.path.dirname(os.path.realpath(__file__))
sys.path.append(current)

from theticketpost.application import Application
from flask import render_template, request
from loguru import logger
import json
import requests
import urllib.parse
import datetime

class App(Application):

    def __init__(self, desc):
        Application.__init__(self, __name__, __file__, desc)


    def parse_search_parameters(self, response):
        country = ""
        category = ""
        q = ""
        domains = ""
        language = ""
        sort_by = ""
        for element in response:
            if element["value"]:
                if element["name"] == "country":
                    country = "&country=" + element["value"]
                elif element["name"] == "category":
                    category = "&category=" + element["value"]
                elif element["name"] == "q":
                    q = "&q=" + urllib.parse.quote(element["value"])
                elif element["name"] == "domains":
                    domains = "&domains=" + element["value"]
                elif element["name"] == "language":
                    language = "&language=" + element["value"]
                elif element["name"] == "sort_by":
                    sort_by = "&sortBy=" + element["value"]

        return {"country": country, "category": category, "q": q, "domains": domains, "language": language, "sort_by": sort_by}


    def get_headlines(self, json_search_parameters):
        response = self.get_configuration_json()
        json_object = json.loads(response.data)
        api_key = next((item for item in json_object if item["name"] == "api_key"), None)

        timestamp = datetime.datetime.now() - datetime.timedelta(days=1)
        last24h = timestamp.strftime("%Y-%m-%dT%H:%M:%SZ")

        search_parameters = self.parse_search_parameters(json_search_parameters)
        if search_parameters["domains"]:
            url = "https://newsapi.org/v2/everything?apiKey=%s&pageSize=5&from=%s%s%s%s%s" % (api_key["value"], last24h, search_parameters["q"], search_parameters["domains"], search_parameters["language"], search_parameters["sort_by"])
        else:
            url = "https://newsapi.org/v2/top-headlines?apiKey=%s&pageSize=5&from=%s%s%s%s" % (api_key["value"], last24h, search_parameters["country"], search_parameters["category"], search_parameters["q"])

        response = requests.get(url)
        data = json.loads(response.text)
        if data["status"] != "error":
            for article in data["articles"]:
                timestamp = datetime.datetime.strptime(article["publishedAt"],"%Y-%m-%dT%H:%M:%SZ")
                article["publishedAt"] = timestamp.strftime("%B %-d, %Y at %-I:%M %p %Z")
                if not article["source"]["id"]:
                    article["source"]["id"] = article["source"]["name"]

            return data["articles"]
        else:
            return []


    def render_component(self):
        content_type = request.headers.get('Content-Type')
        if (content_type == 'application/json'):
            response = request.json
            articles = self.get_headlines(response)
            print(articles)
            return render_template('newsapi/component.html', articles=articles)
