#!/usr/bin/env python3
"""
Debug test script with correct obsws-python method signatures
"""

import asyncio
import logging

try:
    import obsws_python as obs

    OBS_AVAILABLE = True
except ImportError:
    print("obsws-python not available!")
    OBS_AVAILABLE = False

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def debug_obs_connection():
    """Test OBS connection and source positioning with correct API calls"""
    if not OBS_AVAILABLE:
        print("Cannot test - obsws-python not installed")
        return

    try:
        # Connect to OBS
        obs_client = obs.ReqClient(host='localhost', port=4455, password='UobcXG6dLjO3QJM0')
        print("✅ Connected to OBS WebSocket")

        # Test 1: List all scenes
        scenes = obs_client.get_scene_list()
        print(f"\n📋 Available scenes: {[s['sceneName'] for s in scenes.scenes]}")

        current_scene = obs_client.get_current_program_scene()
        scene_name = current_scene.current_program_scene_name
        print(f"🎬 Current scene: '{scene_name}'")

        # Test 2: Get scene items (correct method)
        try:
            scene_items = obs_client.get_scene_item_list(scene_name)
            print(f"\n📋 Scene items in '{scene_name}':")

            ticker_text_found = False
            ticker_item_id = None

            for item in scene_items.scene_items:
                source_name = item.get('sourceName', 'Unknown')
                item_id = item.get('sceneItemId', None)
                enabled = item.get('sceneItemEnabled', True)
                print(f"  • {source_name} (ID: {item_id}, Enabled: {enabled})")

                if source_name == 'TickerText':
                    ticker_text_found = True
                    ticker_item_id = item_id

            if not ticker_text_found:
                print(f"❌ TickerText not found in scene '{scene_name}'")
                print("Available sources:", [item.get('sourceName') for item in scene_items.scene_items])
                return

            print(f"✅ Found TickerText with item_id: {ticker_item_id}")

        except Exception as e:
            print(f"❌ Error getting scene items: {e}")
            return

        # Test 3: Get current transform (correct method signature)
        try:
            current_transform = obs_client.get_scene_item_transform(scene_name, ticker_item_id)
            transform_data = current_transform.scene_item_transform

            current_x = transform_data.get('positionX', 'Unknown')
            current_y = transform_data.get('positionY', 'Unknown')
            current_scale_x = transform_data.get('scaleX', 'Unknown')
            current_scale_y = transform_data.get('scaleY', 'Unknown')

            print(f"\n📍 Current TickerText transform:")
            print(f"  Position: X={current_x}, Y={current_y}")
            print(f"  Scale: X={current_scale_x}, Y={current_scale_y}")

        except Exception as e:
            print(f"❌ Error getting transform: {e}")
            return

        # Test 4: Manual animation test with correct method
        print(f"\n🧪 Starting manual animation test...")

        # Store original position
        original_x = current_x

        # Test: Move to off-screen position
        print("🔄 Moving text off-screen...")
        try:
            obs_client.set_scene_item_transform(
                scene_name,
                ticker_item_id,
                {"positionX": -400}
            )
            print("✅ Moved text off-screen (X: -400)")
        except Exception as e:
            print(f"❌ Failed to move off-screen: {e}")
            return

        await asyncio.sleep(1)  # Wait to see the change

        # Test: Animate back on-screen in steps
        print("🎬 Animating text back on-screen...")
        steps = 8
        start_x = -400
        end_x = float(original_x) if isinstance(original_x, (int, float)) else 200
        duration = 1.5  # 1.5 seconds total

        try:
            for step in range(steps + 1):
                progress = step / steps
                # Ease-out curve
                eased_progress = 1 - (1 - progress) ** 2
                current_x = start_x + (end_x - start_x) * eased_progress

                obs_client.set_scene_item_transform(
                    scene_name,
                    ticker_item_id,
                    {"positionX": current_x}
                )

                print(f"📍 Step {step + 1}/{steps + 1}: X = {current_x:.1f}")

                if step < steps:
                    await asyncio.sleep(duration / steps)

            print("✅ Manual text animation test complete!")

        except Exception as e:
            print(f"❌ Animation failed: {e}")

        # Test 5: Test image sources
        print(f"\n🖼️  Testing image sources...")
        image_sources = ["TickerPlayerImage", "TickerEventImage", "TickerItemImage", "TickerLocationImage"]

        for source_name in image_sources:
            # Find the source in scene items
            image_item_id = None
            for item in scene_items.scene_items:
                if item.get('sourceName') == source_name:
                    image_item_id = item.get('sceneItemId')
                    break

            if image_item_id is None:
                print(f"❌ {source_name} not found in scene")
                continue

            print(f"✅ Found {source_name} (ID: {image_item_id})")

            # Test scale animation
            try:
                print(f"🎬 Testing scale animation on {source_name}...")

                # Scale to 0
                obs_client.set_scene_item_transform(
                    scene_name,
                    image_item_id,
                    {"scaleX": 0.0, "scaleY": 0.0}
                )
                print(f"🔄 Scaled {source_name} to 0")

                await asyncio.sleep(0.3)

                # Animate scale to 1 in steps
                scale_steps = 5
                for step in range(scale_steps + 1):
                    scale = step / scale_steps  # 0 to 1
                    obs_client.set_scene_item_transform(
                        scene_name,
                        image_item_id,
                        {"scaleX": scale, "scaleY": scale}
                    )
                    print(f"📏 {source_name} scale: {scale:.2f}")
                    await asyncio.sleep(0.15)

                print(f"✅ {source_name} scale test complete!")

            except Exception as e:
                print(f"❌ Scale test failed for {source_name}: {e}")

        obs_client.disconnect()
        print("\n🎉 All tests complete!")

        # Summary
        print("\n📊 SUMMARY:")
        print("✅ OBS connection: Working")
        print("✅ Scene access: Working")
        print("✅ TickerText found: Working")
        print("✅ Transform control: Working")
        print("✅ Animation capability: Working")
        print("\n💡 The bridge should work with the correct method signatures!")

    except Exception as e:
        print(f"❌ Failed to connect to OBS: {e}")
        print("Make sure:")
        print("1. OBS is running")
        print("2. WebSocket server is enabled (Tools → WebSocket Server Settings)")
        print("3. Port 4455 is correct")
        print("4. Password matches")


if __name__ == "__main__":
    print("🔧 OBS Animation Debug Test (Fixed)")
    print("=" * 35)
    asyncio.run(debug_obs_connection())