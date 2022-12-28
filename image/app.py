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
                if element["name"] == "image_filename":
                    img_filename = element["value"]
                    break
            return render_template('image/component.html', img_filename=img_filename )
