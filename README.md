# OntoUML Models Repository

## Contents

- [Instructions](#intructions)
- [Documentation Example](#documentation-example)

## NOTICE

The OntoUML model repository is currently being migrated to GitHub with the adoption of the [`ontouml-schema`](https://github.com/OntoUML/ontouml-schema) JSON serialization for easy model processing.

If you wish to collaborate with this initiative submitting your ontologies, feel free to fork the project and open a pull request with your contribution. For questions, you can also create an issue or contact [@claudenirmf](https://github.com/claudenirmf/).

## Instructions

This repository collects a repository of UFO-based models. Each folder represents a single publication and must contain the following files:

- A YAML file containing the metadata on the publication (detailed below)
- The BibTex file containing the citation data for each source publication
- Screenshots of all original diagrams made available in the publications (these must be minified using [tinypng](https://tinypng.com/))
- The JSON serialization of the ontology
- The original project file of the ontology in Visual Paradigm (developed with the [`ontouml-vp-plugin`](https://github.com/OntoUML/ontouml-vp-plugin))
- The diagrams from the Visual Paradigm project

The ontology's folder name should use either the 'name of the ontology + year', or the Google Scholar citation key of the main source publication. The metadata file must follow the structure below:

```yaml
title: "A title of the ontology if available."
created-at: "The year of the first publication of the ontology."
last-update: "The year of the most recent publication of the ontology, if different."
domain: "The list of domains covered in the ontology"
editorial-notes: "A block of text with notes of the ontology documentation process"
types: "The types that apply to the ontology, either claimed by the authors or assessed by the documenting researcher. Examples 'core', 'domain', 'application'."
language: "The language in which the labels of the ontology are written. This field should use IANA's standard for language tags (e.g., 'en' for English, and 'pt-br' for Brazilian Portuguese). See the full list at https://www.iana.org/assignments/language-subtag-registry/language-subtag-registry"
purpose: "The purpose for the development of the ontology (e.g., 'conceptual clarification', or 'database design')"
context: "The context of the ontology's development (e.g., 'research', 'industry', and 'classroom')."
main-source: "The BibTex id of the main source publication for the represented ontology."
style: "Which styles of representation were adopted in the ontology, for example, 'specialization', in the direct specialization UFO concepts, and 'stereotyping', in the use of OntoUML stereotypes."
urls: "An object listing URLs of related resources to the documented ontology."
```

For more details on how to submit a model, visit our [GitHub Wiki](https://github.com/unibz-core/ontouml-models/wiki). Feel free to also post your questions as [issues](https://github.com/unibz-core/ontouml-models/issues), and to open [pull requests](https://github.com/unibz-core/ontouml-models/pulls) with your contributions.

## Documentation Example

For example, for the documentation of the UFO-S ontology, we should have the following folder structure:

```txt
nardi2015commitment/
├── original diagrams/
│   ├── diagram1.png
│   ├── diagram2.png
│   ├── diagram3.png
├── new diagrams/
│   ├── nardi2013towards-diagram1.png
│   ├── nardi2013towards-diagram2.png
│   ├── nardi2013towards-diagram3.png
│   ├── nardi2015commitment-diagram1.png
│   ├── nardi2015commitment-diagram2.png
│   ├── nardi2015commitment-diagram3.png
├── metadata.yaml
├── ontology.json
├── ontology.vpp
├── references.bib
```

The metadata file for UFO-S could be filled as follows:

```yaml
title: "UFO-S"
created-at: 2013
last-update: 2015
domain:
  - "services"
editorial-notes: "The ontology was documented based on the version on the journal publication."
types:
  - "core"
language: "en"
purpose: "conceptual clarification"
context: "research"
main-source: "nardi2015commitment"
style:
  - "ontouml"
urls:
  "github repo": "https://github.com/unibz-core/UFO-S"
```

The contents of the BibTex references file can be as follows:

```bibtex
@inproceedings{nardi2013towards,
  title={Towards a commitment-based reference ontology for services},
  author={Nardi, Julio Cesar and de Almeida Falbo, Ricardo and Almeida, Jo{\~a}o Paulo A and Guizzardi, Giancarlo and Pires, Lu{\'\i}s Ferreira and van Sinderen, Marten J and Guarino, Nicola},
  booktitle={2013 17th IEEE International Enterprise Distributed Object Computing Conference},
  pages={175--184},
  year={2013},
  organization={IEEE}
}

@article{nardi2015commitment,
  title={A commitment-based reference ontology for services},
  author={Nardi, Julio Cesar and de Almeida Falbo, Ricardo and Almeida, Jo{\~a}o Paulo A and Guizzardi, Giancarlo and Pires, Lu{\'\i}s Ferreira and van Sinderen, Marten J and Guarino, Nicola and Fonseca, Claudenir Morais},
  journal={Information systems},
  volume={54},
  pages={263--288},
  year={2015},
  publisher={Elsevier}
}
```
