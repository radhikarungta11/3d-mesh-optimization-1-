#!/usr/bin/env python3

from __future__ import annotations 

import argparse
import json
from pathlib import Path 

from PIL import Image, ImageDraw


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate UV layout debug textures from an OBJ file."
    )
    parser.add_argument(
        "--obj",
        default="input/original.obj",
        help="Path to the OBJ file.",
    )
    parser.add_argument(
        "--texture",
        default="input/texture.png",
        help="Optional texture to overlay UVs onto.",
    )
    parser.add_argument(
        "--output",
        default="output/uv_debug",
        help="Output directory for UV debug images.",
    )
    parser.add_argument(
        "--size",
        type=int,
        default=2048,
        help="Output image size in pixels.",
    )
    return parser.parse_args()


def parse_obj(obj_path: Path) -> tuple[list[tuple[float, float]], list[list[int]]]:
    uvs: list[tuple[float, float]] = []
    faces: list[list[int]] = []

    with obj_path.open("r", encoding="utf-8", errors="ignore") as fh:
        for raw_line in fh:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue

            if line.startswith("vt "):
                parts = line.split()
                if len(parts) >= 3:
                    uvs.append((float(parts[1]), float(parts[2])))
            elif line.startswith("f "):
                face_uvs: list[int] = []
                for part in line.split()[1:]:
                    vals = part.split("/")
                    if len(vals) >= 2 and vals[1]:
                        face_uvs.append(int(vals[1]) - 1)
                if len(face_uvs) >= 3:
                    faces.append(face_uvs)

    return uvs, faces


def uv_to_px(uv: tuple[float, float], size: int) -> tuple[int, int]:
    u, v = uv
    x = int(max(0.0, min(1.0, u)) * (size - 1))
    y = int((1.0 - max(0.0, min(1.0, v))) * (size - 1))
    return x, y


def draw_uv_wireframe(
    image: Image.Image,
    uvs: list[tuple[float, float]],
    faces: list[list[int]],
    color: tuple[int, int, int],
    line_width: int,
) -> None:
    draw = ImageDraw.Draw(image)
    size = image.size[0]

    for face in faces:
        points = [uv_to_px(uvs[index], size) for index in face if 0 <= index < len(uvs)]
        if len(points) < 3:
            continue
        points.append(points[0])
        draw.line(points, fill=color, width=line_width)


def build_checker(size: int, cell_count: int = 16) -> Image.Image:
    img = Image.new("RGB", (size, size), (240, 240, 240))
    draw = ImageDraw.Draw(img)
    cell = max(1, size // cell_count)

    for y in range(0, size, cell):
        for x in range(0, size, cell):
            tile_x = x // cell
            tile_y = y // cell
            color = (230, 230, 230) if (tile_x + tile_y) % 2 == 0 else (70, 70, 70)
            draw.rectangle([x, y, min(x + cell, size), min(y + cell, size)], fill=color)

    return img


def main() -> int:
    args = parse_args()
    obj_path = Path(args.obj).expanduser().resolve()
    texture_path = Path(args.texture).expanduser().resolve()
    output_dir = Path(args.output).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    if not obj_path.exists():
        raise SystemExit(f"OBJ file not found: {obj_path}")

    uvs, faces = parse_obj(obj_path)
    if not uvs:
        raise SystemExit("No UV coordinates found in the OBJ.")
    if not faces:
        raise SystemExit("No faces found in the OBJ.")

    blank_layout = Image.new("RGB", (args.size, args.size), (255, 255, 255))
    draw_uv_wireframe(blank_layout, uvs, faces, color=(0, 0, 0), line_width=1)

    checker = build_checker(args.size)
    draw_uv_wireframe(checker, uvs, faces, color=(255, 64, 64), line_width=1)

    blank_path = output_dir / "uv_layout.png"
    checker_path = output_dir / "uv_checker.png"
    overlay_path = output_dir / "uv_on_texture.png"
    report_path = output_dir / "uv_report.json"

    blank_layout.save(blank_path)
    checker.save(checker_path)

    overlay_created = False
    if texture_path.exists():
        texture = Image.open(texture_path).convert("RGB").resize((args.size, args.size))
        draw_uv_wireframe(texture, uvs, faces, color=(0, 255, 255), line_width=1)
        texture.save(overlay_path)
        overlay_created = True

    u_values = [u for u, _ in uvs]
    v_values = [v for _, v in uvs]
    report = {
        "source_obj": str(obj_path),
        "source_texture": str(texture_path) if texture_path.exists() else None,
        "uv_count": len(uvs),
        "face_count": len(faces),
        "u_range": [min(u_values), max(u_values)],
        "v_range": [min(v_values), max(v_values)],
        "outputs": {
            "uv_layout": str(blank_path),
            "uv_checker": str(checker_path),
            "uv_on_texture": str(overlay_path) if overlay_created else None,
        },
    }
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"Generated UV debug assets in: {output_dir}")
    print(f"UV layout: {blank_path.name}")
    print(f"Checker: {checker_path.name}")
    if overlay_created:
        print(f"Texture overlay: {overlay_path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
