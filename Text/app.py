from threading import Thread
from loguru import logger
import time

class App(Thread):
    def __init__(self):
        Thread.__init__(self)

    def run(self):
        while True:
            logger.debug("TextApp is waiting for you")
            time.sleep(30)

    def hello():
        logger.info("HELLO WORLD!!")
