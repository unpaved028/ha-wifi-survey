import org.jetbrains.kotlin.gradle.dsl.JvmTarget

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

// Vorbelegte Server-Adresse, z. B. ./gradlew assembleDebug -PdefaultServer=http://192.168.178.60:8770
val defaultServer = (project.findProperty("defaultServer") as String?) ?: ""

android {
    namespace = "io.github.unpaved028.wifisurvey"
    compileSdk = 35

    defaultConfig {
        applicationId = "io.github.unpaved028.wifisurvey"
        minSdk = 26
        targetSdk = 34
        versionCode = 2
        versionName = "0.2.0"
        buildConfigField("String", "DEFAULT_SERVER", "\"$defaultServer\"")
    }
    buildFeatures {
        buildConfig = true
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}

kotlin {
    compilerOptions {
        jvmTarget.set(JvmTarget.JVM_17)
    }
}
