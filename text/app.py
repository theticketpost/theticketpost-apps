from theticketpost.application import Application
from flask import render_template, request
import datetime


class App(Application):

    def __init__(self, desc):
        Application.__init__(self, __name__, __file__, desc)

    def foo(self, string):
        timestamp = datetime.datetime.now()
        return timestamp.strftime(string)

    def render_component(self):
        content_type = request.headers.get('Content-Type')
        if (content_type == 'application/json'):
            response = request.json
            img_filename = ""
            for element in response:
                if element["name"] == "text_to_print":
                    text_to_print = element["value"]
                    break
            return render_template('text/component.html', text_to_print=self.foo(text_to_print) )
