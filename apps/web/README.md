# Web application

Reserved for the TypeScript internal web UI in Chinese. Select the framework and create its package manifest, compiler configuration, and lockfile in Phase B.

`src/features` groups user journeys; `src/components` contains shared presentation; `src/lib` contains API clients and evidence-offset conversion. The browser calls the API; it receives no model credentials or direct database access.

The review page must show immutable source evidence alongside candidates, localized issues and character differences, explicit revision conflicts, and per-item commit results. Never show partial commitment as complete success. Convert Unicode code-point offsets explicitly before using JavaScript UTF-16 string indices.
