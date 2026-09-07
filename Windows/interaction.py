"""Input-window gestures use the same thresholds as the macOS app."""
import math


def mouse_shaken(points, sensitivity='보통'):
    scale = {'낮음': 2, '보통': 1, '높음': 0.6}[sensitivity]
    direction = None
    reversals = 0
    leg = total = 0.0
    for previous, current in zip(points, points[1:]):
        elapsed = current[0] - previous[0]
        if not 0 < elapsed < 0.15:
            direction = None; reversals = 0; leg = total = 0.0; continue
        dx, dy = current[1] - previous[1], current[2] - previous[2]
        distance = math.hypot(dx, dy)
        if distance < 4 or distance / elapsed < 600 * scale: continue
        vector = (dx / distance, dy / distance)
        if direction is None: direction = vector
        if sum(a * b for a, b in zip(direction, vector)) < -0.6 and leg >= 20 * scale:
            reversals += 1; direction = vector; leg = 0
        leg += distance; total += distance
        if reversals >= 2 and total >= 90 * scale: return True
    return False
