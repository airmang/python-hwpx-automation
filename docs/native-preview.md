# Optional native preview runtime

The `hwpx_automation.preview_runtime` package provides bounded local PNG
rendering and the watch/worker service used by the desktop file-viewer plugin.
It does not replace `render_preview`, the existing HTML viewer, or the independent
Hancom render oracle. The default and MCP installs gain no native dependencies.

Install the `native-preview` extra to opt into the tested Pillow, FontTools,
HarfBuzz and FreeType stack. This feature requires a core build containing
`hwpx.layout.object_scene`; until that core change is released, install the core
and automation development branches together from source.

```sh
python -m pip install -e ../python-hwpx
python -m pip install -e '.[native-preview]'
hwpx-native-preview --render input.hwpx --out output --font-directory ./licensed-fonts
```

The font directory must contain the unmodified normal/bold files for each
requested family. The current resource names are `HCRBatang.ttf`,
`HCRBatang-Bold.ttf`, `HCRDotum.ttf` and `HCRDotum-Bold.ttf`. Font files are not
included in the source or wheel. Obtain and use them under their original terms.
Available OS Malgun Gothic pairs may be used without copying them into a bundle.
Missing fonts are reported; substitutions require an explicit `--font-map` JSON.

Native modules remain importable without the extra. Dependency loading occurs
when the backend is constructed. The bytes API is
`hwpx_automation.preview_runtime.render_bytes(data, output_dir, ...)`.

The worker service owns its temporary files, immutable input snapshots, child
processes, memory/time/output limits and cancellation. In a Windows virtualenv,
the Python executable can be a redirector to another process: watch mode refuses
that default launch rather than incorrectly enforcing the memory limit on the
redirector. Desktop packages use a frozen native executable, which owns the
actual worker PID. Batch rendering and Mac source execution remain available.

The `hwpx-plugins` desktop preview component builds the platform executable and
bundles its MCP Apps UI separately. A local-only token protects loopback traffic;
the token is not passed through model-visible tool results. Public distribution
of platform bundles, bundled-font rights, signing and notarization are separate
release checks. `qualityValidated` remains false for arbitrary documents.
