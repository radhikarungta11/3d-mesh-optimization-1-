# Textured Mesh Pipeline

This project builds a textured 3D mesh bundle from:

- `input/original.obj`
- `input/texture.png` (or `.jpg`, `.jpeg`, `.webp`)

The pipeline creates:

- `output/textured_model.obj`
- `output/textured_model.mtl`
- `output/textures/<your-texture-file>`
- `output/manifest.json`

## What This Pipeline Does

It takes your existing OBJ mesh and attaches a material that points to your texture image.

This works best when your OBJ already contains UV coordinates (`vt` lines). If the OBJ has no UVs, the texture file can still be linked, but it will not map correctly on the surface until UVs are created in Blender, Maya, MeshLab, or a similar tool.

## Quick Start

1. Create an `input/` folder in this project.
2. Put your files there:

   - `input/original.obj`
   - `input/texture.png`

3. Run:

```bash
python3 scripts/build_textured_mesh.py
```

To inspect whether the OBJ's UVs match your texture, generate UV debug images:

```bash
python3 scripts/generate_uv_layout.py
```

This creates:

- `output/uv_debug/uv_layout.png`
- `output/uv_debug/uv_checker.png`
- `output/uv_debug/uv_on_texture.png`

If `uv_on_texture.png` looks misaligned, the problem is usually that the texture image does not belong to this exact UV layout, not that the PNG file itself is corrupted.

## Reunwrap And Rebake

To generate a fresh UV unwrap and rebake the current texture onto the new layout:

```bash
python3 scripts/reunwrap_and_rebake.py
```

This creates:

- `output/rewrapped/rewrapped_model.obj`
- `output/rewrapped/rewrapped_model.mtl`
- `output/rewrapped/textures/rebaked_texture.png`
- `output/rewrapped/debug/new_uv_layout.png`

This is the right workflow when the mesh UVs are valid but the current wrapping still looks wrong and you want a cleaner atlas layout.

## Options

```bash
python3 scripts/build_textured_mesh.py \
  --obj input/original.obj \
  --texture input/texture.png \
  --output output
```

## What To Check In Your OBJ

Open `input/original.obj` in a text editor and look for:

- `v ...` for vertices
- `f ...` for faces
- `vt ...` for UVs

If there are no `vt` entries, the script will warn you.

## Next Step If You Want Better Results

If your model has no UVs or you want a game-ready format like GLB/FBX, I can extend this into:

- automatic Blender-based UV unwrap + export
- mesh cleanup / decimation
- GLB export for web or AR
- batch processing for many OBJ files
