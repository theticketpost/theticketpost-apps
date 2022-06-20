from threading import Thread
from loguru import logger
import time
from flask import Blueprint, render_template, jsonify
import os

class App(Thread):
    def __init__(self, desc):
        Thread.__init__(self)
        self.desc = desc
        self.blueprint = Blueprint('imageapp_blueprint', __name__,
            template_folder='templates',
            static_folder='static')
        self.blueprint.add_url_rule('/api/apps/image/component',
            view_func=self.render_component,
            methods=['POST'])
        self.blueprint.add_url_rule('/api/apps/image/inspector',
            view_func=self.get_inspector_json)
        self.blueprint.add_url_rule('/api/apps/image/configuration',
            view_func=self.get_configuration_json)


    def run(self):
        while True:
            #logger.debug("ImageApp is waiting for you")
            time.sleep(30)


    def get_description(self):
        return self.desc


    def get_configuration_json(self):
        if ( self.desc["configuration"] ):
            return jsonify( self.desc["configuration_template"] )
        return jsonify({})


    def get_inspector_json(self):
        if ( self.desc["configuration"] ):
            return jsonify( self.desc["configuration_template"] )
        return jsonify({})


    def render_component(self):
        if (request.method == 'POST'):
            content_type = request.headers.get('Content-Type')
            if (content_type == 'application/json'):
                json = request.json
                apps = theticketpost.applications.list()

                return render_template('component.html', config=json )

        return "500"
