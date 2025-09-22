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
from typing import Dict, Any, Optional
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

        # Find Archipelago installation
        self.archipelago_dir = self.find_archipelago_directory()

    def find_archipelago_directory(self):
        """Find the Archipelago installation directory"""
        # Try common locations
        possible_paths = [
            # Current directory first
            ".",
            # Common installation paths
            os.path.expanduser("~/Archipelago"),
            os.path.expanduser("~/AppData/Local/Archipelago"),
            "C:/Archipelago",
            "C:/Program Files/Archipelago",
            "C:/Program Files (x86)/Archipelago",
            # Check if we're already in an Archipelago directory
            os.path.dirname(os.path.abspath(__file__))
        ]

        for path in possible_paths:
            if os.path.exists(os.path.join(path, "CommonClient.py")):
                logger.info(f"Found Archipelago installation at: {path}")
                return os.path.abspath(path)

        logger.error("Could not find Archipelago installation")
        logger.info("Please ensure this script is in your Archipelago directory or update the path")
        return None

    async def connect_obs(self):
        """Connect to OBS WebSocket"""
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
        """Start the official Archipelago text client as subprocess"""
        if not self.archipelago_dir:
            raise Exception("Archipelago directory not found")

        # Try different approaches to start the client
        approaches = [
            # Approach 1: Direct CommonClient.py with connection string
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
            # Approach 2: Text client specifically
            {
                "cmd": [
                    sys.executable,
                    os.path.join(self.archipelago_dir, "TextClient.py"),
                    f"{self.config.get('archipelago_host', 'localhost')}:{self.config.get('archipelago_port', 38281)}"
                ],
                "name": "TextClient.py"
            },
            # Approach 3: CommonClient with manual connection after startup
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

            # Add password if provided
            cmd = approach["cmd"].copy()
            if self.config.get('archipelago_password') and not approach.get('manual_connect'):
                cmd.extend(["--password", self.config['archipelago_password']])

            logger.info(f"Command: {' '.join(cmd)}")

            try:
                # Start the process
                self.archipelago_process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    stdin=subprocess.PIPE,
                    universal_newlines=True,
                    bufsize=1,  # Line buffered
                    cwd=self.archipelago_dir
                )

                # If this is manual connect, send connection commands via stdin
                if approach.get('manual_connect'):
                    connection_commands = [
                        f"/connect {self.config.get('archipelago_host', 'localhost')}:{self.config.get('archipelago_port', 38281)}",
                        f"/name {self.config.get('bot_name', 'OBS_Observer_Bot')}"
                    ]

                    if self.config.get('archipelago_password'):
                        connection_commands.append(f"/password {self.config['archipelago_password']}")

                    # Send commands
                    for cmd in connection_commands:
                        logger.info(f"Sending command: {cmd}")
                        self.archipelago_process.stdin.write(cmd + '\n')
                        self.archipelago_process.stdin.flush()

                # Give the process a moment to start
                import time
                time.sleep(2)

                # Check if process is still running
                if self.archipelago_process.poll() is None:
                    logger.info(f"Approach {i + 1} successful - process running")

                    # If this is the log monitoring approach, set up log monitoring instead of stdout
                    if approach.get('monitor_logs'):
                        self.log_file_path = self.find_latest_log_file()
                        logger.info(f"Will monitor log file: {self.log_file_path}")

                    return self.archipelago_process
                else:
                    # Process exited, try next approach
                    logger.warning(
                        f"Approach {i + 1} failed - process exited with code {self.archipelago_process.returncode}")
                    continue

            except Exception as e:
                logger.warning(f"Approach {i + 1} failed: {e}")
                continue

        # If all approaches failed
        raise Exception("All client startup approaches failed")

    def find_latest_log_file(self):
        """Find the most recent Archipelago log file"""
        log_patterns = [
            "*.log",
            "Archipelago*.log",
            "logs/*.log",
            "logs/Archipelago*.log"
        ]

        import glob

        latest_file = None
        latest_time = 0

        for pattern in log_patterns:
            for log_file in glob.glob(os.path.join(self.archipelago_dir, pattern)):
                mtime = os.path.getmtime(log_file)
                if mtime > latest_time:
                    latest_time = mtime
                    latest_file = log_file

        return latest_file

    async def monitor_log_file(self):
        """Monitor the Archipelago log file for new entries"""
        if not hasattr(self, 'log_file_path') or not self.log_file_path:
            logger.error("No log file path set for monitoring")
            return

        logger.info(f"Monitoring log file: {self.log_file_path}")

        # Patterns for log file entries
        patterns = {
            'item_received': re.compile(r'(.+?) received (.+?) from (.+?)'),
            'item_sent': re.compile(r'(.+?) sent (.+?) to (.+?)'),
            'location_checked': re.compile(r'(.+?) checked (.+?)'),
            'player_joined': re.compile(r'(.+?) has joined'),
            'player_left': re.compile(r'(.+?) has left'),
            'goal_completed': re.compile(r'(.+?) completed their goal'),
            'connected': re.compile(r'Connected|has joined'),
            'file_log': re.compile(r'\[FileLog.*?\]: (.+)'),
            'server_message': re.compile(r'Notice.*?: (.+)'),
        }

        try:
            # Start from the end of the file
            with open(self.log_file_path, 'r', encoding='utf-8') as f:
                f.seek(0, 2)  # Go to end of file

                while self.running:
                    line = f.readline()
                    if not line:
                        await asyncio.sleep(0.1)  # Wait for new content
                        continue

                    line = line.strip()
                    if not line:
                        continue

                    logger.debug(f"Log line: {line}")

                    # Skip kivy and system messages
                    if any(skip in line for skip in ['[kivy', '[GL:', '[Base:', '[Window:', '[Image:', '[Text:']):
                        continue

                    # Parse the line
                    await self.parse_and_trigger_events(line, patterns)

        except Exception as e:
            logger.error(f"Error monitoring log file: {e}")

    async def process_archipelago_output(self):
        """Process output from the Archipelago client or log file"""
        if not self.archipelago_process:
            return

        # If we're monitoring logs, use log file monitoring instead
        if hasattr(self, 'log_file_path') and self.log_file_path:
            await self.monitor_log_file()
            return

        logger.info("Starting to monitor Archipelago client output...")

        # Patterns for different types of messages
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
            # Read output line by line
            while self.running and self.archipelago_process.poll() is None:
                line = await asyncio.get_event_loop().run_in_executor(
                    None, self.archipelago_process.stdout.readline
                )

                if not line:
                    continue

                line = line.strip()
                if not line:
                    continue

                logger.debug(f"Archipelago output: {line}")

                # Skip warning messages
                if "warning" in line.lower() or "_speedups" in line:
                    continue

                # Parse the line and trigger appropriate OBS events
                await self.parse_and_trigger_events(line, patterns)

        except Exception as e:
            logger.error(f"Error processing Archipelago output: {e}")
        finally:
            logger.info("Stopped monitoring Archipelago output")

    async def parse_and_trigger_events(self, line: str, patterns: Dict[str, re.Pattern]):
        """Parse a line of output and trigger appropriate OBS events"""
        try:
            # Check each pattern
            for event_type, pattern in patterns.items():
                match = pattern.search(line)
                if match:
                    await self.handle_parsed_event(event_type, match.groups(), line)
                    return

            # Log unmatched lines for debugging
            logger.debug(f"Unmatched line: {line}")

            # Trigger a generic event for any unmatched but potentially interesting lines
            if any(keyword in line.lower() for keyword in ['item', 'location', 'player', 'goal', 'hint', 'chat']):
                await self.trigger_obs_event("raw_message", {
                    "text": line,
                    "timestamp": datetime.now().isoformat()
                })

        except Exception as e:
            logger.error(f"Error parsing line '{line}': {e}")

    async def handle_parsed_event(self, event_type: str, groups: tuple, raw_line: str):
        """Handle a successfully parsed event"""
        event_data = {
            "raw_line": raw_line,
            "timestamp": datetime.now().isoformat()
        }

        if event_type == 'item_received':
            event_data.update({
                "receiving_player": groups[0],
                "item_name": groups[1],
                "sending_player": groups[2],
                "text": f"{groups[0]} received {groups[1]} from {groups[2]}"
            })

        elif event_type == 'item_sent':
            event_data.update({
                "sending_player": groups[0],
                "item_name": groups[1],
                "receiving_player": groups[2],
                "text": f"{groups[0]} sent {groups[1]} to {groups[2]}"
            })

        elif event_type == 'location_checked':
            event_data.update({
                "player_name": groups[0],
                "location_name": groups[1],
                "text": f"{groups[0]} checked {groups[1]}"
            })

        elif event_type == 'player_joined':
            event_data.update({
                "player_name": groups[0],
                "text": f"{groups[0]} joined the game"
            })

        elif event_type == 'player_left':
            event_data.update({
                "player_name": groups[0],
                "text": f"{groups[0]} left the game"
            })

        elif event_type == 'goal_completed':
            event_data.update({
                "player_name": groups[0],
                "text": f"{groups[0]} completed their goal!"
            })

        elif event_type == 'hint':
            event_data.update({
                "hint_text": groups[0],
                "text": f"Hint: {groups[0]}"
            })

        elif event_type == 'chat':
            event_data.update({
                "timestamp_str": groups[0],
                "player_name": groups[1],
                "message": groups[2],
                "text": f"{groups[1]}: {groups[2]}"
            })

        elif event_type == 'server_message':
            event_data.update({
                "message": groups[0],
                "text": groups[0]
            })

        else:
            # Generic handling for other events
            event_data["text"] = raw_line

        # Trigger the OBS event
        await self.trigger_obs_event(event_type, event_data)

    async def trigger_obs_event(self, event_type: str, event_data: Dict[str, Any]):
        """Trigger OBS events based on parsed Archipelago events"""
        if not self.obs_client:
            if self.config.get('log_all_events', True):
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
                        formatted_text = event_data.get('text', str(event_data))

                    self.obs_client.set_input_settings(
                        source_name, {"text": formatted_text}, True
                    )
                    logger.info(f"Updated text source {source_name}: {formatted_text}")

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
                logger.info(f"Archipelago event: {event_type} - {event_data.get('text', '')}")
                if self.config.get('log_event_data', False):
                    logger.debug(f"Event data: {event_data}")

        except Exception as e:
            logger.error(f"Failed to trigger OBS event {event_type}: {e}")

    async def run(self):
        """Main run loop"""
        logger.info("Starting Subprocess-based Archipelago to OBS Bridge...")

        if not self.archipelago_dir:
            logger.error("Cannot find Archipelago installation")
            return False

        # Connect to OBS
        await self.connect_obs()

        # Start Archipelago client
        try:
            self.start_archipelago_client()
        except Exception as e:
            logger.error(f"Failed to start Archipelago client: {e}")
            return False

        self.running = True

        logger.info("=== BRIDGE IS NOW RUNNING ===")
        logger.info("Monitoring official Archipelago client output...")
        logger.info("Press Ctrl+C to stop")

        try:
            # Start monitoring the client output
            await self.process_archipelago_output()

        except KeyboardInterrupt:
            logger.info("Received interrupt, shutting down...")
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
        finally:
            await self.cleanup()

        return True

    async def cleanup(self):
        """Clean up resources"""
        self.running = False

        if self.archipelago_process:
            logger.info("Terminating Archipelago client process...")
            self.archipelago_process.terminate()
            try:
                self.archipelago_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                logger.warning("Archipelago client did not terminate gracefully, killing...")
                self.archipelago_process.kill()
            logger.info("Archipelago client process stopped")

        if self.obs_client:
            self.obs_client.disconnect()
            logger.info("Closed OBS connection")


def load_config(config_file: str = 'config.json') -> Dict[str, Any]:
    """Load configuration from file"""
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
            "item_received": {
                "type": "text_update",
                "source_name": "LastItemReceived",
                "text_template": "{text}"
            },
            "item_sent": {
                "type": "text_update",
                "source_name": "LastItemSent",
                "text_template": "{text}"
            },
            "location_checked": {
                "type": "text_update",
                "source_name": "LastLocationChecked",
                "text_template": "{text}"
            },
            "player_joined": {
                "type": "text_update",
                "source_name": "PlayerStatus",
                "text_template": "{text}"
            },
            "player_left": {
                "type": "text_update",
                "source_name": "PlayerStatus",
                "text_template": "{text}"
            },
            "goal_completed": {
                "type": "scene_switch",
                "scene_name": "GoalCompleted"
            },
            "hint": {
                "type": "text_update",
                "source_name": "LastHint",
                "text_template": "{text}"
            },
            "chat": {
                "type": "text_update",
                "source_name": "LastChatMessage",
                "text_template": "{text}"
            },
            "server_message": {
                "type": "text_update",
                "source_name": "ServerMessage",
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
