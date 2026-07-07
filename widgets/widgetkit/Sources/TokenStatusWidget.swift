import Foundation
import SwiftUI
import WidgetKit

private let tokenDataURL = URL(string: "https://raw.githubusercontent.com/jehyunlee/dashboards/data/data/tokens.json")!
private let dashboardURL = URL(string: "https://tech.jehyunlee.dev/dashboards/tokens/")!

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
    var id: String { t ?? UUID().uuidString }
}

struct TokenWindow: Decodable {
    let tokens: WindowTokens?
}

struct WindowTokens: Decodable {
    let limit: String?
    let remaining: String?
}

struct TokenEntry: TimelineEntry {
    let date: Date
    let snapshot: TokenSnapshot?
    let error: String?
}

struct TokenProvider: TimelineProvider {
    func placeholder(in context: Context) -> TokenEntry {
        TokenEntry(date: Date(), snapshot: TokenSnapshot.placeholder, error: nil)
    }

    func getSnapshot(in context: Context, completion: @escaping (TokenEntry) -> Void) {
        completion(TokenEntry(date: Date(), snapshot: TokenSnapshot.placeholder, error: nil))
    }

    func getTimeline(in context: Context, completion: @escaping (Timeline<TokenEntry>) -> Void) {
        fetchSnapshot { result in
            let entry: TokenEntry
            switch result {
            case .success(let snapshot):
                entry = TokenEntry(date: Date(), snapshot: snapshot, error: nil)
            case .failure(let error):
                entry = TokenEntry(date: Date(), snapshot: TokenSnapshot.placeholder, error: error.localizedDescription)
            }
            completion(Timeline(entries: [entry], policy: .after(Date().addingTimeInterval(5 * 60))))
        }
    }

    private func fetchSnapshot(completion: @escaping (Result<TokenSnapshot, Error>) -> Void) {
        var request = URLRequest(url: tokenDataURL)
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
                completion(.success(try JSONDecoder().decode(TokenSnapshot.self, from: data)))
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
        let providers = snapshot?.providers ?? []
        let status = effectiveStatus(snapshot)

        VStack(alignment: .leading, spacing: family == .systemSmall ? 8 : 10) {
            header(snapshot: snapshot, status: status)

            if family == .systemSmall {
                smallProviders(providers)
            } else {
                providerTable(providers, includeCharts: family == .systemLarge)
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
                Text("TOKEN STATUS")
                    .font(.caption2.weight(.black))
                    .foregroundStyle(.secondary)
                Text(title(for: status))
                    .font(family == .systemSmall ? .headline.weight(.bold) : .title3.weight(.bold))
                    .lineLimit(1)
                Text(detail(snapshot))
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                    .lineLimit(family == .systemSmall ? 2 : 1)
            }
            Spacer(minLength: 4)
            Circle()
                .fill(color(for: status))
                .frame(width: 12, height: 12)
                .shadow(color: color(for: status).opacity(0.35), radius: 6)
        }
    }

    private func smallProviders(_ providers: [ProviderStatus]) -> some View {
        VStack(alignment: .leading, spacing: 7) {
            ForEach(providers.prefix(3)) { provider in
                HStack(spacing: 6) {
                    Circle().fill(color(for: provider.status ?? "unknown")).frame(width: 7, height: 7)
                    Text(provider.label ?? provider.id.capitalized).font(.caption.weight(.semibold)).lineLimit(1)
                    Spacer(minLength: 4)
                    Text(formatCompact(provider.billing?.usage?.totalTokens)).font(.caption2.monospacedDigit()).foregroundStyle(.secondary)
                }
            }
        }
    }

    private func providerTable(_ providers: [ProviderStatus], includeCharts: Bool) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            ForEach(providers.prefix(3)) { provider in
                VStack(alignment: .leading, spacing: 5) {
                    HStack(alignment: .firstTextBaseline, spacing: 8) {
                        HStack(spacing: 6) {
                            Circle().fill(color(for: provider.status ?? "unknown")).frame(width: 8, height: 8)
                            Text(provider.label ?? provider.id.capitalized).font(.caption.weight(.bold)).lineLimit(1)
                        }
                        Spacer(minLength: 4)
                        Text("30d \(formatCompact(provider.billing?.usage?.totalTokens))")
                            .font(.caption2.monospacedDigit())
                            .foregroundStyle(.secondary)
                        Text(formatMoney(provider.billing?.monthToDateCost))
                            .font(.caption2.monospacedDigit())
                            .foregroundStyle(.secondary)
                    }
                    if includeCharts {
                        Sparkline(points: provider.usageSeries?.points ?? [], tint: providerTint(for: provider.id))
                            .frame(height: 18)
                    }
                }
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
        case "ok": return "APIs connected"
        case "warn": return "Token status stale"
        default: return "Provider check failing"
        }
    }

    private func detail(_ snapshot: TokenSnapshot?) -> String {
        guard let snapshot else { return "Waiting for token status data." }
        return "\(snapshot.summary ?? "") · \(ageText(snapshot.updatedAt))"
    }
}

struct Sparkline: View {
    let points: [SeriesPoint]
    let tint: Color

    var body: some View {
        let values = Array(points.suffix(24)).map { max(0, $0.tokens ?? 0) }
        let maxValue = max(values.max() ?? 1, 1)
        HStack(alignment: .bottom, spacing: 2) {
            ForEach(Array(values.enumerated()), id: \.offset) { _, value in
                Capsule()
                    .fill(tint.opacity(value <= 0 ? 0.18 : 0.9))
                    .frame(maxWidth: .infinity)
                    .frame(height: value <= 0 ? 2 : max(3, CGFloat(value / maxValue) * 18))
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
        .description("OpenAI, Anthropic, Gemini API/token 상태를 바탕화면에서 확인합니다.")
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
            ProviderStatus(id: "openai", label: "OpenAI", status: "ok", billing: Billing(monthToDateCost: 23.93, usage: BillingUsage(totalTokens: 17_300_000)), usageSeries: UsageSeries(available: true, points: placeholderPoints), subscriptionSeries: nil, tokenWindow: nil),
            ProviderStatus(id: "anthropic", label: "Anthropic", status: "ok", billing: Billing(monthToDateCost: 14582, usage: BillingUsage(totalTokens: 21_200_000)), usageSeries: UsageSeries(available: true, points: placeholderPoints), subscriptionSeries: nil, tokenWindow: nil),
            ProviderStatus(id: "gemini", label: "Gemini", status: "ok", billing: nil, usageSeries: UsageSeries(available: true, points: placeholderPoints), subscriptionSeries: nil, tokenWindow: nil)
        ]
    )

    static let placeholderPoints: [SeriesPoint] = (0..<24).map { i in
        SeriesPoint(t: String(i), tokens: Double((i * 7) % 19))
    }
}

private func color(for status: String) -> Color {
    switch status {
    case "ok": return .green
    case "warn", "missing", "rate_limited", "unknown": return .orange
    default: return .red
    }
}

private func providerTint(for providerID: String) -> Color {
    switch providerID {
    case "anthropic": return .orange
    case "gemini": return .teal
    default: return .blue
    }
}

private func formatCompact(_ value: Double?) -> String {
    guard let value, value.isFinite else { return "—" }
    if value >= 1_000_000_000 { return String(format: value >= 10_000_000_000 ? "%.0fB" : "%.1fB", value / 1_000_000_000) }
    if value >= 1_000_000 { return String(format: value >= 10_000_000 ? "%.0fM" : "%.1fM", value / 1_000_000) }
    if value >= 1_000 { return String(format: value >= 10_000 ? "%.0fK" : "%.1fK", value / 1_000) }
    return String(format: "%.0f", value)
}

private func formatMoney(_ value: Double?) -> String {
    guard let value, value.isFinite else { return "—" }
    if value >= 100 { return "$\(Int(value.rounded()))" }
    return String(format: "$%.2f", value)
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
