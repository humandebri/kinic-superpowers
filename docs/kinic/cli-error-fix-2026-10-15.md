# CLI mutation error decoding repair

The live stale-write test returned a server `EtagConflict`, but the CLI printed
a lengthy Candid deserialization error instead of the server's explanation.
The cause was `NodeMutationErrorCode` using snake_case Serde names while Candid
returns PascalCase variant names. Other types already had receive-only aliases.

The repair in the sibling kinic-wiki checkout adds PascalCase aliases for all
five mutation error codes, retaining JSON's snake_case serialization. It also
adds two Candid round-trip regression tests covering the five codes, error
structure and actual `Result<WriteNodeResult, NodeMutationError>` response.

Verification:

- Both regression tests failed before the aliases were added.
- `cargo test -p kinic-vfs-types`: passed.
- `rustfmt --edition 2024 --check crates/vfs_types/src/fs.rs`: passed.
- `cargo build -p kinic-vfs-cli --bin kinic-vfs-cli`: passed.
- Repeating the live stale progress write after rebuilding printed
  `Error: expected_etag does not match current etag: .../progress.md`, exited 1,
  and the bridge did not retry it.

Only `crates/vfs_types/src/fs.rs` changed in kinic-wiki. Existing mobile-demo
changes were preserved. The Rust checks write build artifacts, execute build
scripts and run test code; scope was limited using the Rust Verify skill.

No canister deployment was needed: the server's rejection behavior was correct.
