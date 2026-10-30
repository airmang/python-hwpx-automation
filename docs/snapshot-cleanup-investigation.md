# Verification snapshot cleanup investigation

Follow-up to [issue #78](https://github.com/airmang/python-hwpx-automation/issues/78), observed 2026-10-30.

The historical commit-specific Linux failure has not been reproduced. No
production cleanup change is claimed here.

Current evidence:

- Current main `c1493a7ea0d526d610eae9b5e1d5da08a9a8620b` passed the full Ubuntu
  Python 3.12 suite on 2026-10-27:
  [Actions job](https://github.com/airmang/python-hwpx-automation/actions/runs/40459219718/job/122039597948).
  The suite includes the existing mutated-render-snapshot regression.
- `WorkspacePathError` inherits `PermissionError`, and therefore `OSError`.
  The verifier's recovery tuple `(OSError, RuntimeError)` catches that error;
  the proposed exception-class gap is absent in current code.
- On macOS with descriptor CAS available, the original mixed-form regression
  and two focused chmod/rewrite/recapture/removal cases pass (3 tests). Both a
  same-byte rewrite and a changed payload reject the stale guard, preserve the
  inode, and remove the exact recaptured snapshot without sentinel leftovers.
- This checks macOS `renameatx_np`, not Linux `renameat2`. A local Linux runtime
  was unavailable, so the new narrow cases still need Linux execution through
  the normal CI matrix. The historical failure's cause remains unresolved.

Focused reproduction command:

```bash
python -m pytest -q tests/test_verification_snapshot_cleanup.py \
  tests/test_mixed_form_mcp.py \
  -k 'mode_changed_snapshot or cleans_mutated_render_snapshot'
```

If Linux fails, preserve the exact head, Python version and run URL, inspect
the first stale-guard rejection and the second recaptured-guard removal
separately, and retain inode/device/mode evidence. Never remove a replacement
inode merely to make cleanup pass.
