#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image
import trimesh
import xatlas


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a fresh UV unwrap and rebake an existing texture onto it."
    )
    parser.add_argument("--obj", default="input/original.obj", help="Source OBJ path.")
    parser.add_argument(
        "--texture",
        default="input/texture.png",
        help="Source texture path that matches the current UV layout.",
    )
    parser.add_argument(
        "--output",
        default="output/rewrapped",
        help="Directory for the rewrapped OBJ bundle.",
    )
    parser.add_argument(
        "--size",
        type=int,
        default=2048,
        help="Resolution of the rebaked texture atlas.",
    )
    parser.add_argument(
        "--padding",
        type=int,
        default=4,
        help="Seam padding iterations after baking.",
    )
    return parser.parse_args()


def bilinear_sample(image: np.ndarray, uv: np.ndarray) -> np.ndarray:
    h, w, _ = image.shape
    uv = np.clip(uv, 0.0, 1.0)

    x = uv[:, 0] * (w - 1)
    y = (1.0 - uv[:, 1]) * (h - 1)

    x0 = np.floor(x).astype(np.int32)
    y0 = np.floor(y).astype(np.int32)
    x1 = np.clip(x0 + 1, 0, w - 1)
    y1 = np.clip(y0 + 1, 0, h - 1)

    wx = (x - x0)[:, None]
    wy = (y - y0)[:, None]

    c00 = image[y0, x0]
    c10 = image[y0, x1]
    c01 = image[y1, x0]
    c11 = image[y1, x1]

    c0 = c00 * (1.0 - wx) + c10 * wx
    c1 = c01 * (1.0 - wx) + c11 * wx
    return c0 * (1.0 - wy) + c1 * wy


def barycentric_coords(
    p: np.ndarray, a: np.ndarray, b: np.ndarray, c: np.ndarray
) -> np.ndarray | None:
    v0 = b - a
    v1 = c - a
    v2 = p - a
    den = v0[0] * v1[1] - v1[0] * v0[1]
    if abs(den) < 1e-12:
        return None

    inv = 1.0 / den
    w1 = (v2[..., 0] * v1[1] - v1[0] * v2[..., 1]) * inv
    w2 = (v0[0] * v2[..., 1] - v2[..., 0] * v0[1]) * inv
    w0 = 1.0 - w1 - w2
    return np.stack([w0, w1, w2], axis=-1)


def uv_to_pixels(uvs: np.ndarray, size: int) -> np.ndarray:
    out = np.empty_like(uvs, dtype=np.float64)
    out[:, 0] = uvs[:, 0] * (size - 1)
    out[:, 1] = (1.0 - uvs[:, 1]) * (size - 1)
    return out


def dilate_colors(color: np.ndarray, mask: np.ndarray, iterations: int) -> tuple[np.ndarray, np.ndarray]:
    filled = color.copy()
    valid = mask.copy()

    for _ in range(max(0, iterations)):
        changed = False
        new_filled = filled.copy()
        new_valid = valid.copy()

        for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            shifted_valid = np.zeros_like(valid)
            shifted_color = np.zeros_like(filled)

            if dy == -1:
                shifted_valid[:-1, :] = valid[1:, :]
                shifted_color[:-1, :, :] = filled[1:, :, :]
            elif dy == 1:
                shifted_valid[1:, :] = valid[:-1, :]
                shifted_color[1:, :, :] = filled[:-1, :, :]
            elif dx == -1:
                shifted_valid[:, :-1] = valid[:, 1:]
                shifted_color[:, :-1, :] = filled[:, 1:, :]
            elif dx == 1:
                shifted_valid[:, 1:] = valid[:, :-1]
                shifted_color[:, 1:, :] = filled[:, :-1, :]

            adopt = (~new_valid) & shifted_valid
            if np.any(adopt):
                new_filled[adopt] = shifted_color[adopt]
                new_valid[adopt] = True
                changed = True

        filled = new_filled
        valid = new_valid
        if not changed:
            break

    return filled, valid


def write_obj(
    path: Path,
    mtl_name: str,
    material_name: str,
    vertices: np.ndarray,
    normals: np.ndarray,
    uvs: np.ndarray,
    faces: np.ndarray,
) -> None:
    with path.open("w", encoding="utf-8") as fh:
        fh.write(f"mtllib {mtl_name}\n")
        fh.write("o RewrappedMesh\n")
        fh.write(f"usemtl {material_name}\n")

        for v in vertices:
            fh.write(f"v {v[0]} {v[1]} {v[2]}\n")
        for vt in uvs:
            fh.write(f"vt {vt[0]} {vt[1]}\n")
        for vn in normals:
            fh.write(f"vn {vn[0]} {vn[1]} {vn[2]}\n")

        for face in faces + 1:
            fh.write(
                f"f {face[0]}/{face[0]}/{face[0]} "
                f"{face[1]}/{face[1]}/{face[1]} "
                f"{face[2]}/{face[2]}/{face[2]}\n"
            )


def write_mtl(path: Path, material_name: str, texture_name: str) -> None:
    path.write_text(
        "\n".join(
            [
                f"newmtl {material_name}",
                "Ka 1.000000 1.000000 1.000000",
                "Kd 1.000000 1.000000 1.000000",
                "Ks 0.000000 0.000000 0.000000",
                "d 1.0",
                "illum 2",
                f"map_Kd textures/{texture_name}",
                "",
            ]
        ),
        encoding="utf-8",
    )


def main() -> int:
    args = parse_args()

    obj_path = Path(args.obj).expanduser().resolve()
    texture_path = Path(args.texture).expanduser().resolve()
    output_dir = Path(args.output).expanduser().resolve()
    textures_dir = output_dir / "textures"
    debug_dir = output_dir / "debug"
    textures_dir.mkdir(parents=True, exist_ok=True)
    debug_dir.mkdir(parents=True, exist_ok=True)

    if not obj_path.exists():
        raise SystemExit(f"OBJ file not found: {obj_path}")
    if not texture_path.exists():
        raise SystemExit(f"Texture file not found: {texture_path}")

    mesh = trimesh.load(obj_path, process=False, maintain_order=True)
    if not isinstance(mesh, trimesh.Trimesh):
        raise SystemExit("Expected a single mesh OBJ.")
    if mesh.visual.uv is None:
        raise SystemExit("Source OBJ does not contain UVs to rebake from.")

    vertices = np.asarray(mesh.vertices, dtype=np.float32)
    faces = np.asarray(mesh.faces, dtype=np.int32)
    old_uvs = np.asarray(mesh.visual.uv, dtype=np.float32)
    old_face_uvs = old_uvs[faces]

    old_normals = np.asarray(mesh.vertex_normals, dtype=np.float32)
    if len(old_normals) != len(vertices):
        old_normals = np.zeros_like(vertices, dtype=np.float32)
        old_normals[:, 2] = 1.0

    vmapping, new_faces, new_uvs = xatlas.parametrize(vertices, faces)
    new_vertices = vertices[vmapping]
    new_normals = old_normals[vmapping]
    new_face_uvs = new_uvs[new_faces]

    source_image = Image.open(texture_path).convert("RGBA")
    source_np = np.asarray(source_image, dtype=np.float32)

    target_color = np.zeros((args.size, args.size, 4), dtype=np.float32)
    target_mask = np.zeros((args.size, args.size), dtype=bool)

    for face_index in range(len(faces)):
        dst_uv = new_face_uvs[face_index]
        src_uv = old_face_uvs[face_index]
        tri_px = uv_to_pixels(dst_uv, args.size)

        min_x = max(0, int(np.floor(np.min(tri_px[:, 0]) - 1)))
        max_x = min(args.size - 1, int(np.ceil(np.max(tri_px[:, 0]) + 1)))
        min_y = max(0, int(np.floor(np.min(tri_px[:, 1]) - 1)))
        max_y = min(args.size - 1, int(np.ceil(np.max(tri_px[:, 1]) + 1)))
        if min_x > max_x or min_y > max_y:
            continue

        xs, ys = np.meshgrid(
            np.arange(min_x, max_x + 1, dtype=np.float64),
            np.arange(min_y, max_y + 1, dtype=np.float64),
        )
        points = np.stack([xs + 0.5, ys + 0.5], axis=-1)
        bary = barycentric_coords(points, tri_px[0], tri_px[1], tri_px[2])
        if bary is None:
            continue

        inside = np.all(bary >= -1e-6, axis=-1)
        if not np.any(inside):
            continue

        sampled_uv = (
            bary[..., 0:1] * src_uv[0]
            + bary[..., 1:2] * src_uv[1]
            + bary[..., 2:3] * src_uv[2]
        )
        sampled_pixels = bilinear_sample(source_np, sampled_uv.reshape(-1, 2)).reshape(
            sampled_uv.shape[0], sampled_uv.shape[1], 4
        )

        region = target_color[min_y : max_y + 1, min_x : max_x + 1]
        region_mask = target_mask[min_y : max_y + 1, min_x : max_x + 1]
        write_mask = inside & (~region_mask)
        region[write_mask] = sampled_pixels[write_mask]
        region_mask[write_mask] = True

    dilated_color, dilated_mask = dilate_colors(target_color, target_mask, args.padding)
    alpha = np.where(dilated_mask, 255, 0).astype(np.uint8)
    baked_rgba = np.clip(dilated_color, 0, 255).astype(np.uint8)
    baked_rgba[..., 3] = np.maximum(baked_rgba[..., 3], alpha)

    baked_texture_path = textures_dir / "rebaked_texture.png"
    Image.fromarray(baked_rgba, mode="RGBA").save(baked_texture_path)

    uv_debug = np.full((args.size, args.size, 3), 255, dtype=np.uint8)
    for face_uv in new_face_uvs:
        tri = uv_to_pixels(face_uv, args.size)
        min_x = max(0, int(np.floor(np.min(tri[:, 0]))))
        max_x = min(args.size - 1, int(np.ceil(np.max(tri[:, 0]))))
        min_y = max(0, int(np.floor(np.min(tri[:, 1]))))
        max_y = min(args.size - 1, int(np.ceil(np.max(tri[:, 1]))))
        for start, end in ((0, 1), (1, 2), (2, 0)):
            p0 = tri[start]
            p1 = tri[end]
            steps = max(1, int(np.linalg.norm(p1 - p0)) * 2)
            pts = np.linspace(p0, p1, steps)
            xi = np.clip(np.round(pts[:, 0]).astype(int), 0, args.size - 1)
            yi = np.clip(np.round(pts[:, 1]).astype(int), 0, args.size - 1)
            uv_debug[yi, xi] = np.array([0, 0, 0], dtype=np.uint8)
    uv_debug_path = debug_dir / "new_uv_layout.png"
    Image.fromarray(uv_debug, mode="RGB").save(uv_debug_path)

    material_name = "rebaked_material"
    obj_out = output_dir / "rewrapped_model.obj"
    mtl_out = output_dir / "rewrapped_model.mtl"
    write_obj(obj_out, mtl_out.name, material_name, new_vertices, new_normals, new_uvs, new_faces)
    write_mtl(mtl_out, material_name, baked_texture_path.name)

    report = {
        "source_obj": str(obj_path),
        "source_texture": str(texture_path),
        "output_obj": str(obj_out),
        "output_mtl": str(mtl_out),
        "output_texture": str(baked_texture_path),
        "output_uv_layout": str(uv_debug_path),
        "source_vertices": int(len(vertices)),
        "source_faces": int(len(faces)),
        "output_vertices": int(len(new_vertices)),
        "output_faces": int(len(new_faces)),
        "texture_size": args.size,
        "padding": args.padding,
    }
    (output_dir / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"Created rewrapped mesh bundle in: {output_dir}")
    print(f"OBJ: {obj_out.name}")
    print(f"MTL: {mtl_out.name}")
    print(f"Texture: textures/{baked_texture_path.name}")
    print(f"UV layout: debug/{uv_debug_path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
