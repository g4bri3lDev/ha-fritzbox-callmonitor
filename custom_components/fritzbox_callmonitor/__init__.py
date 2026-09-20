"""The fritzbox_callmonitor integration.

A custom integration that overrides the core `fritzbox_callmonitor` domain. It
keeps the core call-state sensor exactly as it is and adds a call history
sensor plus optional reverse lookup of unknown numbers. See AGENTS.md for what
is vendored from core and how to pull core changes forward.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging

from fritzconnection import FritzConnection
from fritzconnection.core.exceptions import FritzConnectionException, FritzSecurityError
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
import phonenumbers
from requests.exceptions import ConnectionError as RequestsConnectionError

from .base import FritzBoxPhonebook
from .const import (
    CONF_HISTORY_DAYS,
    CONF_HISTORY_LIMIT,
    CONF_LOOKUP_PROVIDER,
    CONF_PHONEBOOK,
    CONF_PREFIXES,
    CONF_TELLOWS_API_KEY,
    DEFAULT_HISTORY_DAYS,
    DEFAULT_HISTORY_LIMIT,
    DEFAULT_LOOKUP_PROVIDER,
    DEFAULT_REGION,
    FRITZ_ATTR_COUNTRY,
    PLATFORMS,
    LookupProvider,
)
from .coordinator import FritzBoxCallHistoryCoordinator
from .lookup import NumberLookup
from .services import async_setup_services

_LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class FritzBoxCallMonitorData:
    """Everything a config entry needs at runtime."""

    connection: FritzConnection
    phonebook: FritzBoxPhonebook
    coordinator: FritzBoxCallHistoryCoordinator
    lookup: NumberLookup


type FritzBoxCallMonitorConfigEntry = ConfigEntry[FritzBoxCallMonitorData]


async def async_setup_entry(
    hass: HomeAssistant, config_entry: FritzBoxCallMonitorConfigEntry
) -> bool:
    """Set up the fritzbox_callmonitor platforms."""
    options = config_entry.options

    def _region(connection: FritzConnection) -> str:
        """Ask the box which country it is in, for number formatting.

        AVM reports it as a dialling code ("049"). Anything unexpected falls
        back to the default rather than failing setup over cosmetics.
        """
        try:
            country = connection.updatecheck[FRITZ_ATTR_COUNTRY]
            region = phonenumbers.region_code_for_country_code(int(country))
        except KeyError, TypeError, ValueError, FritzConnectionException:
            return DEFAULT_REGION
        # region_code_for_country_code returns "ZZ" when it knows of none.
        return region if region and region != "ZZ" else DEFAULT_REGION

    def _connect() -> tuple[FritzConnection, FritzBoxPhonebook, str]:
        # One TR-064 session, shared by the phonebook and the call list.
        connection = FritzConnection(
            address=config_entry.data[CONF_HOST],
            user=config_entry.data[CONF_USERNAME],
            password=config_entry.data[CONF_PASSWORD],
        )
        phonebook = FritzBoxPhonebook(
            connection,
            phonebook_id=config_entry.data[CONF_PHONEBOOK],
            prefixes=options.get(CONF_PREFIXES),
        )
        phonebook.init_phonebook()
        return connection, phonebook, _region(connection)

    try:
        connection, fritzbox_phonebook, region = await hass.async_add_executor_job(
            _connect
        )
    except FritzSecurityError as ex:
        _LOGGER.error(
            (
                "User has insufficient permissions to access FRITZ!Box settings and"
                " its phonebooks: %s"
            ),
            ex,
        )
        return False
    except FritzConnectionException as ex:
        raise ConfigEntryAuthFailed from ex
    except RequestsConnectionError as ex:
        _LOGGER.error("Unable to connect to FRITZ!Box call monitor: %s", ex)
        raise ConfigEntryNotReady from ex

    lookup = NumberLookup(
        hass,
        provider=LookupProvider(
            options.get(CONF_LOOKUP_PROVIDER, DEFAULT_LOOKUP_PROVIDER)
        ),
        tellows_api_key=options.get(CONF_TELLOWS_API_KEY, ""),
    )

    coordinator = FritzBoxCallHistoryCoordinator(
        hass,
        config_entry,
        connection=connection,
        phonebook=fritzbox_phonebook,
        lookup=lookup,
        region=region,
        history_days=options.get(CONF_HISTORY_DAYS, DEFAULT_HISTORY_DAYS),
        history_limit=options.get(CONF_HISTORY_LIMIT, DEFAULT_HISTORY_LIMIT),
    )
    # Deliberately not `async_config_entry_first_refresh`: reading the call
    # list needs the OnTel permission, which the phonebook does not, and core's
    # call-state sensor worked without it. A box that refuses the call list
    # should leave the history entity unavailable, not fail the whole entry.
    await coordinator.async_refresh()

    config_entry.runtime_data = FritzBoxCallMonitorData(
        connection=connection,
        phonebook=fritzbox_phonebook,
        coordinator=coordinator,
        lookup=lookup,
    )

    async_setup_services(hass)
    await hass.config_entries.async_forward_entry_setups(config_entry, PLATFORMS)

    return True


async def async_unload_entry(
    hass: HomeAssistant, config_entry: FritzBoxCallMonitorConfigEntry
) -> bool:
    """Unloading the fritzbox_callmonitor platforms."""
    return await hass.config_entries.async_unload_platforms(config_entry, PLATFORMS)
