# HGPT Image Replacement Workflow

HGPT image replacements are applied directly while the source HGAR archives
are rebuilt. No import step or intermediate database is required.

## Inputs

Place translated PNG files under `resources/trans_pic/trans`. A filename must
end in an underscore followed by a hexadecimal prefix of the original HGPT
SHA-256 hash:

```text
menu_title_a1b2c3d4.png
```

Prefixes must contain at least six hexadecimal characters. Longer prefixes are
preferred because they reduce ambiguity. Directory nesting is allowed.

## Build

After extracting the source ISO and downloading translations, run:

```sh
make export_resources
```

The pipeline scans HGPT entries inside HGAR archives, hashes each original
image, finds a matching PNG prefix, and rebuilds the HGPT entry in place. It
then writes and reparses the containing HGAR archive as a round-trip check.

The generated `build/resource-report.json` lists matched and unmatched images,
duplicate files, and prefix conflicts.

## Image Requirements

- Keep the original width and height.
- RGBA originals accept RGBA PNG replacements.
- Indexed originals are rebuilt with the original palette capacity (16 or 256
  colors). RGBA input is quantized when necessary.
- Do not reuse one prefix for different PNG contents. The build rejects
  ambiguous matches.

Relevant implementation points are `ImageCatalog` in
`app/pipeline/catalog.py` and `rebuild_hgpt` in
`app/pipeline/transforms.py`.

## Troubleshooting

`translated image size mismatch` means the PNG dimensions differ from the
original HGPT image. Resize the replacement to the exact source dimensions.

An image listed as unmatched in the resource report has no corresponding HGPT
hash in the current source tree. Verify the filename suffix and the source game
revision.

`ambiguous translated images` means multiple matching prefixes point to
different content. Rename or remove the conflicting replacement so one image is
selected unambiguously.
