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
                Label("Research OS", systemImage: "brain.head.profile")
                    .font(.title3.weight(.semibold))
                Text("Literature Radar + Memory OS")
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
                    title: "Research Memory Operating System",
                    subtitle: "把雷达、深读、证据、知识图谱、兴趣、insight 和方法论连接成一个可追踪的科研心智系统。",
                    icon: "sparkles.rectangle.stack"
                )
                DashboardCards(model: model)
                HStack(alignment: .top, spacing: 16) {
                    GlassCard(title: "下一步工作流", systemImage: "arrow.triangle.branch") {
                        VStack(alignment: .leading, spacing: 12) {
                            WorkflowStep(number: "1", title: "雷达发现", detail: "搜索/浅读只写入事件层和兴趣状态，不污染事实知识。")
                            WorkflowStep(number: "2", title: "DeepSeek 深读", detail: "深读后生成 MemoryChangeSet、证据片段、原子知识和 insight。")
                            WorkflowStep(number: "3", title: "巩固与纠错", detail: "高风险变更进 review queue；所有写入都有 provenance 和回滚线索。")
                        }
                    }
                    .frame(maxWidth: .infinity)

                    GlassCard(title: "近期候选", systemImage: "doc.text.magnifyingglass") {
                        VStack(spacing: 10) {
                            ForEach(model.displayedRadarPapers.prefix(5)) { paper in
                                CompactPaperRow(paper: paper)
                            }
                            if model.papers.isEmpty {
                                EmptyHint(text: "还没有论文。先加载 Demo 或运行雷达。")
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
            StatCard(title: "Papers", value: "\(dashboard?.counts["papers"] ?? model.papers.count)", caption: "本地候选库", icon: "doc.text")
            StatCard(title: "Knowledge Nodes", value: "\(dashboard?.counts["knowledge_nodes"] ?? 0)", caption: "结构化知识节点", icon: "circle.hexagongrid")
            StatCard(title: "Evidence", value: "\(dashboard?.counts["evidence_spans"] ?? 0)", caption: "可回溯证据片段", icon: "quote.bubble")
            StatCard(title: "Health", value: "\(Int(((dashboard?.health.score ?? 1.0) * 100).rounded()))%", caption: "记忆健康度", icon: "heart.text.square")
        }
    }
}

struct RadarView: View {
    @ObservedObject var model: AppViewModel

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            PageHeader(title: model.t("Today Radar"), subtitle: model.t("Ranked candidates from local memory and official APIs."), icon: "dot.radiowaves.left.and.right")
            ToolbarCard {
                ProfilePicker(model: model)
                Picker(model.t("Sort by"), selection: $model.radarSortMode) {
                    Text(model.t("Relevance")).tag(RadarSortMode.relevance)
                    Text(model.t("Time")).tag(RadarSortMode.time)
                }
                .pickerStyle(.segmented)
                .frame(width: 190)
                Spacer()
                AsyncButton(title: model.t("Demo"), systemImage: "sparkles") { await model.ingestDemo() }
                AsyncButton(title: model.t("Run Radar"), systemImage: "antenna.radiowaves.left.and.right") { await model.runRadar() }
                AsyncButton(title: model.t("Refresh"), systemImage: "arrow.clockwise") { await model.refreshMemoryOS() }
            }
            PaperListView(model: model, papers: model.displayedRadarPapers)
        }
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
                Toggle(model.t("Live APIs"), isOn: $model.useLiveAPIs)
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
                            Badge(paper.sourceLabel)
                            Badge(paper.dateLabel)
                            if let status = paper.analysisStatus { Badge(status) }
                            if paper.isRead { Badge("read") }
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
                        Text(paper.score?.reason ?? "local")
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
                        Link("Open", destination: link)
                    }
                    Spacer()
                }
                .buttonStyle(.bordered)
            }
        }
    }
}

struct CompactPaperRow: View {
    var paper: Paper
    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            Image(systemName: "doc.text")
                .foregroundStyle(.tint)
            VStack(alignment: .leading, spacing: 4) {
                Text(paper.title).font(.subheadline.weight(.medium)).lineLimit(2)
                Text("\(paper.sourceLabel) · \(paper.dateLabel) · \(paper.finalScorePercent)")
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

    var body: some View {
        HStack(alignment: .top, spacing: 16) {
            VStack(alignment: .leading, spacing: 12) {
                PageHeader(title: model.t("Research Profiles"), subtitle: "研究方向不仅是关键词，也会驱动雷达、记忆检索、知识树和元认知反思。", icon: "slider.horizontal.3")
                GlassCard(title: "方向列表", systemImage: "list.bullet.rectangle") {
                    VStack(spacing: 8) {
                        ForEach(model.profiles) { profile in
                            Button {
                                model.selectedProfileID = profile.id
                                draft = profile
                                Task { try? await model.refreshAll() }
                            } label: {
                                HStack {
                                    VStack(alignment: .leading) {
                                        Text(profile.name).font(.headline)
                                        Text(profile.includeTerms.prefix(5).joined(separator: ", ")).font(.caption).foregroundStyle(.secondary)
                                    }
                                    Spacer()
                                    if model.selectedProfileID == profile.id { Image(systemName: "checkmark.circle.fill") }
                                }
                            }
                            .buttonStyle(.plain)
                            Divider()
                        }
                        AsyncButton(title: model.t("New Profile"), systemImage: "plus") { await model.createProfile() }
                    }
                }
                GlassCard(title: model.t("Generate Profile"), systemImage: "wand.and.stars") {
                    VStack(alignment: .leading, spacing: 10) {
                        TextEditor(text: $description).frame(minHeight: 90)
                        AsyncButton(title: model.t("Generate Profile"), systemImage: "sparkles") { await model.createProfileFromDescription(description) }
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
                    ProfileField(title: model.t("Include terms"), values: $profile.includeTerms)
                    ProfileField(title: model.t("Exclude terms"), values: $profile.excludeTerms)
                    ProfileField(title: model.t("Seed papers"), values: $profile.seedPapers)
                    ProfileField(title: model.t("Watch authors"), values: $profile.watchAuthors)
                    ProfileField(title: model.t("Watch labs"), values: $profile.watchLabs)
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
                TextField(modelessPlaceholder, text: $newValue)
                Button(modelessAddTitle) {
                    let trimmed = newValue.trimmingCharacters(in: .whitespacesAndNewlines)
                    guard !trimmed.isEmpty else { return }
                    values.append(trimmed)
                    newValue = ""
                }
            }
        }
    }

    private var modelessPlaceholder: String { "Add item" }
    private var modelessAddTitle: String { "Add" }
}

struct MemoryOSView: View {
    @ObservedObject var model: AppViewModel

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            PageHeader(title: "Memory OS", subtitle: "证据层、事件层、语义知识图谱、方法论、元认知与工作记忆包。", icon: "brain.head.profile")
            ToolbarCard {
                AsyncButton(title: model.t("Refresh"), systemImage: "arrow.clockwise") { await model.refreshMemoryOS() }
                AsyncButton(title: "重建知识树", systemImage: "point.3.connected.trianglepath.dotted") { await model.rebuildKnowledgeTree() }
                AsyncButton(title: "检查记忆", systemImage: "stethoscope") { await model.repairMemory(apply: false) }
                AsyncButton(title: "自动修复", systemImage: "wrench.and.screwdriver") { await model.repairMemory(apply: true) }
                Spacer()
            }
            TabView {
                MemoryDashboardPanel(model: model).tabItem { Label("Dashboard", systemImage: "gauge.with.dots.needle.67percent") }
                KnowledgeTreePanel(model: model).tabItem { Label("Knowledge Tree", systemImage: "tree") }
                ContextPacketPanel(model: model).tabItem { Label("Context Packet", systemImage: "shippingbox") }
                MemoryNotesPanel(model: model).tabItem { Label("Notes", systemImage: "note.text") }
                ReviewQueuePanel(model: model).tabItem { Label("Review", systemImage: "checklist") }
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
                    GlassCard(title: "兴趣状态", systemImage: "flame") {
                        FlowLayout(items: model.memoryDashboard?.interests ?? []) { item in
                            InterestChip(interest: item)
                        }
                        if model.memoryDashboard?.interests.isEmpty ?? true { EmptyHint(text: "还没有浅层兴趣信号。") }
                    }
                    .frame(maxWidth: .infinity)
                    GlassCard(title: "最近事件", systemImage: "clock.arrow.circlepath") {
                        VStack(alignment: .leading, spacing: 8) {
                            ForEach(model.memoryDashboard?.recentEvents ?? []) { event in
                                HStack {
                                    Badge(event.eventType)
                                    Text(event.objectId ?? event.objectType ?? "event")
                                    Spacer()
                                    Text(event.occurredAt ?? "").font(.caption).foregroundStyle(.secondary)
                                }
                            }
                            if model.memoryDashboard?.recentEvents.isEmpty ?? true { EmptyHint(text: "还没有事件记忆。") }
                        }
                    }
                    .frame(maxWidth: .infinity)
                }
                GlassCard(title: "系统层级计数", systemImage: "square.stack.3d.up") {
                    LazyVGrid(columns: Array(repeating: GridItem(.flexible()), count: 4), spacing: 10) {
                        ForEach((model.memoryDashboard?.counts ?? [:]).sorted(by: { $0.key < $1.key }), id: \.key) { key, value in
                            HStack {
                                Text(key.replacingOccurrences(of: "_", with: " ")).font(.caption)
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
            GlassCard(title: "知识树", systemImage: "tree") {
                ScrollView {
                    if let tree = model.mindMap?.tree {
                        TreeNodeView(node: tree)
                    } else {
                        EmptyHint(text: "暂无知识树。")
                    }
                }
            }
            .frame(maxWidth: .infinity)

            GlassCard(title: "图谱概览", systemImage: "network") {
                VStack(alignment: .leading, spacing: 10) {
                    Text("Nodes: \(model.mindMap?.nodes.count ?? 0)")
                    Text("Edges: \(model.mindMap?.edges.count ?? 0)")
                    Divider()
                    ForEach(Array((model.mindMap?.insights ?? []).prefix(8))) { insight in
                        VStack(alignment: .leading, spacing: 3) {
                            HStack { Badge(insight.type); Text("\(Int(insight.confidence * 100))%") }
                            Text(insight.content).font(.callout)
                        }
                        Divider()
                    }
                    if model.mindMap?.insights.isEmpty ?? true { EmptyHint(text: "暂无元认知 insight。") }
                }
            }
            .frame(width: 340)
        }
    }
}

struct TreeNodeView: View {
    var node: KnowledgeTreeNode

    var body: some View {
        if node.children.isEmpty {
            nodeLabel
                .padding(.vertical, 3)
        } else {
            DisclosureGroup(isExpanded: .constant(true)) {
                VStack(alignment: .leading, spacing: 4) {
                    ForEach(node.children) { child in
                        TreeNodeView(node: child)
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
            if let confidence = node.confidence { Text("conf \(Int(confidence * 100))%").foregroundStyle(.secondary).font(.caption) }
        }
    }
}

struct ContextPacketPanel: View {
    @ObservedObject var model: AppViewModel

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            ToolbarCard {
                TextField("输入当前问题或任务，让系统组装工作记忆包", text: $model.contextQuery)
                    .textFieldStyle(.roundedBorder)
                AsyncButton(title: "组装 Context Packet", systemImage: "shippingbox") { await model.buildContextPacket() }
            }
            if let response = model.contextPacket {
                ScrollView {
                    VStack(alignment: .leading, spacing: 12) {
                        Badge("packet: \(response.contextPacketId)")
                        ContextSection(title: "Active Direction", values: response.packet.activeResearchDirection.map { [$0] } ?? [])
                        ContextSection(title: "Semantic", values: response.packet.semanticContext)
                        ContextSection(title: "Evidence", values: response.packet.evidenceContext)
                        ContextSection(title: "Episodes", values: response.packet.episodicContext)
                        ContextSection(title: "Methodology", values: response.packet.methodologyContext)
                        ContextSection(title: "Metacognition", values: response.packet.metacognitiveContext)
                        GlassCard(title: "Forbidden Assumptions", systemImage: "exclamationmark.triangle") {
                            ForEach(response.packet.forbiddenAssumptions, id: \.self) { Text("• \($0)") }
                        }
                    }
                }
            } else {
                EmptyHint(text: "这里会显示一次任务临时激活了哪些语义知识、证据、事件、方法论和元认知。")
            }
        }
    }
}

struct ContextSection: View {
    var title: String
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
                if values.isEmpty { EmptyHint(text: "No entries") }
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

            GlassCard(title: model.selectedMemoryNote?.title ?? "Preview", systemImage: "doc.richtext") {
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
                                Badge(item.riskLevel ?? "risk")
                                Badge(item.status ?? "pending")
                                Spacer()
                                Text(item.createdAt ?? "").font(.caption).foregroundStyle(.secondary)
                            }
                            Text(item.item?.pretty ?? item.id)
                                .font(.system(.caption, design: .monospaced))
                                .textSelection(.enabled)
                        }
                    }
                }
                if model.reviewItems.isEmpty { EmptyHint(text: "暂无需要人工审核的高风险记忆变更。") }
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
                PageHeader(title: model.t("Settings"), subtitle: "本地优先，DeepSeek key 存入 macOS Keychain。", icon: "gearshape")
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
                    SecureField(model.t("Reading and synthesis API key"), text: $model.readerAPIKeyDraft)
                    SecureField(model.t("Fast profile-generation API key"), text: $model.flashAPIKeyDraft)
                    Button(model.t("Save to Keychain")) { model.saveDeepSeekKeys() }
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
                    if !model.zoteroImportCandidates.isEmpty {
                        Text("\(model.zoteroImportCandidates.count) imported candidates")
                        AsyncButton(title: model.t("Integrate Selected"), systemImage: "brain") { await model.integrateSelectedZoteroPapers() }
                    }
                    if let progress = model.integrationProgress {
                        ProgressView(value: progress.fraction) { Text(progress.message) }
                        if let detail = progress.detail { Text(detail).font(.caption).foregroundStyle(.secondary) }
                    }
                }
            }
        }
        .onAppear {
            model.loadDeepSeekKeyDraftsForEditing()
        }
        .fileImporter(isPresented: $showImporter, allowedContentTypes: [.item, .folder], allowsMultipleSelection: false) { result in
            if case .success(let urls) = result, let url = urls.first {
                Task { await model.importZoteroFile(url) }
            }
        }
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
    init(_ text: String) { self.text = text }
    var body: some View {
        Text(text)
            .font(.caption2.weight(.semibold))
            .padding(.horizontal, 8)
            .padding(.vertical, 4)
            .background(Color.accentColor.opacity(0.12), in: Capsule())
            .foregroundStyle(.tint)
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
