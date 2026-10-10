plugins {
    kotlin("jvm") version "2.4.20"
    kotlin("plugin.serialization") version "2.4.20"
    application
}

group = "app.musicbazi"
version = "1.0.0"

repositories {
    mavenCentral()
    maven("https://jitpack.io")
}

val ktorVersion = "3.5.2"

dependencies {
    // InnerTubeX pinned at v0.7.4 (commit a6ca8cb76e9c347d4f21824ca9f19b9db2e5aebd)
    implementation("com.github.MetrolistGroup.innertubex:innertubex-desktop:v0.7.4")

    // Ktor Server (CIO engine: lightweight asynchronous coroutine I/O)
    implementation("io.ktor:ktor-server-core:$ktorVersion")
    implementation("io.ktor:ktor-server-cio:$ktorVersion")
    implementation("io.ktor:ktor-server-content-negotiation:$ktorVersion")
    implementation("io.ktor:ktor-serialization-kotlinx-json:$ktorVersion")

    // Ktor Client (OkHttp engine for InnerTube HTTP requests)
    implementation("io.ktor:ktor-client-okhttp:$ktorVersion")
    implementation("io.ktor:ktor-client-content-negotiation:$ktorVersion")

    // Kotlinx Coroutines & Serialization
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-core:1.9.0")
    implementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.7.3")

    // Lightweight logging
    implementation("ch.qos.logback:logback-classic:1.5.12")

    // Testing
    testImplementation(kotlin("test"))
    testImplementation("io.ktor:ktor-server-test-host:$ktorVersion")
}

application {
    mainClass.set("app.musicbazi.bridge.MainKt")
}

tasks.register<JavaExec>("probe") {
    classpath = sourceSets["main"].runtimeClasspath
    mainClass.set("app.musicbazi.bridge.ProbeHarness")
    val vId = (project.findProperty("videoId") as? String) ?: "dQw4w9WgXcQ"
    val extraArgs = mutableListOf(vId)
    if (project.hasProperty("sabr")) {
        extraArgs.add("--sabr")
    }
    args = extraArgs
}

java {
    sourceCompatibility = JavaVersion.VERSION_17
    targetCompatibility = JavaVersion.VERSION_17
}

tasks.withType<JavaCompile> {
    options.release.set(17)
}

tasks.withType<org.jetbrains.kotlin.gradle.tasks.KotlinCompile> {
    compilerOptions {
        jvmTarget.set(org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17)
        freeCompilerArgs.add("-opt-in=kotlin.time.ExperimentalTime")
    }
}
