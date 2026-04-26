import Foundation
import SwiftUI

enum AppLanguage: String, CaseIterable, Identifiable {
    case english
    case simplifiedChinese

    var id: String { rawValue }

    var displayName: String {
        switch self {
        case .english:
            "English"
        case .simplifiedChinese:
            "简体中文"
        }
    }
}

enum AppThemeMode: String, CaseIterable, Identifiable {
    case system
    case light
    case dark

    var id: String { rawValue }

    func title(language: AppLanguage) -> String {
        switch self {
        case .system:
            L10n.text("Follow System", language)
        case .light:
            L10n.text("Light Appearance", language)
        case .dark:
            L10n.text("Dark Appearance", language)
        }
    }

    var colorScheme: ColorScheme? {
        switch self {
        case .system:
            nil
        case .light:
            .light
        case .dark:
            .dark
        }
    }
}

enum AppSection: String, CaseIterable, Identifiable {
    case radar
    case search
    case profiles
    case memory
    case library
    case settings

    var id: String { rawValue }

    func title(language: AppLanguage) -> String {
        switch self {
        case .radar:
            L10n.text("Today Radar", language)
        case .search:
            L10n.text("Search Lab", language)
        case .profiles:
            L10n.text("Research Profiles", language)
        case .memory:
            L10n.text("Memory", language)
        case .library:
            L10n.text("Read Papers", language)
        case .settings:
            L10n.text("Settings", language)
        }
    }
}

enum RadarSortMode: String, CaseIterable, Identifiable {
    case relevance
    case time

    var id: String { rawValue }

    func title(language: AppLanguage) -> String {
        switch self {
        case .relevance:
            L10n.text("Relevance", language)
        case .time:
            L10n.text("Time", language)
        }
    }
}

struct PaperScore: Codable, Hashable {
    var profileId: String
    var paperId: String
    var bm25Score: Double
    var embeddingScore: Double
    var ruleScore: Double
    var finalScore: Double
    var reason: String
    var updatedAt: String?

    enum CodingKeys: String, CodingKey {
        case profileId = "profile_id"
        case paperId = "paper_id"
        case bm25Score = "bm25_score"
        case embeddingScore = "embedding_score"
        case ruleScore = "rule_score"
        case finalScore = "final_score"
        case reason
        case updatedAt = "updated_at"
    }
}

struct Paper: Codable, Identifiable, Hashable {
    var id: String
    var source: String
    var doi: String?
    var arxivId: String?
    var title: String
    var abstract: String
    var authors: [String]
    var publishedDate: String?
    var updatedDate: String?
    var url: String?
    var pdfUrl: String?
    var category: String?
    var version: String?
    var createdAt: String?
    var updatedAt: String?
    var score: PaperScore?
    var analysisStatus: String?
    var actions: [String]
    var exports: [String]

    enum CodingKeys: String, CodingKey {
        case id
        case source
        case doi
        case arxivId = "arxiv_id"
        case title
        case abstract
        case authors
        case publishedDate = "published_date"
        case updatedDate = "updated_date"
        case url
        case pdfUrl = "pdf_url"
        case category
        case version
        case createdAt = "created_at"
        case updatedAt = "updated_at"
        case score
        case analysisStatus = "analysis_status"
        case actions
        case exports
    }
}

struct ResearchProfile: Codable, Identifiable, Hashable {
    var id: String
    var name: String
    var weight: Double
    var includeTerms: [String]
    var excludeTerms: [String]
    var seedPapers: [String]
    var watchAuthors: [String]
    var watchLabs: [String]
    var arxivQuery: String
    var biorxivQuery: String
    var createdAt: String?
    var updatedAt: String?

    enum CodingKeys: String, CodingKey {
        case id
        case name
        case weight
        case includeTerms = "include_terms"
        case excludeTerms = "exclude_terms"
        case seedPapers = "seed_papers"
        case watchAuthors = "watch_authors"
        case watchLabs = "watch_labs"
        case arxivQuery = "arxiv_query"
        case biorxivQuery = "biorxiv_query"
        case createdAt = "created_at"
        case updatedAt = "updated_at"
    }
}

struct ProfileResponse: Codable {
    var ok: Bool
    var message: String?
    var profile: ResearchProfile
}

struct MemoryNote: Codable, Identifiable, Hashable {
    var id: String
    var profileId: String
    var type: String
    var title: String
    var markdownPath: String?
    var content: String
    var updatedAt: String?

    enum CodingKeys: String, CodingKey {
        case id
        case profileId = "profile_id"
        case type
        case title
        case markdownPath = "markdown_path"
        case content
        case updatedAt = "updated_at"
    }
}

struct IntegrationProgress: Codable, Equatable {
    var phase: String
    var current: Int
    var total: Int
    var message: String
    var detail: String?
    var updatedAt: String?

    enum CodingKeys: String, CodingKey {
        case phase
        case current
        case total
        case message
        case detail
        case updatedAt = "updated_at"
    }

    var fraction: Double? {
        guard total > 0 else { return nil }
        return min(max(Double(current) / Double(total), 0), 1)
    }

    var isTerminal: Bool {
        phase == "done" || phase == "failed"
    }
}

struct WorkerMessage: Codable, Hashable {
    var ok: Bool
    var message: String?
}

struct ProfilesResponse: Codable {
    var ok: Bool
    var profiles: [ResearchProfile]
}

struct PapersResponse: Codable {
    var ok: Bool
    var papers: [Paper]
}

struct MemoryResponse: Codable {
    var ok: Bool
    var notes: [MemoryNote]
}

struct MemoryNoteResponse: Codable {
    var ok: Bool
    var note: MemoryNote
}

struct IngestResponse: Codable {
    var ok: Bool
    var inserted: Int
    var updated: Int
    var total: Int
    var errors: [String]
}

struct RankResponse: Codable {
    var ok: Bool
    var scored: Int
}

struct AnalyzeResponse: Codable {
    var ok: Bool
    var status: String
    var analysis: [String: JSONValue]
}

struct ExportResponse: Codable {
    var ok: Bool
    var files: [String]
}

enum JSONValue: Codable, Hashable {
    case string(String)
    case number(Double)
    case bool(Bool)
    case object([String: JSONValue])
    case array([JSONValue])
    case null

    init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if container.decodeNil() {
            self = .null
        } else if let value = try? container.decode(Bool.self) {
            self = .bool(value)
        } else if let value = try? container.decode(Double.self) {
            self = .number(value)
        } else if let value = try? container.decode(String.self) {
            self = .string(value)
        } else if let value = try? container.decode([JSONValue].self) {
            self = .array(value)
        } else {
            self = .object(try container.decode([String: JSONValue].self))
        }
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        switch self {
        case .string(let value):
            try container.encode(value)
        case .number(let value):
            try container.encode(value)
        case .bool(let value):
            try container.encode(value)
        case .object(let value):
            try container.encode(value)
        case .array(let value):
            try container.encode(value)
        case .null:
            try container.encodeNil()
        }
    }
}
