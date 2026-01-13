#!/usr/bin/env python3
"""
Creative demonstrations for Claude Blender plugin.
Shows the power and flexibility of controlling Blender via code.
"""

import socket
import json
import math
import time

class BlenderDemo:
    def __init__(self, host='127.0.0.1', port=9876):
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.settimeout(30.0)
        self.socket.connect((host, port))
        self._id = 0
        print(f"Connected to Blender at {host}:{port}")

    def call(self, method, **params):
        self._id += 1
        request = {"jsonrpc": "2.0", "id": self._id, "method": method, "params": params}
        self.socket.send(json.dumps(request).encode() + b'\n')
        response = b''
        while b'\n' not in response:
            response += self.socket.recv(65536)
        return json.loads(response.decode())

    def execute(self, code):
        return self.call("execute", code=code)

    def close(self):
        self.socket.close()


def demo_geometric_sculpture(client):
    """Create a beautiful geometric sculpture with colorful materials."""
    print("\n=== Demo 1: Geometric Sculpture ===")

    # Clear the scene first
    client.execute("""
import bpy
# Delete all mesh objects
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)
""")

    # Create the sculpture
    code = '''
import bpy
import math

# Create a collection for our sculpture
if "Sculpture" not in bpy.data.collections:
    coll = bpy.data.collections.new("Sculpture")
    bpy.context.scene.collection.children.link(coll)
else:
    coll = bpy.data.collections["Sculpture"]

# Color palette - vibrant sunset/gem colors
colors = [
    (0.95, 0.2, 0.3, 1),    # Ruby red
    (1.0, 0.5, 0.1, 1),     # Orange
    (1.0, 0.85, 0.2, 1),    # Gold
    (0.2, 0.9, 0.5, 1),     # Emerald
    (0.2, 0.6, 1.0, 1),     # Sapphire
    (0.7, 0.3, 0.9, 1),     # Amethyst
    (0.95, 0.4, 0.7, 1),    # Pink
    (0.3, 0.9, 0.9, 1),     # Cyan
]

# Create materials
materials = []
for i, color in enumerate(colors):
    mat = bpy.data.materials.new(f"Gem_{i}")
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = color
    bsdf.inputs["Metallic"].default_value = 0.3
    bsdf.inputs["Roughness"].default_value = 0.15
    bsdf.inputs["IOR"].default_value = 2.4  # Diamond-like
    materials.append(mat)

# Create spiraling tower of geometric shapes
num_objects = 32
for i in range(num_objects):
    t = i / num_objects
    angle = t * math.pi * 6  # 3 full rotations
    radius = 2 + t * 1.5
    height = t * 8

    # Alternate between shapes
    if i % 4 == 0:
        bpy.ops.mesh.primitive_cube_add(size=0.6)
    elif i % 4 == 1:
        bpy.ops.mesh.primitive_ico_sphere_add(radius=0.35, subdivisions=2)
    elif i % 4 == 2:
        bpy.ops.mesh.primitive_cone_add(radius1=0.4, depth=0.6)
    else:
        bpy.ops.mesh.primitive_torus_add(major_radius=0.3, minor_radius=0.1)

    obj = bpy.context.active_object
    obj.name = f"Gem_{i:02d}"

    # Position in spiral
    obj.location = (
        math.cos(angle) * radius,
        math.sin(angle) * radius,
        height
    )

    # Rotation for dynamic feel
    obj.rotation_euler = (
        t * math.pi * 2,
        math.sin(t * math.pi * 4) * 0.5,
        angle
    )

    # Scale variation
    scale = 0.8 + math.sin(t * math.pi * 3) * 0.3
    obj.scale = (scale, scale, scale)

    # Assign material
    obj.data.materials.append(materials[i % len(materials)])

    # Link to collection
    for c in obj.users_collection:
        c.objects.unlink(obj)
    coll.objects.link(obj)

# Add a central pillar
bpy.ops.mesh.primitive_cylinder_add(radius=0.3, depth=10, location=(0, 0, 4))
pillar = bpy.context.active_object
pillar.name = "CentralPillar"
pillar_mat = bpy.data.materials.new("Pillar_Chrome")
pillar_mat.use_nodes = True
bsdf = pillar_mat.node_tree.nodes.get("Principled BSDF")
bsdf.inputs["Base Color"].default_value = (0.8, 0.8, 0.85, 1)
bsdf.inputs["Metallic"].default_value = 1.0
bsdf.inputs["Roughness"].default_value = 0.05
pillar.data.materials.append(pillar_mat)
for c in pillar.users_collection:
    c.objects.unlink(pillar)
coll.objects.link(pillar)

# Add ground plane with reflective material
bpy.ops.mesh.primitive_plane_add(size=20, location=(0, 0, -0.5))
ground = bpy.context.active_object
ground.name = "Ground"
ground_mat = bpy.data.materials.new("Ground_Mirror")
ground_mat.use_nodes = True
bsdf = ground_mat.node_tree.nodes.get("Principled BSDF")
bsdf.inputs["Base Color"].default_value = (0.02, 0.02, 0.03, 1)
bsdf.inputs["Metallic"].default_value = 0.9
bsdf.inputs["Roughness"].default_value = 0.1
ground.data.materials.append(ground_mat)

# Add camera
bpy.ops.object.camera_add(location=(12, -12, 8))
cam = bpy.context.active_object
cam.name = "SculptureCamera"
cam.rotation_euler = (math.radians(60), 0, math.radians(45))
bpy.context.scene.camera = cam

# Add lighting
bpy.ops.object.light_add(type='AREA', location=(5, -5, 10))
key_light = bpy.context.active_object
key_light.name = "KeyLight"
key_light.data.energy = 500
key_light.data.size = 5
key_light.rotation_euler = (math.radians(45), 0, math.radians(45))

bpy.ops.object.light_add(type='AREA', location=(-5, 5, 8))
fill_light = bpy.context.active_object
fill_light.name = "FillLight"
fill_light.data.energy = 200
fill_light.data.size = 4
fill_light.data.color = (0.8, 0.9, 1.0)

# Add rim light
bpy.ops.object.light_add(type='SPOT', location=(0, 10, 5))
rim_light = bpy.context.active_object
rim_light.name = "RimLight"
rim_light.data.energy = 800
rim_light.rotation_euler = (math.radians(70), 0, math.radians(180))

__result__ = f"Created geometric sculpture with {num_objects} gems!"
'''

    result = client.execute(code)
    print(f"Result: {result.get('result', {}).get('result', 'Done')}")
    return result


def demo_solar_system(client):
    """Create an animated solar system."""
    print("\n=== Demo 2: Animated Solar System ===")

    code = '''
import bpy
import math

# Create solar system collection
if "SolarSystem" not in bpy.data.collections:
    coll = bpy.data.collections.new("SolarSystem")
    bpy.context.scene.collection.children.link(coll)
else:
    coll = bpy.data.collections["SolarSystem"]
    # Clear existing objects in collection
    for obj in list(coll.objects):
        bpy.data.objects.remove(obj, do_unlink=True)

def link_to_collection(obj):
    for c in obj.users_collection:
        c.objects.unlink(obj)
    coll.objects.link(obj)

# Planet data: (name, radius, orbit_radius, color, orbit_speed, has_rings)
planets = [
    ("Sun", 1.5, 0, (1.0, 0.9, 0.3, 1), 0, False),
    ("Mercury", 0.15, 2.5, (0.6, 0.5, 0.5, 1), 4.15, False),
    ("Venus", 0.25, 3.5, (0.9, 0.7, 0.4, 1), 1.62, False),
    ("Earth", 0.28, 4.5, (0.2, 0.4, 0.8, 1), 1.0, False),
    ("Mars", 0.18, 5.8, (0.8, 0.3, 0.2, 1), 0.53, False),
    ("Jupiter", 0.7, 8, (0.8, 0.7, 0.5, 1), 0.084, False),
    ("Saturn", 0.6, 11, (0.9, 0.8, 0.6, 1), 0.034, True),
    ("Uranus", 0.4, 14, (0.6, 0.8, 0.9, 1), 0.012, True),
    ("Neptune", 0.38, 17, (0.3, 0.4, 0.9, 1), 0.006, False),
]

# Frame range
bpy.context.scene.frame_start = 1
bpy.context.scene.frame_end = 250
bpy.context.scene.frame_current = 1

created_objects = []

for name, radius, orbit_radius, color, speed, has_rings in planets:
    # Create planet
    if name == "Sun":
        bpy.ops.mesh.primitive_uv_sphere_add(radius=radius, segments=64, ring_count=32, location=(0, 0, 0))
    else:
        bpy.ops.mesh.primitive_uv_sphere_add(radius=radius, segments=32, ring_count=16, location=(orbit_radius, 0, 0))

    planet = bpy.context.active_object
    planet.name = name
    link_to_collection(planet)
    created_objects.append(name)

    # Create and assign material
    mat = bpy.data.materials.new(f"{name}_Material")
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = color

    if name == "Sun":
        # Emissive sun
        bsdf.inputs["Emission Color"].default_value = color
        bsdf.inputs["Emission Strength"].default_value = 5.0
    else:
        bsdf.inputs["Roughness"].default_value = 0.7

    planet.data.materials.append(mat)

    # Add rings for Saturn and Uranus
    if has_rings:
        bpy.ops.mesh.primitive_torus_add(
            major_radius=radius * 1.8,
            minor_radius=radius * 0.1,
            major_segments=64,
            minor_segments=12,
            location=planet.location
        )
        rings = bpy.context.active_object
        rings.name = f"{name}_Rings"
        rings.scale = (1, 1, 0.05)
        rings.parent = planet
        link_to_collection(rings)

        ring_mat = bpy.data.materials.new(f"{name}_Ring_Material")
        ring_mat.use_nodes = True
        ring_bsdf = ring_mat.node_tree.nodes.get("Principled BSDF")
        ring_bsdf.inputs["Base Color"].default_value = (0.8, 0.7, 0.6, 1)
        ring_bsdf.inputs["Alpha"].default_value = 0.7
        ring_mat.blend_method = 'BLEND'
        rings.data.materials.append(ring_mat)

    # Animate orbiting planets
    if orbit_radius > 0 and speed > 0:
        # Create empty at origin for orbit parent
        bpy.ops.object.empty_add(type='PLAIN_AXES', location=(0, 0, 0))
        orbit_empty = bpy.context.active_object
        orbit_empty.name = f"{name}_Orbit"
        link_to_collection(orbit_empty)

        # Parent planet to orbit empty
        planet.parent = orbit_empty
        planet.location = (orbit_radius, 0, 0)

        # Animate rotation of orbit empty
        orbit_empty.rotation_euler = (0, 0, 0)
        orbit_empty.keyframe_insert(data_path="rotation_euler", frame=1)

        # Full rotation based on orbital period
        orbit_empty.rotation_euler = (0, 0, math.radians(360 * speed))
        orbit_empty.keyframe_insert(data_path="rotation_euler", frame=250)

        # Make animation linear
        if orbit_empty.animation_data and orbit_empty.animation_data.action:
            for fc in orbit_empty.animation_data.action.fcurves:
                for kp in fc.keyframe_points:
                    kp.interpolation = 'LINEAR'

# Add stars background
bpy.ops.mesh.primitive_uv_sphere_add(radius=50, segments=32, ring_count=16, location=(0, 0, 0))
stars = bpy.context.active_object
stars.name = "Stars"
link_to_collection(stars)

# Flip normals inward
bpy.ops.object.mode_set(mode='EDIT')
bpy.ops.mesh.select_all(action='SELECT')
bpy.ops.mesh.flip_normals()
bpy.ops.object.mode_set(mode='OBJECT')

star_mat = bpy.data.materials.new("Stars_Material")
star_mat.use_nodes = True
nodes = star_mat.node_tree.nodes
links = star_mat.node_tree.links
bsdf = nodes.get("Principled BSDF")

# Add noise texture for stars
noise = nodes.new('ShaderNodeTexNoise')
noise.inputs['Scale'].default_value = 200
noise.inputs['Detail'].default_value = 16

color_ramp = nodes.new('ShaderNodeValToRGB')
color_ramp.color_ramp.elements[0].position = 0.6
color_ramp.color_ramp.elements[0].color = (0, 0, 0, 1)
color_ramp.color_ramp.elements[1].position = 0.65
color_ramp.color_ramp.elements[1].color = (1, 1, 1, 1)

links.new(noise.outputs['Fac'], color_ramp.inputs['Fac'])
links.new(color_ramp.outputs['Color'], bsdf.inputs['Emission Color'])
bsdf.inputs['Emission Strength'].default_value = 2.0
bsdf.inputs['Base Color'].default_value = (0, 0, 0, 1)

stars.data.materials.append(star_mat)

# Position camera
bpy.ops.object.camera_add(location=(25, -25, 15))
cam = bpy.context.active_object
cam.name = "SolarCamera"
cam.rotation_euler = (math.radians(65), 0, math.radians(45))
bpy.context.scene.camera = cam

# Add point light at sun
bpy.ops.object.light_add(type='POINT', location=(0, 0, 0))
sun_light = bpy.context.active_object
sun_light.name = "SunLight"
sun_light.data.energy = 5000
sun_light.data.color = (1.0, 0.95, 0.8)
link_to_collection(sun_light)

__result__ = f"Created solar system with {len(created_objects)} celestial bodies and animation!"
'''

    result = client.execute(code)
    print(f"Result: {result.get('result', {}).get('result', 'Done')}")
    return result


def demo_procedural_landscape(client):
    """Create a procedural low-poly landscape."""
    print("\n=== Demo 3: Procedural Low-Poly Landscape ===")

    code = '''
import bpy
import math
import random

# Create landscape collection
if "Landscape" not in bpy.data.collections:
    coll = bpy.data.collections.new("Landscape")
    bpy.context.scene.collection.children.link(coll)
else:
    coll = bpy.data.collections["Landscape"]
    for obj in list(coll.objects):
        bpy.data.objects.remove(obj, do_unlink=True)

def link_to_collection(obj):
    for c in obj.users_collection:
        c.objects.unlink(obj)
    coll.objects.link(obj)

random.seed(42)  # For reproducibility

# Create terrain mesh
bpy.ops.mesh.primitive_grid_add(x_subdivisions=30, y_subdivisions=30, size=20, location=(0, 0, 0))
terrain = bpy.context.active_object
terrain.name = "Terrain"
link_to_collection(terrain)

# Displace vertices for hills
import bmesh
bm = bmesh.new()
bm.from_mesh(terrain.data)

for v in bm.verts:
    # Multiple octaves of noise-like displacement
    x, y = v.co.x, v.co.y
    height = 0
    height += math.sin(x * 0.5) * math.cos(y * 0.5) * 1.5
    height += math.sin(x * 0.8 + 1) * math.cos(y * 0.3) * 0.8
    height += math.sin(x * 1.5 + 2) * math.sin(y * 1.2) * 0.4

    # Add some randomness
    height += random.uniform(-0.1, 0.1)

    # Create a valley in the middle
    dist_from_center = math.sqrt(x*x + y*y)
    if dist_from_center < 3:
        height -= (3 - dist_from_center) * 0.3

    v.co.z = height

bm.to_mesh(terrain.data)
bm.free()
terrain.data.update()

# Create terrain material with vertex colors based on height
terrain_mat = bpy.data.materials.new("TerrainMaterial")
terrain_mat.use_nodes = True
nodes = terrain_mat.node_tree.nodes
links = terrain_mat.node_tree.links

bsdf = nodes.get("Principled BSDF")
bsdf.inputs["Roughness"].default_value = 0.9

# Color ramp based on geometry
geom = nodes.new('ShaderNodeNewGeometry')
sep = nodes.new('ShaderNodeSeparateXYZ')
ramp = nodes.new('ShaderNodeValToRGB')

# Green to brown to white (snow)
ramp.color_ramp.elements[0].position = 0.0
ramp.color_ramp.elements[0].color = (0.15, 0.35, 0.1, 1)  # Dark green
ramp.color_ramp.elements[1].position = 0.5
ramp.color_ramp.elements[1].color = (0.3, 0.5, 0.15, 1)  # Light green
elem = ramp.color_ramp.elements.new(0.75)
elem.color = (0.4, 0.3, 0.2, 1)  # Brown
elem = ramp.color_ramp.elements.new(0.9)
elem.color = (0.95, 0.95, 0.98, 1)  # Snow

# Map position
map_range = nodes.new('ShaderNodeMapRange')
map_range.inputs['From Min'].default_value = -1
map_range.inputs['From Max'].default_value = 3

links.new(geom.outputs['Position'], sep.inputs['Vector'])
links.new(sep.outputs['Z'], map_range.inputs['Value'])
links.new(map_range.outputs['Result'], ramp.inputs['Fac'])
links.new(ramp.outputs['Color'], bsdf.inputs['Base Color'])

terrain.data.materials.append(terrain_mat)

# Add low-poly trees
def create_tree(location, scale=1.0):
    # Trunk
    bpy.ops.mesh.primitive_cylinder_add(radius=0.08*scale, depth=0.5*scale, location=location)
    trunk = bpy.context.active_object
    trunk.location.z += 0.25 * scale
    link_to_collection(trunk)

    trunk_mat = bpy.data.materials.get("TreeTrunk") or bpy.data.materials.new("TreeTrunk")
    trunk_mat.use_nodes = True
    trunk_mat.node_tree.nodes.get("Principled BSDF").inputs["Base Color"].default_value = (0.3, 0.2, 0.1, 1)
    trunk.data.materials.append(trunk_mat)

    # Foliage - stacked cones
    heights = [0.5, 0.85, 1.1]
    radii = [0.4, 0.3, 0.2]

    foliage_mat = bpy.data.materials.get("TreeFoliage") or bpy.data.materials.new("TreeFoliage")
    foliage_mat.use_nodes = True
    foliage_mat.node_tree.nodes.get("Principled BSDF").inputs["Base Color"].default_value = (0.1, 0.4, 0.15, 1)

    for h, r in zip(heights, radii):
        bpy.ops.mesh.primitive_cone_add(
            radius1=r*scale,
            radius2=0,
            depth=0.4*scale,
            location=(location[0], location[1], location[2] + h*scale)
        )
        cone = bpy.context.active_object
        link_to_collection(cone)
        cone.data.materials.append(foliage_mat)
        cone.parent = trunk

    return trunk

# Place trees on terrain
tree_count = 0
for _ in range(50):
    x = random.uniform(-8, 8)
    y = random.uniform(-8, 8)

    # Get height at position (approximate)
    z = math.sin(x * 0.5) * math.cos(y * 0.5) * 1.5
    z += math.sin(x * 0.8 + 1) * math.cos(y * 0.3) * 0.8

    # Only place trees at certain heights (not too low, not too high)
    if 0 < z < 1.5:
        scale = random.uniform(0.7, 1.3)
        create_tree((x, y, z), scale)
        tree_count += 1

# Add water plane
bpy.ops.mesh.primitive_plane_add(size=25, location=(0, 0, -0.3))
water = bpy.context.active_object
water.name = "Water"
link_to_collection(water)

water_mat = bpy.data.materials.new("WaterMaterial")
water_mat.use_nodes = True
water_bsdf = water_mat.node_tree.nodes.get("Principled BSDF")
water_bsdf.inputs["Base Color"].default_value = (0.1, 0.3, 0.5, 1)
water_bsdf.inputs["Metallic"].default_value = 0.0
water_bsdf.inputs["Roughness"].default_value = 0.1
water_bsdf.inputs["IOR"].default_value = 1.33
water_bsdf.inputs["Alpha"].default_value = 0.8
water_mat.blend_method = 'BLEND'
water.data.materials.append(water_mat)

# Add sky/sun
bpy.ops.object.light_add(type='SUN', location=(0, 0, 10))
sun = bpy.context.active_object
sun.name = "Sun"
sun.rotation_euler = (math.radians(45), math.radians(15), math.radians(30))
sun.data.energy = 3
sun.data.color = (1.0, 0.95, 0.85)
link_to_collection(sun)

# Camera setup
bpy.ops.object.camera_add(location=(15, -15, 8))
cam = bpy.context.active_object
cam.name = "LandscapeCamera"
cam.rotation_euler = (math.radians(70), 0, math.radians(45))
bpy.context.scene.camera = cam

# Set world background
world = bpy.context.scene.world
if not world:
    world = bpy.data.worlds.new("World")
    bpy.context.scene.world = world
world.use_nodes = True
bg = world.node_tree.nodes.get("Background")
bg.inputs["Color"].default_value = (0.4, 0.6, 0.9, 1)  # Sky blue
bg.inputs["Strength"].default_value = 0.5

__result__ = f"Created procedural landscape with {tree_count} trees!"
'''

    result = client.execute(code)
    print(f"Result: {result.get('result', {}).get('result', 'Done')}")
    return result


def render_demo(client, name, filepath):
    """Render the current scene."""
    print(f"\nRendering {name}...")

    code = f'''
import bpy

# Configure render settings
bpy.context.scene.render.engine = 'CYCLES'
bpy.context.scene.cycles.samples = 64
bpy.context.scene.cycles.use_denoising = True
bpy.context.scene.render.resolution_x = 1920
bpy.context.scene.render.resolution_y = 1080
bpy.context.scene.render.filepath = "{filepath}"

# Use GPU if available
prefs = bpy.context.preferences.addons.get('cycles')
if prefs:
    prefs.preferences.compute_device_type = 'METAL'  # macOS
    bpy.context.scene.cycles.device = 'GPU'

# Render
bpy.ops.render.render(write_still=True)

__result__ = "Render complete: {filepath}"
'''

    result = client.execute(code)
    print(f"Result: {result.get('result', {}).get('result', 'Done')}")
    return result


if __name__ == "__main__":
    import sys

    print("=" * 60)
    print("Claude Blender Creative Demos")
    print("=" * 60)

    try:
        client = BlenderDemo()

        # Run demos based on argument or all
        demo_arg = sys.argv[1] if len(sys.argv) > 1 else "all"

        if demo_arg in ["1", "sculpture", "all"]:
            demo_geometric_sculpture(client)
            print("\n✓ Geometric sculpture created! Check Blender viewport.")

        if demo_arg in ["2", "solar", "all"]:
            if demo_arg == "all":
                input("\nPress Enter to continue to Solar System demo...")
            demo_solar_system(client)
            print("\n✓ Solar system created! Press Space in Blender to play animation.")

        if demo_arg in ["3", "landscape", "all"]:
            if demo_arg == "all":
                input("\nPress Enter to continue to Landscape demo...")
            demo_procedural_landscape(client)
            print("\n✓ Procedural landscape created!")

        print("\n" + "=" * 60)
        print("All demos complete! Check Blender to see the results.")
        print("=" * 60)

        client.close()

    except ConnectionRefusedError:
        print("ERROR: Could not connect to Blender.")
        print("Make sure the addon is enabled and server is started.")
        sys.exit(1)
