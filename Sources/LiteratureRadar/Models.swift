import Foundation

enum AppLanguage: String, CaseIterable, Identifiable, Codable {
    case english
    case simplifiedChinese

    var id: String { rawValue }
    var displayName: String {
        switch self {
        case .english: "English"
        case .simplifiedChinese: "简体中文"
        }
    }
}

enum AppThemeMode: String, CaseIterable, Identifiable, Codable {
    case system
    case light
    case dark

    var id: String { rawValue }
    var displayName: String {
        switch self {
        case .system: "Follow System"
        case .light: "Light Appearance"
        case .dark: "Dark Appearance"
        }
    }
}

enum AppSection: String, CaseIterable, Identifiable, Codable, Hashable {
    case overview
    case radar
    case search
    case profiles
    case memory
    case library
    case settings

    var id: String { rawValue }
    var title: String {
        switch self {
        case .overview: "Research OS"
        case .radar: "Today Radar"
        case .search: "Search Lab"
        case .profiles: "Research Profiles"
        case .memory: "Memory OS"
        case .library: "Read Papers"
        case .settings: "Settings"
        }
    }
    var systemImage: String {
        switch self {
        case .overview: "sparkles.rectangle.stack"
        case .radar: "dot.radiowaves.left.and.right"
        case .search: "magnifyingglass"
        case .profiles: "slider.horizontal.3"
        case .memory: "brain.head.profile"
        case .library: "books.vertical"
        case .settings: "gearshape"
        }
    }
}

enum RadarSortMode: String, CaseIterable, Identifiable, Codable {
    case relevance
    case time

    var id: String { rawValue }
}

struct WorkerMessage: Codable {
    var ok: Bool
    var message: String?
}

struct ResearchProfile: Identifiable, Codable, Hashable {
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
        case id, name, weight
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

    static var empty: ResearchProfile {
        ResearchProfile(
            id: UUID().uuidString,
            name: "New Profile",
            weight: 1.0,
            includeTerms: [],
            excludeTerms: [],
            seedPapers: [],
            watchAuthors: [],
            watchLabs: [],
            arxivQuery: "",
            biorxivQuery: "",
            createdAt: nil,
            updatedAt: nil
        )
    }
}

struct ProfilesResponse: Codable {
    var ok: Bool
    var profiles: [ResearchProfile]
}

struct ProfileResponse: Codable {
    var ok: Bool
    var profile: ResearchProfile
    var message: String?
}

struct PaperScore: Codable, Hashable {
    var profileId: String?
    var paperId: String?
    var bm25Score: Double?
    var embeddingScore: Double?
    var ruleScore: Double?
    var finalScore: Double?
    var reason: String?
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

struct PaperExport: Codable, Hashable {
    var exportType: String?
    var path: String?
    var createdAt: String?

    enum CodingKeys: String, CodingKey {
        case exportType = "export_type"
        case path
        case createdAt = "created_at"
    }
}

struct Paper: Identifiable, Codable, Hashable {
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
    var pdfPath: String?
    var category: String?
    var version: String?
    var createdAt: String?
    var updatedAt: String?
    var score: PaperScore?
    var analysisStatus: String?
    var actions: [String]
    var exports: [String]

    enum CodingKeys: String, CodingKey {
        case id, source, doi, title, abstract, authors, url, category, version, score, actions, exports
        case arxivId = "arxiv_id"
        case publishedDate = "published_date"
        case updatedDate = "updated_date"
        case pdfUrl = "pdf_url"
        case pdfPath = "pdf_path"
        case createdAt = "created_at"
        case updatedAt = "updated_at"
        case analysisStatus = "analysis_status"
    }

    var dateLabel: String { publishedDate ?? updatedDate ?? "No date" }
    var sourceLabel: String { source.uppercased() }
    var finalScore: Double { score?.finalScore ?? 0 }
    var finalScorePercent: String {
        if finalScore > 1 {
            return "\(Int(finalScore.rounded()))%"
        }
        return "\(Int((max(0, min(finalScore, 1)) * 100).rounded()))%"
    }
    var isRead: Bool { actions.contains("read") }
}

struct PapersResponse: Codable {
    var ok: Bool
    var papers: [Paper]
    var count: Int?
}

struct IngestResponse: Codable {
    var ok: Bool
    var count: Int?
    var inserted: Int?
    var papers: [Paper]?
}

struct RankResponse: Codable {
    var ok: Bool
    var scored: Int?
}

struct AnalyzeResponse: Codable {
    var ok: Bool
    var status: String?
    var analysis: JSONValue?
}

struct MemoryNote: Identifiable, Codable, Hashable {
    var id: String
    var profileId: String?
    var type: String
    var title: String
    var markdownPath: String?
    var content: String
    var updatedAt: String?

    enum CodingKeys: String, CodingKey {
        case id, type, title, content
        case profileId = "profile_id"
        case markdownPath = "markdown_path"
        case updatedAt = "updated_at"
    }
}

struct MemoryResponse: Codable {
    var ok: Bool
    var notes: [MemoryNote]
}

struct MemoryNoteResponse: Codable {
    var ok: Bool
    var note: MemoryNote
}

struct ExportResponse: Codable {
    var ok: Bool
    var files: [String]
}

struct IntegrationProgress: Decodable, Hashable {
    var phase: String
    var current: Int
    var total: Int
    var message: String
    var detail: String?
    var updatedAt: String?

    enum CodingKeys: String, CodingKey {
        case phase, current, completed, total, message, detail
        case updatedAt = "updated_at"
    }

    init(phase: String, current: Int, total: Int, message: String, detail: String?, updatedAt: String?) {
        self.phase = phase
        self.current = current
        self.total = total
        self.message = message
        self.detail = detail
        self.updatedAt = updatedAt
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        phase = try container.decodeIfPresent(String.self, forKey: .phase) ?? "preparing"
        current = try container.decodeIfPresent(Int.self, forKey: .current) ?? container.decodeIfPresent(Int.self, forKey: .completed) ?? 0
        total = try container.decodeIfPresent(Int.self, forKey: .total) ?? 0
        message = try container.decodeIfPresent(String.self, forKey: .message) ?? ""
        detail = try container.decodeIfPresent(String.self, forKey: .detail)
        updatedAt = try container.decodeIfPresent(String.self, forKey: .updatedAt)
    }

    var isTerminal: Bool { ["done", "complete", "failed"].contains(phase.lowercased()) }
    var fraction: Double { total == 0 ? 0 : Double(current) / Double(total) }
}

struct MemoryDashboardResponse: Codable {
    var ok: Bool
    var dashboard: MemoryDashboard
}

struct MemoryDashboard: Codable, Hashable {
    var counts: [String: Int]
    var interests: [InterestState]
    var recentEvents: [RecentEvent]
    var nodeTypes: [NodeTypeCount]
    var pendingReview: Int
    var health: MemoryHealth

    enum CodingKeys: String, CodingKey {
        case counts, interests, health
        case recentEvents = "recent_events"
        case nodeTypes = "node_types"
        case pendingReview = "pending_review"
    }
}

struct InterestState: Codable, Hashable, Identifiable {
    var id: String { topic }
    var topic: String
    var intensity: Double
    var positiveSignalCount: Int?
    var negativeSignalCount: Int?
    var lastActivatedAt: String?

    enum CodingKeys: String, CodingKey {
        case topic, intensity
        case positiveSignalCount = "positive_signal_count"
        case negativeSignalCount = "negative_signal_count"
        case lastActivatedAt = "last_activated_at"
    }
}

struct RecentEvent: Codable, Hashable, Identifiable {
    var id: String { "\(eventType)-\(objectType ?? "")-\(objectId ?? "")-\(occurredAt ?? "")" }
    var eventType: String
    var objectType: String?
    var objectId: String?
    var occurredAt: String?
    var importance: Double?

    enum CodingKeys: String, CodingKey {
        case eventType = "event_type"
        case objectType = "object_type"
        case objectId = "object_id"
        case occurredAt = "occurred_at"
        case importance
    }
}

struct NodeTypeCount: Codable, Hashable, Identifiable {
    var id: String { type }
    var type: String
    var count: Int
}

struct MemoryHealth: Codable, Hashable {
    var score: Double
    var unbackedClaims: Int
    var orphanEdges: Int
    var pendingReview: Int
    var draftNodes: Int

    enum CodingKeys: String, CodingKey {
        case score
        case unbackedClaims = "unbacked_claims"
        case orphanEdges = "orphan_edges"
        case pendingReview = "pending_review"
        case draftNodes = "draft_nodes"
    }
}

struct MindMapResponse: Codable, Hashable {
    var ok: Bool
    var tree: KnowledgeTreeNode
    var nodes: [KnowledgeGraphNode]
    var edges: [KnowledgeGraphEdge]
    var insights: [MemoryInsight]
}

struct KnowledgeTreeNode: Codable, Hashable, Identifiable {
    var id: String { "\(kind)-\(title)" }
    var title: String
    var kind: String
    var intensity: Double?
    var confidence: Double?
    var claimCount: Int?
    var paperCount: Int?
    var children: [KnowledgeTreeNode]

    enum CodingKeys: String, CodingKey {
        case title, kind, intensity, confidence, children
        case claimCount = "claim_count"
        case paperCount = "paper_count"
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        title = try container.decodeIfPresent(String.self, forKey: .title) ?? "Untitled"
        kind = try container.decodeIfPresent(String.self, forKey: .kind) ?? "node"
        intensity = try container.decodeIfPresent(Double.self, forKey: .intensity)
        confidence = try container.decodeIfPresent(Double.self, forKey: .confidence)
        claimCount = try container.decodeIfPresent(Int.self, forKey: .claimCount)
        paperCount = try container.decodeIfPresent(Int.self, forKey: .paperCount)
        children = try container.decodeIfPresent([KnowledgeTreeNode].self, forKey: .children) ?? []
    }
}

struct KnowledgeGraphNode: Codable, Hashable, Identifiable {
    var id: String
    var type: String
    var name: String
    var summary: String?
    var confidence: Double
    var status: String
}

struct KnowledgeGraphEdge: Codable, Hashable, Identifiable {
    var id: String
    var source: String
    var relation: String
    var target: String
    var confidence: Double
    var status: String
}

struct MemoryInsight: Codable, Hashable, Identifiable {
    var id: String
    var type: String
    var content: String
    var status: String
    var confidence: Double
}

struct ContextPacketResponse: Codable, Hashable {
    var ok: Bool
    var contextPacketId: String
    var retrievalTraceId: String
    var packet: ContextPacket

    enum CodingKeys: String, CodingKey {
        case ok, packet
        case contextPacketId = "context_packet_id"
        case retrievalTraceId = "retrieval_trace_id"
    }
}

struct ContextPacket: Codable, Hashable {
    var task: String
    var query: String
    var activeResearchDirection: JSONValue?
    var semanticContext: [JSONValue]
    var evidenceContext: [JSONValue]
    var episodicContext: [JSONValue]
    var methodologyContext: [JSONValue]
    var metacognitiveContext: [JSONValue]
    var forbiddenAssumptions: [String]

    enum CodingKeys: String, CodingKey {
        case task, query
        case activeResearchDirection = "active_research_direction"
        case semanticContext = "semantic_context"
        case evidenceContext = "evidence_context"
        case episodicContext = "episodic_context"
        case methodologyContext = "methodology_context"
        case metacognitiveContext = "metacognitive_context"
        case forbiddenAssumptions = "forbidden_assumptions"
    }
}

struct ReviewQueueResponse: Codable, Hashable {
    var ok: Bool
    var items: [ReviewItem]
}

struct ReviewItem: Codable, Hashable, Identifiable {
    var id: String
    var changeSetId: String?
    var item: JSONValue?
    var riskLevel: String?
    var status: String?
    var createdAt: String?
    var resolvedAt: String?

    enum CodingKeys: String, CodingKey {
        case id, item, status
        case changeSetId = "change_set_id"
        case riskLevel = "risk_level"
        case createdAt = "created_at"
        case resolvedAt = "resolved_at"
    }
}

enum JSONValue: Codable, Hashable, CustomStringConvertible {
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
        } else if let value = try? container.decode([String: JSONValue].self) {
            self = .object(value)
        } else if let value = try? container.decode([JSONValue].self) {
            self = .array(value)
        } else {
            self = .null
        }
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        switch self {
        case .string(let value): try container.encode(value)
        case .number(let value): try container.encode(value)
        case .bool(let value): try container.encode(value)
        case .object(let value): try container.encode(value)
        case .array(let value): try container.encode(value)
        case .null: try container.encodeNil()
        }
    }

    var description: String {
        switch self {
        case .string(let value): value
        case .number(let value): String(format: "%.3g", value)
        case .bool(let value): value ? "true" : "false"
        case .null: "null"
        case .array(let value): value.map(\.description).joined(separator: ", ")
        case .object(let value):
            value.map { key, val in "\(key): \(val.description)" }.sorted().joined(separator: "\n")
        }
    }

    var pretty: String {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        if let data = try? encoder.encode(self), let text = String(data: data, encoding: .utf8) {
            return text
        }
        return description
    }
}
