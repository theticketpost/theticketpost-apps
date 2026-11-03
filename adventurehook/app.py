import os
import sys

current = os.path.dirname(os.path.realpath(__file__))
sys.path.append(current)

from theticketpost.application import Application
from flask import render_template, request
from loguru import logger
import theticketpost.llm as llm
import random
import json

class App(Application):

    def __init__(self, desc, flaskApp):
        Application.__init__(self, __name__, __file__, desc, flaskApp)
        self.dicts = { "theme": [], "location": [], "objetives": [], "threats": [], "npcs": [], "adventure_type": [] }
        for attr in self.desc["inspector_template"]:
            self.dicts[attr["name"]] = [ item["value"] for item in attr["options"] ]


    def get_parameter(self, element):
        if ( element["name"] in self.dicts ):
            max_index = len(self.dicts[element["name"]]) - 1
            random_index = random.randint(1, max_index)
            return element["value"] if element["value"] != "random" else self.dicts[element["name"]][random_index]



    # Function that generates a role-playing game adventure hook from a list of categories
    def generate_hook(self, language, theme, location, objectives, threats, npcs, adventure_type):

        provider = self.get_configuration_value("llm_provider", "openai")
        model = self.get_configuration_value("model")

        # Concatenate the categories into a single input text string
        input_text = f"Please generate an adventure hook without listing the given parameters. " \
                    f"Generate only one role-playing game adventure hook in {language} with the following parameters:\n\n" \
                    f"Theme: {theme}\n" \
                    f"Location: {location}\n" \
                    f"Objectives: {objectives}\n" \
                    f"Threats: {threats}\n" \
                    f"NPCs: {npcs}\n" \
                    f"Type of adventure: {adventure_type}"

        # No 'temperature' or 'max_tokens': current reasoning models reject them, so the length is set in the prompt
        messages = [
            {"role": "system", "content": "You are an AI trained to generate short and concise role-playing game adventure hooks based on specific parameters. Answer with a single paragraph of at most 120 words, in plain text without markdown."},
            {"role": "user", "content": input_text}
        ]
        try:
            output_text = llm.chat(provider, messages, model=model)
        except llm.LLMError as e:
            logger.error(f"Adventure hook: {e}")
            output_text = f"No adventure hook today: {e}"

        return output_text



    def render_component(self):


        # Ejemplo de uso de la función generar_gancho
        language = "english"
        theme = ""
        location = ""
        objectives = ""
        threats = ""
        npcs = ""
        adventure_type = ""
        content_type = request.headers.get('Content-Type')
        if (content_type == 'application/json'):
            response = request.json
            for element in response:
                if element["value"]:
                    if element["name"] == "language":
                        language = element["value"]
                    elif element["name"] == "theme":
                        theme = self.get_parameter(element)
                    elif element["name"] == "location":
                        location = self.get_parameter(element)
                    elif element["name"] == "objectives":
                        objectives = self.get_parameter(element)
                    elif element["name"] == "threats":
                        threats = self.get_parameter(element)
                    elif element["name"] == "npcs":
                        npcs = self.get_parameter(element)
                    elif element["name"] == "adventure_type":
                        adventure_type = self.get_parameter(element)

            hook = self.generate_hook(language, theme, location, objectives, threats, npcs, adventure_type)

            return render_template('adventurehook/component.html', hook=hook, theme=theme)
