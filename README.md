# delegation-scout

A Hermes delegation backend plugin (`delegation.backend: scout`) that routes every
`delegate_task` child run to the right model by task shape — and learns from recorded
past outcomes in its own durable SQLite DB.

Full docs land with implementation; see
`docs/superpowers/specs/2026-11-05-delegation-scout-design.md`.
