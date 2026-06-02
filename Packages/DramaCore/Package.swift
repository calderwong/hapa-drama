// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "DramaCore",
    platforms: [.macOS(.v13)],
    products: [.library(name: "DramaCore", targets: ["DramaCore"])],
    targets: [.target(name: "DramaCore")]
)
