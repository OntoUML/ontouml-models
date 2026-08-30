# Using and downloading models

[Documentation index](README.md) · [Technical overview](technical-overview.md) · [Contributing](contributing.md)

The catalog contains conceptual models: descriptions of concepts and relationships, not a database of observations about individual people or objects. Start in [models/](../models/), choose a folder, and read its `metadata.yaml` for its title, subject, language, sources, and editorial notes. Folder names are identifiers, not a complete description of suitability for your research.

## Choose a format

| Your task | Choose | What to expect |
| --- | --- | --- |
| Understand a model visually | PNGs in `original-diagrams/` or `new-diagrams/` | Images you can view without a modeling editor. One diagram may cover only part of the model. Recreated diagrams are distinct from original representations. |
| Inspect or edit a native project | `ontology.vpp` | A Visual Paradigm project. Use a compatible editor and the appropriate OntoUML tooling; repository checks do not test whether every project opens in your installed version. |
| Process model elements in software | `ontology.json` | JSON model/project data. This is the source for the repository's generated ontology RDF. |
| Analyze a model as a graph | `ontology.ttl` | RDF in Turtle syntax, using the OntoUML Vocabulary. Load it into an RDF library or graph store; SPARQL queries require a query-capable tool. |
| Keep all tracked files for a fixed snapshot | GitHub's source ZIP or tarball for a tag/commit | Native projects, JSON, diagrams, bibliographies, metadata, and repository files present at that snapshot. This is not the single release Turtle asset. |

For RDF analysis across the collection, use the release's aggregated `.ttl` asset. It includes eligible ontology and metadata Turtle, not the native files or images. A `metadata-*.ttl` file describes a distribution; it is not a substitute for `ontology.ttl`.

JSON and Turtle are not guaranteed lossless equivalents. Review the [conversion limits](technical-overview.md#conversion-and-independent-versions), particularly omitted property assignments, unrepresented path-point order, and unresolved diagram links.

## Download a file or a snapshot

For an individual file, open it in GitHub and use **Download raw file** or the raw view's download option. Save the actual file bytes, not the HTML preview page. GitHub documents [viewing and downloading raw file content](https://docs.github.com/en/repositories/working-with-files/using-files/viewing-and-understanding-files#viewing-or-copying-the-raw-file-content).

For the complete repository snapshot, select the desired branch or tag and choose **Code → Download ZIP**, or use the **Source code (zip)** / **Source code (tar.gz)** links on the chosen release page. Extract outside any working checkout if you only want a research copy. See GitHub's [source archive guidance](https://docs.github.com/en/repositories/working-with-files/using-files/downloading-source-code-archives).

For aggregated RDF, open [GitHub Releases](https://github.com/OntoUML/ontouml-models/releases), choose a release, and download its named `ontouml-models-YYYYMMDD.ttl` asset. Do not confuse it with the source archive links in the same Assets section. GitHub explains [finding releases and tags](https://docs.github.com/en/repositories/releasing-projects-on-github/viewing-your-repositorys-releases-and-tags).

The default branch and [latest-release entry point](https://w3id.org/ontouml-models/release) move over time. For reproducibility, record the selected tag **and its commit SHA**, or use a commit-pinned file link. A generated metadata download URL can still point to a moving branch even when you are reading an older metadata snapshot; use the pinned repository file when exact snapshot bytes matter.

## Walkthrough: the Reference Ontology of Trust

> [!NOTE]
> This is a fixed historical example from [release `20260827`](https://github.com/OntoUML/ontouml-models/releases/tag/20260827), at commit `617dc16ee30a94d8c0587463f1b9ba3b3aef07d7`. It is not a claim that this remains the latest release or that later versions contain identical files.

| Open this pinned file | What to learn |
| --- | --- |
| [ROT metadata.yaml](https://github.com/OntoUML/ontouml-models/blob/617dc16ee30a94d8c0587463f1b9ba3b3aef07d7/models/amaral2019rot/metadata.yaml) | The Reference Ontology of Trust (ROT), its contributors, English language, sources, license statement, and editorial note. The note explains that the imported project is larger than the model described in its main source paper. |
| [Original trust diagram](https://github.com/OntoUML/ontouml-models/blob/617dc16ee30a94d8c0587463f1b9ba3b3aef07d7/models/amaral2019rot/original-diagrams/trust.png) | A visual entry point into the model; not proof of complete coverage or semantic correctness. |
| [Native Visual Paradigm project](https://github.com/OntoUML/ontouml-models/blob/617dc16ee30a94d8c0587463f1b9ba3b3aef07d7/models/amaral2019rot/ontology.vpp) | The stored native project for editor-based inspection. |
| [JSON export](https://github.com/OntoUML/ontouml-models/blob/617dc16ee30a94d8c0587463f1b9ba3b3aef07d7/models/amaral2019rot/ontology.json) | The model/project representation used as input to RDF generation. |
| [Ontology Turtle](https://github.com/OntoUML/ontouml-models/blob/617dc16ee30a94d8c0587463f1b9ba3b3aef07d7/models/amaral2019rot/ontology.ttl) | The generated RDF distribution for graph analysis. |
| [Bibliography](https://github.com/OntoUML/ontouml-models/blob/617dc16ee30a94d8c0587463f1b9ba3b3aef07d7/models/amaral2019rot/references.bib) | Source publications to consult and cite for the selected model. |

This walkthrough demonstrates file roles. It is not a semantic audit, a VPP/JSON equivalence test, or a certification of reuse rights. Check the [validation boundary](technical-overview.md#what-validation-establishes) and [identifier caveats](technical-overview.md#identifiers-and-urls) before drawing conclusions from automated checks.

## Reuse and licensing

Read the [existing license statements and caution](../README.md#license-disclaimer), the repository's [LICENSE](../LICENSE), and the chosen model's metadata and original sources. Coverage can be incomplete or inconsistent, including differences between YAML and retained RDF statements. This guide does not decide which statement controls or grant additional permissions. Ask the [catalog administrators](../README.md#catalog-administration) for clarification where necessary.

## Cite the catalog and the models you use

Use the preferred **2023 catalog paper** in [How to Cite this Catalog](../README.md#how-to-cite-this-catalog); [CITATION.cff](../CITATION.cff) supplies machine-readable citation metadata. The paper describes the catalog as of **June 2022**, not every later snapshot.

Also cite the relevant model publications or original sources identified in the selected folder's `metadata.yaml` and, when present, `references.bib`. The catalog citation does not replace credit to the model's authors. Do not invent a model DOI from its folder name or the catalog DOI.

For reproducibility, record:

- the repository URL, release tag if used, and exact commit SHA;
- the model folder(s), distribution filenames, and any subset you selected;
- relevant model/source citations;
- processing tools, versions, and transformations used in your analysis.

For example, the walkthrough selects `models/amaral2019rot/ontology.ttl` from release `20260827` at commit `617dc16ee30a94d8c0587463f1b9ba3b3aef07d7`. That snapshot record complements, rather than changes, the preferred catalog-paper citation.
