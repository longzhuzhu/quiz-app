# Do not keep legacy routes after introducing exam-scoped URLs

The multi-exam platform uses exam-scoped routes such as `/exams/:examSlug/...` as the only supported route shape for exam-scoped pages. Legacy CIPT-era routes such as `/banks`, `/wrong`, and `/vocab` are not kept as compatibility redirects.

This trade-off favors a clean route model over preserving old bookmarks. Keeping both route shapes would make navigation guards, active exam synchronization, and page context harder to reason about. Since the platform is being repositioned from a CIPT-specific app to a multi-exam platform, the route model should make the exam context explicit everywhere.
