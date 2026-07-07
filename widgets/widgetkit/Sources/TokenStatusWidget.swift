import Foundation
import SwiftUI
import WidgetKit

private let tokenDataURL = URL(string: "https://raw.githubusercontent.com/jehyunlee/dashboards/data/data/tokens.json")!
private let tokenHistoryURL = URL(string: "https://raw.githubusercontent.com/jehyunlee/dashboards/data/data/tokens_history.json")!
private let dashboardURL = URL(string: "https://tech.jehyunlee.dev/dashboards/tokens/")!
private let providerOrder = ["openai", "anthropic", "gemini"]

struct TokenSnapshot: Decodable {
    let updatedAt: String?
    let overall: String?
    let summary: String?
    let providers: [ProviderStatus]

    enum CodingKeys: String, CodingKey {
        case updatedAt = "updated_at"
        case overall
        case summary
        case providers
    }
}

struct ProviderStatus: Decodable, Identifiable {
    let id: String
    let label: String?
    let status: String?
    let billing: Billing?
    let usageSeries: UsageSeries?
    let subscriptionSeries: UsageSeries?
    let tokenWindow: TokenWindow?

    enum CodingKeys: String, CodingKey {
        case id
        case label
        case status
        case billing
        case usageSeries = "usage_series"
        case subscriptionSeries = "subscription_series"
        case tokenWindow = "token_window"
    }
}

struct Billing: Decodable {
    let monthToDateCost: Double?
    let usage: BillingUsage?

    enum CodingKeys: String, CodingKey {
        case monthToDateCost = "month_to_date_cost"
        case usage
    }
}

struct BillingUsage: Decodable {
    let totalTokens: Double?

    enum CodingKeys: String, CodingKey {
        case totalTokens = "total_tokens"
    }
}

struct UsageSeries: Decodable {
    let available: Bool?
    let points: [SeriesPoint]?
}

struct SeriesPoint: Decodable, Identifiable {
    let t: String?
    let tokens: Double?
    var id: String { t ?? "point-\(tokens ?? 0)" }
}

struct TokenWindow: Decodable {
    let tokens: WindowTokens?
}

struct WindowTokens: Decodable {
    let limit: String?
    let remaining: String?
}

struct TokenHistory: Decodable {
    let samples: [HistorySample]
}

struct HistorySample: Decodable, Identifiable {
    let t: String?
    let providers: [String: HistoryProviderState]
    var id: String { t ?? "history" }

    init(t: String?, providers: [String: HistoryProviderState]) {
        self.t = t
        self.providers = providers
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: DynamicCodingKey.self)
        let tKey = DynamicCodingKey(stringValue: "t")!
        t = try? container.decode(String.self, forKey: tKey)

        var decoded: [String: HistoryProviderState] = [:]
        for key in container.allKeys where key.stringValue != "t" {
            if let value = try? container.decode(HistoryProviderState.self, forKey: key) {
                decoded[key.stringValue] = value
            }
        }
        providers = decoded
    }
}

struct HistoryProviderState: Decodable {
    let connected: Int?
}

struct DynamicCodingKey: CodingKey {
    let stringValue: String
    let intValue: Int?

    init?(stringValue: String) {
        self.stringValue = stringValue
        self.intValue = nil
    }

    init?(intValue: Int) {
        self.stringValue = String(intValue)
        self.intValue = intValue
    }
}

struct TokenEntry: TimelineEntry {
    let date: Date
    let snapshot: TokenSnapshot?
    let history: TokenHistory
    let error: String?
}

struct TokenProvider: TimelineProvider {
    func placeholder(in context: Context) -> TokenEntry {
        TokenEntry(date: Date(), snapshot: TokenSnapshot.placeholder, history: .placeholder, error: nil)
    }

    func getSnapshot(in context: Context, completion: @escaping (TokenEntry) -> Void) {
        completion(TokenEntry(date: Date(), snapshot: TokenSnapshot.placeholder, history: .placeholder, error: nil))
    }

    func getTimeline(in context: Context, completion: @escaping (Timeline<TokenEntry>) -> Void) {
        fetchPayload { result in
            let entry: TokenEntry
            switch result {
            case .success(let payload):
                entry = TokenEntry(date: Date(), snapshot: payload.snapshot, history: payload.history, error: nil)
            case .failure(let error):
                entry = TokenEntry(date: Date(), snapshot: TokenSnapshot.placeholder, history: .placeholder, error: error.localizedDescription)
            }
            completion(Timeline(entries: [entry], policy: .after(Date().addingTimeInterval(5 * 60))))
        }
    }

    private func fetchPayload(completion: @escaping (Result<(snapshot: TokenSnapshot, history: TokenHistory), Error>) -> Void) {
        fetchJSON(TokenSnapshot.self, from: tokenDataURL) { snapshotResult in
            switch snapshotResult {
            case .failure(let error):
                completion(.failure(error))
            case .success(let snapshot):
                fetchJSON(TokenHistory.self, from: tokenHistoryURL) { historyResult in
                    let history = (try? historyResult.get()) ?? TokenHistory(samples: [])
                    completion(.success((snapshot: snapshot, history: history)))
                }
            }
        }
    }

    private func fetchJSON<T: Decodable>(_ type: T.Type, from url: URL, completion: @escaping (Result<T, Error>) -> Void) {
        var request = URLRequest(url: url)
        request.cachePolicy = .reloadIgnoringLocalCacheData
        URLSession.shared.dataTask(with: request) { data, response, error in
            if let error {
                completion(.failure(error))
                return
            }
            guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode), let data else {
                completion(.failure(URLError(.badServerResponse)))
                return
            }
            do {
                completion(.success(try JSONDecoder().decode(T.self, from: data)))
            } catch {
                completion(.failure(error))
            }
        }.resume()
    }
}

struct TokenStatusWidgetView: View {
    @Environment(\.widgetFamily) private var family
    let entry: TokenEntry

    var body: some View {
        let snapshot = entry.snapshot
        let providers = orderedProviders(snapshot?.providers ?? TokenSnapshot.placeholder.providers)
        let status = effectiveStatus(snapshot)
        let tickCount = family == .systemLarge ? 30 : 18

        VStack(alignment: .leading, spacing: family == .systemSmall ? 8 : 10) {
            header(snapshot: snapshot, status: status)

            if family == .systemSmall {
                SmallMatrix(providers: providers, history: entry.history, tickCount: 10)
            } else {
                MatrixDashboard(providers: providers, history: entry.history, tickCount: tickCount, showColumnHeaders: family == .systemLarge)
            }

            if let error = entry.error {
                Text("last fetch error: \(error)")
                    .font(.caption2)
                    .foregroundStyle(.orange)
                    .lineLimit(1)
            }
        }
        .containerBackground(.regularMaterial, for: .widget)
        .widgetURL(dashboardURL)
    }

    private func header(snapshot: TokenSnapshot?, status: String) -> some View {
        HStack(alignment: .top, spacing: 8) {
            VStack(alignment: .leading, spacing: 3) {
                Text("TOKEN MATRIX")
                    .font(.caption2.weight(.black))
                    .foregroundStyle(.secondary)
                Text(family == .systemSmall ? "3 providers" : "OpenAI · Anthropic · Google")
                    .font(family == .systemSmall ? .headline.weight(.bold) : .title3.weight(.bold))
                    .lineLimit(1)
                Text("5분 단위 · \(detail(snapshot))")
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
            }
            Spacer(minLength: 4)
            VStack(alignment: .trailing, spacing: 4) {
                Circle()
                    .fill(color(for: status))
                    .frame(width: 12, height: 12)
                    .shadow(color: color(for: status).opacity(0.35), radius: 6)
                Text(title(for: status))
                    .font(.caption2.weight(.bold))
                    .foregroundStyle(color(for: status))
                    .lineLimit(1)
            }
        }
    }

    private func effectiveStatus(_ snapshot: TokenSnapshot?) -> String {
        guard let snapshot else { return "unknown" }
        if isStale(snapshot.updatedAt) { return "warn" }
        return snapshot.overall ?? "unknown"
    }

    private func title(for status: String) -> String {
        switch status {
        case "ok": return "OK"
        case "warn": return "STALE"
        default: return "BAD"
        }
    }

    private func detail(_ snapshot: TokenSnapshot?) -> String {
        guard let snapshot else { return "Waiting for token status data." }
        return ageText(snapshot.updatedAt)
    }
}

struct MatrixDashboard: View {
    let providers: [ProviderStatus]
    let history: TokenHistory
    let tickCount: Int
    let showColumnHeaders: Bool

    private let providerWidth: CGFloat = 66

    var body: some View {
        VStack(alignment: .leading, spacing: 7) {
            if showColumnHeaders {
                HStack(spacing: 6) {
                    Text("MODEL")
                        .frame(width: providerWidth, alignment: .leading)
                    MatrixHeader("API 접속")
                    MatrixHeader("구독 토큰")
                    MatrixHeader("API 토큰")
                }
                .font(.caption2.weight(.black))
                .foregroundStyle(.secondary)
            }

            ForEach(providers.prefix(3)) { provider in
                HStack(alignment: .center, spacing: 6) {
                    ProviderPill(provider: provider)
                        .frame(width: providerWidth, alignment: .leading)

                    ConnectionCell(provider: provider, history: history, tickCount: tickCount)
                    UsageCell(
                        value: subscriptionValue(provider),
                        detail: provider.id == "gemini" ? "—" : "6h",
                        points: usageValues(provider.subscriptionSeries, count: tickCount),
                        tint: providerTint(for: provider.id),
                        emptyText: provider.id == "gemini" ? "구독 없음" : "0"
                    )
                    UsageCell(
                        value: usageValue(provider.usageSeries),
                        detail: "6h",
                        points: usageValues(provider.usageSeries, count: tickCount),
                        tint: providerTint(for: provider.id),
                        emptyText: "0"
                    )
                }
            }
        }
    }
}

struct SmallMatrix: View {
    let providers: [ProviderStatus]
    let history: TokenHistory
    let tickCount: Int

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            ForEach(providers.prefix(3)) { provider in
                VStack(alignment: .leading, spacing: 4) {
                    HStack(spacing: 6) {
                        Circle().fill(color(for: provider.status ?? "unknown")).frame(width: 7, height: 7)
                        Text(displayName(provider)).font(.caption.weight(.bold)).lineLimit(1)
                        Spacer(minLength: 4)
                        Text("S \(subscriptionValue(provider)) · API \(usageValue(provider.usageSeries))")
                            .font(.caption2.monospacedDigit())
                            .foregroundStyle(.secondary)
                            .lineLimit(1)
                    }
                    HStack(spacing: 4) {
                        ConnectionTicksView(ticks: connectionTicks(providerID: provider.id, history: history, count: tickCount), tint: color(for: provider.status ?? "unknown"))
                        UsageBars(values: usageValues(provider.subscriptionSeries, count: tickCount), tint: providerTint(for: provider.id), emptyText: nil)
                        UsageBars(values: usageValues(provider.usageSeries, count: tickCount), tint: providerTint(for: provider.id), emptyText: nil)
                    }
                    .frame(height: 12)
                }
            }
        }
    }
}

struct MatrixHeader: View {
    let title: String

    init(_ title: String) {
        self.title = title
    }

    var body: some View {
        Text(title)
            .frame(maxWidth: .infinity, alignment: .leading)
    }
}

struct ProviderPill: View {
    let provider: ProviderStatus

    var body: some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(displayName(provider))
                .font(.caption.weight(.black))
                .lineLimit(1)
            Text(statusText(provider.status))
                .font(.caption2.weight(.bold))
                .foregroundStyle(color(for: provider.status ?? "unknown"))
                .lineLimit(1)
        }
    }
}

struct ConnectionCell: View {
    let provider: ProviderStatus
    let history: TokenHistory
    let tickCount: Int

    var body: some View {
        let ticks = connectionTicks(providerID: provider.id, history: history, count: tickCount)
        VStack(alignment: .leading, spacing: 4) {
            HStack(alignment: .firstTextBaseline, spacing: 4) {
                Text(connectionSummary(ticks))
                    .font(.caption2.monospacedDigit().weight(.bold))
                    .lineLimit(1)
                Spacer(minLength: 0)
                Text("5m")
                    .font(.caption2.weight(.semibold))
                    .foregroundStyle(.secondary)
            }
            ConnectionTicksView(ticks: ticks, tint: color(for: provider.status ?? "unknown"))
                .frame(height: 18)
        }
        .frame(maxWidth: .infinity)
        .padding(6)
        .background(.white.opacity(0.44), in: RoundedRectangle(cornerRadius: 10, style: .continuous))
    }
}

struct UsageCell: View {
    let value: String
    let detail: String
    let points: [Double]
    let tint: Color
    let emptyText: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(alignment: .firstTextBaseline, spacing: 4) {
                Text(value)
                    .font(.caption2.monospacedDigit().weight(.bold))
                    .lineLimit(1)
                    .minimumScaleFactor(0.72)
                Spacer(minLength: 0)
                Text(detail)
                    .font(.caption2.weight(.semibold))
                    .foregroundStyle(.secondary)
            }
            UsageBars(values: points, tint: tint, emptyText: emptyText)
                .frame(height: 18)
        }
        .frame(maxWidth: .infinity)
        .padding(6)
        .background(.white.opacity(0.44), in: RoundedRectangle(cornerRadius: 10, style: .continuous))
    }
}

struct ConnectionTicksView: View {
    let ticks: [Int]
    let tint: Color

    var body: some View {
        HStack(alignment: .center, spacing: 1.5) {
            ForEach(Array(ticks.enumerated()), id: \.offset) { _, state in
                Capsule()
                    .fill(tickColor(state, tint: tint))
                    .frame(maxWidth: .infinity)
                    .frame(height: state < 0 ? 4 : 14)
            }
        }
    }
}

struct UsageBars: View {
    let values: [Double]
    let tint: Color
    let emptyText: String?

    var body: some View {
        if values.isEmpty {
            ZStack {
                HStack(alignment: .center, spacing: 1.5) {
                    ForEach(0..<12, id: \.self) { _ in
                        Capsule()
                            .fill(.secondary.opacity(0.16))
                            .frame(maxWidth: .infinity)
                            .frame(height: 4)
                    }
                }
                if let emptyText {
                    Text(emptyText)
                        .font(.caption2.weight(.bold))
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                }
            }
        } else {
            let maxValue = max(values.max() ?? 1, 1)
            HStack(alignment: .bottom, spacing: 1.5) {
                ForEach(Array(values.enumerated()), id: \.offset) { _, value in
                    Capsule()
                        .fill(tint.opacity(value <= 0 ? 0.18 : 0.92))
                        .frame(maxWidth: .infinity)
                        .frame(height: value <= 0 ? 3 : max(4, CGFloat(value / maxValue) * 18))
                }
            }
        }
    }
}

struct TokenStatusWidget: Widget {
    let kind = "dev.jehyunlee.dashboards.token-status"

    var body: some WidgetConfiguration {
        StaticConfiguration(kind: kind, provider: TokenProvider()) { entry in
            TokenStatusWidgetView(entry: entry)
        }
        .configurationDisplayName("Token Status")
        .description("OpenAI, Anthropic, Google의 API 접속·구독 토큰·API 토큰 흐름을 봅니다.")
        .supportedFamilies([.systemSmall, .systemMedium, .systemLarge])
    }
}

@main
struct JehyunDashboardWidgetBundle: WidgetBundle {
    var body: some Widget {
        TokenStatusWidget()
    }
}

private extension TokenSnapshot {
    static let placeholder = TokenSnapshot(
        updatedAt: ISO8601DateFormatter().string(from: Date()),
        overall: "ok",
        summary: "3/3 provider APIs connected.",
        providers: [
            ProviderStatus(id: "openai", label: "OpenAI", status: "ok", billing: Billing(monthToDateCost: 23.93, usage: BillingUsage(totalTokens: 17_300_000)), usageSeries: UsageSeries(available: true, points: placeholderPoints(seed: 2)), subscriptionSeries: UsageSeries(available: true, points: placeholderPoints(seed: 5)), tokenWindow: nil),
            ProviderStatus(id: "anthropic", label: "Anthropic", status: "ok", billing: Billing(monthToDateCost: 14582, usage: BillingUsage(totalTokens: 21_200_000)), usageSeries: UsageSeries(available: true, points: placeholderPoints(seed: 4)), subscriptionSeries: UsageSeries(available: true, points: placeholderPoints(seed: 9)), tokenWindow: nil),
            ProviderStatus(id: "gemini", label: "Gemini", status: "ok", billing: nil, usageSeries: UsageSeries(available: true, points: placeholderPoints(seed: 1)), subscriptionSeries: nil, tokenWindow: nil)
        ]
    )

    static func placeholderPoints(seed: Int) -> [SeriesPoint] {
        (0..<72).map { i in
            SeriesPoint(t: String(i), tokens: Double((i * seed + 7) % 23))
        }
    }
}

private extension TokenHistory {
    static let placeholder = TokenHistory(samples: (0..<36).map { i in
        HistorySample(t: String(i), providers: [
            "openai": HistoryProviderState(connected: 1),
            "anthropic": HistoryProviderState(connected: 1),
            "gemini": HistoryProviderState(connected: i % 13 == 0 ? 0 : 1)
        ])
    })
}

private func orderedProviders(_ providers: [ProviderStatus]) -> [ProviderStatus] {
    providerOrder.compactMap { id in providers.first { $0.id == id } }
}

private func displayName(_ provider: ProviderStatus) -> String {
    switch provider.id {
    case "gemini": return "Google"
    default: return provider.label ?? provider.id.capitalized
    }
}

private func statusText(_ status: String?) -> String {
    switch status {
    case "ok": return "connected"
    case "warn", "rate_limited": return "limited"
    case "missing": return "missing"
    case "auth_error": return "auth"
    default: return "down"
    }
}

private func color(for status: String) -> Color {
    switch status {
    case "ok": return .green
    case "warn", "missing", "rate_limited", "unknown": return .orange
    default: return .red
    }
}

private func tickColor(_ state: Int, tint: Color) -> Color {
    if state > 0 { return tint.opacity(0.92) }
    if state == 0 { return .red.opacity(0.86) }
    return .secondary.opacity(0.16)
}

private func providerTint(for providerID: String) -> Color {
    switch providerID {
    case "anthropic": return .orange
    case "gemini": return .teal
    default: return .blue
    }
}

private func connectionTicks(providerID: String, history: TokenHistory, count: Int) -> [Int] {
    let tail = Array(history.samples.suffix(count))
    let decoded = tail.map { sample -> Int in
        guard let connected = sample.providers[providerID]?.connected else { return -1 }
        return connected == 1 ? 1 : 0
    }
    if decoded.count >= count { return decoded }
    return Array(repeating: -1, count: count - decoded.count) + decoded
}

private func connectionSummary(_ ticks: [Int]) -> String {
    let known = ticks.filter { $0 >= 0 }
    guard !known.isEmpty else { return "—" }
    let up = known.filter { $0 > 0 }.count
    return "\(up)/\(known.count)"
}

private func usageValues(_ series: UsageSeries?, count: Int) -> [Double] {
    guard series?.available == true, let points = series?.points, !points.isEmpty else { return [] }
    let values = Array(points.suffix(count)).map { max(0, $0.tokens ?? 0) }
    if values.count >= count { return values }
    return Array(repeating: 0, count: count - values.count) + values
}

private func seriesTotal(_ series: UsageSeries?) -> Double? {
    guard series?.available == true, let points = series?.points else { return nil }
    return points.reduce(0) { $0 + max(0, $1.tokens ?? 0) }
}

private func subscriptionValue(_ provider: ProviderStatus) -> String {
    guard provider.id != "gemini", let total = seriesTotal(provider.subscriptionSeries) else { return "—" }
    return formatCompact(total)
}

private func usageValue(_ series: UsageSeries?) -> String {
    guard let total = seriesTotal(series) else { return "—" }
    return formatCompact(total)
}

private func formatCompact(_ value: Double?) -> String {
    guard let value, value.isFinite else { return "—" }
    if value >= 1_000_000_000 { return String(format: value >= 10_000_000_000 ? "%.0fB" : "%.1fB", value / 1_000_000_000) }
    if value >= 1_000_000 { return String(format: value >= 10_000_000 ? "%.0fM" : "%.1fM", value / 1_000_000) }
    if value >= 1_000 { return String(format: value >= 10_000 ? "%.0fK" : "%.1fK", value / 1_000) }
    return String(format: "%.0f", value)
}

private func parsedDate(_ value: String?) -> Date? {
    guard let value else { return nil }
    let fractional = ISO8601DateFormatter()
    fractional.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
    if let date = fractional.date(from: value) { return date }
    return ISO8601DateFormatter().date(from: value)
}

private func isStale(_ value: String?) -> Bool {
    guard let date = parsedDate(value) else { return true }
    return Date().timeIntervalSince(date) > 30 * 60
}

private func ageText(_ value: String?) -> String {
    guard let date = parsedDate(value) else { return "unknown" }
    let seconds = max(0, Int(Date().timeIntervalSince(date).rounded()))
    if seconds < 90 { return "\(seconds)s ago" }
    let minutes = Int((Double(seconds) / 60).rounded())
    if minutes < 90 { return "\(minutes)m ago" }
    return "\(Int((Double(minutes) / 60).rounded()))h ago"
}
