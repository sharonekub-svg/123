"""Homography: image pixels <-> pitch meters.

This is what makes the statistics *metric* (and therefore trustworthy): given a
set of correspondences between points visible in the image and their known
location on the pitch (in meters), we solve for a 3x3 homography H such that

    [X, Y, 1]^T  ~  H · [x, y, 1]^T

mapping image pixel (x, y) to pitch coordinate (X, Y) in meters.

Two camera regimes (see DESIGN.md):

* **Static wide camera** (the product's MVP target): one homography per clip is
  exact. Calibrate once, project every frame.
* **Moving / broadcast camera**: a single H is wrong as the camera pans. We
  propagate the frame-0 homography using per-frame global motion compensation
  (see `propagate`), which is approximate but recovers metric positions without
  a pitch-keypoint model.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import numpy as np


@dataclass
class Calibration:
    image_points: np.ndarray   # (N, 2) pixel coords on the reference frame
    pitch_points: np.ndarray   # (N, 2) meters on the pitch
    ref_frame: int = 0         # index of the frame the image points were taken on

    @staticmethod
    def load(path: str) -> "Calibration":
        with open(path, encoding="utf-8") as fh:
            d = json.load(fh)
        return Calibration(
            image_points=np.asarray(d["image_points"], dtype=np.float64),
            pitch_points=np.asarray(d["pitch_points"], dtype=np.float64),
            ref_frame=int(d.get("ref_frame", 0)),
        )


def homography_from_correspondences(
    image_points: np.ndarray, pitch_points: np.ndarray
) -> np.ndarray:
    """Solve H (3x3) mapping image pixels -> pitch meters. Needs >= 4 points."""
    import cv2

    img = np.asarray(image_points, dtype=np.float64)
    pit = np.asarray(pitch_points, dtype=np.float64)
    if len(img) < 4 or len(pit) < 4 or len(img) != len(pit):
        raise ValueError("need >= 4 matched image/pitch points")
    H, _ = cv2.findHomography(img, pit, method=cv2.RANSAC, ransacReprojThreshold=5.0)
    if H is None:
        raise ValueError("homography estimation failed")
    return H


def project(H: np.ndarray, points: np.ndarray) -> np.ndarray:
    """Apply homography H to (N,2) image points -> (N,2) pitch meters."""
    pts = np.asarray(points, dtype=np.float64).reshape(-1, 1, 2)
    if len(pts) == 0:
        return np.empty((0, 2))
    import cv2

    out = cv2.perspectiveTransform(pts, H)
    return out.reshape(-1, 2)


def project_point(H: np.ndarray, x: float, y: float) -> tuple[float, float]:
    """Project a single image point to pitch meters (pure numpy, no cv2)."""
    v = H @ np.array([x, y, 1.0])
    return float(v[0] / v[2]), float(v[1] / v[2])


def propagate(H0: np.ndarray, cumulative_motion: np.ndarray) -> np.ndarray:
    """Homography for the current frame given frame-0 calibration.

    `cumulative_motion` (3x3) maps reference-frame pixels -> current-frame pixels
    (the accumulated camera motion). To project current-frame pixels we first map
    them back into reference-frame coordinates, then apply H0.
    """
    return H0 @ np.linalg.inv(cumulative_motion)


def estimate_motion(prev_gray, cur_gray) -> np.ndarray:
    """Estimate a 3x3 affine global-motion matrix prev->cur via ORB matching.

    Returns identity on failure (so propagation degrades gracefully).
    """
    import cv2

    orb = cv2.ORB_create(1000)
    k1, d1 = orb.detectAndCompute(prev_gray, None)
    k2, d2 = orb.detectAndCompute(cur_gray, None)
    if d1 is None or d2 is None or len(k1) < 8 or len(k2) < 8:
        return np.eye(3)
    bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
    matches = sorted(bf.match(d1, d2), key=lambda m: m.distance)[:200]
    if len(matches) < 8:
        return np.eye(3)
    src = np.float32([k1[m.queryIdx].pt for m in matches])
    dst = np.float32([k2[m.trainIdx].pt for m in matches])
    A, _ = cv2.estimateAffinePartial2D(src, dst, method=cv2.RANSAC)
    if A is None:
        return np.eye(3)
    M = np.eye(3)
    M[:2, :] = A
    return M


# --------------------------------------------------------------------------- #
def _selftest() -> None:
    """Round-trip: build a known perspective, recover it, check reprojection."""
    # four pitch corners (meters) and a synthetic camera mapping into pixels
    pitch = np.array([[0, 0], [105, 0], [105, 68], [0, 68]], dtype=np.float64)
    # a plausible perspective view of those corners in a 1920x1080 image
    img = np.array([[300, 900], [1600, 880], [1900, 1040], [50, 1060]], dtype=np.float64)

    H = homography_from_correspondences(img, pitch)
    recovered = project(H, img)
    err = np.linalg.norm(recovered - pitch, axis=1).max()
    assert err < 1e-6, f"corner reprojection error too large: {err}"

    # an interior point projected and checked against the manual matrix-multiply
    px, py = 960.0, 950.0
    a = project(H, [[px, py]])[0]
    b = project_point(H, px, py)
    assert np.allclose(a, b, atol=1e-9), (a, b)

    # propagation with identity motion must equal H itself
    assert np.allclose(propagate(H, np.eye(3)), H)
    print("homography self-test OK  (max corner error %.2e m)" % err)


if __name__ == "__main__":
    _selftest()
