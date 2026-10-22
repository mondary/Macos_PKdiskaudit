import AppKit
import SwiftUI
import UniformTypeIdentifiers
import WebKit

// MARK: - Modèle

enum SidebarItem: String, CaseIterable, Identifiable {
    case overview, findings, items, apps, models, zombies, plan, settings

    var id: String { rawValue }

    var title: String {
        switch self {
        case .overview: return "Vue d'ensemble"
        case .findings: return "Le gisement"
        case .items: return "Le détail"
        case .apps: return "Applications"
        case .models: return "Modèles"
        case .zombies: return "Les zombies"
        case .plan: return "Le plan"
        case .settings: return "Réglages"
        }
    }

    var symbol: String {
        switch self {
        case .overview: return "chart.pie"
        case .findings: return "sparkles"
        case .items: return "list.bullet.rectangle"
        case .apps: return "square.grid.2x2"
        case .models: return "cpu"
        case .zombies: return "exclamationmark.triangle"
        case .plan: return "list.number"
        case .settings: return "gearshape"
        }
    }

    var sectionID: String? {
        switch self {
        case .settings: return nil
        default: return rawValue
        }
    }
}

@MainActor
final class AppModel: ObservableObject {
    enum State: Equatable {
        case idle
        case running(phase: String, pct: Double, label: String)
        case done
        case failed(String)

        var isRunning: Bool {
            if case .running = self { return true }
            return false
        }
    }

    @Published var state: State = .idle
    @Published var reportURL: URL?
    @Published var jsonURL: URL?
    @Published var reloadToken = UUID()
    @Published var engineVersion = "—"
    @Published var fdaGranted: Bool = true
    @Published var statusLine = "Prêt."

    let outDir: URL
    private var process: Process?
    private var buffer = ""
    private var pending = ""

    init() {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first!
        outDir = base.appendingPathComponent("PKDiskAudit", isDirectory: true)
        try? FileManager.default.createDirectory(at: outDir, withIntermediateDirectories: true)
        reloadExisting()
        refreshDoctor()
    }

    func reloadExisting() {
        let html = outDir.appendingPathComponent("report.html")
        let json = outDir.appendingPathComponent("report.json")
        if FileManager.default.fileExists(atPath: html.path) { reportURL = html }
        if FileManager.default.fileExists(atPath: json.path) { jsonURL = json }
    }

    var progress: Double {
        if case .running(_, let pct, _) = state { return pct / 100.0 }
        return 0
    }

    // MARK: Scan

    func scan(fast: Bool) {
        guard !state.isRunning else { return }
        guard let engine = EngineLocator.locate() else {
            state = .failed("Moteur pkdisk introuvable. Lance `packaging/build_engine.sh` ou depuis le dépôt.")
            return
        }
        var args = ["run", "--out", outDir.path]
        if fast { args.append("--fast") }

        let process = Process()
        process.executableURL = engine.executable
        process.arguments = engine.arguments + args
        if let cwd = engine.cwd { process.currentDirectoryURL = cwd }
        var env = ProcessInfo.processInfo.environment
        for (key, value) in engine.environment { env[key] = value }
        env["PATH"] = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:" + (env["PATH"] ?? "")
        process.environment = env

        let pipe = Pipe()
        process.standardOutput = pipe
        process.standardError = pipe

        pipe.fileHandleForReading.readabilityHandler = { [weak self] handle in
            let data = handle.availableData
            guard !data.isEmpty, let text = String(data: data, encoding: .utf8) else { return }
            Task { @MainActor in self?.consume(text) }
        }

        process.terminationHandler = { [weak self] proc in
            Task { @MainActor in
                guard let self else { return }
                pipe.fileHandleForReading.readabilityHandler = nil
                if self.state.isRunning {
                    if proc.terminationStatus == 0 {
                        self.finishScan()
                    } else {
                        self.state = .failed("Le moteur s'est arrêté (code \(proc.terminationStatus)).")
                    }
                }
                self.process = nil
            }
        }

        do {
            state = .running(phase: "disk", pct: 0, label: "Démarrage")
            statusLine = "Scan en cours…"
            self.process = process
            try process.run()
        } catch {
            state = .failed("Impossible de lancer le moteur : \(error.localizedDescription)")
        }
    }

    func cancel() {
        process?.terminate()
        process = nil
        state = .idle
        statusLine = "Scan annulé."
    }

    private func consume(_ text: String) {
        pending += text
        while let index = pending.firstIndex(of: "\n") {
            let line = String(pending[pending.startIndex..<index])
            pending = String(pending[pending.index(after: index)...])
            handle(line: line)
        }
    }

    private func handle(line: String) {
        if line.hasPrefix("PHASE ") {
            let parts = line.split(separator: " ", maxSplits: 3).map(String.init)
            if parts.count >= 3 {
                let phase = parts[1]
                let pct = Double(parts[2]) ?? 0
                let label = parts.count > 3 ? parts[3] : ""
                state = .running(phase: phase, pct: pct, label: label)
                statusLine = "\(label.isEmpty ? phase : label)"
            }
        } else if line.hasPrefix("DONE ") {
            finishScan()
        } else if line.hasPrefix("ERREUR ") {
            state = .failed(String(line.dropFirst(7)))
        }
    }

    private func finishScan() {
        reloadExisting()
        state = .done
        statusLine = "Scan terminé."
        reloadToken = UUID()
        refreshDoctor()
    }

    // MARK: Doctor

    func refreshDoctor() {
        guard let engine = EngineLocator.locate() else { return }
        var environment = ProcessInfo.processInfo.environment
        for (key, value) in engine.environment { environment[key] = value }
        environment["PATH"] = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:" + (environment["PATH"] ?? "")
        let executable = engine.executable
        let arguments = engine.arguments + ["doctor"]
        let cwd = engine.cwd
        DispatchQueue.global(qos: .utility).async { [weak self] in
            let process = Process()
            process.executableURL = executable
            process.arguments = arguments
            if let cwd { process.currentDirectoryURL = cwd }
            process.environment = environment
            let pipe = Pipe()
            process.standardOutput = pipe
            process.standardError = Pipe()
            try? process.run()
            process.waitUntilExit()
            let data = pipe.fileHandleForReading.readDataToEndOfFile()
            guard let text = String(data: data, encoding: .utf8),
                  let object = try? JSONSerialization.jsonObject(with: Data(text.utf8)) as? [String: Any] else { return }
            Task { @MainActor in
                self?.engineVersion = object["engine"] as? String ?? "—"
                self?.fdaGranted = object["fda_likely_granted"] as? Bool ?? true
            }
        }
    }

    // MARK: Export

    func exportReport() {
        guard let reportURL else { return }
        let panel = NSSavePanel()
        panel.nameFieldStringValue = "PKDiskAudit-\(Self.stamp()).html"
        panel.allowedContentTypes = [.html]
        if panel.runModal() == .OK, let destination = panel.url {
            try? FileManager.default.removeItem(at: destination)
            try? FileManager.default.copyItem(at: reportURL, to: destination)
            NSWorkspace.shared.activateFileViewerSelecting([destination])
        }
    }

    func revealReport() {
        guard let reportURL else { return }
        NSWorkspace.shared.activateFileViewerSelecting([reportURL])
    }

    func openSystemSettings() {
        if let url = URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles") {
            NSWorkspace.shared.open(url)
        }
    }

    static func stamp() -> String {
        let formatter = DateFormatter()
        formatter.dateFormat = "yyyy-MM-dd-HHmm"
        return formatter.string(from: Date())
    }
}

// MARK: - Localisation du moteur

struct Engine {
    var executable: URL
    var arguments: [String]
    var environment: [String: String]
    var cwd: URL?
}

enum EngineLocator {
    static func locate() -> Engine? {
        // 1. Moteur embarqué dans le bundle (PyInstaller)
        if let url = Bundle.main.url(forResource: "pkdisk", withExtension: nil, subdirectory: "engine") {
            return Engine(executable: url, arguments: [], environment: [:], cwd: nil)
        }
        if let resources = Bundle.main.resourceURL {
            let candidate = resources.appendingPathComponent("engine/pkdisk")
            if FileManager.default.isExecutableFile(atPath: candidate.path) {
                return Engine(executable: candidate, arguments: [], environment: [:], cwd: nil)
            }
        }
        // 2. Dépôt de développement : on remonte depuis le binaire
        var directory = Bundle.main.executableURL?.deletingLastPathComponent()
        for _ in 0..<6 {
            guard let dir = directory else { break }
            let entry = dir.appendingPathComponent("engine/pkdisk/__main__.py")
            if FileManager.default.fileExists(atPath: entry.path) {
                let python = URL(fileURLWithPath: "/usr/bin/env")
                return Engine(
                    executable: python,
                    arguments: ["python3", "-m", "pkdisk"],
                    environment: ["PYTHONPATH": dir.appendingPathComponent("engine").path],
                    cwd: dir
                )
            }
            directory = dir.deletingLastPathComponent()
        }
        // 3. Variable d'environnement
        if let repo = ProcessInfo.processInfo.environment["PKDISKAUDIT_REPO"] {
            let dir = URL(fileURLWithPath: repo)
            let entry = dir.appendingPathComponent("engine/pkdisk/__main__.py")
            if FileManager.default.fileExists(atPath: entry.path) {
                return Engine(
                    executable: URL(fileURLWithPath: "/usr/bin/env"),
                    arguments: ["python3", "-m", "pkdisk"],
                    environment: ["PYTHONPATH": dir.appendingPathComponent("engine").path],
                    cwd: dir
                )
            }
        }
        return nil
    }
}

// MARK: - App

@main
struct PKDiskAuditApp: App {
    @StateObject private var model = AppModel()

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(model)
                .frame(minWidth: 1080, minHeight: 720)
        }
        .commands {
            CommandGroup(after: .newItem) {
                Button("Scanner le disque") { model.scan(fast: false) }
                    .keyboardShortcut("r", modifiers: .command)
                    .disabled(model.state.isRunning)
                Button("Scan rapide") { model.scan(fast: true) }
                    .keyboardShortcut("r", modifiers: [.command, .shift])
                    .disabled(model.state.isRunning)
                Divider()
                Button("Exporter le rapport…") { model.exportReport() }
                    .disabled(model.reportURL == nil)
                Button("Révéler le rapport") { model.revealReport() }
                    .disabled(model.reportURL == nil)
            }
        }
    }
}

// MARK: - Interface

final class UIState: ObservableObject {
    @Published var selection: SidebarItem? = .overview
    @Published var section: String? = "overview"
}

struct ContentView: View {
    @EnvironmentObject private var model: AppModel
    @StateObject private var ui = UIState()

    var body: some View {
        NavigationSplitView {
            List(SidebarItem.allCases, selection: $ui.selection) { item in
                Label(item.title, systemImage: item.symbol)
                    .tag(item)
            }
            .navigationSplitViewColumnWidth(min: 200, ideal: 220, max: 260)
            .safeAreaInset(edge: .bottom) {
                VStack(alignment: .leading, spacing: 4) {
                    Text("PKDiskAudit \(model.engineVersion)")
                        .font(.caption.weight(.medium))
                    if !model.fdaGranted {
                        Button {
                            model.openSystemSettings()
                        } label: {
                            Label("Accès complet au disque requis", systemImage: "exclamationmark.triangle")
                                .font(.caption)
                        }
                        .buttonStyle(.plain)
                        .foregroundStyle(.orange)
                    }
                }
                .padding(12)
                .frame(maxWidth: .infinity, alignment: .leading)
            }
        } detail: {
            Group {
                if ui.selection == .settings {
                    SettingsView()
                } else if let reportURL = model.reportURL {
                    ReportWebView(url: reportURL, reloadToken: model.reloadToken, section: ui.section)
                } else {
                    WelcomeView()
                }
            }
            .toolbar {
                ToolbarItemGroup(placement: .primaryAction) {
                    if model.state.isRunning {
                        ProgressView(value: model.progress)
                            .progressViewStyle(.linear)
                            .frame(width: 160)
                        Button("Annuler") { model.cancel() }
                    } else {
                        Button {
                            model.scan(fast: false)
                        } label: {
                            Label("Scanner", systemImage: "arrow.clockwise")
                        }
                        .keyboardShortcut("r", modifiers: .command)
                    }
                }
                ToolbarItemGroup(placement: .automatic) {
                    Button {
                        model.exportReport()
                    } label: {
                        Label("Exporter", systemImage: "square.and.arrow.up")
                    }
                    .disabled(model.reportURL == nil)
                    Button {
                        model.revealReport()
                    } label: {
                        Label("Révéler", systemImage: "folder")
                    }
                    .disabled(model.reportURL == nil)
                }
            }
            .onChange(of: ui.selection) { _, newValue in
                ui.section = newValue?.sectionID ?? "overview"
            }
            .preferredColorScheme(.dark)
        }
    }
}

struct WelcomeView: View {
    @EnvironmentObject private var model: AppModel

    var body: some View {
        VStack(alignment: .leading, spacing: 22) {
            Text("Où est passée\nla place ?")
                .font(.system(size: 52, weight: .semibold, design: .rounded))
                .tracking(-1.5)
            Text("PKDiskAudit mesure ton disque en lecture seule, classe ce qui est reconstruisible et t'explique chaque poste avant de toucher à quoi que ce soit.")
                .font(.title3)
                .foregroundStyle(.secondary)
                .frame(maxWidth: 620, alignment: .leading)
            HStack(spacing: 12) {
                Button {
                    model.scan(fast: false)
                } label: {
                    Label("Scanner mon Mac", systemImage: "magnifyingglass")
                }
                .keyboardShortcut(.defaultAction)
                Button("Scan rapide") { model.scan(fast: true) }
            }
            .controlSize(.large)
            HStack(spacing: 8) {
                Image(systemName: model.fdaGranted ? "checkmark.seal" : "exclamationmark.triangle")
                    .foregroundStyle(model.fdaGranted ? .green : .orange)
                Text(model.fdaGranted
                     ? "Accès complet au disque accordé."
                     : "Sans Accès complet au disque, certaines zones resteront illisibles. Le scan reste honnête : il signale les parties manquantes.")
                    .font(.callout)
                    .foregroundStyle(.secondary)
            }
            .frame(maxWidth: 620, alignment: .leading)
            Spacer()
        }
        .padding(48)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
    }
}

struct SettingsView: View {
    @EnvironmentObject private var model: AppModel

    var body: some View {
        Form {
            Section("Moteur") {
                LabeledContent("Version", value: model.engineVersion)
                LabeledContent("Dossier de sortie", value: model.outDir.path)
            }
            Section("Accès") {
                HStack {
                    Image(systemName: model.fdaGranted ? "checkmark.seal.fill" : "exclamationmark.triangle.fill")
                        .foregroundStyle(model.fdaGranted ? .green : .orange)
                    Text(model.fdaGranted ? "Accès complet au disque accordé" : "Accès complet au disque non accordé")
                    Spacer()
                    Button("Ouvrir les Réglages Système") { model.openSystemSettings() }
                }
            }
            Section("Rapport") {
                HStack {
                    Button("Exporter le HTML…") { model.exportReport() }
                        .disabled(model.reportURL == nil)
                    Button("Révéler dans le Finder") { model.revealReport() }
                        .disabled(model.reportURL == nil)
                }
            }
            Section("Sécurité") {
                Text("Le scan est en lecture seule. Aucune suppression n'est effectuée par cette version.")
                    .font(.callout)
                    .foregroundStyle(.secondary)
            }
            Section("Soutenir") {
                Link(destination: URL(string: "https://ko-fi.com/pouark")!) {
                    Label("Soutenir PKDiskAudit sur Ko-fi", systemImage: "heart")
                }
                Text("Gratuit, sans compte et hors ligne. Le soutien finance les prochains chantiers.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
        .formStyle(.grouped)
        .navigationTitle("Réglages")
    }
}

// MARK: - WebView

struct ReportWebView: NSViewRepresentable {
    let url: URL
    let reloadToken: UUID
    let section: String?

    final class Coordinator {
        var lastToken: UUID?
        var lastSection: String?
    }

    func makeCoordinator() -> Coordinator { Coordinator() }

    func makeNSView(context: Context) -> WKWebView {
        let configuration = WKWebViewConfiguration()
        configuration.suppressesIncrementalRendering = false
        let webView = WKWebView(frame: .zero, configuration: configuration)
        webView.setValue(false, forKey: "drawsBackground")
        load(webView, coordinator: context.coordinator)
        return webView
    }

    func updateNSView(_ webView: WKWebView, context: Context) {
        if context.coordinator.lastToken != reloadToken {
            load(webView, coordinator: context.coordinator)
        }
        if let section, context.coordinator.lastSection != section {
            context.coordinator.lastSection = section
            webView.evaluateJavaScript("scrollToSection('\(section)');", completionHandler: nil)
        }
    }

    private func load(_ webView: WKWebView, coordinator: Coordinator) {
        coordinator.lastToken = reloadToken
        webView.loadFileURL(url, allowingReadAccessTo: url.deletingLastPathComponent())
    }
}
