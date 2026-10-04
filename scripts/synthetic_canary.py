"""Small deterministic GPU pipeline check; synthetic plane, known camera poses.

Not an SfM accuracy test. Dense output must agree with the generated plane.
No external datasets, credentials or downloads are needed.
"""

import argparse
import json
import math
from pathlib import Path
import random
import sqlite3
import statistics
import struct
import subprocess
import sys
import time
import zlib

WIDTH, HEIGHT, FOCAL, DEPTH = 320, 240, 260.0, 4.0
CAMERAS = (-0.24, -0.12, 0.0, 0.12, 0.24)


def project(x, y, camera_x):
    return FOCAL * (x - camera_x) / DEPTH + WIDTH / 2, FOCAL * y / DEPTH + HEIGHT / 2


def png(path, rows):
    def chunk(name, data):
        return (
            struct.pack("!I", len(data))
            + name
            + data
            + struct.pack("!I", zlib.crc32(name + data) & 0xFFFFFFFF)
        )

    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack("!2I5B", WIDTH, HEIGHT, 8, 0, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"".join(b"\0" + row for row in rows)))
        + chunk(b"IEND", b"")
    )


def generate_fixture(root):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=False)
    (root / "images").mkdir()
    (root / "sparse").mkdir()
    rng = random.Random(91827)
    texture = [[rng.randrange(16, 240) for _ in range(129)] for _ in range(129)]
    points = [
        (x / 10, y / 10, DEPTH) for y in range(-12, 13, 2) for x in range(-17, 18, 2)
    ]
    image_lines = []
    for image_id, camera_x in enumerate(CAMERAS, 1):
        name = f"view-{image_id}.png"
        rows = []
        for v in range(HEIGHT):
            row = []
            for u in range(WIDTH):
                gx = ((u - WIDTH / 2) * DEPTH / FOCAL + camera_x + 4) * 16
                gy = ((v - HEIGHT / 2) * DEPTH / FOCAL + 4) * 16
                ix, iy = math.floor(gx), math.floor(gy)
                dx, dy = gx - ix, gy - iy
                value = (texture[iy][ix] * (1 - dx) + texture[iy][ix + 1] * dx) * (
                    1 - dy
                ) + (texture[iy + 1][ix] * (1 - dx) + texture[iy + 1][ix + 1] * dx) * dy
                row.append(round(value))
            rows.append(bytes(row))
        png(root / "images" / name, rows)
        image_lines.append(f"{image_id} 1 0 0 0 {-camera_x} 0 0 1 {name}")
        image_lines.append(
            " ".join(
                f"{project(x, y, camera_x)[0]:.8f} {project(x, y, camera_x)[1]:.8f} {i}"
                for i, (x, y, z) in enumerate(points, 1)
            )
        )
    (root / "sparse/cameras.txt").write_text(
        f"1 PINHOLE {WIDTH} {HEIGHT} {FOCAL} {FOCAL} {WIDTH / 2} {HEIGHT / 2}\n"
    )
    (root / "sparse/images.txt").write_text("\n".join(image_lines) + "\n")
    (root / "sparse/points3D.txt").write_text(
        "".join(
            f"{i} {x} {y} {z} 128 128 128 0 "
            + " ".join(f"{j} {i - 1}" for j in range(1, 6))
            + "\n"
            for i, (x, y, z) in enumerate(points, 1)
        )
    )
    return {
        "views": len(CAMERAS),
        "width": WIDTH,
        "height": HEIGHT,
        "plane_depth": DEPTH,
        "known_sparse_points": len(points),
    }


def validate_points(points):
    points = list(points)
    if len(points) < 100 or any(
        not all(math.isfinite(float(c)) for c in p) for p in points
    ):
        raise ValueError("Insufficient or nonfinite fused geometry")
    errors = sorted(abs(float(p[2]) - DEPTH) for p in points)
    median = statistics.median(errors)
    p95 = errors[min(len(errors) - 1, int(len(errors) * 0.95))]
    if median > 0.15 or p95 > 0.30:
        raise ValueError("Fused geometry differs from the synthetic plane")
    return {"points": len(points), "median_depth_error": median, "p95_depth_error": p95}


def fuse_points(native, output_path, workspace_path, options):
    # The binding defaults to a binary reconstruction DIRECTORY, unlike the CLI.
    return native.stereo_fusion(
        output_path,
        workspace_path,
        input_type="geometric",
        options=options,
        output_type="ply",
    )


def worker(output, cpu_only=False):
    import pycolmap as pc

    if not pc.has_cuda:
        raise RuntimeError("CUDA-enabled PyCOLMAP required")
    started = time.monotonic()
    output = Path(output)
    fixture = generate_fixture(output / "fixture")
    db = output / "features.db"
    gpu = "0"
    device = pc.Device.cpu if cpu_only else pc.Device.cuda
    pc.extract_features(
        db,
        output / "fixture/images",
        camera_mode=pc.CameraMode.SINGLE,
        extraction_options={
            "gpu_index": gpu,
            "use_gpu": not cpu_only,
            "max_image_size": WIDTH,
            "num_threads": 4,
            "sift": {"max_num_features": 2048},
        },
        device=device,
    )
    pc.match_exhaustive(
        db,
        matching_options={"gpu_index": gpu, "use_gpu": not cpu_only, "num_threads": 4},
        device=device,
    )
    with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as connection:
        features = connection.execute(
            "SELECT COALESCE(SUM(rows),0) FROM keypoints"
        ).fetchone()[0]
        matches = connection.execute(
            "SELECT COALESCE(SUM(rows),0) FROM matches"
        ).fetchone()[0]
    if features < 100 or matches < 50:
        raise ValueError("Synthetic GPU feature/matching output too small")
    dense = output / "dense"
    pc.undistort_images(
        dense,
        output / "fixture/sparse",
        output / "fixture/images",
        num_patch_match_src_images=4,
        num_threads=4,
    )
    options = {
        "gpu_index": gpu,
        "max_image_size": WIDTH,
        "num_threads": 4,
        "num_iterations": 3,
        "depth_min": 3.5,
        "depth_max": 4.5,
        "geom_consistency": True,
        "cache_size": 0.5,
    }
    fusion_options = {"min_num_pixels": 2, "num_threads": 4, "cache_size": 0.5}
    if (
        not pc.PatchMatchOptions(options).check()
        or not pc.StereoFusionOptions(fusion_options).check()
    ):
        raise ValueError("Native dense options rejected")
    if cpu_only:
        report = {
            "api_preflight_passed": True,
            "gpu_execution_validated": False,
            "features": features,
            "matches": matches,
            "pycolmap_version": pc.__version__,
        }
        (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report), flush=True)
        return
    pc.patch_match_stereo(dense, options=options)
    fused = output / "fused.ply"
    cloud = fuse_points(pc, fused, dense, fusion_options)
    quality = validate_points(p.xyz for p in cloud.points3D.values())
    if not fused.is_file() or fused.stat().st_size < 1000:
        raise ValueError("Fused output missing or truncated")
    report = {
        "accepted": True,
        "gpu_execution_validated": True,
        "scope": "synthetic single-GPU pipeline only; known camera poses, no SfM accuracy claim",
        "fixture": fixture,
        "gpu_index": gpu,
        "features": features,
        "matches": matches,
        "quality": quality,
        "elapsed_seconds": time.monotonic() - started,
        "pycolmap_version": pc.__version__,
        "patch_match_options": options,
    }
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument(
        "--check-api",
        action="store_true",
        help="CPU feature/matching/undistortion and dense-options check only",
    )
    args = parser.parse_args()
    if args.worker:
        worker(args.output, cpu_only=args.check_api)
    else:
        # Bound the native extension process externally; Python alarms cannot
        # reliably interrupt a long C++ call. Allocation deadline is separate.
        command = [sys.executable, __file__, "--worker", "--output", str(args.output)]
        if args.check_api:
            command.append("--check-api")
        subprocess.run(command, check=True, timeout=300)


if __name__ == "__main__":
    main()
