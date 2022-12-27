from theticketpost.application import Application
from flask import render_template, request

ALLOWED_EXTENSIONS = {'jpg', 'jpeg', 'svg', 'png'}

class App(Application):
    
    def __init__(self, desc):
        Application.__init__(self, __name__, __file__, desc)


    def render_component(self):
        content_type = request.headers.get('Content-Type')
        if (content_type == 'application/json'):
            config = request.json
            img_filename = ""
            for element in config:
                if element["name"] == "text_to_print":
                    text_to_print = element["value"]
                    break
            return render_template('component2.html', text_to_print=text_to_print )