#!/usr/bin/env python3
"""
Archipelago to OBS Bridge using subprocess approach
Spawns the official Archipelago text client and parses its output
"""

import asyncio
import json
import logging
import os
import re
import subprocess
import sys
from typing import Dict, Any
from datetime import datetime

try:
    import obsws_python as obs
    OBS_AVAILABLE = True
except ImportError:
    print("Warning: obsws-python not available. Install with: pip install obsws-python")
    OBS_AVAILABLE = False

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class ArchipelagoSubprocessBridge:
    """Bridge that uses official Archipelago client as subprocess"""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.obs_client = None
        self.archipelago_process = None
        self.running = False
        self.archipelago_dir = self.find_archipelago_directory()

    def find_archipelago_directory(self):
        possible_paths = [
            ".",
            os.path.expanduser("~/Archipelago"),
            os.path.expanduser("~/AppData/Local/Archipelago"),
            "C:/Archipelago",
            "C:/Program Files/Archipelago",
            "C:/Program Files (x86)/Archipelago",
            os.path.dirname(os.path.abspath(__file__))
        ]
        for path in possible_paths:
            if os.path.exists(os.path.join(path, "CommonClient.py")):
                logger.info(f"Found Archipelago installation at: {path}")
                return os.path.abspath(path)
        logger.error("Could not find Archipelago installation")
        return None

    async def connect_obs(self):
        if not OBS_AVAILABLE:
            logger.warning("OBS integration disabled - obsws-python not available")
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

    def start_archipelago_client(self):
        if not self.archipelago_dir:
            raise Exception("Archipelago directory not found")

        approaches = [
            {
                "cmd": [
                    sys.executable,
                    os.path.join(self.archipelago_dir, "CommonClient.py"),
                    "--connect",
                    f"{self.config.get('archipelago_host', 'localhost')}:{self.config.get('archipelago_port', 38281)}",
                    "--name", self.config.get('bot_name', 'OBS_Observer_Bot')
                ],
                "name": "Direct CommonClient with --connect"
            },
            {
                "cmd": [
                    sys.executable,
                    os.path.join(self.archipelago_dir, "TextClient.py"),
                    f"{self.config.get('archipelago_host', 'localhost')}:{self.config.get('archipelago_port', 38281)}"
                ],
                "name": "TextClient.py"
            },
            {
                "cmd": [
                    sys.executable,
                    os.path.join(self.archipelago_dir, "CommonClient.py")
                ],
                "name": "CommonClient for manual connection",
                "manual_connect": True
            }
        ]

        for i, approach in enumerate(approaches):
            logger.info(f"Trying approach {i + 1}: {approach['name']}")
            cmd = approach["cmd"].copy()
            if self.config.get('archipelago_password') and not approach.get('manual_connect'):
                cmd.extend(["--password", self.config['archipelago_password']])

            try:
                self.archipelago_process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    stdin=subprocess.PIPE,
                    universal_newlines=True,
                    bufsize=1,
                    cwd=self.archipelago_dir
                )
                if approach.get('manual_connect'):
                    connection_commands = [
                        f"/connect {self.config.get('archipelago_host', 'localhost')}:{self.config.get('archipelago_port', 38281)}",
                        f"/name {self.config.get('bot_name', 'OBS_Observer_Bot')}"
                    ]
                    if self.config.get('archipelago_password'):
                        connection_commands.append(f"/password {self.config['archipelago_password']}")
                    for cmd in connection_commands:
                        self.archipelago_process.stdin.write(cmd + '\n')
                        self.archipelago_process.stdin.flush()
                import time; time.sleep(2)
                if self.archipelago_process.poll() is None:
                    logger.info(f"Approach {i + 1} successful - process running")
                    return self.archipelago_process
                else:
                    logger.warning(f"Approach {i + 1} failed - exited with {self.archipelago_process.returncode}")
                    continue
            except Exception as e:
                logger.warning(f"Approach {i + 1} failed: {e}")
                continue
        raise Exception("All client startup approaches failed")

    async def process_archipelago_output(self):
        if not self.archipelago_process:
            return
        logger.info("Starting to monitor Archipelago client output...")
        patterns = {
            'item_received': re.compile(r'(.+?) received (.+?) from (.+?)'),
            'item_sent': re.compile(r'(.+?) sent (.+?) to (.+?)'),
            'location_checked': re.compile(r'(.+?) checked (.+?)'),
            'player_joined': re.compile(r'(.+?) has joined'),
            'player_left': re.compile(r'(.+?) has left'),
            'goal_completed': re.compile(r'(.+?) completed their goal'),
            'hint': re.compile(r'Hint: (.+?)'),
            'chat': re.compile(r'\[(.+?)\] (.+?): (.+)'),
            'server_message': re.compile(r'Notice.*?: (.+)'),
            'release': re.compile(r'(.+?) has released'),
            'collect': re.compile(r'(.+?) has collected'),
            'connected': re.compile(r'Successfully connected to (.+?)'),
            'connection_failed': re.compile(r'Failed to connect|Connection.*failed|Unable to connect'),
        }
        try:
            while self.running and self.archipelago_process.poll() is None:
                line = await asyncio.get_event_loop().run_in_executor(
                    None, self.archipelago_process.stdout.readline
                )
                if not line:
                    continue
                line = line.strip()
                if not line:
                    continue
                await self.parse_and_trigger_events(line, patterns)
        except Exception as e:
            logger.error(f"Error processing Archipelago output: {e}")
        finally:
            logger.info("Stopped monitoring Archipelago output")

    async def parse_and_trigger_events(self, line: str, patterns: Dict[str, re.Pattern]):
        for event_type, pattern in patterns.items():
            match = pattern.search(line)
            if match:
                await self.handle_parsed_event(event_type, match.groups(), line)
                return
        if any(keyword in line.lower() for keyword in ['item', 'location', 'player', 'goal', 'hint', 'chat']):
            await self.trigger_obs_event("raw_message", {"text": line, "timestamp": datetime.now().isoformat()})

    async def handle_parsed_event(self, event_type: str, groups: tuple, raw_line: str):
        event_data = {"raw_line": raw_line, "timestamp": datetime.now().isoformat()}
        if event_type == 'item_received':
            event_data.update({"receiving_player": groups[0], "item_name": groups[1], "sending_player": groups[2], "text": f"{groups[0]} received {groups[1]} from {groups[2]}"})
        elif event_type == 'item_sent':
            event_data.update({"sending_player": groups[0], "item_name": groups[1], "receiving_player": groups[2], "text": f"{groups[0]} sent {groups[1]} to {groups[2]}"})
        elif event_type == 'location_checked':
            event_data.update({"player_name": groups[0], "location_name": groups[1], "text": f"{groups[0]} checked {groups[1]}"})
        elif event_type == 'player_joined':
            event_data.update({"player_name": groups[0], "text": f"{groups[0]} joined the game"})
        elif event_type == 'player_left':
            event_data.update({"player_name": groups[0], "text": f"{groups[0]} left the game"})
        elif event_type == 'goal_completed':
            event_data.update({"player_name": groups[0], "text": f"{groups[0]} completed their goal!"})
        elif event_type == 'hint':
            event_data.update({"hint_text": groups[0], "text": f"Hint: {groups[0]}"})
        elif event_type == 'chat':
            event_data.update({"timestamp_str": groups[0], "player_name": groups[1], "message": groups[2], "text": f"{groups[1]}: {groups[2]}"})
        elif event_type == 'server_message':
            event_data.update({"message": groups[0], "text": groups[0]})
        else:
            event_data["text"] = raw_line
        await self.trigger_obs_event(event_type, event_data)

    async def trigger_obs_event(self, event_type: str, event_data: Dict[str, Any]):
        if not self.obs_client:
            logger.info(f"[NO OBS] {event_type}: {event_data.get('text', str(event_data))}")
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
                    try:
                        response = self.obs_client.get_scene_item_id(scene_name=scene_name, source_name=source_name)
                        item_id = getattr(response, "sceneItemId", None)
                        if item_id is None:
                            logger.warning(f"Source '{source_name}' not found in scene '{scene_name}'. Check config.json.")
                            return
                        self.obs_client.set_scene_item_enabled(scene_name=scene_name, scene_item_id=item_id, scene_item_enabled=visible)
                        logger.info(f"Set {source_name} visibility in {scene_name} to {visible}")
                    except Exception as e:
                        logger.error(f"Failed to toggle visibility for {source_name} in {scene_name}: {e}")

                elif action_type == 'text_update':
                    source_name = action_config.get('source_name')
                    text_template = action_config.get('text_template', '')
                    try:
                        sources = self.obs_client.get_input_list().inputs
                        if not any(src['inputName'] == source_name for src in sources):
                            logger.warning(f"Text source '{source_name}' not found. Check config.json.")
                            return
                        try:
                            formatted_text = text_template.format(**event_data)
                        except (KeyError, ValueError):
                            formatted_text = event_data.get('text', str(event_data))
                        self.obs_client.set_input_settings(source_name, {"text": formatted_text}, True)
                        logger.info(f"Updated text source {source_name}: {formatted_text}")
                    except Exception as e:
                        logger.error(f"Failed to update text source {source_name}: {e}")

                elif action_type == 'filter_toggle':
                    source_name = action_config.get('source_name')
                    filter_name = action_config.get('filter_name')
                    enabled = action_config.get('enabled', True)
                    try:
                        sources = self.obs_client.get_input_list().inputs
                        if not any(src['inputName'] == source_name for src in sources):
                            logger.warning(f"Source '{source_name}' not found. Cannot toggle filter '{filter_name}'.")
                            return
                        filters = self.obs_client.get_source_filter_list(source_name).filters
                        if not any(f['filterName'] == filter_name for f in filters):
                            logger.warning(f"Filter '{filter_name}' not found on source '{source_name}'.")
                            return
                        self.obs_client.set_source_filter_enabled(source_name, filter_name, enabled)
                        logger.info(f"Set filter {filter_name} on {source_name} to {enabled}")
                    except Exception as e:
                        logger.error(f"Failed to toggle filter {filter_name} on {source_name}: {e}")

                elif action_type == 'media_restart':
                    source_name = action_config.get('source_name')
                    try:
                        sources = self.obs_client.get_input_list().inputs
                        if not any(src['inputName'] == source_name for src in sources):
                            logger.warning(f"Media source '{source_name}' not found. Cannot restart.")
                            return
                        self.obs_client.trigger_media_input_action(source_name, "restart")
                        logger.info(f"Restarted media source: {source_name}")
                    except Exception as e:
                        logger.error(f"Failed to restart media source {source_name}: {e}")

            logger.info(f"Archipelago event: {event_type} - {event_data.get('text', '')}")
        except Exception as e:
            logger.error(f"Failed to trigger OBS event {event_type}: {e}")

    async def run(self):
        logger.info("Starting Subprocess-based Archipelago to OBS Bridge...")
        if not self.archipelago_dir:
            logger.error("Cannot find Archipelago installation")
            return False
        await self.connect_obs()
        try:
            self.start_archipelago_client()
        except Exception as e:
            logger.error(f"Failed to start Archipelago client: {e}")
            return False
        self.running = True
        try:
            await self.process_archipelago_output()
        finally:
            await self.cleanup()
        return True

    async def cleanup(self):
        self.running = False
        if self.archipelago_process:
            logger.info("Terminating Archipelago client process...")
            self.archipelago_process.terminate()
            try:
                self.archipelago_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                logger.warning("Archipelago client did not terminate gracefully, killing...")
                self.archipelago_process.kill()
        if self.obs_client:
            self.obs_client.disconnect()
            logger.info("Closed OBS connection")


def load_config(config_file: str = 'config.json') -> Dict[str, Any]:
    default_config = {
        "archipelago_host": "archipelago.gg",
        "archipelago_port": 59331,
        "archipelago_password": "",
        "bot_name": "OBS_Observer_Bot",
        "obs_host": "localhost",
        "obs_port": 4455,
        "obs_password": "",
        "log_all_events": True,
        "log_event_data": False,
        "obs_actions": {
            "item_received": {"type": "text_update", "source_name": "LastItemReceived", "text_template": "{text}"},
            "item_sent": {"type": "text_update", "source_name": "LastItemSent", "text_template": "{text}"},
            "location_checked": {"type": "text_update", "source_name": "LastLocationChecked", "text_template": "{text}"},
            "player_joined": {"type": "text_update", "source_name": "PlayerStatus", "text_template": "{text}"},
            "player_left": {"type": "text_update", "source_name": "PlayerStatus", "text_template": "{text}"},
            "goal_completed": {"type": "scene_switch", "scene_name": "GoalCompleted"},
            "hint": {"type": "text_update", "source_name": "LastHint", "text_template": "{text}"},
            "chat": {"type": "text_update", "source_name": "LastChatMessage", "text_template": "{text}"},
            "server_message": {"type": "text_update", "source_name": "ServerMessage", "text_template": "{text}"}
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
    print("Subprocess-based Archipelago to OBS Bridge")
    print("Uses the official Archipelago client as subprocess")
    print()

    config = load_config()
    bridge = ArchipelagoSubprocessBridge(config)
    await bridge.run()


if __name__ == "__main__":
    # This approach uses the official Archipelago client as a subprocess
    # Benefits:
    # - Uses the official client (no version compatibility issues)
    # - Parses text output to detect events
    # - Should work with any server the official client works with

    asyncio.run(main())
