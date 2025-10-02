#!/usr/bin/env python3
"""
Archipelago to OBS Bridge with Integrated Animation System
Supports player-specific PNGs and smooth animations
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
from pathlib import Path

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


class ArchipelagoAnimatedBridge:
    """Enhanced bridge with PNG support and smooth animations"""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.obs_client = None
        self.archipelago_process = None
        self.running = False
        self.archipelago_dir = self.find_archipelago_directory()
        self.setup_image_directories()

    def setup_image_directories(self):
        """Create image directory structure"""
        base_dir = Path(self.config.get('images_base_dir', './images'))

        # Create directory structure
        self.images = {
            'players': base_dir / 'players',
            'events': base_dir / 'events',
            'items': base_dir / 'items',
            'locations': base_dir / 'locations'
        }

        for dir_path in self.images.values():
            dir_path.mkdir(parents=True, exist_ok=True)

        # Create example images if they don't exist
        self.create_example_images()

        logger.info(f"Image directories set up at: {base_dir}")

    def create_example_images(self):
        """Create placeholder image files as examples"""
        examples = {
            self.images['players'] / 'default_player.png': "Default player avatar",
            self.images['events'] / 'item_received.png': "Item received icon",
            self.images['events'] / 'location_checked.png': "Location checked icon",
            self.images['events'] / 'goal_completed.png': "Goal completed icon",
            self.images['events'] / 'player_joined.png': "Player joined icon",
            self.images['events'] / 'chat.png': "Chat message icon",
            self.images['items'] / 'default_item.png': "Default item icon",
            self.images['locations'] / 'default_location.png': "Default location icon"
        }

        for img_path, description in examples.items():
            if not img_path.exists():
                placeholder_path = img_path.with_suffix('.txt')
                placeholder_path.write_text(f"Replace with PNG: {description}")

    def get_player_image(self, player_name: str) -> str:
        """Get player-specific image path"""
        safe_name = re.sub(r'[^\w\-_\.]', '_', player_name)
        player_img = self.images['players'] / f"{safe_name}.png"
        logger.info(f"Player image: {player_img}")
        logger.info(f"Player image safe name: {safe_name}")

        if player_img.exists():
            return str(player_img)

        player_img_lower = self.images['players'] / f"{safe_name.lower()}.png"
        if player_img_lower.exists():
            return str(player_img_lower)

        default_img = self.images['players'] / 'default_player.png'
        return str(default_img) if default_img.exists() else None

    def get_event_image(self, event_type: str) -> str:
        """Get event-type-specific image path"""
        event_img = self.images['events'] / f"{event_type}.png"
        return str(event_img) if event_img.exists() else None

    def get_item_image(self, item_name: str) -> str:
        """Get item-specific image path"""
        safe_name = re.sub(r'[^\w\-_\.]', '_', item_name)
        item_img = self.images['items'] / f"{safe_name}.png"

        if item_img.exists():
            return str(item_img)

        item_img_lower = self.images['items'] / f"{safe_name.lower()}.png"
        if item_img_lower.exists():
            return str(item_img_lower)

        default_img = self.images['items'] / 'default_item.png'
        return str(default_img) if default_img.exists() else None

    def get_location_image(self, location_name: str) -> str:
        """Get location-specific image path"""
        safe_name = re.sub(r'[^\w\-_\.]', '_', location_name)
        location_img = self.images['locations'] / f"{safe_name}.png"

        if location_img.exists():
            return str(location_img)

        location_img_lower = self.images['locations'] / f"{safe_name.lower()}.png"
        if location_img_lower.exists():
            return str(location_img_lower)

        default_img = self.images['locations'] / 'default_location.png'
        return str(default_img) if default_img.exists() else None

    async def update_ticker_display(self, event_data: Dict[str, Any]):
        """Update ticker with proper position reset for animations"""
        if not self.obs_client:
            return

        ticker_config = self.config.get('ticker_config', {})
        animation_config = self.config.get('animation_config', {})
        scene_name = animation_config.get('scene_name', 'Main Stream')

        logger.info(f"🎬 Updating ticker for: {event_data.get('event_type', 'unknown')}")

        if animation_config.get('enable_animations', True):
            # STEP 1: Reset positions to start (off-screen/invisible)
            await self.reset_ticker_positions(ticker_config, scene_name)

            # STEP 2: Update content while sources are off-screen
            await self.update_ticker_content(event_data, ticker_config)

            # STEP 3: Brief pause to ensure content updates
            await asyncio.sleep(0.1)

            # STEP 4: Animate sources to final positions
            await self.animate_ticker_to_final_positions(ticker_config, animation_config, scene_name)

            logger.info(f"✅ Animated ticker update complete: {event_data.get('ticker_text', '')}")
        else:
            # Just update content without animations
            await self.update_ticker_content(event_data, ticker_config)
            logger.info(f"Static update: {event_data.get('ticker_text', '')}")

    async def reset_ticker_positions(self, ticker_config: Dict, scene_name: str):
        """Reset all ticker elements to starting positions (off-screen/invisible)"""
        logger.info("🔄 Resetting ticker positions to start...")

        # Get animation config to use configurable start positions
        animation_config = self.config.get('animation_config', {})

        # Reset text to configurable off-screen position
        text_source = ticker_config.get('text_source', 'TickerText')
        text_start_x = animation_config.get('text_start_x', -400)  # Use config value, fallback to -400
        await self.set_source_position(text_source, scene_name, x=text_start_x, y=None)

        logger.info(f"🔄 Reset {text_source} to X: {text_start_x}")

        # Reset images to scale 0 (invisible)
        image_sources = [
            ticker_config.get('player_image_source', 'TickerPlayerImage'),
            ticker_config.get('event_image_source', 'TickerEventImage'),
            ticker_config.get('item_image_source', 'TickerItemImage'),
            ticker_config.get('location_image_source', 'TickerLocationImage')
        ]

        for source_name in image_sources:
            if source_name:
                await self.set_source_scale(source_name, scene_name, scale_x=0.0, scale_y=0.0)

    async def animate_ticker_to_final_positions(self, ticker_config: Dict, animation_config: Dict, scene_name: str):

        # ENSURE SCENE IS SET TO MAIN STREAM BEFORE ANIMATIONS
        try:
            # Switch to the main stream scene before starting animations
            self.obs_client.set_current_program_scene(scene_name)
            logger.info(f"📺 Switched to scene '{scene_name}' before animation")

            # Small delay to ensure scene switch is complete
            await asyncio.sleep(0.1)
        except Exception as e:
            logger.warning(f"Could not switch to scene '{scene_name}': {e}")
            # Continue with animations even if scene switch fails

        """Animate all ticker elements to their final positions"""
        logger.info("🎬 Starting animations to final positions...")

        duration = animation_config.get('animation_duration', 0.6)
        steps = animation_config.get('animation_steps', 25)

        # Start text slide animation - pass animation_config parameter
        text_source = ticker_config.get('text_source', 'TickerText')
        text_task = asyncio.create_task(
            self.animate_text_slide_fixed(text_source, scene_name, animation_config, duration, steps)
        )

        # Start image pop animations with staggered timing
        image_sources = [
            ticker_config.get('player_image_source', 'TickerPlayerImage'),
            ticker_config.get('event_image_source', 'TickerEventImage'),
            ticker_config.get('item_image_source', 'TickerItemImage'),
            ticker_config.get('location_image_source', 'TickerLocationImage')
        ]

        image_tasks = []
        for i, source_name in enumerate(image_sources):
            if source_name:
                delay = i * 0.15  # 150ms stagger between images
                task = asyncio.create_task(
                    self.animate_image_pop_fixed(source_name, scene_name, animation_config, duration * 0.8, steps, delay)
                )
                image_tasks.append(task)

        # Wait for all animations to complete
        await text_task
        if image_tasks:
            await asyncio.gather(*image_tasks)

        logger.info("🎉 All animations complete!")

    async def set_source_position(self, source_name: str, scene_name: str, x: float = None, y: float = None):
        """Set source position instantly - FIXED method signature"""
        try:
            # Get scene items to find the source
            scene_items = self.obs_client.get_scene_item_list(scene_name)
            item_id = None

            for item in scene_items.scene_items:
                if item.get('sourceName') == source_name:
                    item_id = item.get('sceneItemId')
                    break

            if item_id is not None:
                transform = {}
                if x is not None:
                    transform["positionX"] = x
                if y is not None:
                    transform["positionY"] = y

                if transform:
                    self.obs_client.set_scene_item_transform(scene_name, item_id, transform)
                    logger.debug(f"Set {source_name} position: {transform}")

        except Exception as e:
            logger.debug(f"Could not set position for {source_name}: {e}")

    async def set_source_scale(self, source_name: str, scene_name: str, scale_x: float, scale_y: float):
        """Set source scale instantly - FIXED method signature"""
        try:
            # Get scene items to find the source
            scene_items = self.obs_client.get_scene_item_list(scene_name)
            item_id = None

            for item in scene_items.scene_items:
                if item.get('sourceName') == source_name:
                    item_id = item.get('sceneItemId')
                    break

            if item_id is not None:
                transform = {
                    "scaleX": scale_x,
                    "scaleY": scale_y
                }
                self.obs_client.set_scene_item_transform(scene_name, item_id, transform)
                logger.debug(f"Set {source_name} scale: {scale_x}, {scale_y}")

        except Exception as e:
            logger.debug(f"Could not set scale for {source_name}: {e}")

    async def animate_text_slide_fixed(self, source_name: str, scene_name: str, animation_config: Dict, duration: float,
                                       steps: int):
        """Slide text from off-screen to final position with configurable parameters"""
        try:
            scene_items = self.obs_client.get_scene_item_list(scene_name)
            item_id = None

            for item in scene_items.scene_items:
                if item.get('sourceName') == source_name:
                    item_id = item.get('sceneItemId')
                    break

            if item_id is None:
                logger.warning(f"Text source {source_name} not found in scene {scene_name}")
                return

            # Get configurable parameters from animation_config
            start_x = float(animation_config.get('text_start_x', -500))
            end_x = float(animation_config.get('text_end_x', 200))
            easing_power = animation_config.get('text_easing_power', 2.5)

            step_delay = duration / steps

            logger.info(f"🎬 WORKING: Animating {source_name} from X:{start_x} to X:{end_x} over {duration}s")

            for step in range(steps + 1):
                progress = step / steps
                eased_progress = 1 - (1 - progress) ** easing_power
                current_x = start_x + (end_x - start_x) * eased_progress
                self.obs_client.set_scene_item_transform(scene_name, item_id, {"positionX": current_x})
                if step < steps:
                    await asyncio.sleep(step_delay)

            logger.info(f"✅ WORKING: Text slide complete: {source_name} at X:{end_x}")

        except Exception as e:
            logger.error(f"Failed to animate text slide for {source_name}: {e}")

    async def animate_image_pop_fixed(self, source_name: str, scene_name: str, animation_config: Dict, duration: float,
                                      steps: int, delay: float = 0):
        """Scale image from 0 to 1 with configurable bounce effect"""
        if delay > 0:
            logger.info(f"🎬 {source_name} waiting {delay}s before animation...")
            await asyncio.sleep(delay)

        try:
            # Get scene items to find the source
            scene_items = self.obs_client.get_scene_item_list(scene_name)
            item_id = None

            for item in scene_items.scene_items:
                if item.get('sourceName') == source_name:
                    item_id = item.get('sceneItemId')
                    break

            if item_id is None:
                logger.warning(f"Image source {source_name} not found in scene {scene_name}")
                return

            # Get configurable parameters from animation_config with fallback defaults
            bounce_enabled = animation_config.get('image_bounce_enabled', True)
            max_overshoot = animation_config.get('image_max_overshoot', 1.4)
            overshoot_point = animation_config.get('image_overshoot_point', 0.6)
            settle_point = animation_config.get('image_settle_point', 0.8)
            intermediate_scale = animation_config.get('image_intermediate_scale', 1.1)
            easing_power = animation_config.get('image_easing_power', 2.0)

            step_delay = duration / steps
            logger.info(f"🎬 Animating {source_name} scale 0→1 over {duration}s (bounce: {bounce_enabled})")

            for step in range(steps + 1):
                progress = step / steps

                if bounce_enabled:
                    # Bounce effect with configurable parameters
                    if progress < overshoot_point:
                        # Growing phase with overshoot
                        scale = progress * max_overshoot
                    elif progress < settle_point:
                        # Settle back phase
                        overshoot_progress = (progress - overshoot_point) / (settle_point - overshoot_point)
                        scale = max_overshoot * (1 - overshoot_progress) + intermediate_scale * overshoot_progress
                    else:
                        # Final settle phase
                        final_progress = (progress - settle_point) / (1 - settle_point)
                        # Apply easing to final settle
                        eased_progress = 1 - (1 - final_progress) ** easing_power
                        scale = intermediate_scale * (1 - eased_progress) + 1.0 * eased_progress
                else:
                    # Simple linear or eased scaling without bounce
                    if easing_power != 1.0:
                        # Apply easing function
                        eased_progress = 1 - (1 - progress) ** easing_power
                        scale = eased_progress
                    else:
                        # Linear scaling
                        scale = progress

                # Ensure scale is never negative
                scale = max(0, scale)

                self.obs_client.set_scene_item_transform(scene_name, item_id, {"scaleX": scale, "scaleY": scale})

                if step < steps:
                    await asyncio.sleep(step_delay)

            logger.info(f"✅ Image pop complete: {source_name} at scale 1.0")

        except Exception as e:
            logger.error(f"Failed to animate image pop for {source_name}: {e}")

    async def update_ticker_content(self, event_data: Dict[str, Any], ticker_config: Dict[str, Any]):
        """Update ticker content (text and images)"""
        # Update main ticker text
        ticker_text_source = ticker_config.get('text_source', 'TickerText')
        ticker_text = event_data.get('ticker_text', event_data.get('text', ''))

        try:
            self.obs_client.set_input_settings(ticker_text_source, {"text": ticker_text}, True)
        except Exception as e:
            logger.error(f"Failed to update ticker text: {e}")

        # Update player image
        if 'player_name' in event_data:
            player_img_path = self.get_player_image(event_data['player_name'])
            if player_img_path:
                player_img_source = ticker_config.get('player_image_source', 'TickerPlayerImage')
                try:
                    self.obs_client.set_input_settings(
                        player_img_source,
                        {"file": player_img_path},
                        True
                    )
                except Exception as e:
                    logger.error(f"Failed to update player image: {e}")

        # Update event type image
        event_img_path = self.get_event_image(event_data.get('event_type', ''))
        if event_img_path:
            event_img_source = ticker_config.get('event_image_source', 'TickerEventImage')
            try:
                self.obs_client.set_input_settings(
                    event_img_source,
                    {"file": event_img_path},
                    True
                )
            except Exception as e:
                logger.error(f"Failed to update event image: {e}")

        # Update item/location specific image
        if 'item_name' in event_data:
            item_img_path = self.get_item_image(event_data['item_name'])
            if item_img_path:
                item_img_source = ticker_config.get('item_image_source', 'TickerItemImage')
                try:
                    self.obs_client.set_input_settings(
                        item_img_source,
                        {"file": item_img_path},
                        True
                    )
                except Exception as e:
                    logger.error(f"Failed to update item image: {e}")

        elif 'location_name' in event_data:
            location_img_path = self.get_location_image(event_data['location_name'])
            if location_img_path:
                location_img_source = ticker_config.get('location_image_source', 'TickerLocationImage')
                try:
                    self.obs_client.set_input_settings(
                        location_img_source,
                        {"file": location_img_path},
                        True
                    )
                except Exception as e:
                    logger.error(f"Failed to update location image: {e}")

    async def handle_goal_completion_celebration(self, event_data: Dict[str, Any]):
        """Handle special goal completion celebration"""
        animation_config = self.config.get('animation_config', {})

        if not animation_config.get('enable_celebrations', True):
            return

        celebration_scene = animation_config.get('celebration_scene', 'GoalCompleted')
        main_scene = animation_config.get('scene_name', 'Main Stream')
        duration = animation_config.get('celebration_duration', 5.0)

        try:
            # Update celebration scene with player name if it has text sources
            celebration_text = f"🎉 {event_data.get('player_name', 'Someone')} COMPLETED THEIR GOAL! 🎉"
            celebration_source = animation_config.get('celebration_text_source', 'CelebrationText')

            try:
                self.obs_client.set_input_settings(celebration_source, {"text": celebration_text}, True)
            except Exception:
                pass  # Celebration text source is optional

            # Switch to celebration scene
            self.obs_client.set_current_program_scene(celebration_scene)
            logger.info(f"🎉 GOAL CELEBRATION: Switched to {celebration_scene}")

            # Wait for celebration duration
            await asyncio.sleep(duration)

            # Return to main scene
            self.obs_client.set_current_program_scene(main_scene)
            logger.info(f"Returned to {main_scene} after celebration")

        except Exception as e:
            logger.error(f"Failed to execute goal completion celebration: {e}")

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
                import time;
                time.sleep(2)
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
            'item_received': re.compile(r'(.+) received (.+) from (.+)'),
            'item_sent': re.compile(r'(.+) sent (.+) to (.+)'),
            'location_checked': re.compile(r'(.+) checked (.+)'),
            'player_joined': re.compile(r'(.+) has joined'),
            'player_left': re.compile(r'(.+) has left'),
            'goal_completed': re.compile(r'(.+) completed their goal'),
            'hint': re.compile(r'Hint: (.+)'),
            'chat': re.compile(r'\[(.+?)\] (.+?): (.+)'),  # Keep non-greedy for timestamp and player
            'server_message': re.compile(r'Notice.*?: (.+)'),
            'release': re.compile(r'(.+) has released'),
            'collect': re.compile(r'(.+) has collected'),
            'connected': re.compile(r'Successfully connected to (.+)'),
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

                # Strip ANSI color codes before parsing
                clean_line = self.strip_ansi_codes(line)
                await self.parse_and_trigger_events(clean_line, patterns)
        except Exception as e:
            logger.error(f"Error processing Archipelago output: {e}")
        finally:
            logger.info("Stopped monitoring Archipelago output")

    def strip_ansi_codes(self, text: str) -> str:
        """Remove ANSI color codes from text"""
        ansi_escape = re.compile(r'\x1b\[[0-9;]*m')
        return ansi_escape.sub('', text)

    async def parse_and_trigger_events(self, line: str, patterns: Dict[str, re.Pattern]):
        for event_type, pattern in patterns.items():
            match = pattern.search(line)
            if match:
                await self.handle_parsed_event(event_type, match.groups(), line)
                return
        if any(keyword in line.lower() for keyword in ['item', 'location', 'player', 'goal', 'hint', 'chat']):
            await self.trigger_obs_event("raw_message", {"text": line, "timestamp": datetime.now().isoformat()})

    def extract_player_name(self, full_player_string: str) -> str:
        """
        Extract just the player name from Archipelago's full player string.
        Example: "GuvnahBRC__Team__1__viewing_Bomb_Rush_Cyberfunk" -> "GuvnahBRC"
        """
        # Split on common delimiters and take the first part
        # Archipelago typically uses patterns like: PlayerName__Team__X__viewing_GameName
        player_name = full_player_string.split('__')[0].strip()

        # Also handle cases where there might be parentheses or brackets
        player_name = player_name.split('(')[0].strip()
        player_name = player_name.split('[')[0].strip()

        logger.debug(f"Extracted player name: '{player_name}' from '{full_player_string}'")
        return player_name

    async def handle_parsed_event(self, event_type: str, groups: tuple, raw_line: str):
        event_data = {
            "raw_line": raw_line,
            "timestamp": datetime.now().isoformat(),
            "event_type": event_type
        }

        if event_type == 'item_received':
            # Extract clean player names
            receiving_player = self.extract_player_name(groups[0])
            sending_player = self.extract_player_name(groups[2])

            event_data.update({
                "receiving_player": receiving_player,
                "item_name": groups[1],
                "sending_player": sending_player,
                "text": f"{receiving_player} received {groups[1]} from {sending_player}",
                "ticker_text": f"{receiving_player} got {groups[1]}!",
                "player_name": receiving_player  # Use cleaned name for image lookup
            })
        elif event_type == 'item_sent':
            sending_player = self.extract_player_name(groups[0])
            receiving_player = self.extract_player_name(groups[2])

            event_data.update({
                "sending_player": sending_player,
                "item_name": groups[1],
                "receiving_player": receiving_player,
                "text": f"{sending_player} sent {groups[1]} to {receiving_player}",
                "ticker_text": f"{sending_player} sent {groups[1]}!",
                "player_name": sending_player
            })
        elif event_type == 'location_checked':
            player_name = self.extract_player_name(groups[0])

            event_data.update({
                "player_name": player_name,
                "location_name": groups[1],
                "text": f"{player_name} checked {groups[1]}",
                "ticker_text": f"{player_name} found {groups[1]}!"
            })
        elif event_type == 'player_joined':
            player_name = self.extract_player_name(groups[0])

            event_data.update({
                "player_name": player_name,
                "text": f"{player_name} joined the game",
                "ticker_text": f"{player_name} joined!"
            })
        elif event_type == 'player_left':
            player_name = self.extract_player_name(groups[0])

            event_data.update({
                "player_name": player_name,
                "text": f"{player_name} left the game",
                "ticker_text": f"{player_name} left"
            })
        elif event_type == 'goal_completed':
            player_name = self.extract_player_name(groups[0])

            event_data.update({
                "player_name": player_name,
                "text": f"{player_name} completed their goal!",
                "ticker_text": f"🎉 {player_name} COMPLETED THEIR GOAL! 🎉"
            })
        elif event_type == 'hint':
            event_data.update({
                "hint_text": groups[0],
                "text": f"Hint: {groups[0]}",
                "ticker_text": f"💡 Hint: {groups[0]}"
            })
        elif event_type == 'chat':
            player_name = self.extract_player_name(groups[1])

            event_data.update({
                "timestamp_str": groups[0],
                "player_name": player_name,
                "message": groups[2],
                "text": f"{player_name}: {groups[2]}",
                "ticker_text": f"{player_name}: {groups[2]}"
            })
        elif event_type == 'server_message':
            event_data.update({
                "message": groups[0],
                "text": groups[0],
                "ticker_text": groups[0]
            })
        else:
            event_data.update({
                "text": raw_line,
                "ticker_text": raw_line
            })

        await self.trigger_obs_event(event_type, event_data)

    async def trigger_obs_event(self, event_type: str, event_data: Dict[str, Any]):
        if not self.obs_client:
            logger.info(f"[NO OBS] {event_type}: {event_data.get('text', str(event_data))}")
            return

        # Update ticker display with animations
        await self.update_ticker_display(event_data)

        # Handle special goal completion celebration
        if event_type == 'goal_completed':
            await self.handle_goal_completion_celebration(event_data)

        # Existing OBS actions (kept for backward compatibility)
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
                            logger.warning(
                                f"Source '{source_name}' not found in scene '{scene_name}'. Check config.json.")
                            return
                        self.obs_client.set_scene_item_enabled(scene_name=scene_name, scene_item_id=item_id,
                                                               scene_item_enabled=visible)
                        logger.info(f"Set {source_name} visibility in {scene_name} to {visible}")
                    except Exception as e:
                        logger.error(f"Failed to toggle visibility for {source_name} in {scene_name}: {e}")

            logger.info(f"Archipelago event: {event_type} - {event_data.get('text', '')}")
        except Exception as e:
            logger.error(f"Failed to trigger OBS event {event_type}: {e}")

    async def run(self):
        logger.info("Starting Animated Archipelago to OBS Bridge...")
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
        "images_base_dir": "./images",
        "log_all_events": True,
        "log_event_data": False,
        "ticker_config": {
            "text_source": "TickerText",
            "player_image_source": "TickerPlayerImage",
            "event_image_source": "TickerEventImage",
            "item_image_source": "TickerItemImage",
            "location_image_source": "TickerLocationImage"
        },
        "animation_config": {
            "enable_animations": True,
            "scene_name": "Main Stream",
            "animation_duration": 0.6,
            "animation_steps": 25,

            # Optional Text Animation Parameters (if not specified, uses working defaults)
            "text_start_x": -500,
            "text_end_x": None,
            "text_easing_power": 2.5,

            # Optional Image Animation Parameters (if not specified, uses working defaults)
            "image_bounce_enabled": True,
            "image_max_overshoot": 1.4,
            "image_overshoot_point": 0.6,
            "image_settle_point": 0.8,
            "image_intermediate_scale": 1.1,
            "image_easing_power": 2.0,

            "enable_celebrations": True,
            "celebration_scene": "GoalCompleted",
            "celebration_duration": 5.0,
            "celebration_text_source": "CelebrationText"
        },
        "obs_actions": {
            "item_received": {"type": "text_update", "source_name": "LastItemReceived", "text_template": "{text}"},
            "item_sent": {"type": "text_update", "source_name": "LastItemSent", "text_template": "{text}"},
            "location_checked": {"type": "text_update", "source_name": "LastLocationChecked",
                                 "text_template": "{text}"},
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
    print("=== Animated Archipelago to OBS Ticker Bridge ===")
    print("Features:")
    print("• Player-specific PNG avatars")
    print("• Event-type icons")
    print("• Item/location specific images")
    print("• Smooth slide-in/pop animations")
    print("• Goal completion celebrations")
    print()

    config = load_config()

    # Display configuration summary
    print("Configuration Summary:")
    print(f"• Archipelago: {config['archipelago_host']}:{config['archipelago_port']}")
    print(f"• OBS: {config['obs_host']}:{config['obs_port']}")
    print(f"• Images: {config['images_base_dir']}")
    print(f"• Animations: {'Enabled' if config['animation_config']['enable_animations'] else 'Disabled'}")
    print(f"• Celebrations: {'Enabled' if config['animation_config']['enable_celebrations'] else 'Disabled'}")
    print()

    bridge = ArchipelagoAnimatedBridge(config)

    try:
        await bridge.run()
    except KeyboardInterrupt:
        print("\nShutdown requested by user")
        await bridge.cleanup()
    except Exception as e:
        logger.error(f"Bridge crashed: {e}")
        await bridge.cleanup()


if __name__ == "__main__":
    print("Archipelago Animated Ticker Bridge")
    print("==================================")
    print()
    print("Setup Instructions:")
    print("1. Set up OBS sources with exact names:")
    print("   - TickerText (Text source)")
    print("   - TickerPlayerImage (Image source)")
    print("   - TickerEventImage (Image source)")
    print("   - TickerItemImage (Image source)")
    print("   - TickerLocationImage (Image source)")
    print()
    print("2. Add filters to sources for animations:")
    print("   - TickerText: Move filter (slide from left)")
    print("   - Images: Scale/Aspect Ratio filter (pop in from 0% to 100%)")
    print()
    print("3. Enable OBS WebSocket server:")
    print("   - Tools → WebSocket Server Settings")
    print("   - Enable server, set port 4455")
    print()
    print("4. Place PNG files in:")
    print("   - images/players/PlayerName.png")
    print("   - images/events/item_received.png, location_checked.png, etc.")
    print("   - images/items/ItemName.png")
    print("   - images/locations/LocationName.png")
    print()
    print("Starting bridge...")
    print()

    asyncio.run(main())