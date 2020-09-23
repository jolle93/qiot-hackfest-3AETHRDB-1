from flask import Flask

import time
import atexit
import ads1015
import RPi.GPIO as GPIO
import logging
from pms5003 import PMS5003, ReadTimeoutError
from flask_json import FlaskJSON, JsonError, json_response, as_json

MICS6814_HEATER_PIN = 24
MICS6814_GAIN = 6.144

ads1015.I2C_ADDRESS_DEFAULT = ads1015.I2C_ADDRESS_ALTERNATE
_is_setup = False
_adc_enabled = False
_adc_gain = 6.148


LOGGER = logging.getLogger()

class Mics6814Reading(object):
    __slots__ = 'oxidising', 'reducing', 'nh3', 'adc'

    def __init__(self, ox, red, nh3, adc=None):
        self.oxidising = ox
        self.reducing = red
        self.nh3 = nh3
        self.adc = adc

    def __repr__(self):
        fmt = """Oxidising: {ox:05.02f} Ohms
Reducing: {red:05.02f} Ohms
NH3: {nh3:05.02f} Ohms"""
        if self.adc is not None:
            fmt += """
ADC: {adc:05.02f} Volts
"""
        return fmt.format(
            ox=self.oxidising,
            red=self.reducing,
            nh3=self.nh3,
            adc=self.adc)

    __str__ = __repr__
    
class GasRaw(dict):
    def __init__(self, data):
        LOGGER.info("GasRaw.__init__()")
        dict.__init__(self, adc = data.adc, nh3 = data.nh3, oxidising = data.oxidising, reducing = data.reducing)

class PollutionRaw(dict):
    def __init__(self, data):
        LOGGER.info("PollutionRaw.__init__()")
        dict.__init__(self, pm1_0 = data[0], pm2_5 = data[1], pm10 = data[2], pm1_0_atm = data[3], pm2_5_atm = data[4], pm10_atm = data[5], gt0_3 = data[6], gt0_5 = data[7], gt1_0 = data[8], gt2_5 = data[9], gt5_0 = data[10], gt10um = data[11])
    def __json__(self):
        return 'Object{pm1_0:"' + str(self.pm1_0) +'"'


def setup():
    global adc, _is_setup
    if _is_setup:
        return
    _is_setup = True

    adc = ads1015.ADS1015(i2c_addr=0x49)
    adc.set_mode('single')
    adc.set_programmable_gain(MICS6814_GAIN)
    adc.set_sample_rate(1600)

    GPIO.setwarnings(False)
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(MICS6814_HEATER_PIN, GPIO.OUT)
    GPIO.output(MICS6814_HEATER_PIN, 1)
    atexit.register(cleanup)


def enable_adc(value=True):
    """Enable reading from the additional ADC pin."""
    global _adc_enabled
    _adc_enabled = value


def set_adc_gain(value):
    """Set gain value for the additional ADC pin."""
    global _adc_gain
    _adc_gain = value


def cleanup():
    GPIO.output(MICS6814_HEATER_PIN, 0)


def read_all():
    """Return gas resistence for oxidising, reducing and NH3"""
    setup()
    ox = adc.get_voltage('in0/gnd')
    red = adc.get_voltage('in1/gnd')
    nh3 = adc.get_voltage('in2/gnd')

    try:
        ox = (ox * 56000) / (3.3 - ox)
    except ZeroDivisionError:
        ox = 0

    try:
        red = (red * 56000) / (3.3 - red)
    except ZeroDivisionError:
        red = 0

    try:
        nh3 = (nh3 * 56000) / (3.3 - nh3)
    except ZeroDivisionError:
        nh3 = 0

    analog = None

    if _adc_enabled:
        if _adc_gain == MICS6814_GAIN:
            analog = adc.get_voltage('ref/gnd')
        else:
            adc.set_programmable_gain(_adc_gain)
            time.sleep(0.05)
            analog = adc.get_voltage('ref/gnd')
            adc.set_programmable_gain(MICS6814_GAIN)

    return Mics6814Reading(ox, red, nh3, analog)


def read_oxidising():
    """Return gas resistance for oxidising gases.
    Eg chlorine, nitrous oxide
    """
    setup()
    return read_all().oxidising


def read_reducing():
    """Return gas resistance for reducing gases.
    Eg hydrogen, carbon monoxide
    """
    setup()
    return read_all().reducing


def read_nh3():
    """Return gas resistance for nh3/ammonia"""
    setup()
    return read_all().nh3


def read_adc():
    """Return spare ADC channel value"""
    setup()
    return read_all().adc

def get_serial_number():
    with open('/sys/firmware/devicetree/base/serial-number', 'r') as f:
        first_line = f.readline()
        return first_line.strip()

app = Flask(__name__)
FlaskJSON(app)

@app.route('/')
def hello_world():
    return 'Hello, World!'

@app.route('/gas')
@as_json
def gas():
    LOGGER.info("Rest getGas()")
    try:
        readings = read_all()
        gas = GasRaw(readings)
        gas['stationId'] = get_serial_number()
        return gas
    except Exception as e:
        print(e)
        
@app.route('/pollution')
@as_json
def pollution():
    LOGGER.info("Rest getPollution")
    try:
        pms5003 = PMS5003()
        data = pms5003.read().data
        pollution = PollutionRaw(data)
        pollution['stationId'] = get_serial_number()
        return pollution
    except Exception as e:
        print(e)

