import logging
import requests
import ipaddress
from datetime import timedelta
from enum import Enum
import voluptuous as vol
from homeassistant.components.sensor import (
    SensorDeviceClass,
    RestoreSensor,
    SensorEntity,
    SensorStateClass,
    PLATFORM_SCHEMA
)
from homeassistant.components.binary_sensor import BinarySensorEntity
import homeassistant.helpers.config_validation as cv
from homeassistant.const import CONF_NAME
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.restore_state import RestoreEntity


_LOGGER = logging.getLogger(__name__)

ATTR_TOTAL_VOLTAGE = "Total Voltage"
ATTR_CURRENT_AMPS = "Current Amps"
ATTR_CHARGE_SPEED = "Charge Speed"
ATTR_OVERRIDDEN_SOC = "Battery Level"
ATTR_UPTIME = "Uptime"
#ATTR_REGENERATED_CHARGE = "Regenerated Charge"
#ATTR_CELL_VOLTAGE = "Cell Voltage"
#ATTR_BATTERY_TEMP = "Battery Temp"

CONF_OWIE_IP = 'owie_local_ip'
DEFAULT_NAME = 'Onewheel Battery Owie'
ICON = 'mdi:battery'

SCAN_INTERVAL = timedelta(seconds=10)

def _ip_val(value) -> str:
    """Validate input is ipaddress."""
    try:
        ipaddress.ip_address(value)
    except ValueError:
        raise vol.Invalid("Not a valid IP address.")    
    return value

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Required(CONF_OWIE_IP): _ip_val,
    vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string
})

async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    """Get the Owie sensor."""

    data = OwieData(config.get(CONF_OWIE_IP))

    sensors = [
        OwieBatterySensor(data, config.get(CONF_NAME)),
        OwieChargingSensor(data, config.get(CONF_NAME))
    ]
    async_add_entities(sensors, True)

def sanitize_response(owie_json):
    """Strip text from values before exporting"""
    _san_properties = ['OVERRIDDEN_SOC','TOTAL_VOLTAGE','CURRENT_AMPS']
    for prop in _san_properties:
        owie_json[prop] = owie_json[prop].strip('%').strip('v').strip(' Amps')
    return owie_json

def charge_speed(amps):
    if amps >= 0:
        return 'Not Charging'
    elif amps > -1:
        return 'Balance Charging'
    elif amps > -2:
        return 'Pint Charger'
    elif amps > -4:
        return 'XR / Pint Ultracharger'
    elif amps > -6:
        return 'XR Hypercharger'
    else:
        return 'Unknown Charger'

class OwieBatterySensor(Entity):
    """Implementation of the battery sensor."""
    _attr_has_entity_name = True
    _attr_device_class = SensorDeviceClass.BATTERY

    def __init__(self, data, name):
        """Initialize the sensor."""
        self.data = data
        self._name = name
        self.async_update()

    @property
    def name(self):
        return self._name

    @property
    def state(self):
        """Return the state of the sensor."""
        return int(self.data.info['OVERRIDDEN_SOC'])

    # @property
    # def extra_state_attributes(self):
    #     """Return the state attributes."""
    #     attrs = {
    #         ATTR_OVERRIDDEN_SOC: self.state,
    #         #ATTR_CHARGE_SPEED: charge_speed(float(self.data.info['CURRENT_AMPS'])),
    #         #ATTR_TOTAL_VOLTAGE: float(self.data.info['TOTAL_VOLTAGE']),
    #         #ATTR_UPTIME: str(self.data.info['UPTIME'])
    #     }
    #     return attrs

    @property
    def state_class(self):
        """Return the type of state for HA long term statistics."""
        return "measurement"

    @property
    def icon(self):  #TODO implement icon according to charge level
        """Icon to use in the frontend, if any."""
        return ICON

    async def async_update(self):
        """Get the latest data from owie and update the states."""
        await self.hass.async_add_executor_job(self.data.update)


class OwieChargingSensor(BinarySensorEntity):
    """Implementation of the charging state sensor."""
    _attr_has_entity_name = True

    def __init__(self, data, name):
        """Initialize the sensor."""
        self.data = data
        self._name = name
        self.current_current = 1
        self.async_update()

    @property
    def name(self):
        return f"{self._name}.ChargingStatus"

    @property
    def device_class(self):
        return "BinarySensorDeviceClass.BATTERY_CHARGING"

    @property
    def is_on(self):
        """Return the state of the sensor."""
        self.current_current = float(self.data.info['CURRENT_AMPS'])
        if self.current_current >= 0:
            return False
        else:
            return True

    @property
    def extra_state_attributes(self):
        """Return the state attributes."""
        return {ATTR_CHARGE_SPEED: charge_speed(self.current_current)}

    async def async_update(self):
        """Get the latest data from owie and update the states."""
        await self.hass.async_add_executor_job(self.data.update)


class OwieData(object):
    """The coordinator for handling the data retrieval."""
    def __init__(self, owie_ip):
        """Initialize the info object."""
        self._owie_address = f"http://{owie_ip}/autoupdate"
        self.info = {}
        self.info.setdefault('OVERRIDDEN_SOC', '0') #TODO this is where to request past data from hass
        self.info.setdefault('TOTAL_VOLTAGE', '0')
        self.info.setdefault('CURRENT_AMPS', '0')
        self.info.setdefault('UPTIME', 'Offline')

    def update(self):
        #response = await self.hass.async_add_executor_job(requests.get(self._owie_address, headers=None, timeout=.1))
        try:
            response = requests.get(self._owie_address, headers=None, timeout=.1)
            if response.status_code == requests.codes.bad:
                # If owie online but sending errors
                _LOGGER.error("updating owie status got {}:{}".format(
                    response.status_code, response.content))
            else:
                self.info = sanitize_response(response.json())
                # _LOGGER.debug("Owie Data got {}".format(self.info))
        except OSError:
            #If owie offline
            _LOGGER.info("Unable to connect to Owie device.")
