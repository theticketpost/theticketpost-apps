from threading import Thread
from loguru import logger
import time
from flask import Blueprint, render_template, jsonify, url_for
import os
import json

class App(Thread):
    def __init__(self, desc):
        Thread.__init__(self)
        self.desc = desc
        self.blueprint = Blueprint('imageapp_blueprint', __name__,
            template_folder='templates',
            static_folder='static',
            static_url_path='/imageapp_blueprint/static')
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


    def refresh(self):
        logger.debug("configuration file updated!")
        return


    def get_description(self):
        if ( self.desc["render_component"] ):
            self.desc["icon_url"] = url_for('imageapp_blueprint.static', filename='icon.svg')
        return self.desc


    def get_configuration_json(self):
        if ( self.desc["configuration"] ):
            path_to_config = os.path.join(os.path.dirname(__file__), 'config.json')
            if os.path.exists(path_to_config):
                with open(path_to_config) as config_file:
                    data = json.load(config_file)
                    return jsonify(data)

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
