"""Support for Loxone Audio zone media player."""

from __future__ import annotations

import datetime
import logging

from homeassistant.components.media_player import (MediaPlayerDeviceClass,
                                                   MediaPlayerEntity,
                                                   MediaPlayerEntityFeature,
                                                   MediaPlayerState)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
import homeassistant.util.dt as dt

from . import LoxoneEntity
from .const import AUDIO_EVENT, DEFAULT_AUDIO_ZONE_V2_PLAY_STATE, EVENT, SENDDOMAIN
from .helpers import (add_room_and_cat_to_value_values, get_all,
                      get_or_create_device)
from .miniserver import get_miniserver_from_hass

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0
DEFAULT_FORCE_UPDATE = False

# This is the "optimistic" view of supported features and will be returned until the
# actual set of supported feature have been determined (will always be all or a subset
# of these).
SUPPORT_LOXONE_AUDIO_ZONE = (
    MediaPlayerEntityFeature.PAUSE
    | MediaPlayerEntityFeature.PLAY
    | MediaPlayerEntityFeature.NEXT_TRACK
    | MediaPlayerEntityFeature.PREVIOUS_TRACK
    | MediaPlayerEntityFeature.VOLUME_SET
    | MediaPlayerEntityFeature.VOLUME_STEP
)


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up Loxone Audio zones."""
    return True


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Load Loxone Audio zones based on a config entry."""
    miniserver = get_miniserver_from_hass(hass)
    loxconfig = miniserver.lox_config.json
    entities = []

    for audioZone in get_all(loxconfig, "AudioZoneV2"):
        audioZone = add_room_and_cat_to_value_values(loxconfig, audioZone)
        audioZone.update(
            {
                "hass": hass,
            }
        )
        entities.append(LoxoneAudioZoneV2(**audioZone))

    async_add_entities(entities)


def play_state_to_media_player_state(play_state: int) -> MediaPlayerState:
    match play_state:
        case 0:
            return MediaPlayerState.IDLE
        case 1:
            return MediaPlayerState.PAUSED
        case 2:
            return MediaPlayerState.PLAYING
        case -1:
            return MediaPlayerState.OFF
        case _:
            _LOGGER.warning(f"Unknown playState:{play_state}")


class LoxoneAudioZoneV2(LoxoneEntity, MediaPlayerEntity):
    """Representation of a AudioZoneV2 Loxone device."""

    def __init__(self, **kwargs):
        _LOGGER.debug(f"Input AudioZoneV2: {kwargs}")
        super().__init__(**kwargs)
        self.hass = kwargs["hass"]

        self._attr_device_class = MediaPlayerDeviceClass.SPEAKER
        self._artist = None
        self._album = None
        self._duration = None
        self._coverurl = None
        self._parent_name = None
        self._time = None
        self._time_updated_at = None
        self._title = None
        self._station = None
        self._sourceName = None
        self._sourceList = None
        self._state = play_state_to_media_player_state(DEFAULT_AUDIO_ZONE_V2_PLAY_STATE)
        self._volume = 0

        self.type = "AudioZoneV2"
        self._attr_device_info = get_or_create_device(
            self.unique_id, self.name, self.type, self.room
        )
        self.player_id = "details" in kwargs and kwargs["details"] and kwargs["details"]["playerid"]

    async def event_handler(self, event):
        should_update = False

        if self.states["volume"] in event.data:
            self._volume = float(event.data[self.states["volume"]]) / 100
            should_update = True

        if self.states["playState"] in event.data:
            self._state = play_state_to_media_player_state(
                event.data[self.states["playState"]]
            )
            should_update = True

        if should_update:
            self.async_schedule_update_ha_state()
    
    async def audio_event_handler(self, ha_event):
        should_update = False

        if 'audio_event' in ha_event.data:
            for event in ha_event.data['audio_event']:
                if event['playerid'] == self.player_id:
                    if event["artist"] != self._artist:
                        self._artist = event["artist"]
                        should_update = True

                    if event["title"] != self._title:
                        self._title = event["title"]
                        should_update = True

                    if event["album"] != self._album:
                        self._album = event["album"]
                        should_update = True
                    
                    duration = int(event["duration"])
                    if duration != self._duration:
                        self._duration = duration
                        should_update = True
                    
                    if event["coverurl"] != self._coverurl:
                        self._coverurl = event["coverurl"]
                        should_update = True
                    
                    parent_name = "parent" in event and event["parent"] and event["parent"]["name"] or None
                    if parent_name != self._parent_name:
                        self._parent_name = parent_name
                        should_update = True

                    new_time = int(event["time"])
                    if new_time != self._time:
                        self._time = new_time
                        self._time_updated_at = dt.utcnow()
                        should_update = True
                    
                    if event["station"] != self._station:
                        self._station = event["station"]
                        should_update = True

                    source_name = event["station"] != "" and "Radio" or ("sourceName" in event and event["sourceName"] or None)
                    if source_name != self._sourceName:
                        self._sourceName = source_name
                        should_update = True

                    # TODO: Add sourceList
                    # self._sourceList = None

                    # The state & volume are updated directly from the Loxone Miniserver
                    # if event['mode'] == 'play':
                    #     self._state = MediaPlayerState.PLAYING
                    # elif event['mode'] == 'stop':
                    #     self._state = MediaPlayerState.IDLE
                    # self._volume = float(event["volume"]) / 100
                    
                    # if should_update:
                    #     _LOGGER.info(f"Audio event: {event}")
                    # else:
                    #     _LOGGER.info(f"Received audio event in playerid: {self.player_id} but no changes were made")

                    break

        if should_update:
            self.async_schedule_update_ha_state()

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        """Subscribe to audio events."""
        self.hass.bus.async_listen(AUDIO_EVENT, self.audio_event_handler)

    # properties
    @property
    def media_album_artist(self) -> str | None:
        """Album artist of current playing media, music track only."""
        return self._artist

    @property
    def media_album_name(self) -> str | None:
        """Album name of current playing media, music track only."""
        return self._album

    @property
    def media_artist(self) -> str | None:
        """Artist of current playing media, music track only."""
        return self._artist

    @property
    def media_duration(self) -> int | None:
        """Duration of current playing media in seconds."""
        return self._duration

    @property
    def media_image_remotely_accessible(self) -> bool:
        """True if property media_image_url is accessible outside of the home network."""
        return True

    @property
    def media_image_url(self) -> str | None:
        """Image URL of current playing media."""
        return self._coverurl

    @property
    def media_playlist(self) -> str | None:
        """Title of Playlist currently playing."""
        return self._parent_name

    @property
    def media_position(self) -> int | None:
        """Position of current playing media in seconds."""
        return self._time

    @property
    def media_position_updated_at(self) -> datetime | None:
        """Timestamp of when _attr_media_position was last updated. The timestamp should be set by calling homeassistant.util.dt.utcnow()."""
        return self._time_updated_at

    @property
    def media_title(self) -> str | None:
        """Title of current playing media."""
        return self._title or self._station

    @property
    def source(self) -> str | None:
        """The currently selected input source for the media player."""
        return self._sourceName

    @property
    def source_list(self) -> list[str] | None:
        """The list of possible input sources for the media player. (This list should contain human readable names, suitable for frontend display)."""
        return self._sourceList

    @property
    def state(self) -> MediaPlayerState:
        """Return the playback state."""
        return self._state

    @property
    def volume_level(self) -> float | None:
        """Volume level of the media player (0..1)."""
        return self._volume

    @property
    def supported_features(self) -> MediaPlayerEntityFeature:
        """Flag media player features that are supported."""
        return SUPPORT_LOXONE_AUDIO_ZONE

    # commands
    async def async_media_play(self) -> None:
        """Send play command to device."""
        self.hass.bus.async_fire(SENDDOMAIN, dict(uuid=self.uuidAction, value="play"))
        self.async_schedule_update_ha_state()

    async def async_media_pause(self) -> None:
        """Send pause command to device."""
        self.hass.bus.async_fire(SENDDOMAIN, dict(uuid=self.uuidAction, value="pause"))
        self.async_schedule_update_ha_state()

    async def async_media_stop(self) -> None:
        """Send stop command to device."""
        self.hass.bus.async_fire(SENDDOMAIN, dict(uuid=self.uuidAction, value="pause"))
        self.async_schedule_update_ha_state()

    async def async_media_next_track(self) -> None:
        """Send next track command to device."""
        self.hass.bus.async_fire(SENDDOMAIN, dict(uuid=self.uuidAction, value="next"))
        self.async_schedule_update_ha_state()

    async def async_media_previous_track(self) -> None:
        """Send previous track command to device."""
        self.hass.bus.async_fire(SENDDOMAIN, dict(uuid=self.uuidAction, value="prev"))
        self.async_schedule_update_ha_state()

    async def async_set_volume_level(self, volume: float) -> None:
        """Send new volume_level to device."""
        volume_int = int(volume * 100)
        self.hass.bus.async_fire(
            SENDDOMAIN, dict(uuid=self.uuidAction, value=f"volume/{volume_int}")
        )
        self.async_schedule_update_ha_state()

    async def async_volume_up(self) -> None:
        """Send volume UP to device."""
        self.hass.bus.async_fire(SENDDOMAIN, dict(uuid=self.uuidAction, value="volUp"))
        self.async_schedule_update_ha_state()

    async def async_volume_down(self) -> None:
        """Send volume DOWN to device."""
        self.hass.bus.async_fire(
            SENDDOMAIN, dict(uuid=self.uuidAction, value="volDown")
        )
        self.async_schedule_update_ha_state()
