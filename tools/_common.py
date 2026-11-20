"""Shared helpers for the plain Python tools (NumPy, SciPy, Pillow; OpenCV when present).

Conventions used by every tool (see CONTRACT.md):
- millimetres in every file; vehicle coordinates have their origin on the ground under the middle of the
  front axle, X toward the rear, Y toward the vehicle's right, Z up;
- pixel coordinates: origin at the top-left corner, integer values at pixel centres (the OpenCV convention);
- camera model: X_cam = R @ (X_world - C), camera +x right, +y down, +z forward; u = cx + f * x/z,
  v = cy + f * y/z, with f in pixels.
- exit codes: 0 success, 1 a measured gate failed, 2 bad input.
"""
import argparse
import json
import os
import sys

import numpy as np

EXIT_OK, EXIT_GATE, EXIT_BAD = 0, 1, 2


class BadInput(Exception):
    """Raised for input a tool cannot work with. Tools turn it into exit code 2."""


class ArgParser(argparse.ArgumentParser):
    """argparse that prints one line of usage and exits 2 when run with no arguments or bad ones."""

    def __init__(self, *a, usage_line=None, **k):
        super().__init__(*a, **k)
        self.usage_line = usage_line

    def error(self, message):
        sys.stderr.write('usage: %s\nerror: %s\n' % (self.usage_line or self.format_usage().strip(), message))
        sys.exit(EXIT_BAD)

    def parse(self, argv):
        if not argv:
            print('usage: %s' % (self.usage_line or self.format_usage().strip()))
            sys.exit(EXIT_BAD)
        return self.parse_args(argv)


def run(main):
    """Call main(argv) and map BadInput to exit 2. main returns the exit code."""
    try:
        code = main(sys.argv[1:])
    except BadInput as e:
        sys.stderr.write('bad input: %s\n' % e)
        code = EXIT_BAD
    sys.exit(code)


def load_json(path, what='file'):
    if not os.path.isfile(path):
        raise BadInput('%s not found: %s' % (what, path))
    try:
        with open(path, 'r', encoding='utf-8-sig') as f:
            return json.load(f)
    except (ValueError, UnicodeDecodeError) as e:
        raise BadInput('%s is not valid JSON: %s (%s)' % (what, path, e))


def save_json(path, obj):
    """Write JSON atomically (write a temporary file, then rename) so a waiting reader never sees half a file."""
    d = os.path.dirname(os.path.abspath(path))
    os.makedirs(d, exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(obj, f, indent=1, default=_json_default)
        f.write('\n')
    os.replace(tmp, path)


def _json_default(o):
    if isinstance(o, np.generic):
        return o.item()
    if isinstance(o, np.ndarray):
        return o.tolist()
    raise TypeError('not JSON serialisable: %r' % type(o))


def number(v, what):
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise BadInput('%s must be a number, got %r' % (what, v))
    if not np.isfinite(x):
        raise BadInput('%s must be finite, got %r' % (what, v))
    return x


# ------------------------------------------------------------------ camera

def rodrigues(rv):
    """Rotation vector -> 3x3 rotation matrix."""
    rv = np.asarray(rv, float)
    th = np.linalg.norm(rv)
    if th < 1e-12:
        return np.eye(3)
    k = rv / th
    K = np.array([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]])
    return np.eye(3) + np.sin(th) * K + (1 - np.cos(th)) * K @ K


def rotation_vector(R):
    """3x3 rotation matrix -> rotation vector (inverse of rodrigues)."""
    from scipy.spatial.transform import Rotation
    return Rotation.from_matrix(np.asarray(R, float)).as_rotvec()


def look_at(C, at, up=(0, 0, 1)):
    """World-to-camera rotation for a camera at C looking at `at`, image up along `up` (rows: camera axes)."""
    C, at, up = np.asarray(C, float), np.asarray(at, float), np.asarray(up, float)
    fwd = at - C
    fwd /= np.linalg.norm(fwd)
    right = np.cross(fwd, up)
    if np.linalg.norm(right) < 1e-9:          # looking straight up or down
        right = np.cross(fwd, (1.0, 0, 0))
    right /= np.linalg.norm(right)
    down = np.cross(fwd, right)
    return np.stack([right, down, fwd])


class Camera:
    """Pinhole camera in vehicle millimetres; see the module docstring for the convention."""

    def __init__(self, C, R, f, cx, cy, width, height):
        self.C = np.asarray(C, float)
        self.R = np.asarray(R, float)
        self.f, self.cx, self.cy = float(f), float(cx), float(cy)
        self.width, self.height = int(width), int(height)

    def cam_coords(self, X):
        return (np.atleast_2d(np.asarray(X, float)) - self.C) @ self.R.T

    def project(self, X):
        Xc = self.cam_coords(X)
        return np.stack([self.cx + self.f * Xc[:, 0] / Xc[:, 2], self.cy + self.f * Xc[:, 1] / Xc[:, 2]], 1)

    def depth(self, X):
        return self.cam_coords(X)[:, 2]

    def as_dict(self):
        return dict(width=self.width, height=self.height, position_mm=self.C.tolist(),
                    rotation=self.R.tolist(), rotation_vector=rotation_vector(self.R).tolist(),
                    focal_px=self.f, centre_px=[self.cx, self.cy],
                    forward=self.R[2].tolist(), up=(-self.R[1]).tolist())

    @staticmethod
    def from_dict(d):
        try:
            R = np.array(d['rotation'], float) if 'rotation' in d else rodrigues(d['rotation_vector'])
            return Camera(d['position_mm'], R, d['focal_px'], d['centre_px'][0], d['centre_px'][1],
                          d['width'], d['height'])
        except (KeyError, TypeError, ValueError, IndexError) as e:
            raise BadInput('camera entry is incomplete: %s' % e)


def load_cameras(path):
    d = load_json(path, 'cameras file')
    if not isinstance(d, dict) or not isinstance(d.get('cameras'), dict) or not d['cameras']:
        raise BadInput('%s has no "cameras" object' % path)
    return d, {k: Camera.from_dict(v) for k, v in d['cameras'].items()}


# ------------------------------------------------------------------ pictures

def have_cv2():
    try:
        import cv2  # noqa: F401
        return True
    except ImportError:
        return False


def open_image(path, what='picture'):
    from PIL import Image
    if not os.path.isfile(path):
        raise BadInput('%s not found: %s' % (what, path))
    try:
        im = Image.open(path)
        im.load()
    except Exception as e:
        raise BadInput('%s cannot be read: %s (%s)' % (what, path, e))
    return im


def find_image(folder, stem, exts=('.png', '.jpg', '.jpeg', '.tif', '.tiff', '.webp', '.bmp')):
    """The file in `folder` named <stem>.<ext>, or None."""
    for e in exts:
        for cand in (stem + e, stem + e.upper()):
            p = os.path.join(folder, cand)
            if os.path.isfile(p):
                return p
    return None


def font(size):
    from PIL import ImageFont
    for name in ('DejaVuSans-Bold.ttf', 'DejaVuSans.ttf', 'Arial Bold.ttf', 'arialbd.ttf', 'arial.ttf'):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def mask_boundary(mask):
    """Boolean image of the pixels on the edge of a boolean mask (inside pixels that touch the outside)."""
    from scipy import ndimage
    if not mask.any():
        return np.zeros_like(mask)
    er = ndimage.binary_erosion(mask, structure=np.ones((3, 3), bool), border_value=0)
    return mask & ~er
