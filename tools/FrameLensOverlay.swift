import Cocoa

final class PPMImageLoader {
    static func load(path: String) -> NSImage? {
        guard let data = try? Data(contentsOf: URL(fileURLWithPath: path)) else {
            return nil
        }

        var index = 0
        func nextToken() -> String? {
            while index < data.count {
                let byte = data[index]
                if byte == 35 {
                    while index < data.count && data[index] != 10 { index += 1 }
                } else if byte == 10 || byte == 13 || byte == 32 || byte == 9 {
                    index += 1
                } else {
                    break
                }
            }

            let start = index
            while index < data.count {
                let byte = data[index]
                if byte == 10 || byte == 13 || byte == 32 || byte == 9 { break }
                index += 1
            }

            guard index > start else { return nil }
            return String(data: data[start..<index], encoding: .ascii)
        }

        guard
            nextToken() == "P6",
            let widthText = nextToken(),
            let heightText = nextToken(),
            let maxText = nextToken(),
            let width = Int(widthText),
            let height = Int(heightText),
            Int(maxText) == 255
        else {
            return nil
        }

        while index < data.count {
            let byte = data[index]
            if byte == 10 || byte == 13 || byte == 32 || byte == 9 {
                index += 1
            } else {
                break
            }
        }

        let expectedBytes = width * height * 3
        guard data.count >= index + expectedBytes else {
            return nil
        }

        let rgb = data[index..<(index + expectedBytes)]
        var rgba = Data(capacity: width * height * 4)
        for offset in stride(from: 0, to: rgb.count, by: 3) {
            let red = rgb[rgb.index(rgb.startIndex, offsetBy: offset)]
            let green = rgb[rgb.index(rgb.startIndex, offsetBy: offset + 1)]
            let blue = rgb[rgb.index(rgb.startIndex, offsetBy: offset + 2)]
            rgba.append(red)
            rgba.append(green)
            rgba.append(blue)
            rgba.append(red == 0 && green == 0 && blue == 0 ? 0 : 255)
        }

        guard let provider = CGDataProvider(data: rgba as CFData),
              let cgImage = CGImage(
                width: width,
                height: height,
                bitsPerComponent: 8,
                bitsPerPixel: 32,
                bytesPerRow: width * 4,
                space: CGColorSpaceCreateDeviceRGB(),
                bitmapInfo: CGBitmapInfo(rawValue: CGImageAlphaInfo.last.rawValue),
                provider: provider,
                decode: nil,
                shouldInterpolate: false,
                intent: .defaultIntent
              )
        else {
            return nil
        }

        return NSImage(cgImage: cgImage, size: NSSize(width: width, height: height))
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate {
    let path: String
    let commandPath: String
    let scale: Int
    let duration: Double?
    let opacity: Double
    let showBorder: Bool
    let clickThrough: Bool
    let levelName: String
    let showPanel: Bool
    let commands = [
        ("Tap", "tap"),
        ("Double Tap", "double_tap"),
        ("Pitch Up", "pitch_up"),
        ("Pitch Down", "pitch_down"),
        ("Roll Left", "roll_left"),
        ("Roll Right", "roll_right"),
        ("Heading Left", "heading_left"),
        ("Heading Right", "heading_right"),
        ("Reset Pose", "reset_pose"),
        ("Still", "still"),
        ("Shake", "shake"),
        ("Sleep", "sleep"),
        ("Wake", "wake"),
        ("Break Lua", "break_lua"),
        ("Reset Lua", "reset_lua"),
        ("Disconnect", "disconnect"),
        ("Reconnect", "reconnect")
    ]
    var window: NSWindow?
    var panelWindow: NSWindow?
    var imageView: NSImageView?
    var timer: Timer?

    init(
        path: String,
        commandPath: String,
        scale: Int,
        duration: Double?,
        opacity: Double,
        showBorder: Bool,
        clickThrough: Bool,
        levelName: String,
        showPanel: Bool
    ) {
        self.path = path
        self.commandPath = commandPath
        self.scale = max(1, scale)
        self.duration = duration
        self.opacity = min(1.0, max(0.1, opacity))
        self.showBorder = showBorder
        self.clickThrough = clickThrough
        self.levelName = levelName
        self.showPanel = showPanel
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)

        let width = 640 * scale
        let height = 400 * scale
        let rect = NSRect(x: 80, y: 280, width: width, height: height)
        let window = NSWindow(
            contentRect: rect,
            styleMask: [.titled, .closable, .miniaturizable, .resizable],
            backing: .buffered,
            defer: false
        )
        window.title = "Frame Emulator Lens"
        switch levelName {
        case "normal":
            window.level = .normal
        case "screensaver":
            window.level = .screenSaver
        default:
            window.level = .floating
        }
        window.isOpaque = false
        window.backgroundColor = .clear
        window.alphaValue = opacity
        window.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
        window.isMovableByWindowBackground = true
        window.ignoresMouseEvents = clickThrough

        let container = NSView(frame: NSRect(x: 0, y: 0, width: width, height: height))
        container.wantsLayer = true
        container.layer?.backgroundColor = NSColor.clear.cgColor
        container.layer?.borderColor = NSColor.systemGreen.withAlphaComponent(showBorder ? 0.55 : 0.0).cgColor
        container.layer?.borderWidth = showBorder ? 2 : 0
        container.layer?.cornerRadius = 8

        let imageView = NSImageView(frame: container.bounds.insetBy(dx: 2, dy: 2))
        imageView.autoresizingMask = [.width, .height]
        imageView.imageScaling = .scaleAxesIndependently
        container.addSubview(imageView)
        window.contentView = container
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)

        self.window = window
        self.imageView = imageView
        refresh()
        if showPanel {
            createDevPanel(origin: NSPoint(x: rect.maxX + 16, y: rect.maxY - 520))
        }

        timer = Timer.scheduledTimer(withTimeInterval: 0.1, repeats: true) { [weak self] _ in
            self?.refresh()
        }

        if let duration {
            Timer.scheduledTimer(withTimeInterval: duration, repeats: false) { _ in
                NSApp.terminate(nil)
            }
        }
    }

    func refresh() {
        if let image = PPMImageLoader.load(path: path) {
            imageView?.image = image
        }
    }

    func createDevPanel(origin: NSPoint) {
        let panelRect = NSRect(x: origin.x, y: max(80, origin.y), width: 260, height: 520)
        let panel = NSWindow(
            contentRect: panelRect,
            styleMask: [.titled, .closable, .miniaturizable],
            backing: .buffered,
            defer: false
        )
        panel.title = "Frame Hardware"
        panel.level = .floating

        let stack = NSStackView(frame: NSRect(x: 16, y: 16, width: 228, height: 488))
        stack.orientation = .vertical
        stack.alignment = .leading
        stack.spacing = 8

        addLabel("Input", to: stack)
        addButton(title: "Tap", command: "tap", to: stack)
        addButton(title: "Double Tap", command: "double_tap", to: stack)

        addSeparator(to: stack)
        addLabel("Head Pose", to: stack)
        addButtonRow([("Pitch Up", "pitch_up"), ("Pitch Down", "pitch_down")], to: stack)
        addButtonRow([("Roll Left", "roll_left"), ("Roll Right", "roll_right")], to: stack)
        addButtonRow([("Heading Left", "heading_left"), ("Heading Right", "heading_right")], to: stack)
        addButtonRow([("Reset Pose", "reset_pose"), ("Shake", "shake")], to: stack)
        addButton(title: "Still", command: "still", to: stack)

        addSeparator(to: stack)
        addLabel("Runtime", to: stack)
        addButtonRow([("Sleep", "sleep"), ("Wake", "wake")], to: stack)
        addButtonRow([("Break Lua", "break_lua"), ("Reset Lua", "reset_lua")], to: stack)
        addButtonRow([("Disconnect", "disconnect"), ("Reconnect", "reconnect")], to: stack)

        panel.contentView = stack
        panel.makeKeyAndOrderFront(nil)
        panelWindow = panel
    }

    func addLabel(_ text: String, to stack: NSStackView) {
        let label = NSTextField(labelWithString: text)
        label.font = NSFont.boldSystemFont(ofSize: 13)
        stack.addArrangedSubview(label)
    }

    func addSeparator(to stack: NSStackView) {
        let separator = NSBox(frame: NSRect(x: 0, y: 0, width: 220, height: 1))
        separator.boxType = .separator
        stack.addArrangedSubview(separator)
    }

    func addButton(title: String, command: String, to stack: NSStackView) {
        let button = NSButton(title: title, target: self, action: #selector(sendCommand(_:)))
        button.bezelStyle = .rounded
        button.identifier = NSUserInterfaceItemIdentifier(command)
        button.widthAnchor.constraint(equalToConstant: 220).isActive = true
        stack.addArrangedSubview(button)
    }

    func addButtonRow(_ buttons: [(String, String)], to stack: NSStackView) {
        let row = NSStackView()
        row.orientation = .horizontal
        row.spacing = 8
        for (title, command) in buttons {
            let button = NSButton(title: title, target: self, action: #selector(sendCommand(_:)))
            button.bezelStyle = .rounded
            button.identifier = NSUserInterfaceItemIdentifier(command)
            button.widthAnchor.constraint(equalToConstant: 106).isActive = true
            row.addArrangedSubview(button)
        }
        stack.addArrangedSubview(row)
    }

    @objc func sendCommand(_ sender: NSButton) {
        guard let command = sender.identifier?.rawValue else { return }
        let line = command + "\n"
        guard let data = line.data(using: .utf8) else { return }
        let url = URL(fileURLWithPath: commandPath)
        if FileManager.default.fileExists(atPath: commandPath),
           let handle = try? FileHandle(forWritingTo: url) {
            handle.seekToEndOfFile()
            handle.write(data)
            try? handle.close()
        } else {
            try? data.write(to: url)
        }
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        true
    }
}

let arguments = CommandLine.arguments
guard arguments.count >= 2 else {
    fputs("usage: FrameLensOverlay.swift <snapshot.ppm> <commands.txt> [scale] [duration] [opacity] [border] [clickThrough] [level] [panel]\n", stderr)
    exit(2)
}

let path = arguments[1]
let commandPath = arguments.count >= 3 ? arguments[2] : "/tmp/frame-emulator-commands.txt"
let scale = arguments.count >= 4 ? (Int(arguments[3]) ?? 1) : 1
let durationArg = arguments.count >= 5 ? (Double(arguments[4]) ?? 0) : 0
let duration = durationArg > 0 ? durationArg : nil
let opacity = arguments.count >= 6 ? (Double(arguments[5]) ?? 1.0) : 1.0
let showBorder = arguments.count >= 7 ? arguments[6] != "0" : true
let clickThrough = arguments.count >= 8 ? arguments[7] == "1" : false
let levelName = arguments.count >= 9 ? arguments[8] : "floating"
let showPanel = arguments.count >= 10 ? arguments[9] != "0" : true

let app = NSApplication.shared
let delegate = AppDelegate(
    path: path,
    commandPath: commandPath,
    scale: scale,
    duration: duration,
    opacity: opacity,
    showBorder: showBorder,
    clickThrough: clickThrough,
    levelName: levelName,
    showPanel: showPanel
)
app.delegate = delegate
app.run()
