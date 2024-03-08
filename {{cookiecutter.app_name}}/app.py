import os
import sys

current = os.path.dirname(os.path.realpath(__file__))
sys.path.append(current)

from theticketpost.application import Application
from flask import render_template, request


class App(Application):

    def __init__(self, desc, flaskApp):
        Application.__init__(self, __name__, __file__, desc, flaskApp)


    def render_component(self):
        #content_type = request.headers.get('Content-Type')
        #if (content_type == 'application/json'):
        #    response = request.json
        #    variable_value = ""
        #    for element in response:
        #        if element["name"] == "variable_name":
        #            variable_value = element["value"]
        #            break
        #     return render_template('{{cookiecutter.app_name}}/component.html', variable_name=variable_value)
        return render_template('{{cookiecutter.app_name}}/component.html')
