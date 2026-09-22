pluginManagement {
    repositories { google(); mavenCentral(); gradlePluginPortal() }
}
dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        google()
        mavenCentral()
        exclusiveContent {
            forRepository {
                maven {
                    name = "BundledInsta360"
                    url = uri("vendor-maven")
                    metadataSources { gradleMetadata(); mavenPom(); artifact() }
                }
            }
            filter {
                includeGroup("com.arashivision")
                includeGroup("com.arashivision.inskmp")
                includeGroup("com.arashivision.minicamera")
                includeGroup("com.arashivision.sdk")
                includeGroup("com.insta360.infrastructure")
            }
        }
    }
}
rootProject.name = "AcePro2Wireless"
include(":app")
