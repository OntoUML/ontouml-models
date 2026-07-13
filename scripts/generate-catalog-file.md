# Generate `catalog.ttl`

`catalog.ttl` is a generated repository artifact. Do not edit it directly.

The generator combines three inputs:

- `catalog.yaml` supplies the non-derived catalog-level metadata, such as the catalog IRI, title, description, license, contact point, creators, and metadata issuance timestamp;
- each direct model folder's `models/<model>/metadata.ttl` supplies its exact RDF subject IRI when that subject is typed as `dcat:Dataset` and linked to the configured catalog through `dct:isPartOf`, plus every `dct:contributor` IRI occurring in that file;
- the existing `catalog.ttl`, when present, supplies the previous semantic state and the current values of `dct:modified` and `fdpo:metadataModified`.

The generator preserves dataset IRIs exactly as they occur in model-level metadata. It does not infer an IRI from a directory name and does not add or remove a trailing slash.

The catalog's `dct:contributor` values are derived from the union of all `dct:contributor` values in the model-level metadata files. Exact duplicates are emitted only once. As a conservative additional duplicate check, contributor IRIs that differ only by `http`/`https` or trailing slashes are treated as equivalent. When equivalent forms occur, the generator retains an existing source IRI deterministically, preferring HTTPS and then a form without a trailing slash; it does not synthesize an IRI that was absent from the model metadata.

## Modification timestamps

`dct:modified` and `fdpo:metadataModified` are intentionally absent from `catalog.yaml`. They are managed by comparing the generated semantic catalog with the existing `catalog.ttl`.

The properties have distinct operational meanings:

- `dct:modified` records the latest semantic change to the catalog's model membership, represented by the catalog's `dcat:dataset` statements;
- `fdpo:metadataModified` records the latest semantic change to the catalog-level metadata, including derived contributors and changes to `dct:modified`.

The update rules are:

| Detected change | `dct:modified` | `fdpo:metadataModified` |
| --- | --- | --- |
| No semantic change | Preserve | Preserve |
| Catalog metadata only | Preserve | Update |
| Catalog membership | Update | Update |
| No existing `catalog.ttl` | Initialize | Initialize |

When both values are initialized or updated together, the generator uses the same timestamp for both. New values are serialized as UTC `xsd:dateTime` literals. For migration safety, an existing valid `dct:modified` value using `xsd:date` is preserved until catalog membership actually changes; the generator does not invent a historical time that was never recorded.

Semantic comparison is RDF-based rather than text-based. Triple order, indentation, line wrapping, prefix order, and blank-node identifiers do not by themselves update either timestamp. The output is still rendered in the generator's canonical deterministic serialization, so a serialization-only difference can be rewritten without changing the timestamps.

## Local use

Install the existing script dependencies:

```bash
python -m pip install -r scripts/requirements.txt
```

Synchronize the generated file:

```bash
python scripts/generate_catalog_file.py .
```

The current UTC time is consulted only when an actual semantic change requires a timestamp to be initialized or updated.

For deterministic tests or controlled regeneration, provide an explicit timestamp:

```bash
python scripts/generate_catalog_file.py . \
  --generation-timestamp 2026-07-13T19:42:31Z
```

Check synchronization without writing:

```bash
python scripts/generate_catalog_file.py . --check
```

Check mode never consults the current clock and never writes files. It exits with status `0` when no semantic catalog change exists, even if the current Turtle uses a different but equivalent serialization. It exits with status `1` when the output is missing or catalog membership or metadata is semantically stale. The error identifies whether catalog membership or catalog metadata changed.

Repeated write execution against unchanged inputs is idempotent and produces no diff. If only formatting differs, a write can restore the canonical serialization while preserving both modification timestamps.

## Change behavior

- Adding a valid `models/<model>/metadata.ttl` adds its exact dataset IRI and updates both modification timestamps.
- Removing a model-level `metadata.ttl` removes its dataset IRI and updates both modification timestamps.
- Renaming a model directory does not change `catalog.ttl` when the dataset IRI remains stable.
- Changing a model dataset IRI changes catalog membership and updates both modification timestamps.
- Adding, removing, or changing a model-level `dct:contributor` updates the derived catalog contributor list and `fdpo:metadataModified`, but preserves `dct:modified` when membership is unchanged.
- A model-level contributor edit that leaves the final deduplicated catalog contributor set unchanged does not update either timestamp.
- Changing other non-identity model metadata does not change `catalog.ttl`.
- Changing catalog-level metadata in `catalog.yaml` updates the corresponding RDF metadata and `fdpo:metadataModified`, but preserves `dct:modified` when membership is unchanged.

Generation fails explicitly when:

- `catalog.yaml` is missing, malformed, incomplete, contains duplicate keys, or contains unsupported fields;
- `models/` is missing or contains no direct model-level `metadata.ttl` files;
- model metadata is not valid Turtle;
- a model metadata file does not contain exactly one IRI subject typed as `dcat:Dataset`;
- a dataset does not declare `dct:isPartOf` for the configured catalog;
- the same dataset IRI occurs in more than one model folder;
- a model-level `dct:contributor` value is not an absolute HTTP(S) IRI;
- an existing `catalog.ttl` is not valid UTF-8 or parseable Turtle;
- an existing catalog contains the configured catalog subject but does not contain exactly one valid `dct:modified` and one valid `fdpo:metadataModified` value for it;
- the generated Turtle cannot be parsed or does not contain the discovered dataset membership, contributor set, and selected timestamps.

## Automated lifecycle

The model-submission workflow generates model-level metadata first, synchronizes `catalog.ttl`, and commits both the model folder and the generated catalog file to the same pull-request branch.

The release workflow:

1. checks catalog synchronization during pull-request validation;
2. synchronizes the catalog before evaluating release-relevant changes on scheduled or manual runs;
3. commits and pushes a necessary synchronization only for an actual release publication;
4. generates the release artifact after synchronization; and
5. creates the release against the final synchronized commit.

This ordering ensures that a model addition and its catalog membership update are included in one release. The release workflow has no `push` trigger, and synchronization commits use the workflow's `GITHUB_TOKEN`, avoiding recursive release runs. If branch rules or a concurrent update prevent the synchronization push, the workflow fails before publishing rather than releasing an unsynchronized catalog.

## Source format

`catalog.yaml` has a deliberately fixed schema. All non-derived fields are required so catalog-level metadata cannot be silently dropped from the generated RDF. Contributors are intentionally absent because they are derived from model-level metadata. `modified` and `metadata_modified` are intentionally absent because they are derived from semantic change detection against the existing catalog. Dates use `YYYY-MM-DD`; metadata date-times must include `Z` or an explicit UTC offset; URI fields use absolute HTTP(S) IRIs except for the contact email, which uses a `mailto:` IRI.
