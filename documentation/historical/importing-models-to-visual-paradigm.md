# Historical guide to importing models into Visual Paradigm

> [!WARNING]
> **Historical status:** This version-specific procedure was copied from a repository Wiki snapshot dated 8 November 2023. It describes Visual Paradigm 16.3 and editor behavior asserted by that snapshot; it has not been verified against current products, editions, licenses, or interfaces. It is not the current automated conversion contract. For current repository submissions, follow [Contributing and reporting problems](../contributing.md).

**Provenance:** [Original Wiki page](https://github.com/OntoUML/ontouml-models/wiki/Importing-Models-from-Other-Editors-and-Formats-to-Visual-Paradigm) · [immutable page revision `72e6ca6db619a3e9aa3f4c982ff81dd5b4cfe85e`](https://github.com/OntoUML/ontouml-models/wiki/Importing-Models-from-Other-Editors-and-Formats-to-Visual-Paradigm/72e6ca6db619a3e9aa3f4c982ff81dd5b4cfe85e) · inspected in Wiki repository snapshot `8d172200661ba9abee6ca058ae26e558e0efa8a1` (8 November 2023)

This page preserves information from the snapshot about migrating models from other modeling editors to Visual Paradigm:

- [Visual Paradigm built-in importing options](#visual-paradigm-built-in-importing-options)
- [Importing from other editors to Visual Paradigm](#importing-from-other-editors-to-visual-paradigm)
  - [From Astah to Visual Paradigm](#from-astah-to-visual-paradigm)
- [Documentation about importing to Visual Paradigm](#documentation-about-importing-to-visual-paradigm)

## Visual Paradigm built-in importing options

The source snapshot stated that Visual Paradigm version 16.3 provided built-in imports from the following tools and formats:

- Bizagi
- Default Diagram Element Format
- Enterprise Architect
- Erwin Project (XML)
- Excel
- MXMI
- NetBeans UML Project
- PowerDesigner DataArchitect
- Rational DNX
- Rational Model
- Rational Rhapsody Project
- Rational System Architect
- Rose Project
- Text Based Sequence Diagram
- Visio
- Visual Paradigm Project
- Visual UML
- XML

It stated that only the following options were available in the Visual Paradigm Community version:

- Default Diagram Element Format
- Erwin Project (XML)
- XML

The snapshot said that the other imports could be performed through the Visual Paradigm Modeler version using an evaluation period. This is retained as a historical statement, not a claim about current edition or license availability.

It located the import options under **Project > Import**.

## Importing from other editors to Visual Paradigm

### From Astah to Visual Paradigm

The source described this procedure:

1. Start your [Astah](https://astah.net/) installation.
2. Open your project.
3. Go to **Tools > XML Input & Output > Save as XML project**.

<img src="https://github.com/Matt-81/.github-images/blob/main/astah2vpp0.png"
  alt="Astah project to Visual Paradigm project, step 1."
  width="700">

This generates an XML Metadata Interchange (XMI) file.

4. Start your [Visual Paradigm](https://www.visual-paradigm.com/) installation.
5. Go to **Project > Import > XMI**.

<img src="https://github.com/Matt-81/.github-images/blob/main/astah2vpp1.png"
  alt="Astah project to Visual Paradigm project, step 2."
  width="400">

The snapshot noted that this step required at least the Visual Paradigm Modeler edition and suggested using its evaluation license. This is not a current product or license claim.

6. Go to **Project > Save > Save as**.

<img src="https://github.com/Matt-81/.github-images/blob/main/astah2vpp2.png"
  alt="Astah project to Visual Paradigm project, step 3."
  width="200">

The snapshot stated that the resulting `.vpp` file could then be opened with Visual Paradigm Community Edition.

## Documentation about importing to Visual Paradigm

The source linked to [Visual Paradigm documentation about data importing](https://circle.visual-paradigm.com/docs/export-and-import/importing/) and stated that it covered these formats and tools:

- BPMN 2.0
- Bizagi
- ERwin Data Modeler
- Microsoft Excel
- NetBeans 6.x UML diagrams
- Rational Rhapsody
- Rational Rose
- Rational Software Architect DNX
- Rational Software Architect EMX
- Rational System Architect
- Visio drawing
- Visual Paradigm project
- XMI
- XML

For the complete historical description, refer to the linked Visual Paradigm documentation. Its present content and product applicability have not been verified for this repository documentation.

Changes from the source snapshot are limited to the historical/provenance notice, navigation and Markdown presentation, explicit attribution of version-dependent claims to the snapshot, and minor grammar corrections; the substantive import lists, Astah procedure, screenshots, and source links are preserved.
