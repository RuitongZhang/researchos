import SwiftUI
import UniformTypeIdentifiers

struct ContentView: View {
    @StateObject private var model = AppViewModel()

    var body: some View {
        NavigationSplitView {
            SidebarView(model: model)
                .navigationSplitViewColumnWidth(min: 210, ideal: 240, max: 280)
        } detail: {
            ZStack {
                AppBackdrop()
                Group {
                    switch model.selectedSection {
                    case .overview:
                        OverviewView(model: model)
                    case .radar:
                        RadarView(model: model)
                    case .search:
                        SearchLabView(model: model)
                    case .profiles:
                        ProfilesView(model: model)
                    case .memory:
                        MemoryOSView(model: model)
                    case .library:
                        LibraryView(model: model)
                    case .settings:
                        SettingsView(model: model)
                    }
                }
                .padding(24)
            }
        }
        .task { await model.bootstrap() }
        .font(.system(size: model.fontSize))
        .preferredColorScheme(colorScheme)
        .frame(minWidth: 1180, minHeight: 760)
    }

    private var colorScheme: ColorScheme? {
        switch model.themeMode {
        case .system: nil
        case .light: .light
        case .dark: .dark
        }
    }
}

struct AppBackdrop: View {
    var body: some View {
        LinearGradient(
            colors: [Color(nsColor: .windowBackgroundColor), Color.accentColor.opacity(0.08), Color(nsColor: .controlBackgroundColor)],
            startPoint: .topLeading,
            endPoint: .bottomTrailing
        )
        .ignoresSafeArea()
    }
}

struct SidebarView: View {
    @ObservedObject var model: AppViewModel

    var body: some View {
        VStack(spacing: 0) {
            VStack(alignment: .leading, spacing: 8) {
                Label(model.t("Research OS"), systemImage: "brain.head.profile")
                    .font(.title3.weight(.semibold))
                Text(model.t("Literature Radar + Memory OS"))
                    .foregroundStyle(.secondary)
                    .font(.caption)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding()

            List(selection: $model.selectedSection) {
                ForEach(AppSection.allCases) { section in
                    Label(model.t(section.title), systemImage: section.systemImage)
                        .tag(section)
                }
            }
            .listStyle(.sidebar)

            if model.showStatusHints {
                VStack(alignment: .leading, spacing: 8) {
                    if model.isBusy {
                        ProgressView().controlSize(.small)
                    }
                    Text(model.statusLine)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .lineLimit(3)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding()
            }
        }
    }
}

struct OverviewView: View {
    @ObservedObject var model: AppViewModel

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                PageHeader(
                    title: model.t("Research Memory Operating System"),
                    subtitle: model.t("Connect radar, deep reading, evidence, knowledge graph, interest, insights, and methods into a traceable research memory system."),
                    icon: "sparkles.rectangle.stack"
                )
                DashboardCards(model: model)
                HStack(alignment: .top, spacing: 16) {
                    GlassCard(title: model.t("Next Workflow"), systemImage: "arrow.triangle.branch") {
                        VStack(alignment: .leading, spacing: 12) {
                            WorkflowStep(number: "1", title: model.t("Radar Discovery"), detail: model.t("Search and shallow reading only write events and interest states, without polluting factual knowledge."))
                            WorkflowStep(number: "2", title: model.t("DeepSeek Deep Read"), detail: model.t("Deep reading creates MemoryChangeSet, evidence spans, atomic knowledge, and insights."))
                            WorkflowStep(number: "3", title: model.t("Consolidate and Repair"), detail: model.t("High-risk changes enter the review queue; every write keeps provenance and rollback clues."))
                        }
                    }
                    .frame(maxWidth: .infinity)

                    GlassCard(title: model.t("Recent Candidates"), systemImage: "doc.text.magnifyingglass") {
                        VStack(spacing: 10) {
                            ForEach(model.displayedRadarPapers.prefix(5)) { paper in
                                CompactPaperRow(model: model, paper: paper)
                            }
                            if model.papers.isEmpty {
                                EmptyHint(text: model.t("No papers yet. Open Today Radar or run Radar first."))
                            }
                        }
                    }
                    .frame(maxWidth: .infinity)
                }
            }
        }
    }
}

struct DashboardCards: View {
    @ObservedObject var model: AppViewModel

    var body: some View {
        let dashboard = model.memoryDashboard
        LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: 14), count: 4), spacing: 14) {
            StatCard(title: model.t("Papers"), value: "\(dashboard?.counts["papers"] ?? model.papers.count)", caption: model.t("Local candidate library"), icon: "doc.text")
            StatCard(title: model.t("Knowledge Nodes"), value: "\(dashboard?.counts["knowledge_nodes"] ?? 0)", caption: model.t("Structured knowledge nodes"), icon: "circle.hexagongrid")
            StatCard(title: model.t("Evidence"), value: "\(dashboard?.counts["evidence_spans"] ?? 0)", caption: model.t("Traceable evidence spans"), icon: "quote.bubble")
            StatCard(title: model.t("Health"), value: "\(Int(((dashboard?.health.score ?? 1.0) * 100).rounded()))%", caption: model.t("Memory health"), icon: "heart.text.square")
        }
    }
}

struct RadarView: View {
    @ObservedObject var model: AppViewModel

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            PageHeader(title: model.t("Today Radar"), subtitle: model.t("Prioritizes newly found online papers you have not read; local papers are only shown as a small supplement."), icon: "dot.radiowaves.left.and.right")
            ToolbarCard {
                ProfilePicker(model: model)
                Picker(model.t("Sort by"), selection: $model.radarSortMode) {
                    Text(model.t("Relevance")).tag(RadarSortMode.relevance)
                    Text(model.t("Time")).tag(RadarSortMode.time)
                }
                .pickerStyle(.segmented)
                .frame(width: 190)
                Spacer()
                AsyncButton(title: model.t("Run Radar"), systemImage: "antenna.radiowaves.left.and.right") { await model.runRadar() }
                AsyncButton(title: model.t("Refresh"), systemImage: "arrow.clockwise") { await model.refreshMemoryOS() }
            }
            PaperListView(model: model, papers: model.displayedRadarPapers)
        }
        .task { await model.ensureRadarHasOnlineCandidates() }
    }
}

struct SearchLabView: View {
    @ObservedObject var model: AppViewModel

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            PageHeader(title: model.t("Search Lab"), subtitle: model.t("Run relevance search or broader exploration against local and live sources."), icon: "magnifyingglass")
            ToolbarCard {
                TextField(model.t("Query, DOI, arXiv ID, author, or topic"), text: $model.searchQuery)
                    .textFieldStyle(.roundedBorder)
                Picker(model.t("Mode"), selection: $model.searchMode) {
                    Text(model.t("Relevance")).tag("relevance")
                    Text(model.t("Explore")).tag("explore")
                }
                .pickerStyle(.segmented)
                .frame(width: 180)
                Toggle(model.t("Search online"), isOn: $model.useLiveAPIs)
                AsyncButton(title: model.t("Search"), systemImage: "magnifyingglass") { await model.runSearch() }
            }
            PaperListView(model: model, papers: model.searchResults)
        }
    }
}

struct PaperListView: View {
    @ObservedObject var model: AppViewModel
    var papers: [Paper]

    var body: some View {
        ScrollView {
            LazyVStack(spacing: 12) {
                ForEach(papers) { paper in
                    PaperCard(model: model, paper: paper)
                }
                if papers.isEmpty {
                    EmptyHint(text: model.t("No papers yet"))
                }
            }
            .padding(.vertical, 4)
        }
    }
}

struct PaperCard: View {
    @ObservedObject var model: AppViewModel
    var paper: Paper

    var body: some View {
        GlassCard {
            VStack(alignment: .leading, spacing: 10) {
                HStack(alignment: .top) {
                    VStack(alignment: .leading, spacing: 6) {
                        HStack(spacing: 8) {
                            Badge(paper.isLocalSource ? model.t("Local") : paper.sourceLabel, color: paper.isLocalSource ? .green : .accentColor)
                            Badge(paper.publishedDate ?? paper.updatedDate ?? model.t("No date"))
                            if let status = paper.analysisStatus { Badge(model.t(status)) }
                            if paper.isRead { Badge(model.t("read")) }
                        }
                        Text(paper.title)
                            .font(.headline)
                            .fixedSize(horizontal: false, vertical: true)
                        Text(paper.authors.prefix(5).joined(separator: ", "))
                            .foregroundStyle(.secondary)
                            .font(.caption)
                    }
                    Spacer()
                    VStack(alignment: .trailing, spacing: 4) {
                        Text(paper.finalScorePercent)
                            .font(.title3.weight(.semibold))
                        Text(model.t(paper.score?.reason ?? "local"))
                            .font(.caption2)
                            .foregroundStyle(.secondary)
                    }
                }
                Text(paper.abstract)
                    .font(.callout)
                    .foregroundStyle(.secondary)
                    .lineLimit(4)
                HStack {
                    AsyncButton(title: model.t("Mark read"), systemImage: "checkmark.circle") { await model.markRead(paper) }
                    AsyncButton(title: model.t("Like"), systemImage: "hand.thumbsup") { await model.sendFeedback("like", paper: paper) }
                    AsyncButton(title: model.t("Analyze"), systemImage: "bolt") { await model.analyze(paper) }
                    AsyncButton(title: model.t("Assess usefulness"), systemImage: "brain") { await model.assessUsefulness(paper) }
                    if let url = paper.url, let link = URL(string: url) {
                        Link(model.t("Open"), destination: link)
                    }
                    Spacer()
                }
                .buttonStyle(.bordered)
            }
        }
    }
}

struct CompactPaperRow: View {
    @ObservedObject var model: AppViewModel
    var paper: Paper
    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            Image(systemName: "doc.text")
                .foregroundStyle(.tint)
            VStack(alignment: .leading, spacing: 4) {
                Text(paper.title).font(.subheadline.weight(.medium)).lineLimit(2)
                Text("\(paper.sourceLabel) · \(paper.publishedDate ?? paper.updatedDate ?? model.t("No date")) · \(paper.finalScorePercent)")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            Spacer()
        }
    }
}

struct ProfilesView: View {
    @ObservedObject var model: AppViewModel
    @State private var draft = ResearchProfile.empty
    @State private var description = ""
    @FocusState private var isDescriptionFocused: Bool

    var body: some View {
        HStack(alignment: .top, spacing: 16) {
            VStack(alignment: .leading, spacing: 12) {
                PageHeader(title: model.t("Research Profiles"), subtitle: "研究方向不仅是关键词，也会驱动雷达、记忆检索、知识树和元认知反思。", icon: "slider.horizontal.3")
                GlassCard(title: model.t("Profile List"), systemImage: "list.bullet.rectangle") {
                    ScrollView {
                        VStack(spacing: 6) {
                            ForEach(model.profiles) { profile in
                                Button {
                                    model.selectedProfileID = profile.id
                                    draft = profile
                                    Task { try? await model.refreshAll() }
                                } label: {
                                    HStack {
                                        VStack(alignment: .leading, spacing: 5) {
                                            Text(profile.name).font(.headline)
                                            Text(profile.includeTerms.prefix(5).joined(separator: ", "))
                                                .font(.caption)
                                                .foregroundStyle(.secondary)
                                                .lineLimit(2)
                                        }
                                        Spacer()
                                        if model.selectedProfileID == profile.id { Image(systemName: "checkmark.circle.fill") }
                                    }
                                    .padding(.vertical, 10)
                                    .padding(.horizontal, 8)
                                    .frame(maxWidth: .infinity, alignment: .leading)
                                    .contentShape(Rectangle())
                                    .background(model.selectedProfileID == profile.id ? Color.accentColor.opacity(0.10) : Color.clear, in: RoundedRectangle(cornerRadius: 10))
                                }
                                .buttonStyle(.plain)
                                Divider()
                            }
                        }
                    }
                    .frame(minHeight: isDescriptionFocused ? 160 : 300, maxHeight: isDescriptionFocused ? 220 : 380)
                    HStack {
                        Spacer()
                        AsyncButton(title: model.t("New Profile"), systemImage: "plus") { await model.createProfile() }
                        Spacer()
                    }
                }
                GlassCard(title: model.t("Generate Profile"), systemImage: "wand.and.stars") {
                    VStack(alignment: .leading, spacing: 10) {
                        TextEditor(text: $description)
                            .focused($isDescriptionFocused)
                            .frame(height: isDescriptionFocused ? 360 : 92)
                        AsyncButton(title: model.t("Generate Profile"), systemImage: "sparkles") { await model.createProfileFromDescription(description) }
                        if let progress = model.profileGenerationProgress {
                            WorkflowProgressPanel(
                                model: model,
                                title: model.t("Profile Generation Progress"),
                                progress: progress,
                                phases: ["preparing", "calling_llm", "saving", "done"]
                            )
                        }
                    }
                }
            }
            .frame(width: 390)

            ProfileEditor(model: model, profile: $draft)
                .onAppear { draft = model.selectedProfile ?? model.profiles.first ?? .empty }
                .onChange(of: model.selectedProfileID) { _, _ in draft = model.selectedProfile ?? .empty }
        }
    }
}

struct ProfileEditor: View {
    @ObservedObject var model: AppViewModel
    @Binding var profile: ResearchProfile

    var body: some View {
        GlassCard(title: model.t("Edit"), systemImage: "pencil.and.outline") {
            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    TextField(model.t("Name"), text: $profile.name)
                    Slider(value: $profile.weight, in: 0.1...2.0) { Text(model.t("Weight")) }
                    ProfileField(model: model, title: model.t("Include terms"), values: $profile.includeTerms)
                    ProfileField(model: model, title: model.t("Exclude terms"), values: $profile.excludeTerms)
                    ProfileField(model: model, title: model.t("Seed papers"), values: $profile.seedPapers)
                    ProfileField(model: model, title: model.t("Watch authors"), values: $profile.watchAuthors)
                    ProfileField(model: model, title: model.t("Watch labs"), values: $profile.watchLabs)
                    TextField(model.t("arXiv query"), text: $profile.arxivQuery)
                    TextField(model.t("bioRxiv query"), text: $profile.biorxivQuery)
                    HStack {
                        AsyncButton(title: model.t("Save Profile"), systemImage: "square.and.arrow.down") { await model.saveProfile(profile) }
                        AsyncButton(title: model.t("Delete"), systemImage: "trash") { await model.deleteProfile(profile) }
                        Spacer()
                    }
                    .buttonStyle(.borderedProminent)
                }
            }
        }
    }
}

struct ProfileField: View {
    @ObservedObject var model: AppViewModel
    var title: String
    @Binding var values: [String]
    @State private var newValue = ""

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(title).font(.caption.weight(.semibold)).foregroundStyle(.secondary)
            ForEach(Array(values.enumerated()), id: \.offset) { idx, value in
                HStack {
                    TextField(title, text: Binding(get: { values[idx] }, set: { values[idx] = $0 }))
                    Button(role: .destructive) { values.remove(at: idx) } label: { Image(systemName: "minus.circle") }
                        .buttonStyle(.borderless)
                }
            }
            HStack {
                TextField(model.t("Add item"), text: $newValue)
                Button(model.t("Add")) {
                    let trimmed = newValue.trimmingCharacters(in: .whitespacesAndNewlines)
                    guard !trimmed.isEmpty else { return }
                    values.append(trimmed)
                    newValue = ""
                }
            }
        }
    }

}

struct MemoryOSView: View {
    @ObservedObject var model: AppViewModel
    @State private var showGlossary = false

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            PageHeader(title: model.t("Memory OS"), subtitle: model.t("Evidence, events, semantic knowledge graph, methods, metacognition, and working memory packets."), icon: "brain.head.profile")
            ToolbarCard {
                AsyncButton(title: model.t("Refresh"), systemImage: "arrow.clockwise") { await model.refreshMemoryOS() }
                AsyncButton(title: model.t("Rebuild Knowledge Tree"), systemImage: "point.3.connected.trianglepath.dotted") { await model.rebuildKnowledgeTree() }
                AsyncButton(title: model.t("Inspect Memory"), systemImage: "stethoscope") { await model.repairMemory(apply: false) }
                AsyncButton(title: model.t("Auto Repair"), systemImage: "wrench.and.screwdriver") { await model.repairMemory(apply: true) }
                Button {
                    showGlossary.toggle()
                } label: {
                    Label(model.t("Term Guide"), systemImage: "questionmark.circle")
                }
                .popover(isPresented: $showGlossary) {
                    MemoryGlossaryPanel(model: model)
                        .padding(16)
                        .frame(width: 420)
                }
                Spacer()
            }
            TabView {
                MemoryDashboardPanel(model: model).tabItem { Label(model.t("Dashboard"), systemImage: "gauge.with.dots.needle.67percent") }
                KnowledgeTreePanel(model: model).tabItem { Label(model.t("Knowledge Tree"), systemImage: "tree") }
                ContextPacketPanel(model: model).tabItem { Label(model.t("Context Packet"), systemImage: "shippingbox") }
                MemoryNotesPanel(model: model).tabItem { Label(model.t("Notes"), systemImage: "note.text") }
                ReviewQueuePanel(model: model).tabItem { Label(model.t("Review"), systemImage: "checklist") }
            }
        }
    }
}

struct MemoryGlossaryPanel: View {
    @ObservedObject var model: AppViewModel

    private var items: [(String, String)] {
        [
            ("Evidence", "Short source-backed passages extracted from papers."),
            ("Knowledge Nodes", "Concepts the app keeps as long-term research knowledge."),
            ("Knowledge Tree", "A topic hierarchy built from those concepts."),
            ("Interest States", "A lightweight estimate of what you currently care about."),
            ("Recent Events", "A log of actions such as reading, saving, feedback, and radar discovery."),
            ("Context Packet", "A temporary bundle of relevant memory for the current task."),
            ("Review", "High-risk memory changes that should be checked before trusting them.")
        ]
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Label(model.t("Term Guide"), systemImage: "questionmark.circle")
                .font(.headline)
            ForEach(items, id: \.0) { item in
                VStack(alignment: .leading, spacing: 3) {
                    Text(model.t(item.0)).font(.subheadline.weight(.semibold))
                    Text(model.t(item.1)).font(.caption).foregroundStyle(.secondary)
                }
            }
        }
    }
}

struct MemoryDashboardPanel: View {
    @ObservedObject var model: AppViewModel

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                DashboardCards(model: model)
                HStack(alignment: .top, spacing: 16) {
                    GlassCard(title: model.t("Interest States"), systemImage: "flame") {
                        FlowLayout(items: model.memoryDashboard?.interests ?? []) { item in
                            InterestChip(interest: item)
                        }
                        if model.memoryDashboard?.interests.isEmpty ?? true { EmptyHint(text: model.t("No shallow interest signals yet.")) }
                    }
                    .frame(maxWidth: .infinity)
                    GlassCard(title: model.t("Recent Events"), systemImage: "clock.arrow.circlepath") {
                        VStack(alignment: .leading, spacing: 8) {
                            ForEach(model.memoryDashboard?.recentEvents ?? []) { event in
                                HStack {
                                    Badge(model.t(event.eventType))
                                    Text(event.objectId ?? event.objectType ?? model.t("event"))
                                    Spacer()
                                    Text(event.occurredAt ?? "").font(.caption).foregroundStyle(.secondary)
                                }
                            }
                            if model.memoryDashboard?.recentEvents.isEmpty ?? true { EmptyHint(text: model.t("No event memory yet.")) }
                        }
                    }
                    .frame(maxWidth: .infinity)
                }
                GlassCard(title: model.t("System Layer Counts"), systemImage: "square.stack.3d.up") {
                    LazyVGrid(columns: Array(repeating: GridItem(.flexible()), count: 4), spacing: 10) {
                        ForEach((model.memoryDashboard?.counts ?? [:]).sorted(by: { $0.key < $1.key }), id: \.key) { key, value in
                            HStack {
                                Text(model.t(key.replacingOccurrences(of: "_", with: " "))).font(.caption)
                                Spacer()
                                Text("\(value)").bold()
                            }
                            .padding(10)
                            .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 12))
                        }
                    }
                }
            }
        }
    }
}

struct KnowledgeTreePanel: View {
    @ObservedObject var model: AppViewModel

    var body: some View {
        HStack(alignment: .top, spacing: 16) {
            GlassCard(title: model.t("Knowledge Tree"), systemImage: "tree") {
                ScrollView {
                    if let tree = model.mindMap?.tree {
                        TreeNodeView(node: tree, confidenceLabel: model.t("Confidence"))
                    } else {
                        EmptyHint(text: model.t("No knowledge tree yet."))
                    }
                }
            }
            .frame(maxWidth: .infinity)

            GlassCard(title: model.t("Graph Overview"), systemImage: "network") {
                VStack(alignment: .leading, spacing: 10) {
                    Text("\(model.t("Nodes")): \(model.mindMap?.nodes.count ?? 0)")
                    Text("\(model.t("Edges")): \(model.mindMap?.edges.count ?? 0)")
                    Divider()
                    ForEach(Array((model.mindMap?.insights ?? []).prefix(8))) { insight in
                        VStack(alignment: .leading, spacing: 3) {
                            HStack { Badge(insight.type); Text("\(Int(insight.confidence * 100))%") }
                            Text(insight.content).font(.callout)
                        }
                        Divider()
                    }
                    if model.mindMap?.insights.isEmpty ?? true { EmptyHint(text: model.t("No metacognitive insights yet.")) }
                }
            }
            .frame(width: 340)
        }
    }
}

struct TreeNodeView: View {
    var node: KnowledgeTreeNode
    var confidenceLabel: String

    var body: some View {
        if node.children.isEmpty {
            nodeLabel
                .padding(.vertical, 3)
        } else {
            DisclosureGroup(isExpanded: .constant(true)) {
                VStack(alignment: .leading, spacing: 4) {
                    ForEach(node.children) { child in
                        TreeNodeView(node: child, confidenceLabel: confidenceLabel)
                            .padding(.leading, 14)
                    }
                }
            } label: { nodeLabel }
            .padding(.vertical, 4)
        }
    }

    private var nodeLabel: some View {
        HStack(spacing: 8) {
            Badge(node.kind)
            Text(node.title).font(.callout.weight(.medium))
            if let intensity = node.intensity { Text("\(Int(intensity * 100))%").foregroundStyle(.secondary).font(.caption) }
            if let confidence = node.confidence { Text("\(confidenceLabel) \(Int(confidence * 100))%").foregroundStyle(.secondary).font(.caption) }
        }
    }
}

struct ContextPacketPanel: View {
    @ObservedObject var model: AppViewModel

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            ToolbarCard {
                TextField(model.t("Enter the current question or task to assemble a working memory packet"), text: $model.contextQuery)
                    .textFieldStyle(.roundedBorder)
                AsyncButton(title: model.t("Assemble Context Packet"), systemImage: "shippingbox") { await model.buildContextPacket() }
            }
            if let response = model.contextPacket {
                ScrollView {
                    VStack(alignment: .leading, spacing: 12) {
                        Badge("\(model.t("packet")): \(response.contextPacketId)")
                        ContextSection(title: model.t("Active Direction"), emptyText: model.t("No entries"), values: response.packet.activeResearchDirection.map { [$0] } ?? [])
                        ContextSection(title: model.t("Semantic"), emptyText: model.t("No entries"), values: response.packet.semanticContext)
                        ContextSection(title: model.t("Evidence"), emptyText: model.t("No entries"), values: response.packet.evidenceContext)
                        ContextSection(title: model.t("Episodes"), emptyText: model.t("No entries"), values: response.packet.episodicContext)
                        ContextSection(title: model.t("Methodology"), emptyText: model.t("No entries"), values: response.packet.methodologyContext)
                        ContextSection(title: model.t("Metacognition"), emptyText: model.t("No entries"), values: response.packet.metacognitiveContext)
                        GlassCard(title: model.t("Forbidden Assumptions"), systemImage: "exclamationmark.triangle") {
                            ForEach(response.packet.forbiddenAssumptions, id: \.self) { Text("• \($0)") }
                        }
                    }
                }
            } else {
                EmptyHint(text: model.t("This panel shows which semantic knowledge, evidence, events, methods, and metacognition are activated for a task."))
            }
        }
    }
}

struct ContextSection: View {
    var title: String
    var emptyText: String
    var values: [JSONValue]

    var body: some View {
        GlassCard(title: title, systemImage: "rectangle.stack") {
            VStack(alignment: .leading, spacing: 8) {
                ForEach(Array(values.enumerated()), id: \.offset) { _, value in
                    Text(value.pretty)
                        .font(.system(.caption, design: .monospaced))
                        .textSelection(.enabled)
                        .padding(8)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 10))
                }
                if values.isEmpty { EmptyHint(text: emptyText) }
            }
        }
    }
}

struct MemoryNotesPanel: View {
    @ObservedObject var model: AppViewModel

    var body: some View {
        HStack(spacing: 16) {
            GlassCard(title: model.t("Memory notes"), systemImage: "note.text") {
                List(model.memoryNotes, selection: $model.selectedMemoryNoteID) { note in
                    VStack(alignment: .leading, spacing: 4) {
                        Text(note.title).font(.headline).lineLimit(2)
                        Text("\(note.type) · \(note.updatedAt ?? "")").font(.caption).foregroundStyle(.secondary)
                    }
                    .tag(note.id as String?)
                    .onTapGesture { Task { await model.loadMemoryNote(id: note.id) } }
                }
                .frame(minWidth: 280)
            }
            .frame(width: 330)

            GlassCard(title: model.selectedMemoryNote?.title ?? model.t("Preview"), systemImage: "doc.richtext") {
                ScrollView {
                    if model.isLoadingMemoryNote {
                        ProgressView(model.t("Loading memory note"))
                    } else {
                        Text(model.selectedMemoryNote?.content ?? model.t("Select a memory note to preview."))
                            .font(.system(.body, design: .monospaced))
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .textSelection(.enabled)
                    }
                }
            }
        }
    }
}

struct ReviewQueuePanel: View {
    @ObservedObject var model: AppViewModel

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 12) {
                ForEach(model.reviewItems) { item in
                    GlassCard {
                        VStack(alignment: .leading, spacing: 8) {
                            HStack {
                                Badge(model.t(item.riskLevel ?? "risk"))
                                Badge(model.t(item.status ?? "pending"))
                                Spacer()
                                Text(item.createdAt ?? "").font(.caption).foregroundStyle(.secondary)
                            }
                            Text(item.item?.pretty ?? item.id)
                                .font(.system(.caption, design: .monospaced))
                                .textSelection(.enabled)
                        }
                    }
                }
                if model.reviewItems.isEmpty { EmptyHint(text: model.t("No high-risk memory changes need manual review.")) }
            }
        }
    }
}

struct LibraryView: View {
    @ObservedObject var model: AppViewModel

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            PageHeader(title: model.t("Read Papers"), subtitle: model.t("Papers that have been read or integrated into your knowledge system."), icon: "books.vertical")
            PaperListView(model: model, papers: model.readPapers)
        }
    }
}

struct SettingsView: View {
    @ObservedObject var model: AppViewModel
    @State private var showImporter = false

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                PageHeader(title: model.t("Settings"), subtitle: model.t("Local-first; DeepSeek keys are stored in macOS Keychain."), icon: "gearshape")
                GlassCard(title: model.t("Interface"), systemImage: "macwindow") {
                    Form {
                        Picker(model.t("Language"), selection: $model.language) {
                            ForEach(AppLanguage.allCases) { Text($0.displayName).tag($0) }
                        }
                        Picker(model.t("Appearance"), selection: $model.themeMode) {
                            ForEach(AppThemeMode.allCases) { Text(model.t($0.displayName)).tag($0) }
                        }
                        Slider(value: $model.fontSize, in: 12...20) { Text(model.t("Font size")) }
                        Toggle(model.t("Show status hints"), isOn: $model.showStatusHints)
                    }
                }
                GlassCard(title: model.t("DeepSeek"), systemImage: "key") {
                    Text(model.t("Saved keys are not displayed here, so opening Settings does not read Keychain. Leave a field blank to keep the saved value."))
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    SecureField(model.t("DeepSeek V4 Pro key for deep reading and memory synthesis"), text: $model.readerAPIKeyDraft)
                    SecureField(model.t("DeepSeek V4 Flash key for profile generation"), text: $model.flashAPIKeyDraft)
                    HStack {
                        Button(model.t("Save to Keychain")) { model.saveDeepSeekKeys() }
                        Button(model.t("Clear saved keys"), role: .destructive) { model.clearDeepSeekKeys() }
                    }
                }
                GlassCard(title: model.t("Exports"), systemImage: "square.and.arrow.up") {
                    TextField(model.t("Obsidian vault path"), text: $model.obsidianPath)
                    HStack {
                        AsyncButton(title: model.t("Export Obsidian"), systemImage: "folder") { await model.exportObsidian() }
                        AsyncButton(title: model.t("Export Zotero"), systemImage: "tray.and.arrow.up") { await model.exportZotero() }
                    }
                }
                GlassCard(title: model.t("Zotero Import"), systemImage: "tray.and.arrow.down") {
                    Text(model.t("No Zotero import yet. Export BibTeX, RIS, or CSL JSON from Zotero and choose the export file or folder here. Local PDFs under files/ are read automatically when available."))
                        .foregroundStyle(.secondary)
                    Button(model.t("Choose Zotero Export File or Folder")) { showImporter = true }
                    if let progress = model.zoteroImportProgress {
                        WorkflowProgressPanel(
                            model: model,
                            title: model.t("Import Progress"),
                            progress: progress,
                            phases: ["scanning", "parsing", "reading_pdfs", "saving", "done"]
                        )
                    }
                    if !model.zoteroImportCandidates.isEmpty {
                        Text(String(format: model.t("%d imported candidates"), model.zoteroImportCandidates.count))
                        AsyncButton(title: model.t("Integrate Selected"), systemImage: "brain") { await model.integrateSelectedZoteroPapers() }
                    }
                    if let progress = model.integrationProgress {
                        WorkflowProgressPanel(
                            model: model,
                            title: model.t("Integration Progress"),
                            progress: progress,
                            phases: ["preparing", "reading_pdfs", "calling_llm", "writing_memory", "done"]
                        )
                    }
                }
            }
        }
        .fileImporter(isPresented: $showImporter, allowedContentTypes: zoteroImportTypes, allowsMultipleSelection: false) { result in
            switch result {
            case .success(let urls):
                guard let url = urls.first else {
                    model.statusLine = model.t("No file was selected.")
                    return
                }
                Task {
                    let accessGranted = url.startAccessingSecurityScopedResource()
                    defer {
                        if accessGranted {
                            url.stopAccessingSecurityScopedResource()
                        }
                    }
                    await model.importZoteroFile(url)
                }
            case .failure(let error):
                model.statusLine = "\(model.t("Could not choose Zotero export")): \(error.localizedDescription)"
            }
        }
    }

    private var zoteroImportTypes: [UTType] {
        var types: [UTType] = [.folder, .item, .data, .json, .plainText]
        for extensionName in ["bib", "bibtex", "ris", "csljson"] {
            if let type = UTType(filenameExtension: extensionName) {
                types.append(type)
            }
        }
        return types
    }
}

struct WorkflowProgressPanel: View {
    @ObservedObject var model: AppViewModel
    var title: String
    var progress: IntegrationProgress
    var phases: [String]

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Divider()
            HStack {
                Text(title).font(.subheadline.weight(.semibold))
                Spacer()
                Text(model.t(progress.phase)).font(.caption).foregroundStyle(.secondary)
            }
            if progress.total > 0 && !isIndeterminate {
                ProgressView(value: progress.fraction) {
                    Text(model.t(progress.message))
                } currentValueLabel: {
                    Text("\(progress.current)/\(progress.total)")
                }
            } else {
                ProgressView {
                    Text(model.t(progress.message))
                }
            }
            if let detail = progress.detail, !detail.isEmpty {
                Text(detail)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(2)
                    .truncationMode(.middle)
            }
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 6) {
                    ForEach(phases, id: \.self) { phase in
                        HStack(spacing: 4) {
                            Image(systemName: icon(for: phase))
                                .font(.caption2)
                            Text(model.t(phase))
                                .font(.caption2.weight(.medium))
                                .lineLimit(1)
                        }
                        .foregroundStyle(color(for: phase))
                        .padding(.horizontal, 8)
                        .padding(.vertical, 5)
                        .background(color(for: phase).opacity(0.12), in: Capsule())
                    }
                }
            }
        }
    }

    private var isIndeterminate: Bool {
        ["scanning", "calling_llm"].contains(progress.phase)
    }

    private func icon(for phase: String) -> String {
        if progress.phase == "failed" { return "xmark.circle.fill" }
        if phaseOrder(phase) < phaseOrder(progress.phase) || progress.phase == "done" {
            return "checkmark.circle.fill"
        }
        if phase == progress.phase {
            return "clock.fill"
        }
        return "circle"
    }

    private func color(for phase: String) -> Color {
        if progress.phase == "failed" { return .red }
        if phase == progress.phase { return .accentColor }
        if phaseOrder(phase) < phaseOrder(progress.phase) || progress.phase == "done" {
            return .green
        }
        return .secondary
    }

    private func phaseOrder(_ phase: String) -> Int {
        if phase == "failed" { return phases.count + 1 }
        return phases.firstIndex(of: phase) ?? phases.count
    }
}

struct PageHeader: View {
    var title: String
    var subtitle: String
    var icon: String

    var body: some View {
        HStack(alignment: .top, spacing: 14) {
            Image(systemName: icon)
                .font(.system(size: 28, weight: .semibold))
                .frame(width: 54, height: 54)
                .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 18))
            VStack(alignment: .leading, spacing: 6) {
                Text(title).font(.largeTitle.weight(.semibold))
                Text(subtitle).foregroundStyle(.secondary)
            }
            Spacer()
        }
    }
}

struct ToolbarCard<Content: View>: View {
    @ViewBuilder var content: Content
    var body: some View {
        HStack(spacing: 12) { content }
            .padding(12)
            .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
    }
}

struct GlassCard<Content: View>: View {
    var title: String?
    var systemImage: String?
    @ViewBuilder var content: Content

    init(title: String? = nil, systemImage: String? = nil, @ViewBuilder content: () -> Content) {
        self.title = title
        self.systemImage = systemImage
        self.content = content()
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            if let title {
                HStack {
                    if let systemImage { Image(systemName: systemImage).foregroundStyle(.tint) }
                    Text(title).font(.headline)
                    Spacer()
                }
            }
            content
        }
        .padding(16)
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 22, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 22, style: .continuous).stroke(.white.opacity(0.08)))
    }
}

struct StatCard: View {
    var title: String
    var value: String
    var caption: String
    var icon: String

    var body: some View {
        GlassCard {
            HStack(alignment: .top) {
                VStack(alignment: .leading, spacing: 6) {
                    Text(title).font(.caption).foregroundStyle(.secondary)
                    Text(value).font(.system(size: 30, weight: .bold, design: .rounded))
                    Text(caption).font(.caption2).foregroundStyle(.secondary)
                }
                Spacer()
                Image(systemName: icon).font(.title2).foregroundStyle(.tint)
            }
        }
    }
}

struct Badge: View {
    var text: String
    var color: Color
    init(_ text: String, color: Color = .accentColor) {
        self.text = text
        self.color = color
    }
    var body: some View {
        Text(text)
            .font(.caption2.weight(.semibold))
            .padding(.horizontal, 8)
            .padding(.vertical, 4)
            .background(color.opacity(0.12), in: Capsule())
            .foregroundStyle(color)
    }
}

struct EmptyHint: View {
    var text: String
    var body: some View {
        Text(text)
            .foregroundStyle(.secondary)
            .frame(maxWidth: .infinity, minHeight: 90)
            .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 16))
    }
}

struct WorkflowStep: View {
    var number: String
    var title: String
    var detail: String
    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            Text(number)
                .font(.headline)
                .frame(width: 30, height: 30)
                .background(Color.accentColor.opacity(0.15), in: Circle())
            VStack(alignment: .leading, spacing: 4) {
                Text(title).font(.headline)
                Text(detail).foregroundStyle(.secondary)
            }
        }
    }
}

struct InterestChip: View {
    var interest: InterestState
    var body: some View {
        HStack(spacing: 6) {
            Text(interest.topic)
            Text("\(Int(interest.intensity * 100))%")
                .foregroundStyle(.secondary)
        }
        .font(.caption.weight(.medium))
        .padding(.horizontal, 10)
        .padding(.vertical, 6)
        .background(.thinMaterial, in: Capsule())
    }
}

struct ProfilePicker: View {
    @ObservedObject var model: AppViewModel
    var body: some View {
        Picker(model.t("Profile"), selection: Binding(get: { model.selectedProfileID ?? "" }, set: { newValue in
            model.selectedProfileID = newValue.isEmpty ? nil : newValue
            Task { try? await model.refreshAll() }
        })) {
            ForEach(model.profiles) { profile in
                Text(profile.name).tag(profile.id)
            }
        }
        .frame(width: 240)
    }
}

struct AsyncButton: View {
    var title: String
    var systemImage: String
    var role: ButtonRole?
    var action: () async -> Void

    init(title: String, systemImage: String, role: ButtonRole? = nil, action: @escaping () async -> Void) {
        self.title = title
        self.systemImage = systemImage
        self.role = role
        self.action = action
    }

    var body: some View {
        Button(role: role) {
            Task { await action() }
        } label: {
            Label(title, systemImage: systemImage)
        }
    }
}

struct FlowLayout<Data: RandomAccessCollection, Content: View>: View where Data.Element: Identifiable {
    var items: Data
    var content: (Data.Element) -> Content

    var body: some View {
        LazyVGrid(columns: [GridItem(.adaptive(minimum: 120), spacing: 8)], alignment: .leading, spacing: 8) {
            ForEach(items) { item in content(item) }
        }
    }
}
