#!/usr/bin/env python3
"""
Standalone Archipelago to OBS Bridge
Works without needing full Archipelago installation
"""

import asyncio
import json
import logging
import os
from typing import Dict, Any, Optional, List
import websockets
from websockets.exceptions import ConnectionClosed
import obsws_python as obs

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class StandaloneArchipelagoOBS:
    """Standalone Archipelago observer that works without CommonClient"""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.obs_client = None
        self.archipelago_ws = None
        self.running = False

        # Store server state
        self.connected_players = {}
        self.player_names = {}
        self.location_names = {}
        self.item_names = {}
        self.game_data = {}

        # Connection info
        self.server = config.get('archipelago_host', 'localhost')
        self.port = config.get('archipelago_port', 38281)
        self.password = config.get('archipelago_password', '')
        self.auth = config.get('bot_name', 'OBS_Observer_Bot')

    async def connect_obs(self):
        """Connect to OBS WebSocket"""
        try:
            self.obs_client = obs.ReqClient(
                host=self.config.get('obs_host', 'localhost'),
                port=self.config.get('obs_port', 4455),
                password=self.config.get('obs_password', '')
            )
            logger.info("Connected to OBS WebSocket")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to OBS: {e}")
            return False

    async def connect_archipelago(self):
        """Connect to Archipelago server"""
        try:
            uri = f"ws://{self.server}:{self.port}"
            self.archipelago_ws = await websockets.connect(uri)
            logger.info(f"Connected to Archipelago server at {uri}")

            # Send connect packet with proper version tuple format
            connect_packet = {
                "cmd": "Connect",
                "password": self.password,
                "game": "Observer",
                "name": self.auth,
                "uuid": self.config.get('uuid', ''),
                "version": [0, 4, 6],  # Use list format instead of dict
                "items_handling": 0,
                "tags": ["Tracker", "Observer"],
                "slot_data": False
            }

            await self.archipelago_ws.send(json.dumps([connect_packet]))
            logger.info("Sent connect packet to Archipelago")
            return True

        except Exception as e:
            logger.error(f"Failed to connect to Archipelago: {e}")
            return False

    async def request_data_package(self):
        """Request data package for name resolution"""
        if not self.archipelago_ws:
            return

        data_package_request = {
            "cmd": "GetDataPackage",
            "games": []
        }
        await self.archipelago_ws.send(json.dumps([data_package_request]))
        logger.info("Requested data package")

    def resolve_player_name(self, player_id: int) -> str:
        """Get player name from ID"""
        return self.player_names.get(player_id, f"Player_{player_id}")

    def resolve_item_name(self, item_id: int) -> str:
        """Get item name from ID"""
        for game_items in self.item_names.values():
            if item_id in game_items:
                return game_items[item_id]
        return f"Item_{item_id}"

    def resolve_location_name(self, location_id: int) -> str:
        """Get location name from ID"""
        for game_locations in self.location_names.values():
            if location_id in game_locations:
                return game_locations[location_id]
        return f"Location_{location_id}"

    async def handle_archipelago_message(self, message_data: list):
        """Process messages from Archipelago server"""
        for packet in message_data:
            cmd = packet.get('cmd')

            try:
                if cmd == 'Connected':
                    await self.handle_connected(packet)
                elif cmd == 'RoomInfo':
                    await self.handle_room_info(packet)
                elif cmd == 'ReceivedItems':
                    await self.handle_received_items(packet)
                elif cmd == 'LocationInfo':
                    await self.handle_location_info(packet)
                elif cmd == 'RoomUpdate':
                    await self.handle_room_update(packet)
                elif cmd == 'PrintJSON':
                    await self.handle_print_json(packet)
                elif cmd == 'DataPackage':
                    await self.handle_data_package(packet)
                elif cmd == 'ConnectionRefused':
                    await self.handle_connection_refused(packet)
                else:
                    logger.debug(f"Unknown command: {cmd}")

            except Exception as e:
                logger.error(f"Error handling {cmd}: {e}")

    async def handle_connected(self, packet):
        """Handle successful connection"""
        slot_data = packet.get('slot_data', {})
        slot_info = packet.get('slot_info', {})

        # Store player information
        for slot_id, player_info in slot_info.items():
            slot_id = int(slot_id)
            self.player_names[slot_id] = player_info.get('name', f'Player_{slot_id}')
            self.connected_players[slot_id] = {
                'name': player_info.get('name'),
                'game': player_info.get('game'),
                'type': player_info.get('type', 0)
            }

        logger.info(f"Observer connected! Monitoring {len(slot_info)} players")

        # Request data package for name resolution
        await self.request_data_package()

        await self.trigger_obs_event("server_connected", {
            "player_count": len(slot_info),
            "players": self.connected_players
        })

    async def handle_room_info(self, packet):
        """Handle room information"""
        await self.trigger_obs_event("room_info", {
            "seed_name": packet.get('seed_name', 'Unknown'),
            "players": len(packet.get('players', [])),
            "permissions": packet.get('permissions', {}),
            "hint_cost": packet.get('hint_cost', 10)
        })

    async def handle_connection_refused(self, packet):
        """Handle connection refusal"""
        errors = packet.get('errors', [])
        logger.error(f"Connection refused: {errors}")

        await self.trigger_obs_event("connection_refused", {
            "errors": errors
        })

    async def handle_received_items(self, packet):
        """Handle item reception events"""
        items = packet.get('items', [])
        index = packet.get('index', 0)

        for i, item in enumerate(items):
            receiving_player = self.resolve_player_name(item.get('player', 0))
            item_name = self.resolve_item_name(item.get('item', 0))
            location_name = self.resolve_location_name(item.get('location', 0))

            await self.trigger_obs_event("item_received", {
                "receiving_player": receiving_player,
                "item_name": item_name,
                "location_name": location_name,
                "item_id": item.get('item'),
                "location_id": item.get('location'),
                "player_id": item.get('player'),
                "flags": item.get('flags', 0)
            })

    async def handle_location_info(self, packet):
        """Handle location check events"""
        locations = packet.get('locations', [])

        for location in locations:
            player_name = self.resolve_player_name(location.get('player', 0))
            item_name = self.resolve_item_name(location.get('item', 0))
            location_name = self.resolve_location_name(location.get('location', 0))

            await self.trigger_obs_event("location_checked", {
                "player_name": player_name,
                "item_name": item_name,
                "location_name": location_name,
                "player_id": location.get('player'),
                "item_id": location.get('item'),
                "location_id": location.get('location')
            })

    async def handle_room_update(self, packet):
        """Handle room updates"""
        await self.trigger_obs_event("room_update", packet)

    async def handle_print_json(self, packet):
        """Handle PrintJSON messages"""
        message_type = packet.get('type', 'Chat')
        data = packet.get('data', [])

        # Simple parsing of PrintJSON data
        parsed_text = self.parse_print_json_data(data)

        event_data = {
            "type": message_type,
            "text": parsed_text,
            "raw_data": data
        }

        # Map message types to events
        event_mapping = {
            'ItemSend': 'global_item_send',
            'ItemCheat': 'global_item_found',
            'Hint': 'global_hint',
            'Join': 'global_player_join',
            'Part': 'global_player_part',
            'Chat': 'global_chat',
            'ServerChat': 'server_chat',
            'Goal': 'goal_completed',
            'Release': 'player_released',
            'Collect': 'player_collected',
            'Countdown': 'countdown'
        }

        event_name = event_mapping.get(message_type, 'unknown_message')
        await self.trigger_obs_event(event_name, event_data)

    def parse_print_json_data(self, data: List) -> str:
        """Parse PrintJSON data to readable text"""
        result = ""

        for part in data:
            if isinstance(part, dict):
                part_type = part.get('type')
                text = part.get('text', '')

                if part_type == 'player_id' and isinstance(text, int):
                    result += self.resolve_player_name(text)
                elif part_type == 'item_id' and isinstance(text, int):
                    result += self.resolve_item_name(text)
                elif part_type == 'location_id' and isinstance(text, int):
                    result += self.resolve_location_name(text)
                else:
                    result += str(text)
            else:
                result += str(part)

        return result

    async def handle_data_package(self, packet):
        """Handle data package for name resolution"""
        data_package = packet.get('data', {})
        games = data_package.get('games', {})

        for game_name, game_data in games.items():
            self.game_data[game_name] = game_data

            # Store item names
            if game_name not in self.item_names:
                self.item_names[game_name] = {}
            if 'item_name_to_id' in game_data:
                for item_name, item_id in game_data['item_name_to_id'].items():
                    self.item_names[game_name][item_id] = item_name

            # Store location names
            if game_name not in self.location_names:
                self.location_names[game_name] = {}
            if 'location_name_to_id' in game_data:
                for location_name, location_id in game_data['location_name_to_id'].items():
                    self.location_names[game_name][location_id] = location_name

        logger.info(f"Updated data package for {len(games)} games")

        await self.trigger_obs_event("data_package_updated", {
            "games": list(games.keys()),
            "game_count": len(games)
        })

    async def trigger_obs_event(self, event_type: str, event_data: Dict[str, Any]):
        """Trigger OBS events based on Archipelago events"""
        if not self.obs_client:
            if self.config.get('log_all_events', True):
                logger.info(f"[NO OBS] {event_type}: {event_data}")
            return

        try:
            obs_actions = self.config.get('obs_actions', {})

            if event_type in obs_actions:
                action_config = obs_actions[event_type]
                action_type = action_config.get('type')

                if action_type == 'scene_switch':
                    scene_name = action_config.get('scene_name')
                    self.obs_client.set_current_program_scene(scene_name)
                    logger.info(f"Switched to scene: {scene_name}")

                elif action_type == 'source_visibility':
                    source_name = action_config.get('source_name')
                    scene_name = action_config.get('scene_name')
                    visible = action_config.get('visible', True)

                    self.obs_client.set_scene_item_enabled(
                        scene_name, source_name, visible
                    )
                    logger.info(f"Set {source_name} visibility to {visible}")

                elif action_type == 'text_update':
                    source_name = action_config.get('source_name')
                    text_template = action_config.get('text_template', '')

                    try:
                        formatted_text = text_template.format(**event_data)
                    except (KeyError, ValueError):
                        formatted_text = f"{event_type}: {event_data.get('text', str(event_data))}"

                    self.obs_client.set_input_settings(
                        source_name, {"text": formatted_text}, True
                    )
                    logger.info(f"Updated text source {source_name}")

                elif action_type == 'filter_toggle':
                    source_name = action_config.get('source_name')
                    filter_name = action_config.get('filter_name')
                    enabled = action_config.get('enabled', True)

                    self.obs_client.set_source_filter_enabled(
                        source_name, filter_name, enabled
                    )
                    logger.info(f"Set filter {filter_name} on {source_name} to {enabled}")

                elif action_type == 'media_restart':
                    source_name = action_config.get('source_name')
                    self.obs_client.trigger_media_input_action(source_name, "restart")
                    logger.info(f"Restarted media source: {source_name}")

            # Log events
            if self.config.get('log_all_events', True):
                logger.info(f"Archipelago event: {event_type}")
                if self.config.get('log_event_data', False):
                    logger.debug(f"Event data: {event_data}")

        except Exception as e:
            logger.error(f"Failed to trigger OBS event {event_type}: {e}")

    async def listen_to_archipelago(self):
        """Main message listening loop"""
        try:
            async for message in self.archipelago_ws:
                try:
                    data = json.loads(message)
                    await self.handle_archipelago_message(data)
                except json.JSONDecodeError as e:
                    logger.error(f"Failed to decode message: {e}")
                except Exception as e:
                    logger.error(f"Error handling message: {e}")

        except ConnectionClosed:
            logger.warning("Archipelago connection closed")
            await self.trigger_obs_event("archipelago_disconnected", {})
        except Exception as e:
            logger.error(f"Error in message loop: {e}")

    async def run(self):
        """Main run loop"""
        logger.info("Starting Standalone Archipelago to OBS Bridge...")

        # Connect to OBS
        await self.connect_obs()

        # Connect to Archipelago
        if not await self.connect_archipelago():
            return False

        self.running = True

        try:
            await self.listen_to_archipelago()
        except KeyboardInterrupt:
            logger.info("Received interrupt, shutting down...")
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
        finally:
            await self.cleanup()

        return True

    async def cleanup(self):
        """Clean up connections"""
        self.running = False

        if self.archipelago_ws:
            await self.archipelago_ws.close()
            logger.info("Closed Archipelago connection")

        if self.obs_client:
            self.obs_client.disconnect()
            logger.info("Closed OBS connection")


def load_config(config_file: str = 'config.json') -> Dict[str, Any]:
    """Load configuration from file"""
    default_config = {
        "archipelago_host": "localhost",
        "archipelago_port": 38281,
        "archipelago_password": "",
        "bot_name": "OBS_Observer_Bot",
        "uuid": "",
        "obs_host": "localhost",
        "obs_port": 4455,
        "obs_password": "",
        "log_all_events": True,
        "log_event_data": False,
        "obs_actions": {
            "global_item_send": {
                "type": "text_update",
                "source_name": "LastItemSent",
                "text_template": "{text}"
            },
            "global_item_found": {
                "type": "text_update",
                "source_name": "LastItemFound",
                "text_template": "{text}"
            },
            "item_received": {
                "type": "text_update",
                "source_name": "LastItemReceived",
                "text_template": "{receiving_player} got {item_name}"
            },
            "location_checked": {
                "type": "text_update",
                "source_name": "LastLocationChecked",
                "text_template": "{player_name} checked {location_name}"
            },
            "global_player_join": {
                "type": "text_update",
                "source_name": "PlayerStatus",
                "text_template": "Player joined: {text}"
            },
            "global_player_part": {
                "type": "text_update",
                "source_name": "PlayerStatus",
                "text_template": "Player left: {text}"
            },
            "goal_completed": {
                "type": "scene_switch",
                "scene_name": "GoalCompleted"
            },
            "player_released": {
                "type": "text_update",
                "source_name": "ReleaseNotice",
                "text_template": "Player Released! {text}"
            },
            "player_collected": {
                "type": "text_update",
                "source_name": "CollectNotice",
                "text_template": "Player Collected! {text}"
            },
            "server_connected": {
                "type": "source_visibility",
                "scene_name": "Main",
                "source_name": "ConnectedIndicator",
                "visible": True
            },
            "archipelago_disconnected": {
                "type": "source_visibility",
                "scene_name": "Main",
                "source_name": "ConnectedIndicator",
                "visible": False
            },
            "room_info": {
                "type": "text_update",
                "source_name": "SeedInfo",
                "text_template": "Seed: {seed_name} | Players: {players}"
            },
            "global_chat": {
                "type": "text_update",
                "source_name": "LastChatMessage",
                "text_template": "{text}"
            }
        }
    }

    if os.path.exists(config_file):
        try:
            with open(config_file, 'r') as f:
                user_config = json.load(f)

                def deep_merge(default, user):
                    for key, value in user.items():
                        if key in default and isinstance(default[key], dict) and isinstance(value, dict):
                            deep_merge(default[key], value)
                        else:
                            default[key] = value

                deep_merge(default_config, user_config)
        except Exception as e:
            logger.warning(f"Failed to load config: {e}")
    else:
        try:
            with open(config_file, 'w') as f:
                json.dump(default_config, f, indent=2)
            logger.info(f"Created default config: {config_file}")
        except Exception as e:
            logger.warning(f"Failed to create config: {e}")

    return default_config


async def main():
    """Main entry point"""
    config = load_config()
    bridge = StandaloneArchipelagoOBS(config)
    await bridge.run()


if __name__ == "__main__":
    # Install required packages:
    # pip install websockets obsws-python

    print("Starting Standalone Archipelago to OBS Bridge...")
    print("This version works without needing full Archipelago installation.")
    print("Only requires: pip install websockets obsws-python")
    print()

    asyncio.run(main())
