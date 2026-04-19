"""Export Maine camera poses aligned to the normalized PLY viewer space."""

import json
import struct
from pathlib import Path

import numpy as np

SCRIPT_DIR = Path(__file__).resolve().parent
IMAGES_BIN = SCRIPT_DIR / "maine" / "colmap_output" / "sparse" / "0" / "images.bin"
OUTPUT_TRAJECTORY = SCRIPT_DIR / "maine_all_camera_positions.json"
OUTPUT_MODULE = SCRIPT_DIR.parent / "frontend" / "public" / "splat" / "maine-pose-data.js"
PLY_PATH = SCRIPT_DIR.parent / "frontend" / "public" / "maine_output.ply"
SAMPLED_INDICES = [0, 21, 41, 62, 83, 103, 124, 145, 165, 186]
NUM_SAMPLES = len(SAMPLED_INDICES)
ALIGN_ROTATION = np.array([
    [-0.80572852, -0.01028171, 0.59219577],
    [-0.59223764, 0.02663207, -0.80532311],
    [-0.0074913, -0.99959243, -0.02754743],
])
SOURCE_CENTER = np.array([1.6828398388907575, 0.4484998992759764, 1.4257787833081692])
TARGET_CENTER = np.array([-0.1377539561612607, -0.06989357915844244, -0.033940927807751445])
ALIGN_SCALE = 0.273894122822032


def qvec_to_rotmat(qvec):
    """Convert quaternion (qw, qx, qy, qz) to a 3x3 rotation matrix."""
    w, x, y, z = qvec
    return np.array([
        [1 - 2 * y * y - 2 * z * z, 2 * x * y - 2 * z * w, 2 * x * z + 2 * y * w],
        [2 * x * y + 2 * z * w, 1 - 2 * x * x - 2 * z * z, 2 * y * z - 2 * x * w],
        [2 * x * z - 2 * y * w, 2 * y * z + 2 * x * w, 1 - 2 * x * x - 2 * y * y],
    ])


def read_images_bin(path):
    images = []
    with open(path, "rb") as f:
        num_images = struct.unpack("Q", f.read(8))[0]
        for _ in range(num_images):
            image_id = struct.unpack("I", f.read(4))[0]
            qvec = struct.unpack("4d", f.read(32))
            tvec = struct.unpack("3d", f.read(24))
            camera_id = struct.unpack("I", f.read(4))[0]
            name = b""
            while True:
                ch = f.read(1)
                if ch == b"\x00":
                    break
                name += ch
            num_points2d = struct.unpack("Q", f.read(8))[0]
            f.read(num_points2d * 24)
            images.append({
                "id": image_id,
                "name": name.decode(),
                "qvec": qvec,
                "tvec": tvec,
                "camera_id": camera_id,
            })
    return images


def transform_position(position):
    return (ALIGN_SCALE * (ALIGN_ROTATION @ (position - SOURCE_CENTER)) + TARGET_CENTER).tolist()


def transform_rotation(rotation_cw):
    return (ALIGN_ROTATION @ rotation_cw).tolist()


def write_pose_module(cameras, trajectory):
    OUTPUT_MODULE.write_text(
        "export const sampledTrajectoryIndices = "
        + json.dumps(SAMPLED_INDICES)
        + ";\n\nexport const maineCameras = "
        + json.dumps(cameras, indent=4)
        + ";\n\nexport const maineTrajectoryPoints = "
        + json.dumps(trajectory, indent=4)
        + ";\n"
    )


def main():
    images = read_images_bin(IMAGES_BIN)
    images.sort(key=lambda x: x["name"])
    print(f"Loaded {len(images)} images from COLMAP")
    print(f"Using PLY-aligned transform for {PLY_PATH.name}")

    trajectory = []
    transformed_cameras = []

    for img in images:
        rotation_wc = qvec_to_rotmat(img["qvec"])
        translation_wc = np.array(img["tvec"])
        center_world = -rotation_wc.T @ translation_wc
        rotation_cw = rotation_wc.T

        trajectory.append(transform_position(center_world))
        transformed_cameras.append({
            "img_name": img["name"].replace(".png", ""),
            "position": transform_position(center_world),
            "rotation": transform_rotation(rotation_cw),
        })

    cameras = []
    for cam_id, img_idx in enumerate(SAMPLED_INDICES):
        pose = transformed_cameras[img_idx]
        cameras.append({
            "id": cam_id,
            "img_name": pose["img_name"],
            "width": 1280,
            "height": 720,
            "position": pose["position"],
            "rotation": pose["rotation"],
            "fy": 943.2348532572976,
            "fx": 943.2348532572976,
        })

    OUTPUT_TRAJECTORY.write_text(json.dumps([{"position": p} for p in trajectory]))
    write_pose_module(cameras, trajectory)

    print(f"Wrote {NUM_SAMPLES} sampled cameras to {OUTPUT_MODULE.name}")
    print(f"Wrote full trajectory with {len(trajectory)} points to {OUTPUT_TRAJECTORY.name}")


if __name__ == "__main__":
    main()
