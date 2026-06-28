#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path


SUPPORTED_TEXTURE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a textured OBJ bundle from an OBJ mesh and a texture image."
    )
    parser.add_argument(
        "--obj",
        default="input/original.obj",
        help="Path to the source OBJ file.",
    )
    parser.add_argument(
        "--texture",
        default=None,
        help="Path to the texture image. If omitted, the script auto-detects one in input/.",
    )
    parser.add_argument(
        "--output",
        default="output",
        help="Output directory for the textured bundle.",
    )
    return parser.parse_args()


def find_texture(input_dir: Path) -> Path | None:
    for candidate in sorted(input_dir.iterdir()):
        if candidate.is_file() and candidate.suffix.lower() in SUPPORTED_TEXTURE_EXTS:
            return candidate
    return None


def analyze_obj(obj_path: Path) -> dict[str, int]:
    stats = {
        "vertices": 0,
        "uvs": 0,
        "normals": 0,
        "faces": 0,
        "mtllib": 0,
        "usemtl": 0,
    }

    with obj_path.open("r", encoding="utf-8", errors="ignore") as fh:
        for raw_line in fh:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("v "):
                stats["vertices"] += 1
            elif line.startswith("vt "):
                stats["uvs"] += 1
            elif line.startswith("vn "):
                stats["normals"] += 1
            elif line.startswith("f "):
                stats["faces"] += 1
            elif line.startswith("mtllib "):
                stats["mtllib"] += 1
            elif line.startswith("usemtl "):
                stats["usemtl"] += 1

    return stats


def strip_existing_material_refs(obj_text: str) -> str:
    kept_lines = []
    for line in obj_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("mtllib ") or stripped.startswith("usemtl "):
            continue
        kept_lines.append(line)
    return "\n".join(kept_lines).rstrip() + "\n"


def build_mtl(texture_filename: str, material_name: str) -> str:
    return (
        f"newmtl {material_name}\n"
        "Ka 1.000000 1.000000 1.000000\n"
        "Kd 1.000000 1.000000 1.000000\n"
        "Ks 0.000000 0.000000 0.000000\n"
        "d 1.0\n"
        "illum 2\n"
        f"map_Kd textures/{texture_filename}\n"
    )


def build_obj_with_material(clean_obj_text: str, mtl_filename: str, material_name: str) -> str:
    return f"mtllib {mtl_filename}\nusemtl {material_name}\n{clean_obj_text}"


def main() -> int:
    args = parse_args()

    obj_path = Path(args.obj).expanduser().resolve()
    output_dir = Path(args.output).expanduser().resolve()
    texture_path = Path(args.texture).expanduser().resolve() if args.texture else None

    if not obj_path.exists():
        raise SystemExit(f"OBJ file not found: {obj_path}")

    if texture_path is None:
        detected = find_texture(obj_path.parent)
        if detected is None:
            raise SystemExit(
                "No texture provided and none found in the input folder. "
                "Add a texture image or pass --texture."
            )
        texture_path = detected.resolve()

    if not texture_path.exists():
        raise SystemExit(f"Texture file not found: {texture_path}")

    if texture_path.suffix.lower() not in SUPPORTED_TEXTURE_EXTS:
        raise SystemExit(
            f"Unsupported texture format: {texture_path.suffix}. "
            f"Use one of: {', '.join(sorted(SUPPORTED_TEXTURE_EXTS))}"
        )

    stats = analyze_obj(obj_path)
    if stats["vertices"] == 0 or stats["faces"] == 0:
        raise SystemExit("The OBJ does not appear to contain a valid mesh.")

    output_dir.mkdir(parents=True, exist_ok=True)
    textures_dir = output_dir / "textures"
    textures_dir.mkdir(parents=True, exist_ok=True)

    material_name = "textured_material"
    output_obj = output_dir / "textured_model.obj"
    output_mtl = output_dir / "textured_model.mtl"
    output_texture = textures_dir / texture_path.name
    manifest_path = output_dir / "manifest.json"

    shutil.copy2(texture_path, output_texture)

    original_obj_text = obj_path.read_text(encoding="utf-8", errors="ignore")
    clean_obj_text = strip_existing_material_refs(original_obj_text)
    output_obj.write_text(
        build_obj_with_material(clean_obj_text, output_mtl.name, material_name),
        encoding="utf-8",
    )
    output_mtl.write_text(
        build_mtl(output_texture.name, material_name),
        encoding="utf-8",
    )

    manifest = {
        "source_obj": str(obj_path),
        "source_texture": str(texture_path),
        "output_obj": str(output_obj),
        "output_mtl": str(output_mtl),
        "output_texture": str(output_texture),
        "mesh_stats": stats,
        "warnings": [],
    }

    if stats["uvs"] == 0:
        manifest["warnings"].append(
            "OBJ has no UV coordinates (vt entries). Texture linkage was created, "
            "but mapping will not display correctly until UVs are added."
        )

    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print(f"Created textured mesh bundle in: {output_dir}")
    print(f"OBJ: {output_obj.name}")
    print(f"MTL: {output_mtl.name}")
    print(f"Texture: textures/{output_texture.name}")
    print(
        "UV status: "
        + ("OK" if stats["uvs"] > 0 else "Missing UVs - texture may not map correctly")
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
