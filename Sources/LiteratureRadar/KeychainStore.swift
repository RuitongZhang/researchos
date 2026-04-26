import Foundation
import Security

private final class KeychainKeyCache: @unchecked Sendable {
    private let lock = NSLock()
    private var readerKey: String?
    private var flashKey: String?

    func reader() -> String? {
        lock.lock()
        let value = readerKey
        lock.unlock()
        return value
    }

    func flash() -> String? {
        lock.lock()
        let value = flashKey
        lock.unlock()
        return value
    }

    func setReader(_ value: String) {
        lock.lock()
        readerKey = value
        lock.unlock()
    }

    func setFlash(_ value: String) {
        lock.lock()
        flashKey = value
        lock.unlock()
    }

    func clear() {
        lock.lock()
        readerKey = ""
        flashKey = ""
        lock.unlock()
    }
}

enum KeychainStore {
    static let readerService = "LiteratureRadarDeepSeekReaderAPIKey"
    static let flashService = "LiteratureRadarDeepSeekFlashAPIKey"
    static let legacyService = "LiteratureRadarDeepSeekAPIKey"
    static let defaultAccount = "default"
    private static let cache = KeychainKeyCache()

    static func loadReaderKey() -> String {
        if let cached = cache.reader() { return cached }

        let key = load(service: readerService) ?? load(service: legacyService) ?? ""
        cache.setReader(key)
        return key
    }

    static func loadFlashKey() -> String {
        if let cached = cache.flash() { return cached }

        let key = load(service: flashService) ?? ""
        cache.setFlash(key)
        return key
    }

    static func saveReaderKey(_ key: String) throws {
        try save(key, service: readerService)
        cache.setReader(key)
    }

    static func saveFlashKey(_ key: String) throws {
        try save(key, service: flashService)
        cache.setFlash(key)
    }

    static func loadDeepSeekKey() -> String {
        loadReaderKey()
    }

    static func saveDeepSeekKey(_ key: String) throws {
        try saveReaderKey(key)
    }

    static func clearDeepSeekKeys() throws {
        try clear(service: readerService)
        try clear(service: flashService)
        try clear(service: legacyService)
        cache.clear()
    }

    private static func load(service: String) -> String? {
        var query = baseQuery(service: service)
        query[kSecReturnData as String] = true
        query[kSecMatchLimit as String] = kSecMatchLimitOne

        var item: CFTypeRef?
        let status = SecItemCopyMatching(query as CFDictionary, &item)
        guard status == errSecSuccess,
              let data = item as? Data,
              let key = String(data: data, encoding: .utf8) else {
            return nil
        }
        return key
    }

    private static func save(_ key: String, service: String) throws {
        if key.isEmpty {
            try clear(service: service)
            return
        }
        let data = Data(key.utf8)
        let deleteStatus = SecItemDelete(baseQuery(service: service) as CFDictionary)
        if deleteStatus != errSecSuccess && deleteStatus != errSecItemNotFound {
            throw NSError(domain: NSOSStatusErrorDomain, code: Int(deleteStatus))
        }

        var query = baseQuery(service: service)
        query[kSecValueData as String] = data
        query[kSecAttrLabel as String] = service
        query[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        let addStatus = SecItemAdd(query as CFDictionary, nil)
        guard addStatus == errSecSuccess else {
            throw NSError(domain: NSOSStatusErrorDomain, code: Int(addStatus))
        }
    }

    private static func clear(service: String) throws {
        let status = SecItemDelete(baseQuery(service: service) as CFDictionary)
        if status != errSecSuccess && status != errSecItemNotFound {
            throw NSError(domain: NSOSStatusErrorDomain, code: Int(status))
        }
    }

    private static func baseQuery(service: String) -> [String: Any] {
        [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: defaultAccount
        ]
    }
}
