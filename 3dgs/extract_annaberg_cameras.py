"""Export Annaberg camera poses aligned to the normalized PLY viewer space."""

import json
import struct
from pathlib import Path

import numpy as np

SCRIPT_DIR = Path(__file__).resolve().parent
IMAGES_BIN = SCRIPT_DIR / "annaberg" / "colmap_sparse_0" / "images.bin"
OUTPUT_TRAJECTORY = SCRIPT_DIR / "annaberg_all_camera_positions.json"
OUTPUT_MODULE = SCRIPT_DIR.parent / "frontend" / "public" / "splat" / "annaberg-pose-data.js"
SAMPLED_INDICES = [0, 10, 20, 30, 40, 50, 60, 70, 80, 90]
NUM_SAMPLES = len(SAMPLED_INDICES)

# gsplat normalize_world_space=True: (pos - center) / scale, no rotation
SOURCE_CENTER = np.array([-0.00619141, -0.03893983, -0.01132717])
ALIGN_SCALE = 0.3011857514680327   # 1 / scene_scale
ALIGN_ROTATION = np.eye(3)
TARGET_CENTER = np.array([0.0, 0.0, 0.0])

# Camera intrinsics from cameras.bin (SIMPLE_RADIAL, f=3170.78, w=4912, h=3229)
CAM_FX = 3170.776970690481
CAM_FY = 3170.776970690481
CAM_W = 4912
CAM_H = 3229


def qvec_to_rotmat(qvec):
    w, x, y, z = qvec
    return np.array([
        [1 - 2*y*y - 2*z*z, 2*x*y - 2*z*w, 2*x*z + 2*y*w],
        [2*x*y + 2*z*w, 1 - 2*x*x - 2*z*z, 2*y*z - 2*x*w],
        [2*x*z - 2*y*w, 2*y*z + 2*x*w, 1 - 2*x*x - 2*y*y],
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
        + ";\n\nexport const annabergCameras = "
        + json.dumps(cameras, indent=4)
        + ";\n\nexport const annabergTrajectoryPoints = "
        + json.dumps(trajectory, indent=4)
        + ";\n"
    )


def main():
    images = read_images_bin(IMAGES_BIN)
    images.sort(key=lambda x: x["name"])
    print(f"Loaded {len(images)} images from COLMAP")

    trajectory = []
    transformed_cameras = []

    for img in images:
        rotation_wc = qvec_to_rotmat(img["qvec"])
        translation_wc = np.array(img["tvec"])
        center_world = -rotation_wc.T @ translation_wc
        rotation_cw = rotation_wc.T

        trajectory.append(transform_position(center_world))
        transformed_cameras.append({
            "img_name": img["name"],
            "position": transform_position(center_world),
            "rotation": transform_rotation(rotation_cw),
        })

    cameras = []
    for cam_id, img_idx in enumerate(SAMPLED_INDICES):
        pose = transformed_cameras[img_idx]
        cameras.append({
            "id": cam_id,
            "img_name": pose["img_name"],
            "width": CAM_W,
            "height": CAM_H,
            "position": pose["position"],
            "rotation": pose["rotation"],
            "fy": CAM_FY,
            "fx": CAM_FX,
        })

    OUTPUT_TRAJECTORY.write_text(json.dumps([{"position": p} for p in trajectory]))
    write_pose_module(cameras, trajectory)

    print(f"Wrote {NUM_SAMPLES} sampled cameras to {OUTPUT_MODULE.name}")
    print(f"Wrote full trajectory ({len(trajectory)} points) to {OUTPUT_TRAJECTORY.name}")
    print("\nFirst 3 normalized positions:")
    for c in cameras[:3]:
        print(f"  {c['img_name']}: {[round(v,3) for v in c['position']]}")


if __name__ == "__main__":
    main()
