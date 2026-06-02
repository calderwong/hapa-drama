// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "HapaDramaApp",
    platforms: [.macOS(.v13)],
    products: [
        .executable(name: "HapaDramaApp", targets: ["HapaDramaApp"])
    ],
    targets: [
        .executableTarget(name: "HapaDramaApp")
    ]
)
