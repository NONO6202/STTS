import Foundation

enum MouseShakeSensitivity: String, CaseIterable, Identifiable, Codable {
    case low = "낮음", normal = "보통", high = "높음"
    var id: String { rawValue }
    var scale: CGFloat {
        AppContract.shared.shakeSensitivities[rawValue] ?? 1
    }
}

/// Points per second, not hardware-dependent mouse counts. One fast move is not a shake.
struct MouseShakeDetector {
    private var previous: (point: CGPoint, time: TimeInterval)?
    private var direction: CGVector?
    private var gestureStart: TimeInterval?
    private var reversals = 0
    private var legDistance: CGFloat = 0
    private var totalDistance: CGFloat = 0

    mutating func sample(_ point: CGPoint, at time: TimeInterval, sensitivity: MouseShakeSensitivity = .normal) -> Bool {
        defer { previous = (point, time) }
        guard let previous else { return false }
        let elapsed = time - previous.time
        guard elapsed > 0, elapsed < 0.15 else { resetGesture(); return false }
        let dx = point.x - previous.point.x, dy = point.y - previous.point.y
        let distance = hypot(dx, dy)
        if let start = gestureStart, time - start > 0.65 { resetGesture() }
        guard distance >= 4, distance / elapsed >= 600 * sensitivity.scale else { return false }
        let vector = CGVector(dx: dx / distance, dy: dy / distance)
        if gestureStart == nil { gestureStart = time; direction = vector }
        if let direction, vector.dx * direction.dx + vector.dy * direction.dy < -0.6, legDistance >= 20 * sensitivity.scale {
            reversals += 1; self.direction = vector; legDistance = 0
        }
        legDistance += distance; totalDistance += distance
        return reversals >= 2 && totalDistance >= 90 * sensitivity.scale
    }
    private mutating func resetGesture() {
        direction = nil; gestureStart = nil; reversals = 0; legDistance = 0; totalDistance = 0
    }
}

enum ComposerPlacement {
    static func frame(near point: CGPoint, in screen: CGRect) -> CGRect {
        let width = min(480, screen.width - 16), height: CGFloat = 44
        let x = min(max(point.x + 14, screen.minX + 8), screen.maxX - width - 8)
        let y = min(max(point.y - height - 14, screen.minY + 8), screen.maxY - height - 8)
        return CGRect(x: x, y: y, width: width, height: height)
    }
}
