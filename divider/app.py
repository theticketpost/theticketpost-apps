from theticketpost.application import Application
from flask import render_template, request


class App(Application):

    def __init__(self, desc, flaskApp):
        Application.__init__(self, __name__, __file__, desc, flaskApp)


    def render_component(self):
        content_type = request.headers.get('Content-Type')
        if (content_type == 'application/json'):
            response = request.json
            img_filename = ""
            for element in response:
                if element["name"] == "text_to_print":
                    text_to_print = element["value"]
                    break
            return render_template('divider/component.html', text_to_print=text_to_print )
