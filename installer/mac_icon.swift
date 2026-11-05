// Puts a square iPhone icon on the plate a Mac icon is drawn on: Apple's 1024 grid, an 824 plate with rounded
// corners in the middle, the margins transparent and a soft shadow under it. iOS rounds its icons itself, macOS does not.
// Usage: swift mac_icon.swift <square.png> <out.png>
import AppKit

let canvas = 1024.0
let plate = NSRect(x: 100, y: 100, width: 824, height: 824)
let radius = 185.4

let arguments = CommandLine.arguments
guard arguments.count == 3, let source = NSImage(contentsOfFile: arguments[1]),
      let bitmap = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: Int(canvas), pixelsHigh: Int(canvas),
                                    bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
                                    colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)
else { exit(1) }

NSGraphicsContext.saveGraphicsState()
NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: bitmap)
let shape = NSBezierPath(roundedRect: plate, xRadius: radius, yRadius: radius)
let shadow = NSShadow()
shadow.shadowOffset = NSSize(width: 0, height: -10)
shadow.shadowBlurRadius = 20
shadow.shadowColor = NSColor.black.withAlphaComponent(0.3)
NSGraphicsContext.saveGraphicsState()
shadow.set()
NSColor.black.setFill()
shape.fill()
NSGraphicsContext.restoreGraphicsState()
shape.addClip()
source.draw(in: plate, from: .zero, operation: .copy, fraction: 1)
NSGraphicsContext.restoreGraphicsState()

guard let png = bitmap.representation(using: .png, properties: [:]),
      (try? png.write(to: URL(fileURLWithPath: arguments[2]))) != nil
else { exit(1) }
