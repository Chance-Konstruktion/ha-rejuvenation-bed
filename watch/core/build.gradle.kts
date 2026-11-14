plugins {
    id("org.jetbrains.kotlin.jvm")
}

kotlin {
    jvmToolchain(17)
}

tasks.test {
    useJUnit()
}

dependencies {
    testImplementation("junit:junit:4.13.2")
}
