from threading import Thread
from loguru import logger
import time
from flask import Blueprint, render_template
import os

class App(Thread):
    def __init__(self, desc):
        Thread.__init__(self)
        self.desc = desc
        self.configuration = True
        self.component = True
        self.inspector = True
        self.blueprint = Blueprint('imageapp_blueprint', __name__,
            template_folder='templates',
            static_folder='static')
        self.blueprint.add_url_rule('/api/apps/image/component',
            view_func=self.render_component,
            methods=['POST'])
        self.blueprint.add_url_rule('/api/apps/image/inspector',
            view_func=self.render_inspector)
        self.blueprint.add_url_rule('/api/apps/image/configuration',
            view_func=self.render_configuration)


    def run(self):
        while True:
            #logger.debug("ImageApp is waiting for you")
            time.sleep(30)


    def get_description(self):
        return self.desc


    def render_configuration(self):
        return render_template('configuration.html')


    def render_inspector(self):
        return render_template('inspector.html')


    def render_component(self):
        if (request.method == 'POST'):
            content_type = request.headers.get('Content-Type')
            if (content_type == 'application/json'):
                json = request.json
                apps = theticketpost.applications.list()

                return render_template('component.html', config=json )

        return "500"
