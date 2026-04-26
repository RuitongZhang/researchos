import Foundation

enum WorkerClientError: LocalizedError {
    case missingWorker
    case invalidPayload
    case failed(status: Int32, stderr: String)
    case emptyOutput
    case timedOut(command: String, seconds: TimeInterval)

    var errorDescription: String? {
        switch self {
        case .missingWorker:
            "Python worker script was not found."
        case .invalidPayload:
            "Could not encode worker payload."
        case .failed(let status, let stderr):
            "Worker failed with status \(status): \(stderr)"
        case .emptyOutput:
            "Worker returned no output."
        case .timedOut(let command, let seconds):
            "Worker command '\(command)' timed out after \(Int(seconds)) seconds."
        }
    }
}

final class LockedData: @unchecked Sendable {
    private let lock = NSLock()
    private var value = Data()

    func set(_ data: Data) {
        lock.lock()
        value = data
        lock.unlock()
    }

    func get() -> Data {
        lock.lock()
        let data = value
        lock.unlock()
        return data
    }
}

final class WorkerClient: Sendable {
    func run<T: Decodable>(_ command: String, payload: [String: Any] = [:], timeout: TimeInterval = 45) async throws -> T {
        let data = try await runData(command, payload: payload, timeout: timeout)
        let decoder = JSONDecoder()
        return try decoder.decode(T.self, from: data)
    }

    func runData(_ command: String, payload: [String: Any] = [:], timeout: TimeInterval = 45) async throws -> Data {
        guard JSONSerialization.isValidJSONObject(payload) else {
            throw WorkerClientError.invalidPayload
        }
        let inputData = try JSONSerialization.data(withJSONObject: payload)
        return try await Task.detached(priority: .userInitiated) { [command, inputData, timeout] () throws -> Data in
            try Self.runProcessSync(command: command, inputData: inputData, timeout: timeout)
        }.value
    }

    private static func runProcessSync(command: String, inputData: Data, timeout: TimeInterval) throws -> Data {
        let workerURL = try workerURL()
        let python = pythonInvocation()
        let process = Process()
        process.executableURL = python.executable
        process.arguments = python.argumentsPrefix + [workerURL.path, command]
        var environment = ProcessInfo.processInfo.environment
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        environment["PYTHONUNBUFFERED"] = "1"
        if needsDeepSeekKeys(for: command) {
            let readerKey = KeychainStore.loadReaderKey()
            if !readerKey.isEmpty {
                environment["DEEPSEEK_READER_API_KEY"] = readerKey
                environment["DEEPSEEK_API_KEY"] = readerKey
            }
            let flashKey = KeychainStore.loadFlashKey()
            if !flashKey.isEmpty {
                environment["DEEPSEEK_FLASH_API_KEY"] = flashKey
            }
        }
        process.environment = environment

        let stdinPipe = Pipe()
        let stdoutPipe = Pipe()
        let stderrPipe = Pipe()
        process.standardInput = stdinPipe
        process.standardOutput = stdoutPipe
        process.standardError = stderrPipe

        try process.run()

        let stdout = LockedData()
        let stderr = LockedData()
        let group = DispatchGroup()
        group.enter()
        DispatchQueue.global(qos: .userInitiated).async {
            stdout.set(stdoutPipe.fileHandleForReading.readDataToEndOfFile())
            group.leave()
        }
        group.enter()
        DispatchQueue.global(qos: .userInitiated).async {
            stderr.set(stderrPipe.fileHandleForReading.readDataToEndOfFile())
            group.leave()
        }

        stdinPipe.fileHandleForWriting.write(inputData)
        try? stdinPipe.fileHandleForWriting.close()

        let deadline = Date().addingTimeInterval(timeout)
        while process.isRunning && Date() < deadline {
            Thread.sleep(forTimeInterval: 0.05)
        }
        if process.isRunning {
            process.terminate()
            process.waitUntilExit()
            group.wait()
            throw WorkerClientError.timedOut(command: command, seconds: timeout)
        }
        process.waitUntilExit()
        group.wait()

        let output = stdout.get()
        let errorOutput = stderr.get()
        if process.terminationStatus != 0 {
            let stderr = String(data: errorOutput, encoding: .utf8) ?? ""
            let stdout = String(data: output, encoding: .utf8) ?? ""
            throw WorkerClientError.failed(
                status: process.terminationStatus,
                stderr: stderr.isEmpty ? stdout : stderr
            )
        }
        if output.isEmpty {
            throw WorkerClientError.emptyOutput
        }
        return output
    }

    private static func workerURL() throws -> URL {
        let mainBundle = Bundle.main
        let resourceRoot = mainBundle.resourceURL
        let executableRoot = mainBundle.executableURL?.deletingLastPathComponent()
        let candidates = [
            resourceRoot?.appendingPathComponent("LiteratureRadar_LiteratureRadar.bundle/Resources/worker/litradar.py"),
            resourceRoot?.appendingPathComponent("Resources/worker/litradar.py"),
            resourceRoot?.appendingPathComponent("worker/litradar.py"),
            executableRoot?.appendingPathComponent("LiteratureRadar_LiteratureRadar.bundle/Resources/worker/litradar.py"),
            executableRoot?.appendingPathComponent("../Resources/LiteratureRadar_LiteratureRadar.bundle/Resources/worker/litradar.py"),
            URL(fileURLWithPath: FileManager.default.currentDirectoryPath)
                .appendingPathComponent("Sources/LiteratureRadar/Resources/worker/litradar.py")
        ].compactMap { $0 }

        for candidate in candidates where FileManager.default.fileExists(atPath: candidate.path) {
            return candidate
        }
        throw WorkerClientError.missingWorker
    }

    private static func needsDeepSeekKeys(for command: String) -> Bool {
        [
            "profile-from-description",
            "usefulness",
            "synthesize",
            "integrate-papers"
        ].contains(command)
    }

    private static func pythonInvocation() -> (executable: URL, argumentsPrefix: [String]) {
        let env = ProcessInfo.processInfo.environment
        let candidates = [
            env["LITRADAR_PYTHON"],
            "/opt/miniconda3/bin/python3",
            "/opt/homebrew/bin/python3",
            "/usr/local/bin/python3",
            "/usr/bin/python3"
        ].compactMap { $0 }

        for candidate in candidates where FileManager.default.isExecutableFile(atPath: candidate) {
            return (URL(fileURLWithPath: candidate), [])
        }
        return (URL(fileURLWithPath: "/usr/bin/env"), ["python3"])
    }
}
