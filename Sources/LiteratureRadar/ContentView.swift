import SwiftUI
import UniformTypeIdentifiers

struct ContentView: View {
    @StateObject private var viewModel = AppViewModel()

    var body: some View {
        NavigationSplitView {
            SidebarView()
                .environmentObject(viewModel)
        } detail: {
            Group {
                switch viewModel.selectedSection {
                case .radar:
                    RadarView()
                case .search:
                    SearchLabView()
                case .profiles:
                    ProfilesView()
                case .memory:
                    MemoryView()
                case .library:
                    ReadPapersView()
                case .settings:
                    SettingsView()
                }
            }
            .environmentObject(viewModel)
            .safeAreaInset(edge: .bottom) {
                if viewModel.showStatusHints {
                    StatusBar()
                        .environmentObject(viewModel)
                }
            }
            .background(Color(nsColor: .textBackgroundColor).opacity(0.72))
        }
        .font(.system(size: viewModel.fontSize))
        .preferredColorScheme(viewModel.themeMode.colorScheme)
        .task {
            await viewModel.bootstrap()
        }
    }
}

struct SidebarView: View {
    @EnvironmentObject private var viewModel: AppViewModel

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            VStack(alignment: .leading, spacing: 2) {
                Text("LiteratureRadar")
                    .font(.title3.bold())
                Text(viewModel.selectedProfile?.name ?? viewModel.t("Ready"))
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
            }
            .padding(.horizontal, 14)
            .padding(.top, 18)

            VStack(spacing: 4) {
                ForEach(AppSection.allCases) { section in
                    Button {
                        viewModel.selectedSection = section
                    } label: {
                        HStack(spacing: 10) {
                            Image(systemName: icon(for: section))
                                .frame(width: 20)
                            Text(section.title(language: viewModel.language))
                            Spacer()
                        }
                        .padding(.horizontal, 12)
                        .padding(.vertical, 9)
                        .contentShape(Rectangle())
                        .background(
                            viewModel.selectedSection == section
                                ? Color.accentColor.opacity(0.14)
                                : Color.clear,
                            in: RoundedRectangle(cornerRadius: 8)
                        )
                    }
                    .buttonStyle(.plain)
                    .foregroundStyle(viewModel.selectedSection == section ? .primary : .secondary)
                }
            }
            .padding(.horizontal, 8)

            Spacer()

            if viewModel.showStatusHints {
                VStack(alignment: .leading, spacing: 8) {
                    if viewModel.isBusy {
                        ProgressView()
                            .controlSize(.small)
                    }
                    Text(viewModel.statusLine)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .lineLimit(3)
                }
                .padding(12)
                .background(.quaternary.opacity(0.45), in: RoundedRectangle(cornerRadius: 8))
                .padding(10)
            }
        }
        .frame(minWidth: 230)
        .background(.bar)
    }

    private func icon(for section: AppSection) -> String {
        switch section {
        case .radar:
            "dot.radiowaves.left.and.right"
        case .search:
            "magnifyingglass"
        case .profiles:
            "slider.horizontal.3"
        case .memory:
            "brain.head.profile"
        case .library:
            "books.vertical"
        case .settings:
            "gearshape"
        }
    }
}

struct RadarView: View {
    @EnvironmentObject private var viewModel: AppViewModel

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Header(title: viewModel.t("Today Radar"), subtitle: viewModel.t("Ranked candidates from local memory and official APIs."))
            QuickStatsView()
            HStack {
                ProfilePicker()
                Picker(viewModel.t("Sort by"), selection: $viewModel.radarSortMode) {
                    ForEach(RadarSortMode.allCases) { mode in
                        Text(mode.title(language: viewModel.language)).tag(mode)
                    }
                }
                .pickerStyle(.segmented)
                .frame(width: 220)
                Spacer()
                Button {
                    Task { await viewModel.ingestDemo() }
                } label: {
                    Label(viewModel.t("Demo"), systemImage: "tray.and.arrow.down")
                }
                Button {
                    Task { await viewModel.runRadar() }
                } label: {
                    Label(viewModel.t("Run Radar"), systemImage: "arrow.clockwise")
                }
                .buttonStyle(.borderedProminent)
            }

            PaperList(papers: viewModel.displayedRadarPapers)
        }
        .padding(20)
    }
}

struct QuickStatsView: View {
    @EnvironmentObject private var viewModel: AppViewModel

    var body: some View {
        HStack(spacing: 8) {
            StatChip(title: viewModel.t("Candidates"), value: "\(viewModel.papers.count)", systemImage: "doc.text.magnifyingglass")
            StatChip(title: viewModel.t("Saved"), value: "\(viewModel.papers.filter { $0.actions.contains("save") }.count)", systemImage: "bookmark")
            StatChip(title: viewModel.t("Memory notes"), value: "\(viewModel.memoryNotes.count)", systemImage: "brain.head.profile")
            Spacer()
        }
    }
}

struct StatChip: View {
    let title: String
    let value: String
    let systemImage: String

    var body: some View {
        HStack(spacing: 8) {
            Image(systemName: systemImage)
                .foregroundStyle(.secondary)
            VStack(alignment: .leading, spacing: 1) {
                Text(value)
                    .font(.headline.monospacedDigit())
                Text(title)
                    .font(.caption2)
                    .foregroundStyle(.secondary)
            }
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 8)
        .background(.background, in: RoundedRectangle(cornerRadius: 8))
        .overlay {
            RoundedRectangle(cornerRadius: 8).stroke(.quaternary)
        }
    }
}

struct SearchLabView: View {
    @EnvironmentObject private var viewModel: AppViewModel

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Header(title: viewModel.t("Search Lab"), subtitle: viewModel.t("Run relevance search or broader exploration against local and live sources."))
            HStack(spacing: 10) {
                TextField(viewModel.t("Query, DOI, arXiv ID, author, or topic"), text: $viewModel.searchQuery)
                    .textFieldStyle(.roundedBorder)
                Picker(viewModel.t("Mode"), selection: $viewModel.searchMode) {
                    Text(viewModel.t("Relevance")).tag("relevance")
                    Text(viewModel.t("Explore")).tag("explore")
                }
                .pickerStyle(.segmented)
                .frame(width: 210)
                Toggle(viewModel.t("Online Search"), isOn: $viewModel.useLiveAPIs)
                    .toggleStyle(.switch)
                Button {
                    Task { await viewModel.runSearch() }
                } label: {
                    Label(viewModel.t("Search"), systemImage: "magnifyingglass")
                }
                .buttonStyle(.borderedProminent)
            }
            ProfilePicker()
            PaperList(papers: viewModel.searchResults.isEmpty ? viewModel.papers : viewModel.searchResults)
        }
        .padding(20)
    }
}

struct ProfilesView: View {
    @EnvironmentObject private var viewModel: AppViewModel
    @State private var editingProfile: ResearchProfile?
    @State private var pendingDelete: ResearchProfile?
    @State private var isCreatingProfile = false

    var body: some View {
        HStack(alignment: .top, spacing: 16) {
            VStack(alignment: .leading) {
                Header(title: viewModel.t("Research Profiles"), subtitle: viewModel.t("Each profile has its own terms, weights, seeds, and exclusions."))
                List(viewModel.profiles, selection: $viewModel.selectedProfileID) { profile in
                    VStack(alignment: .leading, spacing: 4) {
                        Text(profile.name).font(.headline)
                        Text("\(viewModel.t("Weight")) \(profile.weight, specifier: "%.2f")")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    .tag(profile.id)
                    .contextMenu {
                        Button(viewModel.t("Edit")) {
                            viewModel.selectedProfileID = profile.id
                            editingProfile = profile
                        }
                        Button(viewModel.t("New Profile")) {
                            isCreatingProfile = true
                        }
                        Button(viewModel.t("Delete"), role: .destructive) {
                            pendingDelete = profile
                        }
                    }
                }
                .frame(minWidth: 260)
                Button {
                    isCreatingProfile = true
                } label: {
                    Label(viewModel.t("New Profile"), systemImage: "plus")
                }
                .help(viewModel.t("New Profile"))
            }

            if let profile = viewModel.selectedProfile {
                ProfileEditor(profile: profile) { updated in
                    Task { await viewModel.saveProfile(updated) }
                } onDelete: {
                    pendingDelete = profile
                }
                .id(profile.id)
            } else {
                ContentUnavailableView(viewModel.t("No profile"), systemImage: "slider.horizontal.3")
            }
        }
        .padding(20)
        .alert(viewModel.t("Delete profile?"), isPresented: Binding(
            get: { pendingDelete != nil },
            set: { if !$0 { pendingDelete = nil } }
        )) {
            Button(viewModel.t("Cancel"), role: .cancel) {
                pendingDelete = nil
            }
            Button(viewModel.t("Delete"), role: .destructive) {
                if let pendingDelete {
                    Task { await viewModel.deleteProfile(pendingDelete) }
                }
                pendingDelete = nil
            }
        } message: {
            Text(viewModel.t("This removes the profile and its profile-specific scores, feedback, and notes. Papers stay in the library."))
        }
        .sheet(isPresented: $isCreatingProfile) {
            NewProfileSheet(isPresented: $isCreatingProfile)
                .environmentObject(viewModel)
        }
    }
}

enum NewProfileMode: String, CaseIterable, Identifiable {
    case manual
    case naturalLanguage

    var id: String { rawValue }
}

struct NewProfileSheet: View {
    @EnvironmentObject private var viewModel: AppViewModel
    @Binding var isPresented: Bool
    @State private var mode: NewProfileMode = .naturalLanguage
    @State private var description = ""

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Header(title: viewModel.t("New Profile"), subtitle: viewModel.t("Create manually or generate search keywords from a natural-language direction."))
            Picker(viewModel.t("Creation mode"), selection: $mode) {
                Text(viewModel.t("Natural-language description")).tag(NewProfileMode.naturalLanguage)
                Text(viewModel.t("Manual fields")).tag(NewProfileMode.manual)
            }
            .pickerStyle(.segmented)

            if mode == .naturalLanguage {
                HStack {
                    InfoPopover(
                        title: viewModel.t("Profile description tips"),
                        message: viewModel.t("Describe the topic, methods, organism/data type, must-have terms, terms to exclude, and optionally famous scholars or labs. Mention variants if you care about them; the generator will also add common OR variants such as single cell OR single-cell.")
                    )
                    Text(viewModel.t("Profile description tips"))
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                TextEditor(text: $description)
                    .frame(minHeight: 170)
                    .overlay {
                        RoundedRectangle(cornerRadius: 8).stroke(.quaternary)
                    }
            } else {
                Text(viewModel.t("Manual mode creates a blank profile that you can edit in the profile editor."))
                    .foregroundStyle(.secondary)
            }

            HStack {
                Spacer()
                Button(viewModel.t("Cancel")) {
                    isPresented = false
                }
                Button {
                    Task {
                        if mode == .manual {
                            await viewModel.createProfile()
                        } else {
                            await viewModel.createProfileFromDescription(description)
                        }
                        isPresented = false
                    }
                } label: {
                    Label(mode == .manual ? viewModel.t("Create") : viewModel.t("Generate Profile"), systemImage: "sparkles")
                }
                .buttonStyle(.borderedProminent)
            }
        }
        .padding(22)
        .frame(width: 620)
    }
}

struct MemoryView: View {
    @EnvironmentObject private var viewModel: AppViewModel

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Header(title: viewModel.t("Memory"), subtitle: viewModel.t("Profile-level overviews, claims, open questions, and weekly digests."))
            HStack {
                ProfilePicker()
                Spacer()
                Button {
                    Task { await viewModel.synthesizeWeekly() }
                } label: {
                    Label(viewModel.t("Synthesize"), systemImage: "wand.and.stars")
                }
                .buttonStyle(.borderedProminent)
            }
            HStack(spacing: 16) {
                List(viewModel.memoryNotes, selection: $viewModel.selectedMemoryNoteID) { note in
                    VStack(alignment: .leading, spacing: 4) {
                        Text(note.title).font(.headline)
                        Text(note.type)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    .tag(note.id)
                }
                .frame(width: 280)
                .onChange(of: viewModel.selectedMemoryNoteID) { _, noteID in
                    Task { await viewModel.loadMemoryNote(id: noteID) }
                }

                ScrollView {
                    Group {
                        if viewModel.isLoadingMemoryNote {
                            ProgressView(viewModel.t("Loading memory note"))
                                .frame(maxWidth: .infinity, alignment: .leading)
                        } else {
                            Text(viewModel.selectedMemoryNote?.content ?? memoryPlaceholder)
                                .font(.system(.body, design: .serif))
                                .frame(maxWidth: .infinity, alignment: .leading)
                                .textSelection(.enabled)
                        }
                    }
                    .padding()
                }
            }
        }
        .padding(20)
    }

    private var memoryPlaceholder: String {
        viewModel.memoryNotes.isEmpty ? viewModel.t("No memory notes yet.") : viewModel.t("Select a memory note to preview.")
    }
}

struct ReadPapersView: View {
    @EnvironmentObject private var viewModel: AppViewModel

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Header(title: viewModel.t("Read Papers"), subtitle: viewModel.t("Papers that have been read or integrated into your knowledge system."))
            HStack {
                ProfilePicker()
                Spacer()
                Button {
                    Task {
                        do { try await viewModel.refreshAll() } catch { viewModel.statusLine = error.localizedDescription }
                    }
                } label: {
                    Label(viewModel.t("Refresh"), systemImage: "arrow.clockwise")
                }
            }
            PaperList(papers: viewModel.readPapers)
        }
        .padding(20)
    }
}

struct SettingsView: View {
    @EnvironmentObject private var viewModel: AppViewModel
    @State private var isImportingZotero = false

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                Header(title: viewModel.t("Settings"), subtitle: viewModel.t("How to get a DeepSeek key"))

                SettingsPanel(title: viewModel.t("Language"), systemImage: "globe") {
                    Picker(viewModel.t("Interface language"), selection: $viewModel.language) {
                        ForEach(AppLanguage.allCases) { language in
                            Text(language.displayName).tag(language)
                        }
                    }
                    .pickerStyle(.segmented)
                }

                SettingsPanel(title: viewModel.t("Interface"), systemImage: "sidebar.left") {
                    Toggle(viewModel.t("Show status hints"), isOn: $viewModel.showStatusHints)
                        .toggleStyle(.switch)
                    HStack {
                        Text(viewModel.t("Font size"))
                        Slider(value: $viewModel.fontSize, in: 12...20, step: 1)
                        Text("\(Int(viewModel.fontSize))")
                            .monospacedDigit()
                    }
                    Picker(viewModel.t("Appearance"), selection: $viewModel.themeMode) {
                        ForEach(AppThemeMode.allCases) { mode in
                            Text(mode.title(language: viewModel.language)).tag(mode)
                        }
                    }
                    .pickerStyle(.segmented)
                    Text(viewModel.t("Status hints include the lower-left sidebar hint and the bottom status bar."))
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }

                SettingsPanel(title: viewModel.t("DeepSeek"), systemImage: "key") {
                    SecureField(viewModel.t("Reading and synthesis API key"), text: $viewModel.readerAPIKeyDraft)
                        .textFieldStyle(.roundedBorder)
                    SecureField(viewModel.t("Fast profile-generation API key"), text: $viewModel.flashAPIKeyDraft)
                        .textFieldStyle(.roundedBorder)
                    Text(viewModel.t("Paste your DeepSeek API key here, then press Save to Keychain. The app stores it in macOS Keychain under service LiteratureRadarDeepSeekAPIKey. For command-line use, you can also run: export DEEPSEEK_API_KEY=sk-..."))
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .textSelection(.enabled)
                    Button {
                        viewModel.saveDeepSeekKeys()
                    } label: {
                        Label(viewModel.t("Save to Keychain"), systemImage: "key")
                    }
                }

                SettingsPanel(title: viewModel.t("Exports"), systemImage: "square.and.arrow.up") {
                    TextField(viewModel.t("Obsidian vault path"), text: $viewModel.obsidianPath)
                        .textFieldStyle(.roundedBorder)
                    HStack {
                        Button {
                            Task { await viewModel.exportObsidian() }
                        } label: {
                            Label(viewModel.t("Export Obsidian"), systemImage: "square.and.arrow.up")
                        }
                        Button {
                            Task { await viewModel.exportZotero() }
                        } label: {
                            Label(viewModel.t("Export Zotero"), systemImage: "doc.richtext")
                        }
                    }
                }

                SettingsPanel(title: viewModel.t("Zotero Import"), systemImage: "books.vertical") {
                    HStack {
                        InfoPopover(
                            title: viewModel.t("Zotero export tutorial"),
                            message: viewModel.t("In Zotero, select papers, choose File > Export Items..., pick BibTeX, RIS, or CSL JSON. If Zotero creates a folder with a .bib file plus a files/ PDF folder, you can select either the folder or the .bib file here.")
                        )
                        Text(viewModel.t("Zotero export tutorial"))
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    Text(viewModel.t("No Zotero import yet. Export BibTeX, RIS, or CSL JSON from Zotero and choose the export file or folder here. Local PDFs under files/ are read automatically when available."))
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    HStack {
                        Button {
                            isImportingZotero = true
                        } label: {
                            Label(viewModel.t("Choose Zotero Export File or Folder"), systemImage: "folder")
                        }
                        Button {
                            Task { await viewModel.integrateSelectedZoteroPapers() }
                        } label: {
                            Label(viewModel.t("Integrate Selected"), systemImage: "brain.head.profile")
                        }
                        .buttonStyle(.borderedProminent)
                        .disabled(viewModel.selectedZoteroPaperIDs.isEmpty || viewModel.isIntegratingMemory)
                    }
                    if let progress = viewModel.integrationProgress {
                        IntegrationProgressPanel(progress: progress)
                    }
                    if !viewModel.zoteroImportCandidates.isEmpty {
                        Text(viewModel.t("Imported papers"))
                            .font(.headline)
                        Text(viewModel.t("Select papers to merge into the current profile's long-term memory."))
                            .font(.caption)
                            .foregroundStyle(.secondary)
                        VStack(spacing: 6) {
                            ForEach(viewModel.zoteroImportCandidates) { paper in
                                Toggle(isOn: Binding(
                                    get: { viewModel.selectedZoteroPaperIDs.contains(paper.id) },
                                    set: { viewModel.setZoteroSelection(paper.id, isSelected: $0) }
                                )) {
                                    VStack(alignment: .leading, spacing: 2) {
                                        Text(paper.title)
                                            .font(.subheadline.weight(.semibold))
                                        Text(paper.authors.prefix(3).joined(separator: ", "))
                                            .font(.caption)
                                            .foregroundStyle(.secondary)
                                    }
                                }
                                .toggleStyle(.checkbox)
                            }
                        }
                        .padding(10)
                        .background(.quaternary.opacity(0.32), in: RoundedRectangle(cornerRadius: 8))
                    }
                }
            }
            .padding(20)
            .frame(maxWidth: 920, alignment: .leading)
        }
        .fileImporter(
            isPresented: $isImportingZotero,
            allowedContentTypes: [.item, .folder],
            allowsMultipleSelection: false
        ) { result in
            if case .success(let urls) = result, let url = urls.first {
                Task { await viewModel.importZoteroFile(url) }
            }
        }
    }
}

struct IntegrationProgressPanel: View {
    @EnvironmentObject private var viewModel: AppViewModel
    let progress: IntegrationProgress

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .center, spacing: 10) {
                Image(systemName: iconName)
                    .foregroundStyle(iconColor)
                    .font(.title3)
                    .frame(width: 24)
                VStack(alignment: .leading, spacing: 2) {
                    Text(viewModel.t("Long-term memory integration"))
                        .font(.headline)
                    Text(phaseTitle)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                Spacer()
                if progress.total > 0 {
                    Text("\(progress.current)/\(progress.total)")
                        .font(.caption.monospacedDigit())
                        .foregroundStyle(.secondary)
                }
            }

            if let fraction = progress.fraction {
                ProgressView(value: fraction)
                    .progressViewStyle(.linear)
            } else {
                ProgressView()
                    .controlSize(.small)
            }

            Text(progress.message)
                .font(.subheadline)
                .foregroundStyle(progress.phase == "failed" ? .red : .primary)
                .textSelection(.enabled)

            if let detail = progress.detail, !detail.isEmpty {
                Text(detail)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(3)
                    .textSelection(.enabled)
            }

            Text(viewModel.t("Large Zotero imports may take several minutes because local PDFs are read first and DeepSeek synthesis runs in batches."))
                .font(.caption)
                .foregroundStyle(.secondary)
        }
        .padding(12)
        .background(.quaternary.opacity(0.32), in: RoundedRectangle(cornerRadius: 8))
    }

    private var phaseTitle: String {
        switch progress.phase {
        case "preparing":
            viewModel.t("Preparing")
        case "saving_feedback":
            viewModel.t("Saving selections")
        case "ranking":
            viewModel.t("Refreshing scores")
        case "reading_pdfs":
            viewModel.t("Reading PDFs")
        case "batch_synthesis":
            viewModel.t("Batch synthesis")
        case "final_merge":
            viewModel.t("Final memory merge")
        case "writing_memory":
            viewModel.t("Writing memory")
        case "exporting_obsidian":
            viewModel.t("Exporting Obsidian")
        case "done":
            viewModel.t("Complete")
        case "failed":
            viewModel.t("Failed")
        default:
            progress.phase
        }
    }

    private var iconName: String {
        switch progress.phase {
        case "done":
            "checkmark.circle.fill"
        case "failed":
            "exclamationmark.triangle.fill"
        case "reading_pdfs":
            "doc.text.magnifyingglass"
        case "batch_synthesis", "final_merge":
            "brain.head.profile"
        default:
            "arrow.triangle.2.circlepath"
        }
    }

    private var iconColor: Color {
        switch progress.phase {
        case "done":
            .green
        case "failed":
            .red
        default:
            .accentColor
        }
    }
}

struct InfoPopover: View {
    let title: String
    let message: String
    @State private var isShowing = false

    var body: some View {
        Button {
            isShowing.toggle()
        } label: {
            Image(systemName: "exclamationmark.circle")
        }
        .buttonStyle(.plain)
        .help(title)
        .popover(isPresented: $isShowing) {
            VStack(alignment: .leading, spacing: 8) {
                Text(title).font(.headline)
                Text(message)
                    .font(.body)
                    .fixedSize(horizontal: false, vertical: true)
            }
            .padding(14)
            .frame(width: 320)
        }
    }
}

struct SettingsPanel<Content: View>: View {
    let title: String
    let systemImage: String
    let content: Content

    init(title: String, systemImage: String, @ViewBuilder content: () -> Content) {
        self.title = title
        self.systemImage = systemImage
        self.content = content()
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Label(title, systemImage: systemImage)
                .font(.headline)
            content
        }
        .padding(16)
        .background(.background, in: RoundedRectangle(cornerRadius: 8))
        .overlay {
            RoundedRectangle(cornerRadius: 8).stroke(.quaternary)
        }
    }
}

struct PaperList: View {
    @EnvironmentObject private var viewModel: AppViewModel
    let papers: [Paper]

    var body: some View {
        ScrollView {
            LazyVStack(spacing: 10) {
                if papers.isEmpty {
                    ContentUnavailableView(viewModel.t("No papers yet"), systemImage: "doc.text.magnifyingglass")
                        .padding(.top, 80)
                } else {
                    ForEach(papers) { paper in
                        PaperCard(paper: paper)
                    }
                }
            }
            .padding(.vertical, 4)
        }
    }
}

struct PaperCard: View {
    @EnvironmentObject private var viewModel: AppViewModel
    let paper: Paper

    var body: some View {
        VStack(alignment: .leading, spacing: 9) {
            HStack(alignment: .top) {
                VStack(alignment: .leading, spacing: 5) {
                    Text(paper.title)
                        .font(.headline)
                        .textSelection(.enabled)
                    Text(metaLine)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                Spacer()
                if let score = paper.score {
                    Text("\(score.finalScore, specifier: "%.0f")")
                        .font(.system(size: 23, weight: .bold, design: .rounded))
                        .foregroundStyle(scoreColor(score.finalScore))
                        .frame(width: 52, height: 40)
                        .background(scoreColor(score.finalScore).opacity(0.12), in: RoundedRectangle(cornerRadius: 8))
                }
            }
            Text(paper.abstract)
                .lineLimit(4)
                .foregroundStyle(.primary)
            if let reason = paper.score?.reason, !reason.isEmpty {
                Label(reason, systemImage: "sparkles")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            HStack {
                ForEach(paper.actions, id: \.self) { action in
                    Text(action)
                        .font(.caption2)
                        .padding(.horizontal, 6)
                        .padding(.vertical, 3)
                        .background(.blue.opacity(0.12), in: Capsule())
                }
                ForEach(paper.exports, id: \.self) { target in
                    Text(target)
                        .font(.caption2)
                        .padding(.horizontal, 6)
                        .padding(.vertical, 3)
                        .background(.purple.opacity(0.12), in: Capsule())
                }
                if let analysisStatus = paper.analysisStatus {
                    Text(analysisStatus)
                        .font(.caption2)
                        .padding(.horizontal, 6)
                        .padding(.vertical, 3)
                        .background(.green.opacity(0.12), in: Capsule())
                }
                Spacer()
                Button {
                    Task { await viewModel.sendFeedback("save", paper: paper) }
                } label: {
                    Label(viewModel.t("Save"), systemImage: "bookmark")
                }
                .help(viewModel.t("Save"))
                Button {
                    Task { await viewModel.markRead(paper) }
                } label: {
                    Label(viewModel.t("Mark read"), systemImage: "checkmark.circle")
                }
                .help(viewModel.t("Mark read"))
                Button {
                    Task { await viewModel.sendFeedback("like", paper: paper) }
                } label: {
                    Label(viewModel.t("Like"), systemImage: "hand.thumbsup")
                }
                .help(viewModel.t("Like"))
                Button {
                    Task { await viewModel.sendFeedback("not_relevant", paper: paper) }
                } label: {
                    Label(viewModel.t("Hide"), systemImage: "eye.slash")
                }
                .help(viewModel.t("Hide"))
                Button {
                    Task { await viewModel.analyze(paper) }
                } label: {
                    Label(viewModel.t("Analyze"), systemImage: "wand.and.stars")
                }
                .help(viewModel.t("Analyze"))
                Button {
                    Task { await viewModel.assessUsefulness(paper) }
                } label: {
                    Label(viewModel.t("Assess usefulness"), systemImage: "target")
                }
                .help(viewModel.t("Assess usefulness"))
            }
            .labelStyle(.iconOnly)
            .buttonStyle(.borderless)
        }
        .padding(14)
        .background(.background, in: RoundedRectangle(cornerRadius: 8))
        .overlay {
            RoundedRectangle(cornerRadius: 8).stroke(.quaternary)
        }
    }

    private var metaLine: String {
        let authorText = paper.authors.prefix(3).joined(separator: ", ")
        return [paper.source, paper.publishedDate, paper.category, authorText]
            .compactMap { $0 }
            .filter { !$0.isEmpty }
            .joined(separator: " · ")
    }

    private func scoreColor(_ score: Double) -> Color {
        if score >= 70 { return .green }
        if score >= 40 { return .orange }
        return .secondary
    }
}

struct ProfileEditor: View {
    @EnvironmentObject private var viewModel: AppViewModel
    @State private var draft: ResearchProfile
    let onSave: (ResearchProfile) -> Void
    let onDelete: () -> Void

    init(profile: ResearchProfile, onSave: @escaping (ResearchProfile) -> Void, onDelete: @escaping () -> Void) {
        _draft = State(initialValue: profile)
        self.onSave = onSave
        self.onDelete = onDelete
    }

    var body: some View {
        Form {
            TextField(viewModel.t("Name"), text: $draft.name)
            HStack {
                Text(viewModel.t("Weight"))
                Slider(value: $draft.weight, in: 0.1...3.0)
                Text("\(draft.weight, specifier: "%.2f")")
                    .monospacedDigit()
            }
            TokenListEditor(title: viewModel.t("Include terms"), values: $draft.includeTerms)
            TokenListEditor(title: viewModel.t("Exclude terms"), values: $draft.excludeTerms)
            TokenListEditor(title: viewModel.t("Seed papers"), values: $draft.seedPapers)
            TokenListEditor(title: viewModel.t("Watch authors"), values: $draft.watchAuthors)
            TokenListEditor(title: viewModel.t("Watch labs"), values: $draft.watchLabs)
            VStack(alignment: .leading, spacing: 6) {
                Text(viewModel.t("arXiv query")).font(.caption).foregroundStyle(.secondary)
                TextField(viewModel.t("arXiv query"), text: $draft.arxivQuery)
                    .textFieldStyle(.roundedBorder)
            }
            VStack(alignment: .leading, spacing: 6) {
                Text(viewModel.t("bioRxiv query")).font(.caption).foregroundStyle(.secondary)
                TextField(viewModel.t("bioRxiv query"), text: $draft.biorxivQuery)
                    .textFieldStyle(.roundedBorder)
            }
            HStack {
                Button {
                    onSave(draft)
                } label: {
                    Label(viewModel.t("Save Profile"), systemImage: "checkmark")
                }
                .buttonStyle(.borderedProminent)
                Spacer()
                Button(role: .destructive) {
                    onDelete()
                } label: {
                    Label(viewModel.t("Delete"), systemImage: "trash")
                }
                .foregroundStyle(.red)
                .help(viewModel.t("Delete profile"))
            }
        }
        .formStyle(.grouped)
        .id(draft.id)
    }
}

struct TokenListEditor: View {
    @EnvironmentObject private var viewModel: AppViewModel
    let title: String
    @Binding var values: [String]
    @State private var draftValue = ""

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(title).font(.caption).foregroundStyle(.secondary)
            HStack {
                TextField(viewModel.t("Add item"), text: $draftValue)
                    .textFieldStyle(.roundedBorder)
                    .onSubmit(addDraft)
                Button {
                    addDraft()
                } label: {
                    Label(viewModel.t("Add"), systemImage: "plus")
                }
                .labelStyle(.iconOnly)
                .help(viewModel.t("Add"))
            }
            FlowLayout(spacing: 6) {
                ForEach(values, id: \.self) { value in
                    HStack(spacing: 4) {
                        Text(value)
                        Button {
                            values.removeAll { $0 == value }
                        } label: {
                            Image(systemName: "xmark")
                                .font(.caption2)
                        }
                        .buttonStyle(.plain)
                        .help(viewModel.t("Remove"))
                    }
                    .font(.caption)
                    .padding(.horizontal, 8)
                    .padding(.vertical, 5)
                    .background(.quaternary.opacity(0.7), in: Capsule())
                }
            }
        }
    }

    private func addDraft() {
        let items = draftValue
            .components(separatedBy: CharacterSet(charactersIn: ",\n"))
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }
        for item in items where !values.contains(item) {
            values.append(item)
        }
        draftValue = ""
    }
}

struct FlowLayout: Layout {
    var spacing: CGFloat = 8

    init(spacing: CGFloat = 8) {
        self.spacing = spacing
    }

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let width = proposal.width ?? 320
        var x: CGFloat = 0
        var y: CGFloat = 0
        var rowHeight: CGFloat = 0
        for subview in subviews {
            let size = subview.sizeThatFits(.unspecified)
            if x > 0 && x + size.width > width {
                x = 0
                y += rowHeight + spacing
                rowHeight = 0
            }
            x += size.width + spacing
            rowHeight = max(rowHeight, size.height)
        }
        return CGSize(width: width, height: y + rowHeight)
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        var x = bounds.minX
        var y = bounds.minY
        var rowHeight: CGFloat = 0
        for subview in subviews {
            let size = subview.sizeThatFits(.unspecified)
            if x > bounds.minX && x + size.width > bounds.maxX {
                x = bounds.minX
                y += rowHeight + spacing
                rowHeight = 0
            }
            subview.place(at: CGPoint(x: x, y: y), proposal: ProposedViewSize(size))
            x += size.width + spacing
            rowHeight = max(rowHeight, size.height)
        }
    }
}

struct ProfilePicker: View {
    @EnvironmentObject private var viewModel: AppViewModel

    var body: some View {
        Picker(viewModel.t("Profile"), selection: $viewModel.selectedProfileID) {
            ForEach(viewModel.profiles) { profile in
                Text(profile.name).tag(profile.id as String?)
            }
        }
        .frame(maxWidth: 280)
        .onChange(of: viewModel.selectedProfileID) {
            Task {
                do { try await viewModel.refreshAll() } catch { viewModel.statusLine = error.localizedDescription }
            }
        }
    }
}

struct Header: View {
    let title: String
    let subtitle: String

    var body: some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(title)
                .font(.largeTitle.bold())
            Text(subtitle)
                .foregroundStyle(.secondary)
        }
    }
}

struct StatusBar: View {
    @EnvironmentObject private var viewModel: AppViewModel

    var body: some View {
        HStack {
            if viewModel.isBusy {
                ProgressView()
                    .controlSize(.small)
            }
            Text(viewModel.statusLine)
                .font(.caption)
                .foregroundStyle(.secondary)
            Spacer()
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 8)
        .background(.bar)
    }
}
