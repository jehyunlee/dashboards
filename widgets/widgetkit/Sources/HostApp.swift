import SwiftUI

@main
struct JehyunDashboardWidgetsApp: App {
    var body: some Scene {
        WindowGroup {
            VStack(alignment: .leading, spacing: 14) {
                Text("Jehyun Dashboard Widgets")
                    .font(.title2.bold())
                Text("Token Status 위젯이 설치되어 있습니다.")
                    .font(.headline)
                Text("바탕화면을 우클릭하고 ‘위젯 편집…’을 선택한 뒤 Jehyun Dashboards 또는 Token Status를 찾아 추가하세요.")
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
                Link("Open full dashboard", destination: URL(string: "https://tech.jehyunlee.dev/dashboards/tokens/")!)
                    .padding(.top, 4)
            }
            .padding(24)
            .frame(width: 460, height: 240)
        }
    }
}
