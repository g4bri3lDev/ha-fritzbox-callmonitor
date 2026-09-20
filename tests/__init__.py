"""Tests for the fritzbox_callmonitor custom integration."""

from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, CONF_USERNAME

from custom_components.fritzbox_callmonitor.const import CONF_PHONEBOOK, SERIAL_NUMBER

MOCK_HOST = "fake_host"
MOCK_PORT = 1234
MOCK_USERNAME = "fake_username"
MOCK_PASSWORD = "fake_password"
MOCK_PHONEBOOK_NAME = "fake_phonebook_name"
MOCK_PHONEBOOK_ID = 0
MOCK_SERIAL_NUMBER = "fake_serial_number"

MOCK_CONFIG_ENTRY = {
    CONF_HOST: MOCK_HOST,
    CONF_PORT: MOCK_PORT,
    CONF_PASSWORD: MOCK_PASSWORD,
    CONF_USERNAME: MOCK_USERNAME,
    CONF_PHONEBOOK: MOCK_PHONEBOOK_ID,
    SERIAL_NUMBER: MOCK_SERIAL_NUMBER,
}

MOCK_DEVICE_INFO = {
    "Name": "FRITZ!Box 7590",
    "HW": "226",
    "Version": "100.01.01",
    "Revision": "10000",
    "Serial": MOCK_SERIAL_NUMBER,
    "OEM": "avm",
    "Lang": "de",
    "Annex": "B",
    "Lab": None,
    "Country": "049",
    "Flag": None,
    "UpdateAvailable": False,
    "UpdateSuccessful": "unknown",
    "BoxUserID": 0,
}

# Entity ids are derived from the device name and the translated entity name.
ENTITY_CALL_MONITOR = "sensor.fritz_box_7590_call_monitor_fake_phonebook_name"
ENTITY_CALL_HISTORY = "sensor.fritz_box_7590_call_history_fake_phonebook_name"
