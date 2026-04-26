// swift-tools-version: 6.0

import PackageDescription

let package = Package(
    name: "LiteratureRadar",
    platforms: [
        .macOS(.v14)
    ],
    products: [
        .executable(name: "LiteratureRadar", targets: ["LiteratureRadar"])
    ],
    targets: [
        .executableTarget(
            name: "LiteratureRadar",
            path: "Sources/LiteratureRadar",
            resources: [
                .copy("Resources")
            ]
        )
    ]
)
