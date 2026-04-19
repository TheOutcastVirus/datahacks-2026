"""Parse COLMAP images.bin and output normalized camera poses for main.js."""
import json
import struct
from pathlib import Path

import numpy as np

SCRIPT_DIR = Path(__file__).resolve().parent
IMAGES_BIN = SCRIPT_DIR / "maine" / "colmap_output" / "sparse" / "0" / "images.bin"
OUTPUT_TRAJECTORY = SCRIPT_DIR / "maine_all_camera_positions.json"
NUM_CAMERAS = 10  # cameras to sample for main.js
WORLD_TO_VIEWER = np.array([
    [-1.0, 0.0, 0.0],
    [0.0, 0.0, -1.0],
    [0.0, -1.0, 0.0],
])


def qvec_to_rotmat(qvec):
    """Convert quaternion (qw, qx, qy, qz) to 3x3 rotation matrix."""
    w, x, y, z = qvec
    return np.array([
        [1 - 2*y*y - 2*z*z,     2*x*y - 2*z*w,       2*x*z + 2*y*w],
        [2*x*y + 2*z*w,         1 - 2*x*x - 2*z*z,   2*y*z - 2*x*w],
        [2*x*z - 2*y*w,         2*y*z + 2*x*w,       1 - 2*x*x - 2*y*y],
    ])


def read_images_bin(path):
    images = []
    with open(path, "rb") as f:
        num_images = struct.unpack("Q", f.read(8))[0]
        for _ in range(num_images):
            image_id = struct.unpack("I", f.read(4))[0]
            qvec = struct.unpack("4d", f.read(32))   # qw qx qy qz
            tvec = struct.unpack("3d", f.read(24))   # tx ty tz
            camera_id = struct.unpack("I", f.read(4))[0]
            # read null-terminated name
            name = b""
            while True:
                ch = f.read(1)
                if ch == b"\x00":
                    break
                name += ch
            num_points2d = struct.unpack("Q", f.read(8))[0]
            f.read(num_points2d * 24)  # skip 2D points (x, y, point3d_id)
            images.append({
                "id": image_id,
                "name": name.decode(),
                "qvec": qvec,
                "tvec": tvec,
                "camera_id": camera_id,
            })
    return images


def main():
    images = read_images_bin(IMAGES_BIN)
    images.sort(key=lambda x: x["name"])
    print(f"Loaded {len(images)} images from COLMAP")

    # Convert to viewer-space positions and camera-to-world rotation matrices.
    # COLMAP: R_wc (world-to-cam), t_wc; camera center = -R_wc^T @ t_wc
    positions = []
    rotmats = []  # camera-to-world rotation (what main.js expects)
    for img in images:
        R_wc = qvec_to_rotmat(img["qvec"])
        t_wc = np.array(img["tvec"])
        cam_center = -R_wc.T @ t_wc
        positions.append(WORLD_TO_VIEWER @ cam_center)
        rotmats.append(WORLD_TO_VIEWER @ R_wc.T)

    positions = np.array(positions)  # (N, 3)

    # Apply gsplat normalize_world_space normalization:
    # center by mean, scale by max distance from center
    scene_center = positions.mean(axis=0)
    centered = positions - scene_center
    scene_scale = np.linalg.norm(centered, axis=1).max()
    positions_norm = centered / scene_scale

    print(f"Scene center: {scene_center.tolist()}")
    print(f"Scene scale:  {scene_scale:.4f}")
    print(f"Normalized position range:")
    print(f"  X: [{positions_norm[:,0].min():.3f}, {positions_norm[:,0].max():.3f}]")
    print(f"  Y: [{positions_norm[:,1].min():.3f}, {positions_norm[:,1].max():.3f}]")
    print(f"  Z: [{positions_norm[:,2].min():.3f}, {positions_norm[:,2].max():.3f}]")

    # Sample NUM_CAMERAS evenly spaced
    N = len(images)
    indices = [int(round(i * (N - 1) / (NUM_CAMERAS - 1))) for i in range(NUM_CAMERAS)]
    print(f"\nSampled indices: {indices}")
    print(f"Sampled frames:  {[images[i]['name'] for i in indices]}")

    # Build camera entries in main.js format
    cameras = []
    for cam_idx, img_idx in enumerate(indices):
        img = images[img_idx]
        pos = positions_norm[img_idx].tolist()
        R_cw = rotmats[img_idx]
        cameras.append({
            "id": cam_idx,
            "img_name": img["name"].replace(".png", ""),
            "width": 1280,
            "height": 720,
            "position": pos,
            "rotation": R_cw.tolist(),
            "fy": 943.2348532572976,
            "fx": 943.2348532572976,
        })

    print("\n// cameras array for main.js:")
    print("let cameras = " + json.dumps(cameras, indent=4) + ";")

    # Also dump all positions for corridor constraint (optional wider set)
    all_norm = [{"position": positions_norm[i].tolist()} for i in range(N)]
    with OUTPUT_TRAJECTORY.open("w") as f:
        json.dump(all_norm, f)
    print(f"\nAll {N} normalized positions written to {OUTPUT_TRAJECTORY.name}")


if __name__ == "__main__":
    main()
