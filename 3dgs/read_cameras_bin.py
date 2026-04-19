import struct

with open("maine/colmap_output/sparse/0/cameras.bin", "rb") as f:
    num = struct.unpack("Q", f.read(8))[0]
    print(f"num cameras: {num}")
    for _ in range(num):
        cam_id = struct.unpack("I", f.read(4))[0]
        model_id = struct.unpack("i", f.read(4))[0]
        w = struct.unpack("Q", f.read(8))[0]
        h = struct.unpack("Q", f.read(8))[0]
        # SIMPLE_RADIAL has params: f, cx, cy, k
        # PINHOLE has params: fx, fy, cx, cy
        # Read 4 doubles (covers both)
        params = struct.unpack("4d", f.read(32))
        print(f"cam_id={cam_id} model_id={model_id} w={w} h={h} params={params}")
