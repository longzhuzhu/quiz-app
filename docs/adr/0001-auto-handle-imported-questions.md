# Auto-handle imported questions by default

Imported questions should no longer default to manual review for routine quality doubts. The import flow automatically imports every **可入库题目**, automatically skips every **不可用题目**, and exposes a read-only **自动处理记录** next to the manual review entry so users can trace what the program decided without being forced through accept-or-skip work.

Manual review remains as a fallback for exceptional cases, not the primary path for low confidence or missing-field results. This trade-off favors lower import friction because users had little meaningful choice in the previous review queue: structurally complete questions were usually accepted, while unusable questions should not require human confirmation.
