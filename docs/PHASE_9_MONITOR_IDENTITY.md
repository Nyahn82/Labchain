# Phase 9 monitor identity preparation

This step creates only a second retained Org1 client identity. It does not
install into `/etc`, create the monitor OS user, change the application client,
bootstrap permissions, touch the database, start/restart services, or send Fabric
transactions. The existing User1 provisioner and reviewed crypto configuration
are unchanged.

## Source and cryptogen strategy

The fixed User2 source is:

```text
/opt/rhu-labchain/blockchain/network/generated/single-vps/crypto-config/peerOrganizations/org1.labchain.internal/users/User2@org1.labchain.internal
```

Its signing certificate is `msp/signcerts/User2@org1.labchain.internal-cert.pem`;
the signing key is `msp/keystore/priv_sk`. All generated directories are 0700,
files 0600, owned by the provisioning operator. No key is printed or added to
Git. The full source and private receipt path are checked with both
`git check-ignore` and `git ls-files` before publication.

The static reviewed config intentionally retains `Users: {Count: 0}`. The helper
copies the entire retained hierarchy into a private temporary directory and
changes **only the temporary config's Org1 user count to 2**. Org2 remains 0.
It runs pinned `cryptogen extend`, never `generate`. The pinned implementation
skips existing User1 and adds User2, using the copied retained Org1 CA. Real
cryptogen tests verify this behavior rather than assuming Count 1 adds a user.

Before invoking cryptogen, the helper checks the retained 2.5.16 archive against
the reviewed SHA-256 `18c91e7f2f11b601e6622cc70454d568af897707ee9adf111e9fa91a233881bf`,
compares the executable bytes to its `bin/cryptogen` member, and checks the
reported version. It never downloads or replaces tooling.

Every pre-existing file's bytes and permissions, and every existing directory's
permissions, must match after extension. The sole allowed addition is the exact
User2 file/directory allowlist. Cryptogen creates an **empty** `msp/admincerts`
directory for a NodeOU client; no admin certificate is permitted there.
Unexpected new files, empty directories, other users or modified old material
cause refusal before publication. Only the new User2 directory is published.

## Identity and concurrency validation

Validation reuses existing application-client/runtime checks and adds:

- Expected User2 CN and OU=client; admin/peer/orderer OUs rejected; CA:FALSE.
- Org1 certificate-chain verification and matching certificate/private key.
- A signing public key and certificate distinct from User1.
- Exact CA/MSP configuration and client TLS certificate/key validation.
- No symlinks, hard-linked files, special files, ambiguous files or extra keys.
- Full retained crypto, single-VPS runtime and application-client runtime
  snapshots; original User1 source/runtime matching is checked without calling
  its provisioner.
- The same exclusive nonblocking lock used by the existing application
  provisioner's CLI: `runtime/.app-client-single-vps.lock`. All mutating identity
  operations should honor this lock.
- Before publication, byte/mode snapshots plus inode/mtime/ctime stamps detect
  concurrent replacement or modification. Publication uses Linux
  `renameat2(RENAME_NOREPLACE)` so even a raced empty destination cannot be
  overwritten. The full baseline and runtime validator run again afterward.

A private 0600 receipt is stored at:

```text
blockchain/network/generated/single-vps/monitor-client-receipt.json
```

It contains snapshots/digests, not private-key bytes, and is ignored by Git.
A durable PENDING receipt precedes publication; VERIFIED is written atomically
only after final validation. Repeat provisioning verifies the receipt and all
material, and makes no new identity. An existing User2 without a matching
VERIFIED receipt, or any interrupted attempt, fails closed. Do not delete a
receipt or replace identities to force a retry; reconcile the preserved state.

Source provisioning, as `rhuadmin:rhuadmin`:

```bash
cd /opt/rhu-labchain
bash blockchain/network/scripts/provision-monitor-client-single-vps.sh
```

Subsequent verification without extension:

```bash
bash blockchain/network/scripts/provision-monitor-client-single-vps.sh --check
```

`--check` acquires the provisioning lock but does not create a source identity,
copy credentials, rewrite a receipt, or run cryptogen extend.

## Public TLS CA sources

These exact existing sources are validated against the retained hierarchy and
runtime manifest. Peer1/peer2 share the Org1 TLS CA; peer3/peer4 share Org2's.

| Installed public filename | Source under `/opt/rhu-labchain/blockchain/network/` |
| --- | --- |
| `tls/peer1-ca.crt` | `runtime/single-vps/node1/peer/tls/ca.crt` |
| `tls/peer2-ca.crt` | `runtime/single-vps/node2/peer/tls/ca.crt` |
| `tls/peer3-ca.crt` | `runtime/single-vps/node3/peer/tls/ca.crt` |
| `tls/peer4-ca.crt` | `runtime/single-vps/node4/peer/tls/ca.crt` |
| `tls/orderer-ca.crt` | `runtime/single-vps/public/orderer-tls-ca.crt` |

No peer/orderer TLS private key, server key, CA signing key, or User1 key is
copied by the installer. The generated User2 TLS client identity stays in the
retained source and is not installed; the monitor needs only public TLS roots
and its one enrollment signing key.

## Separate future installation — not run in this task

`deploy/install_monitor_identity.py` is a reviewed, fixed-target helper.
The `rhu-labchain-monitor` user/group must already have been created in a later
authorized deployment. Its UID must differ from root and the FastAPI operator
(`rhuadmin`). The parent `/etc/rhu-labchain` must exist, and the final target must
not exist. The helper creates no OS account and starts no service.

First check prerequisites (no credential copying):

```bash
cd /opt/rhu-labchain
sudo .venv/bin/python deploy/install_monitor_identity.py
```

Only during that separately authorized deployment, install:

```bash
sudo .venv/bin/python deploy/install_monitor_identity.py --execute
```

The helper holds the shared provisioning lock, validates the receipt/source,
copies an explicit ten-file allowlist into a private staging directory beside
the target, verifies bytes and key/certificate matching, rechecks source
snapshots, sets ownership to `rhu-labchain-monitor:rhu-labchain-monitor`, then
publishes atomically without replacement. All directories are 0700 and files
0600, including public certificates (only the monitor needs to read them).
The final layout is:

```text
/etc/rhu-labchain/monitor-identity/
  msp/config.yaml
  msp/signcerts/client.crt
  msp/keystore/client.key
  msp/cacerts/ca.org1.labchain.internal-cert.pem
  msp/tlscacerts/tlsca.org1.labchain.internal-cert.pem
  tls/peer1-ca.crt
  tls/peer2-ca.crt
  tls/peer3-ca.crt
  tls/peer4-ca.crt
  tls/orderer-ca.crt
```

FastAPI may later receive Unix socket group access, but it must never receive
the monitor UID or private-directory access. Owner-only 0700/0600 modes keep
credentials inaccessible through the socket group. A repeated install refuses
to overwrite the target; renewal/recovery needs a separate reviewed procedure.

## Tests and limits

Completed on 2026-10-05 (Asia/Singapore): source-only provisioning and a separate
`--check` both succeeded. The private receipt is VERIFIED. Independent before/
after checks confirmed all **93 pre-existing crypto files** unchanged; exactly
**eight User2 files** were added. User1 source, application-client runtime and
single-VPS runtime snapshot digests remained identical:

| Tree | SHA-256 of canonical byte/mode snapshot, before = after |
| --- | --- |
| User1 source | `bed967ce1e747a8af3f701517bce318b24f2ab398c8b07ae2763182823cbf9b9` |
| Application-client runtime | `b0dbcc1ac6ba60bf5a04ff3c8e97f95399d851cb644715fb60e069ccdc3f7e04` |
| Fabric runtime | `89b9c9bee9904476783e129d692639fca45dc9c47d4fd02b440676d123311322` |

User2 certificate-file SHA-256:
`0f7d2fc59abed470bc97eed68da95f8fe48819d327acf08fb49e97b5ab62fef9`.
Org1 CA chain, client OU, distinct User1/User2 public keys, certificate/key match,
0600 key mode, and ignored/untracked status all passed. This fingerprint hashes
the certificate's PEM file bytes, not OpenSSL's DER certificate fingerprint.

Focused tests: **36 passed in 117.89s**, including the existing application
provisioner tests unchanged. Python compilation, shell syntax, tracked diff
whitespace and separate new-file whitespace checks passed. No production OS
user, installation, service configuration, permission grant or ledger action
was performed. The installer was exercised only against a synthetic temporary
staging directory and synthetic credentials.

Focused tests use the actual pinned cryptogen on entirely separate synthetic
networks. They verify User1 preservation, exact User2 generation, distinctness,
OU/CA/key matching, permissions, idempotency, unknown User2 refusal, unexpected
files/directories, concurrent changes, lock conflicts, no-clobber publication,
symlink refusal, safe errors, existing runtime validation, and installer staging.
The staged install is also checked by the existing Node offline credential
validator; it does not connect to Fabric.

```bash
.venv/bin/python -m pytest blockchain/network/tests/test_monitor_client.py blockchain/network/tests/test_app_client.py -vv -ra --tb=long
.venv/bin/python -m py_compile blockchain/network/scripts/provision_monitor_client.py deploy/install_monitor_identity.py blockchain/network/tests/test_monitor_client.py
git diff --check
```

This remains retained-CA academic-prototype provisioning, not production CA
enrollment or revocation management. It requires Linux with renameat2 and the
retained pinned archive. CA private keys are used only in the private temporary
copy, whose parent is ignored and protected. No blockchain transaction or
network regeneration is required to issue this client. Receipt-based idempotency
deliberately stops after later credential/config changes and requires explicit
review. Cooperative operations are serialized; an uncooperative writer can
still cause a final-check failure after publication, leaving a PENDING receipt
for manual reconciliation. Neither a source identity nor an offline credential
check establishes live Fabric ACL/TLS compatibility or grants application RBAC.
