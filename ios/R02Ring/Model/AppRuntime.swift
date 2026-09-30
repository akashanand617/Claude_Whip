import Foundation
import SwiftData

/// Process-wide owner of the health store and the app model. Scenes, App
/// Intents and Bluetooth state restoration all reach this one instance, so a
/// cold background launch starts the ring manager without any view appearing.
@MainActor
final class AppRuntime {
    static let shared = AppRuntime()

    let container: ModelContainer
    let model: AppModel

    private init() {
        do {
            container = try ModelContainer(for: HeartRateRecord.self, StepRecord.self,
                                           SleepSessionRecord.self, SleepStageRecord.self, HealthCoverageRecord.self)
        } catch {
            fatalError("Could not create the local health store: \(error)")
        }
        model = AppModel()
        // Installed before launch finishes so foreground pings present; the
        // center holds its delegate weakly and the model retains the poster.
        model.notificationPoster.installAsDelegate()
        model.start(modelContext: container.mainContext)
    }
}
