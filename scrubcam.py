#!/usr/bin/env python
"""Code for ScrubCam field camera device

The code that runs on the Scrubcam field camera device.  Gets
configuration information from a YAML file provided as a command line
argument.  There is an example configuration file at:

cfgs/config.yaml.example

To run:

./scrubcam.py cfgs/YOUR_CONFIGURATION_FILE.yaml

"""
import logging
import io
import argparse
from datetime import datetime

import yaml
import picamera

from dencam.gui import State

from scrubcam.vision import ObjectDetectionSystem
from scrubcam.networking import ClientSocketHandler
from scrubcam.display import Display
from scrubcam.lora import LoRaSender

logging.basicConfig(level='INFO',
                    format='[%(levelname)s] %(message)s (%(name)s)')
log = logging.getLogger('main')

parser = argparse.ArgumentParser()
parser.add_argument('config_filename')
parser.add_argument('-c', '--continue', dest='cont', action='store_true')
args = parser.parse_args()
CONFIG_FILE = args.config_filename
CONTINUE_RUN = args.cont

with open(CONFIG_FILE, encoding="utf-8") as f:
    configs = yaml.load(f, Loader=yaml.SafeLoader)

RECORD = configs['RECORD']
RECORD_CONF_THRESHOLD = configs['RECORD_CONF_THRESHOLD']
CAMERA_RESOLUTION = configs['CAMERA_RESOLUTION']
CAMERA_ROTATION = configs['CAMERA_ROTATION']
FILTER_CLASSES = configs['FILTER_CLASSES']

HEADLESS = configs['HEADLESS']
CONNECT_REMOTE_SERVER = configs['CONNECT_REMOTE_SERVER']
LORA_ON = configs['LORA_ON']


def main():
    """Main routine of Scrubcam

    """
    if LORA_ON:
        lora_sender = LoRaSender()
    else:
        log.info('LoRa is ***DISABLED***\n\n')

    detector = ObjectDetectionSystem(configs)
    stream = io.BytesIO()

    camera = picamera.PiCamera()
    camera.rotation = CAMERA_ROTATION
    camera.resolution = CAMERA_RESOLUTION

    if CONNECT_REMOTE_SERVER:
        log.info('Connecting to server enabled')
        socket_handler = ClientSocketHandler(configs)
        socket_handler.send_host_configs(FILTER_CLASSES, CONTINUE_RUN)
    else:
        log.info('Connecting to ScrubDash server is ***DISABLED***\n\n')

    if not HEADLESS:
        state = State(4)
        display = Display(configs, camera, state)

    try:
        for _ in camera.capture_continuous(stream, format='jpeg'):
            if CONNECT_REMOTE_SERVER:
                socket_handler.send_heartbeat_every_15s()
            detector.infer(stream)
            detector.print_report()

            lboxes = detector.labeled_boxes
            if not HEADLESS:
                display.update(lboxes)

            if len(lboxes) > 0:
                if RECORD and lboxes[0]['confidence'] > RECORD_CONF_THRESHOLD:
                    detected_classes = [lbox['class_name'] for lbox in lboxes]
                    if any(itm in FILTER_CLASSES for itm in detected_classes):
                        if CONNECT_REMOTE_SERVER:
                            socket_handler.send_image_and_boxes(stream, lboxes)
                            log.debug('Image sent')
                        detector.save_current_frame(None, lboxes=lboxes)
                        if LORA_ON:
                            to_send = f"Top-1: {lboxes[0]['class_name']}"
                            lora_sender.send(to_send)

                    with open('what_was_seen.log', 'a+', encoding="utf-8") as seen_file:
                        time_format = '%Y-%m-%d %H:%M:%S'
                        tstamp = str(datetime.now().strftime(time_format))
                        top_class = lboxes[0]['class_name']
                        seen_file.write(f'{tstamp} | {top_class}\n')

            stream.seek(0)
            stream.truncate()
    except KeyboardInterrupt:
        log.warning('KeyboardInterrupt')
        if CONNECT_REMOTE_SERVER:
            socket_handler.close()


if __name__ == "__main__":
    main()
