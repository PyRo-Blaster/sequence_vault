# End-to-end tests

Browser journeys live with the web app in `apps/web/e2e` and run with Playwright against the real backend (`make e2e`). They cover upload, evidence review, issue resolution, bulk approval, commit with per-item results, search, record detail and FASTA export (T02), concurrent edits (T12), pending content (T09) and viewer permissions. Published results after human review must equal gold exactly.

Remaining T01–T20 journeys for DOCX/XLSX/PDF formats belong to P6.
