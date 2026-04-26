import Foundation
import SwiftUI

@MainActor
final class AppViewModel: ObservableObject {
    @Published var selectedSection: AppSection = .overview
    @Published var language: AppLanguage {
        didSet {
            UserDefaults.standard.set(language.rawValue, forKey: "appLanguage")
        }
    }
    @Published var papers: [Paper] = []
    @Published var searchResults: [Paper] = []
    @Published var readPapers: [Paper] = []
    @Published var profiles: [ResearchProfile] = []
    @Published var memoryNotes: [MemoryNote] = []
    @Published var memoryDashboard: MemoryDashboard?
    @Published var mindMap: MindMapResponse?
    @Published var reviewItems: [ReviewItem] = []
    @Published var contextPacket: ContextPacketResponse?
    @Published var contextQuery: String = ""
    @Published var selectedMemoryNoteID: String?
    @Published var selectedMemoryNote: MemoryNote?
    @Published var isLoadingMemoryNote: Bool = false
    @Published var zoteroImportCandidates: [Paper] = []
    @Published var selectedZoteroPaperIDs: Set<String> = []
    @Published var integrationProgress: IntegrationProgress?
    @Published var selectedProfileID: String?
    @Published var searchQuery: String = ""
    @Published var searchMode: String = "relevance"
    @Published var radarSortMode: RadarSortMode = .relevance
    @Published var useLiveAPIs: Bool = false
    @Published var isBusy: Bool = false
    @Published var statusLine: String
    @Published var obsidianPath: String = "\(NSHomeDirectory())/Documents/LiteratureRadarVault"
    @Published var readerAPIKeyDraft: String
    @Published var flashAPIKeyDraft: String
    @Published var didBootstrap: Bool = false
    @Published var showStatusHints: Bool {
        didSet {
            UserDefaults.standard.set(showStatusHints, forKey: "showStatusHints")
        }
    }
    @Published var fontSize: Double {
        didSet {
            UserDefaults.standard.set(fontSize, forKey: "fontSize")
        }
    }
    @Published var themeMode: AppThemeMode {
        didSet {
            UserDefaults.standard.set(themeMode.rawValue, forKey: "themeMode")
        }
    }

    private nonisolated let worker = WorkerClient()
    private var didLoadDeepSeekKeyDrafts = false

    var isIntegratingMemory: Bool {
        if let integrationProgress {
            return !integrationProgress.isTerminal
        }
        return false
    }

    init() {
        let rawLanguage = UserDefaults.standard.string(forKey: "appLanguage")
        let initialLanguage = AppLanguage(rawValue: rawLanguage ?? "") ?? .simplifiedChinese
        self.language = initialLanguage
        self.readerAPIKeyDraft = ""
        self.flashAPIKeyDraft = ""
        self.statusLine = L10n.text("Ready", initialLanguage)
        self.showStatusHints = UserDefaults.standard.bool(forKey: "showStatusHints")
        let savedFontSize = UserDefaults.standard.double(forKey: "fontSize")
        self.fontSize = savedFontSize > 0 ? savedFontSize : 14
        let rawTheme = UserDefaults.standard.string(forKey: "themeMode")
        self.themeMode = AppThemeMode(rawValue: rawTheme ?? "") ?? .system
    }

    var selectedProfile: ResearchProfile? {
        guard let selectedProfileID else { return profiles.first }
        return profiles.first { $0.id == selectedProfileID }
    }

    func t(_ key: String) -> String {
        L10n.text(key, language)
    }

    var displayedRadarPapers: [Paper] {
        switch radarSortMode {
        case .relevance:
            return papers
        case .time:
            return papers.sorted {
                ($0.publishedDate ?? $0.updatedDate ?? "") > ($1.publishedDate ?? $1.updatedDate ?? "")
            }
        }
    }

    func bootstrap() async {
        guard !didBootstrap else { return }
        didBootstrap = true
        await runBusy("Initializing database") { [self] in
            let _: WorkerMessage = try await self.worker.run("init", payload: ["seed_demo": false], timeout: 10)
            try await self.refreshAll()
        }
        if papers.isEmpty {
            statusLine = t("Initializing local database only. Use Demo or Run Radar after the app opens.")
        }
    }

    func refreshAll() async throws {
        let profileResponse: ProfilesResponse = try await worker.run("profile-list", timeout: 10)
        profiles = profileResponse.profiles
        if selectedProfileID == nil {
            selectedProfileID = profiles.first?.id
        }
        let paperResponse: PapersResponse = try await worker.run(
            "list-papers",
            payload: ["profile_id": selectedProfileID ?? "", "limit": 35],
            timeout: 15
        )
        papers = paperResponse.papers
        let memoryResponse: MemoryResponse = try await worker.run(
            "memory-list",
            payload: ["profile_id": selectedProfileID ?? "", "include_content": false],
            timeout: 10
        )
        memoryNotes = memoryResponse.notes
        if let selectedMemoryNoteID,
           !memoryResponse.notes.contains(where: { $0.id == selectedMemoryNoteID }) {
            self.selectedMemoryNoteID = nil
            self.selectedMemoryNote = nil
        }
        let readResponse: PapersResponse = try await worker.run(
            "read-papers",
            payload: ["profile_id": selectedProfileID ?? "", "limit": 200],
            timeout: 15
        )
        readPapers = readResponse.papers
        let dashboardResponse: MemoryDashboardResponse = try await worker.run(
            "memory-dashboard",
            payload: ["profile_id": selectedProfileID ?? ""],
            timeout: 15
        )
        memoryDashboard = dashboardResponse.dashboard
        mindMap = try await worker.run(
            "mind-map",
            payload: ["profile_id": selectedProfileID ?? ""],
            timeout: 15
        )
        let reviewResponse: ReviewQueueResponse = try await worker.run("review-list", timeout: 15)
        reviewItems = reviewResponse.items
    }

    func ingestDemo() async {
        await runBusy("Loading demo papers") { [self] in
            let _: IngestResponse = try await self.worker.run("ingest", payload: ["demo": true], timeout: 20)
            let _: RankResponse = try await self.worker.run("rank", timeout: 30)
            try await self.refreshAll()
        }
    }

    func runRadar() async {
        await runBusy("Running radar") { [self] in
            let payload: [String: Any] = [
                "sources": ["arxiv", "biorxiv", "europepmc"],
                "limit": 30,
                "profiles": self.selectedProfileID.map { [$0] } ?? []
            ]
            let _: IngestResponse = try await self.worker.run("ingest", payload: payload, timeout: 120)
            let _: RankResponse = try await self.worker.run("rank", timeout: 30)
            try await self.refreshAll()
        }
    }

    func runSearch() async {
        guard !searchQuery.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            statusLine = t("Enter a query first.")
            return
        }
        await runBusy("Searching") { [self] in
            let response: PapersResponse = try await self.worker.run(
                "search",
                payload: [
                    "query": self.searchQuery,
                    "mode": self.searchMode,
                    "profile_id": self.selectedProfileID ?? "",
                    "live": self.useLiveAPIs,
                    "limit": 40
                ],
                timeout: self.useLiveAPIs ? 120 : 25
            )
            self.searchResults = response.papers
            let _: RankResponse = try await self.worker.run("rank", timeout: 30)
            try await self.refreshAll()
        }
    }

    func saveProfile(_ profile: ResearchProfile) async {
        await runBusy("Saving profile") { [self] in
            let _: WorkerMessage = try await self.worker.run(
                "profile-upsert",
                payload: [
                    "id": profile.id,
                    "name": profile.name,
                    "weight": profile.weight,
                    "include_terms": profile.includeTerms,
                    "exclude_terms": profile.excludeTerms,
                    "seed_papers": profile.seedPapers,
                    "watch_authors": profile.watchAuthors,
                    "watch_labs": profile.watchLabs,
                    "arxiv_query": profile.arxivQuery,
                    "biorxiv_query": profile.biorxivQuery
                ]
            )
            try await self.refreshAll()
        }
    }

    func createProfile() async {
        await runBusy("Creating profile") { [self] in
            let _: WorkerMessage = try await self.worker.run(
                "profile-upsert",
                payload: [
                    "name": "New Profile",
                    "weight": 1.0,
                    "include_terms": [],
                    "exclude_terms": [],
                    "seed_papers": [],
                    "watch_authors": [],
                    "watch_labs": []
                ]
            )
            try await self.refreshAll()
        }
    }

    func createProfileFromDescription(_ description: String) async {
        let trimmed = description.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else {
            statusLine = t("Describe the research direction first.")
            return
        }
        await runBusy("Generating profile") { [self] in
            let response: ProfileResponse = try await self.worker.run(
                "profile-from-description",
                payload: [
                    "description": trimmed,
                    "model": "deepseek-v4-flash"
                ],
                timeout: 90
            )
            self.selectedProfileID = response.profile.id
            try await self.refreshAll()
            self.statusLine = response.message ?? self.t("Generated profile")
        }
    }

    func deleteProfile(_ profile: ResearchProfile) async {
        await runBusy("Deleting profile") { [self] in
            let _: WorkerMessage = try await self.worker.run(
                "profile-delete",
                payload: ["id": profile.id],
                timeout: 15
            )
            if self.selectedProfileID == profile.id {
                self.selectedProfileID = nil
            }
            try await self.refreshAll()
        }
    }

    func sendFeedback(_ action: String, paper: Paper) async {
        await runBusy("Saving feedback") { [self] in
            let _: WorkerMessage = try await self.worker.run(
                "feedback",
                payload: [
                    "paper_id": paper.id,
                    "profile_id": self.selectedProfileID ?? "",
                    "action": action
                ]
            )
            let _: RankResponse = try await self.worker.run("rank", timeout: 30)
            try await self.refreshAll()
        }
    }

    func analyze(_ paper: Paper) async {
        await runBusy("Analyzing paper") { [self] in
            let _: AnalyzeResponse = try await self.worker.run(
                "analyze",
                payload: [
                    "paper_id": paper.id,
                    "profile_id": self.selectedProfileID ?? "",
                    "model": "deepseek-v4-flash"
                ]
            )
            try await self.refreshAll()
        }
    }

    func assessUsefulness(_ paper: Paper) async {
        await runBusy("Assessing paper usefulness") { [self] in
            let _: AnalyzeResponse = try await self.worker.run(
                "usefulness",
                payload: [
                    "paper_id": paper.id,
                    "profile_id": self.selectedProfileID ?? "",
                    "obsidian_path": self.obsidianPath,
                    "model": "deepseek-v4-pro"
                ],
                timeout: 120
            )
            try await self.refreshAll()
            self.selectedSection = .memory
        }
    }

    func markRead(_ paper: Paper) async {
        await sendFeedback("read", paper: paper)
    }

    func synthesizeWeekly() async {
        await runBusy("Synthesizing weekly memory") { [self] in
            let _: MemoryResponse = try await self.worker.run(
                "synthesize",
                payload: [
                    "profile_id": self.selectedProfileID ?? "",
                    "type": "weekly_digest",
                    "obsidian_path": self.obsidianPath,
                    "model": "deepseek-v4-pro"
                ]
            )
            try await self.refreshAll()
        }
    }

    func loadMemoryNote(id: String?) async {
        guard let id else {
            selectedMemoryNoteID = nil
            selectedMemoryNote = nil
            return
        }
        selectedMemoryNoteID = id
        if selectedMemoryNote?.id == id {
            return
        }
        isLoadingMemoryNote = true
        do {
            let response: MemoryNoteResponse = try await worker.run(
                "memory-get",
                payload: ["id": id],
                timeout: 20
            )
            if selectedMemoryNoteID == id {
                selectedMemoryNote = response.note
            }
        } catch {
            statusLine = error.localizedDescription
        }
        isLoadingMemoryNote = false
    }

    func exportObsidian() async {
        await runBusy("Exporting Obsidian vault") { [self] in
            let response: ExportResponse = try await self.worker.run(
                "export",
                payload: [
                    "format": "obsidian",
                    "path": self.obsidianPath,
                    "profile_id": self.selectedProfileID ?? ""
                ]
            )
            self.statusLine = "Exported \(response.files.count) Obsidian files."
            try await self.refreshAll()
        }
    }

    func exportZotero() async {
        await runBusy("Exporting Zotero files") { [self] in
            let exportPath = "\(NSHomeDirectory())/Documents/LiteratureRadarZotero"
            let response: ExportResponse = try await self.worker.run(
                "export",
                payload: [
                    "format": "zotero",
                    "path": exportPath,
                    "profile_id": self.selectedProfileID ?? ""
                ]
            )
            self.statusLine = "Exported \(response.files.count) Zotero files to \(exportPath)."
        }
    }

    func loadDeepSeekKeyDraftsForEditing() {
        guard !didLoadDeepSeekKeyDrafts else { return }
        readerAPIKeyDraft = KeychainStore.loadReaderKey()
        flashAPIKeyDraft = KeychainStore.loadFlashKey()
        didLoadDeepSeekKeyDrafts = true
    }

    func saveDeepSeekKeys() {
        do {
            try KeychainStore.saveReaderKey(readerAPIKeyDraft)
            try KeychainStore.saveFlashKey(flashAPIKeyDraft)
            didLoadDeepSeekKeyDrafts = true
            statusLine = t("DeepSeek keys saved to Keychain.")
        } catch {
            statusLine = "Could not save key: \(error.localizedDescription)"
        }
    }

    func importZoteroFile(_ url: URL) async {
        await runBusy("Importing Zotero export") { [self] in
            let response: PapersResponse = try await self.worker.run(
                "zotero-import",
                payload: ["path": url.path],
                timeout: 120
            )
            self.zoteroImportCandidates = response.papers
            self.selectedZoteroPaperIDs = Set(response.papers.map(\.id))
            try await self.refreshAll()
        }
    }

    func integrateSelectedZoteroPapers() async {
        let selected = Array(selectedZoteroPaperIDs)
        guard !selected.isEmpty else {
            statusLine = "Select at least one imported paper."
            return
        }
        let progressURL = FileManager.default.temporaryDirectory
            .appendingPathComponent("litradar-integration-\(UUID().uuidString).json")
        integrationProgress = IntegrationProgress(
            phase: "preparing",
            current: 0,
            total: selected.count,
            message: t("Preparing long-term memory integration"),
            detail: nil,
            updatedAt: nil
        )
        let progressTask = startIntegrationProgressPolling(url: progressURL)
        isBusy = true
        statusLine = t("Integrating Zotero papers")
        do {
            let response: MemoryResponse = try await worker.run(
                "integrate-papers",
                payload: [
                    "paper_ids": selected,
                    "profile_id": selectedProfileID ?? "",
                    "obsidian_path": obsidianPath,
                    "model": "deepseek-v4-pro",
                    "progress_path": progressURL.path
                ],
                timeout: 1_800
            )
            memoryNotes = response.notes
            try await refreshAll()
            integrationProgress = IntegrationProgress(
                phase: "done",
                current: selected.count,
                total: selected.count,
                message: t("Long-term memory integration complete."),
                detail: nil,
                updatedAt: nil
            )
            selectedSection = .memory
            statusLine = "\(t("Done")): \(t("Integrating Zotero papers"))"
        } catch {
            integrationProgress = IntegrationProgress(
                phase: "failed",
                current: integrationProgress?.current ?? 0,
                total: integrationProgress?.total ?? selected.count,
                message: t("Long-term memory integration failed."),
                detail: error.localizedDescription,
                updatedAt: nil
            )
            statusLine = error.localizedDescription
        }
        progressTask.cancel()
        try? FileManager.default.removeItem(at: progressURL)
        isBusy = false
    }

    private func startIntegrationProgressPolling(url: URL) -> Task<Void, Never> {
        Task { [weak self] in
            let decoder = JSONDecoder()
            while !Task.isCancelled {
                if let data = try? Data(contentsOf: url),
                   let progress = try? decoder.decode(IntegrationProgress.self, from: data) {
                    self?.integrationProgress = progress
                }
                try? await Task.sleep(nanoseconds: 500_000_000)
            }
        }
    }

    func setZoteroSelection(_ paperID: String, isSelected: Bool) {
        if isSelected {
            selectedZoteroPaperIDs.insert(paperID)
        } else {
            selectedZoteroPaperIDs.remove(paperID)
        }
    }

    func refreshMemoryOS() async {
        await runBusy("Refreshing") { [self] in
            try await self.refreshAll()
        }
    }

    func rebuildKnowledgeTree() async {
        await runBusy("Rebuilding knowledge tree") { [self] in
            let _: WorkerMessage = try await self.worker.run(
                "rebuild-taxonomy",
                payload: ["profile_id": self.selectedProfileID ?? ""],
                timeout: 30
            )
            try await self.refreshAll()
        }
    }

    func buildContextPacket() async {
        let query = contextQuery.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !query.isEmpty else {
            statusLine = t("Enter a query first.")
            return
        }
        await runBusy("Assembling context packet") { [self] in
            let response: ContextPacketResponse = try await self.worker.run(
                "context-packet",
                payload: [
                    "query": query,
                    "task": "research_assistant",
                    "profile_id": self.selectedProfileID ?? ""
                ],
                timeout: 30
            )
            self.contextPacket = response
            try await self.refreshAll()
        }
    }

    func repairMemory(apply: Bool = false) async {
        await runBusy(apply ? "Repairing memory" : "Inspecting memory") { [self] in
            let _: WorkerMessage = try await self.worker.run(
                "repair-memory",
                payload: ["apply": apply],
                timeout: 30
            )
            try await self.refreshAll()
        }
    }

    private func runBusy(_ label: String, operation: @escaping () async throws -> Void) async {
        isBusy = true
        statusLine = t(label)
        do {
            try await operation()
            if statusLine == t(label) {
                statusLine = "\(t("Done")): \(t(label))"
            }
        } catch {
            statusLine = error.localizedDescription
        }
        isBusy = false
    }
}
