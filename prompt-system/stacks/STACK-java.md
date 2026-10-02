# Stack: Java

- Write idiomatic Java following the Google Java Style Guide.
- Java 21 LTS minimum; records and sealed classes for value types and restricted hierarchies.
- Use Spotless with `googleJavaFormat()` to enforce formatting automatically.
- Prefer constructor injection via Dagger/Hilt over field injection.
- Prefer immutable objects; mark fields `final` by default.
- Naming: PascalCase for classes/interfaces, camelCase for methods/fields, UPPER_SNAKE_CASE for constants.
- Imports: no wildcard imports; explicit imports only.
- Errors: typed exceptions; checked exceptions for recoverable conditions, unchecked for programming errors; never swallow.
- Streams: `stream()` for transformations, but a `for` loop is fine for side effects; no nested streams (S3).
- Tests: JUnit 5; `@DisplayName` for human-readable test names; one assertion focus per test.
- Build: Maven or Gradle; wrapper committed; lockfile equivalent (`maven.lock` or `gradle.lockfile`) for reproducible builds.
- Linting: Spotless or Checkstyle; pre-commit hook runs it on save.
