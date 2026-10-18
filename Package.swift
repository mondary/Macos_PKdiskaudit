// swift-tools-version: 6.0

import PackageDescription

let package = Package(
    name: "PKDiskAudit",
    platforms: [.macOS(.v14)],
    products: [.executable(name: "PKDiskAudit", targets: ["PKDiskAudit"])],
    targets: [.executableTarget(
        name: "PKDiskAudit",
        path: "src/macos",
        exclude: ["Resources"]
    )],
    swiftLanguageModes: [.v5]
)
