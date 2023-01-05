from theticketpost.application import Application
from flask import render_template, request


class App(Application):

    def __init__(self, desc):
        Application.__init__(self, __name__, __file__, desc)


    def render_component(self):
        #content_type = request.headers.get('Content-Type')
        #if (content_type == 'application/json'):
        #    response = request.json
        #    img_filename = ""
        #    for element in response:
        #        if element["name"] == "variable_name":
        #            variable_value = element["value"]
        #            break
        #     return render_template('sudoku/component.html', variable_name=variable_value)
        return render_template('sudoku/component.html')
