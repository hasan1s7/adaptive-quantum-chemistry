# v0.3 transport compatibility

The repository transports the expanded experiment decision ledger in eight
lossless binary pieces. Seven pieces are 10 MiB (10,485,760 bytes) each; the last
is 1,800,145 bytes. This replaces four pieces that were too large for the delivery
transport. A full 10 MiB piece occupies 13,981,016 bytes after base64 encoding,
leaving room for ordinary request metadata below the reported 16 MiB request
body limit. This record describes local packaging verification; it does not
claim that an upload has completed.

## The scientific evidence is unchanged

The restored file remains `results/lab/decision_ledger.jsonl.gz`, exactly
75,200,465 bytes, with SHA256:

```text
845a2c1846f8a1b5887134775c80c3f77f9efe4df3ef3fd18fd34fde4e8ccb07
```

That digest is the ledger digest in the unchanged scientific evaluation seal.
The change does not recompress the gzip, rewrite its records, change the
experiment accounting, or rerun any experiment. All 156 protected files checked
across scientific source, scientific data, results, the retained v0.1 release,
and existing v0.2 verification records retained their original hashes.

The exact previous four-piece manifest is preserved at
`releases/v0.2.0/transport-original.json`, with SHA256
`f7870cbcc4325ef3b20c54236a0b291254ca51efe7d8b964d2c7efaca3a1666c`.
It is a historical record of the former chunk boundaries. Its part paths name
the old arrangement and must not be used to restore the new arrangement. The
four old part digests were also verified by slicing the fully restored ledger
at the original boundaries. Existing v0.2 verification records were preserved.

## Restore from the current manifest

Run from the repository directory:

```bash
python scripts/archive_evidence.py restore
```

The current manifest is `data/evidence_chunks/lab-ledger/manifest.json`, with
SHA256 `505601d4a2eade4c3e5783213268cfbd3cd66a6b32cd713e994fe95d0a3324cd`.
The helper verifies every piece and the reconstructed file before placing it at
the final path. A second restore verifies the existing file and does not rewrite
it. A mismatched existing file is rejected. Opening the saved-results app does
not require restoring this full audit ledger; a complete scientific evidence
audit does.

## Verification record

`verification/v03/transport-compatibility.json` records the original and current
manifest digests, every part's digest and size, protected file hashes, the
temporary restoration, and the test result. Before replacing the original
transport directory, the eight new pieces were restored in a temporary root;
the result was compared byte for byte with the original ledger, checked against
its sealed digest, and restored a second time to verify idempotence. The original
oversized pieces were removed only after these checks passed.

Run the transport tests with:

```bash
python -m unittest tests.test_evidence_transport -v
```

The tests cover bounded default chunk sizes, exact round-trip restoration,
idempotence, rejection of corrupt pieces and conflicting existing files, the
complete bundled eight-piece reconstruction, and recovery of the historical
four-piece checksums from the unchanged ledger.
