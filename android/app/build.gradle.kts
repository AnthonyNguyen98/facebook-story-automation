plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "vn.megas.storycompanion"
    compileSdk = 35

    defaultConfig {
        applicationId = "vn.megas.storycompanion"
        minSdk = 26
        targetSdk = 35
        versionCode = 2
        versionName = "0.2.0-pilot"
    }

    buildTypes {
        release {
            isMinifyEnabled = false
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }
}

dependencies {
    testImplementation("junit:junit:4.13.2")
}
