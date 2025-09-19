#!/usr/bin/env python3
"""
Archipelago to OBS Bridge - Full Server Observer
Run this from your Archipelago directory to use proper imports
"""

import sys
import os

# Add Archipelago directory to path if running from within Archipelago
archipelago_dir = os.path.dirname(os.path.abspath(__file__))
if archipelago_dir not in sys.path:
    sys.path.append(archipelago_dir)

import asyncio
import json
import logging
from typing import Dict, Any, Optional, List

try:
    import obsws_python as obs

    OBS_AVAILABLE = True
except ImportError:
    print("Warning: obsws-python not installed. Install with: pip install obsws-python")
    OBS_AVAILABLE = False

# Try to import Archipelago modules
try:
    from CommonClient import CommonContext, server_loop, ClientCommandProcessor, logger as ap_logger
    from NetUtils import NetworkItem, ClientStatus, JSONtoTextParser
    from Utils import Version

    ARCHIPELAGO_AVAILABLE = True
except ImportError as e:
    print(f"Error importing Archipelago modules: {e}")
    print("Make sure you're running this script from your Archipelago directory")
    ARCHIPELAGO_AVAILABLE = False

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class ArchipelagoOBSContext(CommonContext):
    """Archipelago client context for OBS bridge"""

    def __init__(self, config: Dict[str, Any]):
        super().__init__()

        self.config = config
        self.obs_client = None

        # Set up Archipelago client properties
        self.game = "Observer"
        self.items_handling = 0b000  # No item handling needed
        self.want_slot_data = True  # We want to see slot data
        self.tags = set(["Tracker", "Observer"])

        # Store additional state for OBS
        self.connected_players = {}
        self.all_locations = {}
        self.all_items = {}

        # Set server connection info
        self.server = config.get('archipelago_host', 'archipelago.gg')
        self.port = config.get('archipelago_port', 59331)
        self.password = config.get('archipelago_password', '')
        self.auth = config.get('bot_name', 'OBS_Observer_Bot')

    async def connect_obs(self):
        """Connect to OBS WebSocket"""
        if not OBS_AVAILABLE:
            logger.error("obsws-python not available, OBS integration disabled")
            return False

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

    def on_package(self, cmd: str, args: dict):
        """Handle incoming packets from Archipelago"""
        asyncio.create_task(self.handle_package(cmd, args))

    async def handle_package(self, cmd: str, args: dict):
        """Process Archipelago packages"""
        try:
            if cmd == "Connected":
                await self.handle_connected(args)
            elif cmd == "RoomInfo":
                await self.handle_room_info(args)
            elif cmd == "ReceivedItems":
                await self.handle_received_items(args)
            elif cmd == "LocationInfo":
                await self.handle_location_info(args)
            elif cmd == "RoomUpdate":
                await self.handle_room_update(args)
            elif cmd == "PrintJSON":
                await self.handle_print_json(args)
            elif cmd == "DataPackage":
                await self.handle_data_package(args)
            else:
                logger.debug(f"Unhandled command: {cmd}")

        except Exception as e:
            logger.error(f"Error handling {cmd}: {e}")

    async def handle_connected(self, args):
        """Handle connection confirmation"""
        slot_data = args.get('slot_data', {})

        # Update player info
        if hasattr(self, 'slot_info'):
            for slot_id, slot_info in self.slot_info.items():
                self.connected_players[slot_id] = {
                    'name': slot_info.name,
                    'game': slot_info.game,
                    'type': slot_info.type
                }

        logger.info(f"Observer connected! Monitoring {len(self.connected_players)} players")

        await self.trigger_obs_event("server_connected", {
            "player_count": len(self.connected_players),
            "players": self.connected_players,
            "slot_data": slot_data
        })

    async def handle_room_info(self, args):
        """Handle room information updates"""
        await self.trigger_obs_event("room_info", {
            "seed_name": args.get('seed_name', ''),
            "permissions": args.get('permissions', {}),
            "hint_cost": args.get('hint_cost', 10),
            "location_check_points": args.get('location_check_points', 1),
            "players": len(args.get('players', [])),
            "version": str(args.get('version', {})),
            "forfeit_mode": args.get('forfeit_mode', 'goal'),
            "remaining_mode": args.get('remaining_mode', 'goal')
        })

    async def handle_received_items(self, args):
        """Handle item reception events"""
        items = args.get('items', [])
        index = args.get('index', 0)

        for i, network_item in enumerate(items):
            # Convert NetworkItem to dict-like access
            if hasattr(network_item, 'item'):
                item_id = network_item.item
                location_id = network_item.location
                player_id = network_item.player
                flags = network_item.flags if hasattr(network_item, 'flags') else 0
            else:
                # Fallback for dict format
                item_id = network_item.get('item', 0)
                location_id = network_item.get('location', 0)
                player_id = network_item.get('player', 0)
                flags = network_item.get('flags', 0)

            receiving_player = self.resolve_player_name(player_id)
            item_name = self.resolve_item_name(item_id)
            location_name = self.resolve_location_name(location_id)

            await self.trigger_obs_event("item_received", {
                "receiving_player": receiving_player,
                "item_name": item_name,
                "location_name": location_name,
                "item_id": item_id,
                "location_id": location_id,
                "player_id": player_id,
                "flags": flags,
                "index": index + i
            })

    async def handle_location_info(self, args):
        """Handle location check events"""
        locations = args.get('locations', [])

        for location in locations:
            player_id = location.get('player', 0)
            item_id = location.get('item', 0)
            location_id = location.get('location', 0)

            player_name = self.resolve_player_name(player_id)
            item_name = self.resolve_item_name(item_id)
            location_name = self.resolve_location_name(location_id)

            await self.trigger_obs_event("location_checked", {
                "player_name": player_name,
                "item_name": item_name,
                "location_name": location_name,
                "player_id": player_id,
                "item_id": item_id,
                "location_id": location_id
            })

    async def handle_room_update(self, args):
        """Handle room state updates"""
        await self.trigger_obs_event("room_update", args)

    async def handle_print_json(self, args):
        """Handle PrintJSON messages (chat, notifications, etc.)"""
        message_type = args.get('type', 'Chat')
        data = args.get('data', [])

        # Parse the message using Archipelago's parser if available
        try:
            if hasattr(self, 'jsontotextparser'):
                parsed_text = self.jsontotextparser(data)
            else:
                # Fallback parsing
                parsed_text = self.simple_parse_json_data(data)
        except Exception as e:
            logger.warning(f"Failed to parse message: {e}")
            parsed_text = str(data)

        event_data = {
            "type": message_type,
            "text": parsed_text,
            "raw_data": data
        }

        # Map different message types to specific events
        event_mapping = {
            'ItemSend': 'global_item_send',
            'ItemCheat': 'global_item_found',
            'Hint': 'global_hint',
            'Join': 'global_player_join',
            'Part': 'global_player_part',
            'Chat': 'global_chat',
            'ServerChat': 'server_chat',
            'Tutorial': 'tutorial',
            'TagsChanged': 'tags_changed',
            'CommandResult': 'command_result',
            'AdminCommandResult': 'admin_command_result',
            'Goal': 'goal_completed',
            'Release': 'player_released',
            'Collect': 'player_collected',
            'Countdown': 'countdown'
        }

        event_name = event_mapping.get(message_type, 'unknown_message')
        await self.trigger_obs_event(event_name, event_data)

    def simple_parse_json_data(self, data: List) -> str:
        """Simple fallback parser for PrintJSON data"""
        result = ""
        for part in data:
            if isinstance(part, dict):
                if part.get('type') == 'player_id':
                    player_id = part.get('text', 0)
                    result += self.resolve_player_name(player_id)
                elif part.get('type') == 'item_id':
                    item_id = part.get('text', 0)
                    result += self.resolve_item_name(item_id)
                elif part.get('type') == 'location_id':
                    location_id = part.get('text', 0)
                    result += self.resolve_location_name(location_id)
                else:
                    result += str(part.get('text', ''))
            else:
                result += str(part)
        return result

    async def handle_data_package(self, args):
        """Handle data packages for name resolution"""
        data_package = args.get('data', {})
        games = data_package.get('games', {})

        logger.info(f"Received data package for {len(games)} games")

        await self.trigger_obs_event("data_package_updated", {
            "games": list(games.keys()),
            "game_count": len(games)
        })

    def resolve_player_name(self, player_id: int) -> str:
        """Get player name from ID"""
        if hasattr(self, 'slot_info') and player_id in self.slot_info:
            return self.slot_info[player_id].name
        return self.connected_players.get(player_id, {}).get('name', f"Player_{player_id}")

    def resolve_item_name(self, item_id: int) -> str:
        """Get item name from ID"""
        # Try to use Archipelago's built-in item lookup
        if hasattr(self, 'item_names'):
            for game_items in self.item_names.values():
                if item_id in game_items:
                    return game_items[item_id]
        return f"Item_{item_id}"

    def resolve_location_name(self, location_id: int) -> str:
        """Get location name from ID"""
        # Try to use Archipelago's built-in location lookup
        if hasattr(self, 'location_names'):
            for game_locations in self.location_names.values():
                if location_id in game_locations:
                    return game_locations[location_id]
        return f"Location_{location_id}"

    async def trigger_obs_event(self, event_type: str, event_data: Dict[str, Any]):
        """Trigger OBS events based on Archipelago events"""
        if not self.obs_client:
            if self.config.get('log_all_events', True):
                logger.info(f"[NO OBS] {event_type}: {event_data}")
            return

        try:
            # Map Archipelago events to OBS actions
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

                    # Format text with event data
                    try:
                        formatted_text = text_template.format(**event_data)
                    except (KeyError, ValueError) as e:
                        # Fallback if template formatting fails
                        formatted_text = f"{event_type}: {event_data.get('text', str(event_data))}"
                        logger.warning(f"Text template formatting failed: {e}")

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

            # Log events for debugging
            if self.config.get('log_all_events', True):
                logger.info(f"Archipelago event: {event_type}")
                if self.config.get('log_event_data', False):
                    logger.debug(f"Event data: {event_data}")

        except Exception as e:
            logger.error(f"Failed to trigger OBS event {event_type}: {e}")

    async def server_auth(self, password_requested: bool = False):
        """Handle server authentication"""
        if password_requested and not self.password:
            await super().server_auth(password_requested)

        await self.get_username()
        await self.send_connect()

    async def connection_closed(self):
        """Handle connection closure"""
        await super().connection_closed()
        await self.trigger_obs_event("archipelago_disconnected", {})
        logger.warning("Lost connection to Archipelago server")


class ArchipelagoOBSBridge:
    """Main bridge controller"""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.context = None

    async def run(self):
        """Run the bridge"""
        if not ARCHIPELAGO_AVAILABLE:
            logger.error("Archipelago modules not available. Make sure you're running from the Archipelago directory.")
            return False

        logger.info("Starting Archipelago to OBS Bridge (Full Server Observer)...")

        # Create context
        self.context = ArchipelagoOBSContext(self.config)

        # Connect to OBS
        await self.context.connect_obs()

        # Start Archipelago client
        self.context.server_task = asyncio.create_task(
            server_loop(self.context), name="server loop"
        )

        try:
            await self.context.server_task
        except KeyboardInterrupt:
            logger.info("Received interrupt, shutting down...")
        finally:
            await self.cleanup()

        return True

