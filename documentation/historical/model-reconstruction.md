# Historical model-reconstruction guidance

> **Historical status:** This material was copied from a repository Wiki snapshot dated 8 November 2023. It preserves earlier guidance for manually reconstructing models and awaits curator confirmation. It is not the current automated conversion contract. For current repository submissions, follow [Contributing and reporting problems](../contributing.md); ask a curator before relying on these modeling rules where interpretation is required.

**Provenance:** [Original Wiki page](https://github.com/OntoUML/ontouml-models/wiki/Frequently-Asked-Questions) · [immutable page revision `5d838b8dafb9ec4e48fd830460c79296b5ec4a96`](https://github.com/OntoUML/ontouml-models/wiki/Frequently-Asked-Questions/5d838b8dafb9ec4e48fd830460c79296b5ec4a96) · inspected in Wiki repository snapshot `8d172200661ba9abee6ca058ae26e558e0efa8a1` (8 November 2023)

This page preserves useful information for people recreating models for the OntoUML/UFO Catalog, especially models from the [List of UFO and OntoUML Ontology Models](https://docs.google.com/spreadsheets/d/1JXEA3k58yAkV_jbmEc7HP9QK7RgZC5Jk1y8MR7ylFyQ/edit?usp=sharing).

If the model to be migrated is in an editable format other than `vpp`, see the [historical guide to importing models into Visual Paradigm](importing-models-to-visual-paradigm.md).

This document is historical background for the current [contribution guidance](../contributing.md). The status notice above governs the instructions that follow.

- [How do I interpret the direction of relations when documenting an ontology?](#how-do-i-interpret-the-direction-of-relations-when-documenting-an-ontology)
- [How do I interpret the ontological natures of non-sortals classes (i.e., «category», «phaseMixin», «roleMixin», «historicalRoleMixin», and «mixin») when documenting an ontology?](#how-do-i-interpret-the-ontological-natures-of-non-sortals-classes-ie-category-phasemixin-rolemixin-historicalrolemixin-and-mixin-when-documenting-an-ontology)
- [How do I document stereotypes that are not part of the current OntoUML profile?](#how-do-i-document-stereotypes-that-are-not-part-of-the-current-ontouml-profile)
- [How should I lay out a diagram?](#how-should-i-lay-out-a-diagram)
- [How do I interpret the `{frozen}` constraint on attributes and relation ends?](#how-do-i-interpret-the-frozen-constraint-on-attributes-and-relation-ends)
- [How do I interpret the `{essential}` and `{inseparable}` constraints on compositions and aggregations?](#how-do-i-interpret-the-essential-and-inseparable-constraints-on-compositions-and-aggregations)
- [How do I interpret Generalization Sets?](#how-do-i-interpret-generalization-sets)
- [When documenting an ontology, how do I represent imported classes? (e.g., classes with names like `UFO::Endurant`)](#when-documenting-an-ontology-how-do-i-represent-imported-classes-eg-classes-with-names-like-ufoendurant)

## How do I interpret the direction of relations when documenting an ontology?

If the relation has a mandatory direction given by its stereotype and the related classes, this direction should be used. If the direction is still unclear (e.g., there is no mandatory direction, or the stereotype is custom or missing), the model must be interpreted and a direction chosen. Relation labels and reading directions can be highly informative in this case.

Remember, however, to preserve the original reading direction of the relations, as the reading direction and the direction of a relation are not necessarily the same.

## How do I interpret the ontological natures of non-sortals classes (i.e., «category», «phaseMixin», «roleMixin», «historicalRoleMixin», and «mixin») when documenting an ontology?

In 2018, changes were introduced to OntoUML allowing non-sortal classes to have moments as instances. Therefore, if the model being documented was last updated before that, the instances of non-sortal classes should be assumed to be substantials (i.e., functional complexes, collectives, or quantities), unless stated otherwise. You should also check the references in your source files, as they probably incorporated these changes to OntoUML if they cite [this paper](https://link.springer.com/chapter/10.1007/978-3-030-00847-5_12) or a more recent work.

## How do I document stereotypes that are not part of the current OntoUML profile?

Some stereotypes have been spelled in different ways throughout diverse publications, especially for concepts that were yet to be developed. For consistency, document every stereotype as presented in the original source files except for those listed in the table below.

If you believe another stereotype mapping should be included in this table, [open an issue](https://github.com/OntoUML/ontouml-models/issues) with your suggestion.

| Original stereotype | Translation into current profile |
| --- | --- |
| «powertype» | «type» |
| «highordertype» | «type» |
| «hou» | «type» |
| «universal» | «type» |
| «2ndOT» | «type» |
| «relatorKind» | «relator» |
| «modeKind» | «mode» |
| «quantityKind» | «quantity» |
| «collectiveKind» | «collective» |
| «qualityKind» | «quality» |

## How should I lay out a diagram?

Keep diagrams as similar to the original ones as possible. The way people build diagrams also carries information that can be processed. Avoid applying automatic layouts as much as possible.

## How do I interpret the `{frozen}` constraint on attributes and relation ends?

Some tools rename the `{readOnly}` constraint to `{frozen}`, in which case `{readOnly}` must be used. Other tools also introduce the `{addOnly}` constraint, but it does not have a translation into OntoUML in this guidance. Document `{addOnly}` in the same way as in the original model.

## How do I interpret the `{essential}` and `{inseparable}` constraints on compositions and aggregations?

For `{essential}`, set the part association end as `{readOnly}`.

For `{inseparable}`, set the whole association end as `{readOnly}`.

## How do I interpret Generalization Sets?

Do not infer that generalizations from the same class are part of a generalization set only from their diagrammatic representation. In a diagram, a generalization set can be identified when the generalizations that are part of it are clearly indicated with a name or with the generalization set's properties (e.g., `isDisjoint`, `isCovering`).

According to the [UML Specification](https://www.omg.org/spec/UML/2.5.1/About-UML/), when generalization relationship lines are named, that name designates a Generalization Set to which the Generalization belongs. If there are no labels on the Generalization arrows, it cannot be determined from the diagram whether there are any Generalization Sets in the model.

## When documenting an ontology, how do I represent imported classes? (e.g., classes with names like `UFO::Endurant`)

In UML, classes from packages different from the one being viewed are represented with their package's name before the class's name, followed by a double colon (`::`). For example, `UFO::Endurant` indicates that the class `Endurant` is defined in the package `UFO` and imported into the current package being shown.

When documenting an ontology with imported classes, **do not** write the package name and double colon in the class's name field. Represent the class by creating it in a different package. The historical procedure was:

1. In the Visual Paradigm **Model Explorer**, right-click the highest-level item (which has the name of the model) and select **Model Element > Package**.
2. A new package is created and a **Package Specification** dialog opens so that you can name the package. For example, for the class `UFO::Endurant`, set the name to `UFO` and select **OK**.
3. In **Model Explorer**, right-click the created package (e.g., `UFO`) and create a new class in it (e.g., `Endurant`). Select **Model Element > Class** and enter the class's name in the **Class Specification** dialog.
4. Still using **Model Explorer**, drag the created class from its package to the diagram where it will be represented. This imports the class into the diagram.
5. To represent imported classes visually, right-click an empty spot in the diagram and select **Presentation Options > Class Display Options > When Different From View**.

Changes from the source snapshot are limited to the historical/provenance notice, repaired repository navigation and spreadsheet URL, Markdown presentation, and minor grammar corrections; the substantive reconstruction guidance is preserved.
