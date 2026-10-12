"""Hologram Maker: turns stereo photos (or a photo plus a depth map) into 3D output.

The pipeline is capture -> depth -> 3D data -> display formats:

* a coloured point cloud (PLY) for any 3D viewer, Blender or a game engine,
* novel views rendered from the depth map, packed as a multi-view *quilt*
  for light field displays (Looking Glass),
* a four-sided layout for a Pepper's-ghost pyramid on a phone, tablet or monitor,
* depth slices for a swept-volume (volumetric) display,
* red/cyan anaglyph and side-by-side stereo.

Everything here needs only numpy, so it runs on a Raspberry Pi 5 or a laptop.
"""

__version__ = "0.1.0"
