import Foundation
import Security

enum KeychainStore {
    static let readerService = "LiteratureRadarDeepSeekReaderAPIKey"
    static let flashService = "LiteratureRadarDeepSeekFlashAPIKey"
    static let legacyService = "LiteratureRadarDeepSeekAPIKey"
    static let defaultAccount = "default"

    static func loadReaderKey() -> String {
        load(service: readerService) ?? load(service: legacyService) ?? ""
    }

    static func loadFlashKey() -> String {
        load(service: flashService) ?? ""
    }

    static func saveReaderKey(_ key: String) throws {
        try save(key, service: readerService)
    }

    static func saveFlashKey(_ key: String) throws {
        try save(key, service: flashService)
    }

    static func loadDeepSeekKey() -> String {
        loadReaderKey()
    }

    static func saveDeepSeekKey(_ key: String) throws {
        try saveReaderKey(key)
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
