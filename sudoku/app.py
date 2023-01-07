import os
import sys

current = os.path.dirname(os.path.realpath(__file__))
sys.path.append(current)

from theticketpost.application import Application
from flask import render_template, request
from loguru import logger

from generator import *

class App(Application):

    def __init__(self, desc):
        Application.__init__(self, __name__, __file__, desc)


    def generate_sudoku(self, level):
        difficulties = {
            'easy': (35, 0),
            'medium': (81, 5),
            'hard': (81, 10),
            'extreme': (81, 15)
        }

        difficulty = difficulties[level]

        gen = Generator(os.path.join(current, "base.txt"))
        gen.randomize(100)

        gen.reduce_via_logical(difficulty[0])
        if difficulty[1] != 0:
            gen.reduce_via_random(difficulty[1])

        return gen.board.get_list()


    def render_component(self):
        content_type = request.headers.get('Content-Type')
        if (content_type == 'application/json'):
            response = request.json
            img_filename = ""
            for element in response:
                if element["name"] == "level":
                    level = element["value"]
                    break
            return render_template('sudoku/component.html', numbers = self.generate_sudoku(level), level=level)
