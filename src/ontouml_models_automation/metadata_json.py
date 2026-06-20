"""Generate ``metadata-json.ttl`` from a dataset-level ``metadata.yaml`` file.

The generated RDF describes the JSON distribution of one OntoUML/UFO Catalog
model, i.e., the ``ontology.json`` file contained in a dataset folder.

This module intentionally does **not** generate ``metadata.ttl`` and does **not**
transform ``ontology.json`` into ``ontology.ttl``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.parse import urlparse
from uuid import NAMESPACE_URL, UUID, uuid5

import yaml
from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import DCTERMS, RDF, XSD

DCAT = Namespace("http://www.w3.org/ns/dcat#")
FDPO = Namespace("https://w3id.org/fdp/fdp-o#")
OCMV = Namespace("https://w3id.org/ontouml-models/vocabulary#")
OWL = Namespace("http://www.w3.org/2002/07/owl#")
RDFS = Namespace("http://www.w3.org/2000/01/rdf-schema#")
SKOS = Namespace("http://www.w3.org/2004/02/skos/core#")

DEFAULT_MODEL_BASE_URI = "https://w3id.org/ontouml-models/model/"
DEFAULT_DISTRIBUTION_BASE_URI = "https://w3id.org/ontouml-models/distribution/"
DEFAULT_SCHEMA_URI = "https://w3id.org/ontouml/schema"
DEFAULT_JSON_MEDIA_TYPE = "https://www.iana.org/assignments/media-types/application/json"
DEFAULT_DOWNLOAD_REPOSITORY = "OntoUML/ontouml-models"
DEFAULT_DOWNLOAD_BRANCH = "master"


class MetadataJsonError(Exception):
    """Base class for metadata-json generation errors."""


class MissingMetadataYamlError(MetadataJsonError):
    """Raised when a dataset folder has no metadata.yaml file."""


class InvalidMetadataYamlError(MetadataJsonError):
    """Raised when metadata.yaml cannot be parsed or is not a mapping."""


class MissingMandatoryFieldError(MetadataJsonError):
    """Raised when mandatory input data is missing."""


class InvalidFieldValueError(MetadataJsonError):
    """Raised when an input value is present but unsupported or malformed."""


@dataclass(frozen=True)
class MetadataJsonConfig:
    """Configuration for generating JSON distribution metadata."""

    repository: str = DEFAULT_DOWNLOAD_REPOSITORY
    branch: str = DEFAULT_DOWNLOAD_BRANCH
    model_base_uri: str = DEFAULT_MODEL_BASE_URI
    distribution_base_uri: str = DEFAULT_DISTRIBUTION_BASE_URI
    schema_uri: str = DEFAULT_SCHEMA_URI
    default_title_language: str = "en"
    metadata_timestamp: datetime | None = None
    overwrite: bool = True
    check_ontology_json: bool = True
    generate_missing_distribution_id: bool = False


@dataclass(frozen=True)
class JsonDistributionMetadata:
    """Normalized fields required to build ``metadata-json.ttl``."""

    dataset_folder: Path
    model_uri: URIRef
    distribution_uri: URIRef
    model_title: str
    distribution_title: str
    distribution_title_language: str | None
    issued: Literal
    license_uri: URIRef
    download_url: URIRef
    schema_uri: URIRef
    media_type_uri: URIRef
    metadata_issued: Literal
    metadata_modified: Literal


def generate_metadata_json_ttl(
    dataset_folder: Path | str,
    config: MetadataJsonConfig | None = None,
) -> Path:
    """Generate ``metadata-json.ttl`` for one dataset folder.

    Args:
        dataset_folder: Path to a model/dataset folder containing ``metadata.yaml``.
        config: Optional generation configuration.

    Returns:
        The path to the generated ``metadata-json.ttl`` file.

    Raises:
        MetadataJsonError: If input files or metadata values are invalid.
    """

    config = config or MetadataJsonConfig()
    dataset_path = Path(dataset_folder).resolve()
    metadata = load_metadata_yaml(dataset_path)
    normalized = normalize_json_distribution_metadata(dataset_path, metadata, config)
    graph = build_json_distribution_graph(normalized)

    output_path = dataset_path / "metadata-json.ttl"
    if output_path.exists() and not config.overwrite:
        raise InvalidFieldValueError(
            f"Refusing to overwrite existing file: {output_path}. Omit --no-overwrite to replace it."
        )

    output_path.write_text(
        graph.serialize(format="turtle", encoding="utf-8").decode("utf-8"),
        encoding="utf-8",
    )
    return output_path


def generate_for_dataset_folders(
    dataset_folders: Iterable[Path | str],
    config: MetadataJsonConfig | None = None,
) -> list[Path]:
    """Generate ``metadata-json.ttl`` for multiple dataset folders."""

    return [generate_metadata_json_ttl(Path(path), config) for path in dataset_folders]


def find_dataset_folders(models_dir: Path | str) -> list[Path]:
    """Return child folders of ``models_dir`` containing ``metadata.yaml``."""

    root = Path(models_dir)
    if not root.exists():
        raise MissingMetadataYamlError(f"Models directory does not exist: {root}")
    if not root.is_dir():
        raise MissingMetadataYamlError(f"Models path is not a directory: {root}")

    return sorted(path for path in root.iterdir() if (path / "metadata.yaml").is_file())


def load_metadata_yaml(dataset_folder: Path) -> Mapping[str, Any]:
    """Load ``metadata.yaml`` from a dataset folder."""

    metadata_path = dataset_folder / "metadata.yaml"
    if not metadata_path.is_file():
        raise MissingMetadataYamlError(f"Missing required file: {metadata_path}")

    try:
        with metadata_path.open("r", encoding="utf-8") as stream:
            # Use BaseLoader intentionally. PyYAML's SafeLoader implicitly casts
            # timestamp-like scalars to ``datetime`` objects and truncates
            # nanosecond precision to Python's microsecond precision. Existing
            # catalog distribution metadata uses xsd:dateTime lexical values with
            # nanoseconds, so we preserve YAML scalar lexical forms and perform
            # explicit coercion below.
            data = yaml.load(stream, Loader=yaml.BaseLoader)
    except yaml.YAMLError as exc:
        raise InvalidMetadataYamlError(f"Invalid YAML in {metadata_path}: {exc}") from exc

    if not isinstance(data, Mapping):
        raise InvalidMetadataYamlError(f"{metadata_path} must contain a YAML mapping/object.")

    return data


def normalize_json_distribution_metadata(
    dataset_folder: Path,
    data: Mapping[str, Any],
    config: MetadataJsonConfig,
) -> JsonDistributionMetadata:
    """Normalize accepted YAML variants into one internal metadata object.

    Supported YAML layout, recommended:

    model:
      id: d88fe48c-d574-43b4-85d6-a6e1aeaa6726
      title: Reference Ontology of Trust
      issued: 2019
      license: https://creativecommons.org/licenses/by/4.0/
    distributions:
      json:
        id: 7c83f03b-c170-49d2-9dd9-0a600be6cc96

    The function also accepts equivalent top-level fields such as ``id``,
    ``title``, ``issued``, and ``license`` for migration convenience.
    """

    model = _mapping_value(data, "model", default=data)
    distributions = _mapping_value(data, "distributions", "distribution", default={})
    json_distribution = _mapping_value(
        distributions,
        "json",
        "ontology_json",
        "metadata_json",
        default={},
    )

    if config.check_ontology_json and not (dataset_folder / "ontology.json").is_file():
        raise MissingMandatoryFieldError(
            f"Missing required ontology JSON file: {dataset_folder / 'ontology.json'}"
        )

    model_uri = _resource_uri(
        _first_present(model, data, keys=("uri", "iri", "model_uri")),
        _first_present(model, data, keys=("id", "uuid", "model_id")),
        base_uri=config.model_base_uri,
        field_name="model.id or model.uri",
        trailing_slash=False,
    )

    model_title_raw = _first_present(model, data, keys=("title", "name"))
    model_title, _model_title_lang = _coerce_title(model_title_raw, "model.title")
    if not model_title:
        raise MissingMandatoryFieldError("Missing mandatory field: model.title")

    issued_raw = _first_present(json_distribution, model, data, keys=("issued", "date", "created"))
    if issued_raw is None:
        raise MissingMandatoryFieldError("Missing mandatory field: model.issued")
    issued_literal = _date_literal(issued_raw, "model.issued")

    license_raw = _first_present(json_distribution, model, data, keys=("license", "license_uri"))
    if license_raw is None:
        raise MissingMandatoryFieldError("Missing mandatory field: model.license")
    license_uri = _uri_ref(license_raw, "model.license")

    distribution_uri_raw = _first_present(
        json_distribution,
        data,
        keys=("uri", "iri", "distribution_uri", "json_distribution_uri"),
    )
    distribution_id_raw = _first_present(
        json_distribution,
        data,
        keys=("id", "uuid", "distribution_id", "json_distribution_id"),
    )
    if distribution_uri_raw is None and distribution_id_raw is None and config.generate_missing_distribution_id:
        distribution_id_raw = str(uuid5(NAMESPACE_URL, f"{model_uri}/ontology.json"))

    distribution_uri = _resource_uri(
        distribution_uri_raw,
        distribution_id_raw,
        base_uri=config.distribution_base_uri,
        field_name="distributions.json.id or distributions.json.uri",
        trailing_slash=True,
    )

    title_raw = _first_present(json_distribution, keys=("title", "name"))
    if title_raw is None:
        distribution_title = f"JSON distribution of {model_title}"
        title_language = config.default_title_language
    else:
        distribution_title, title_language = _coerce_title(title_raw, "distributions.json.title")
        if title_language is None:
            title_language = _scalar_string(
                _first_present(json_distribution, keys=("title_language", "lang", "language")),
                "distributions.json.title_language",
                allow_none=True,
            ) or config.default_title_language

    schema_uri = _uri_ref(
        _first_present(json_distribution, keys=("conforms_to_schema", "conformsToSchema", "schema"))
        or config.schema_uri,
        "distributions.json.conforms_to_schema",
    )

    media_type_uri = _uri_ref(
        _first_present(json_distribution, keys=("media_type", "mediaType"))
        or DEFAULT_JSON_MEDIA_TYPE,
        "distributions.json.media_type",
    )
    if str(media_type_uri) != DEFAULT_JSON_MEDIA_TYPE:
        raise InvalidFieldValueError(
            "metadata-json.ttl describes ontology.json and therefore requires "
            f"media type {DEFAULT_JSON_MEDIA_TYPE}; got {media_type_uri}."
        )

    is_complete_raw = _first_present(json_distribution, keys=("is_complete", "isComplete", "complete"))
    if is_complete_raw is not None and not _coerce_boolean(is_complete_raw, "distributions.json.is_complete"):
        raise InvalidFieldValueError(
            "metadata-json.ttl describes ontology.json and therefore requires "
            "distributions.json.is_complete: true."
        )

    download_url = _uri_ref(
        _first_present(json_distribution, keys=("download_url", "downloadURL"))
        or _default_download_url(config.repository, config.branch, dataset_folder.name),
        "distributions.json.download_url",
    )

    timestamp = config.metadata_timestamp or _utc_now()
    metadata_issued_raw = _first_present(
        json_distribution,
        data,
        keys=("metadata_issued", "metadataIssued"),
    )
    metadata_modified_raw = _first_present(
        json_distribution,
        data,
        keys=("metadata_modified", "metadataModified"),
    )

    metadata_issued = _date_literal(metadata_issued_raw or timestamp, "metadata_issued")
    metadata_modified = _date_literal(metadata_modified_raw or timestamp, "metadata_modified")

    return JsonDistributionMetadata(
        dataset_folder=dataset_folder,
        model_uri=model_uri,
        distribution_uri=distribution_uri,
        model_title=model_title,
        distribution_title=distribution_title,
        distribution_title_language=title_language,
        issued=issued_literal,
        license_uri=license_uri,
        download_url=download_url,
        schema_uri=schema_uri,
        media_type_uri=media_type_uri,
        metadata_issued=metadata_issued,
        metadata_modified=metadata_modified,
    )


def build_json_distribution_graph(metadata: JsonDistributionMetadata) -> Graph:
    """Build the RDF graph for one JSON distribution metadata record."""

    graph = Graph()
    _bind_prefixes(graph)

    subject = metadata.distribution_uri
    graph.add((subject, RDF.type, DCAT.Distribution))
    graph.add((subject, DCTERMS.isPartOf, metadata.model_uri))
    graph.add((subject, DCTERMS.issued, metadata.issued))
    graph.add((subject, DCAT.mediaType, metadata.media_type_uri))
    graph.add((subject, DCTERMS.license, metadata.license_uri))
    graph.add((subject, OCMV.conformsToSchema, metadata.schema_uri))

    if metadata.distribution_title_language:
        graph.add(
            (
                subject,
                DCTERMS.title,
                Literal(metadata.distribution_title, lang=metadata.distribution_title_language),
            )
        )
    else:
        graph.add((subject, DCTERMS.title, Literal(metadata.distribution_title)))

    graph.add((subject, DCAT.downloadURL, metadata.download_url))
    graph.add((subject, OCMV.isComplete, Literal(True, datatype=XSD.boolean)))
    graph.add((subject, FDPO.metadataIssued, metadata.metadata_issued))
    graph.add((subject, FDPO.metadataModified, metadata.metadata_modified))
    return graph


def _bind_prefixes(graph: Graph) -> None:
    graph.bind("fdpo", FDPO)
    graph.bind("dcat", DCAT)
    graph.bind("dct", DCTERMS)
    graph.bind("ocmv", OCMV)
    graph.bind("owl", OWL)
    graph.bind("rdf", RDF)
    graph.bind("rdfs", RDFS)
    graph.bind("skos", SKOS)
    graph.bind("xsd", XSD)


def _mapping_value(
    mapping: Mapping[str, Any],
    *keys: str,
    default: Mapping[str, Any] | None = None,
) -> Mapping[str, Any]:
    for key in keys:
        value = mapping.get(key)
        if value is not None:
            if not isinstance(value, Mapping):
                raise InvalidFieldValueError(f"Expected mapping/object for field '{key}'.")
            return value
    return default or {}


def _first_present(*mappings: Mapping[str, Any], keys: Iterable[str]) -> Any:
    for mapping in mappings:
        for key in keys:
            if key in mapping and mapping[key] is not None:
                return mapping[key]
    return None


def _resource_uri(
    uri_value: Any,
    id_value: Any,
    *,
    base_uri: str,
    field_name: str,
    trailing_slash: bool,
) -> URIRef:
    if uri_value is not None:
        uri = str(_uri_ref(uri_value, field_name))
        if trailing_slash and not uri.endswith("/"):
            uri = f"{uri}/"
        if not trailing_slash and uri.endswith("/"):
            uri = uri.rstrip("/")
        return URIRef(uri)

    if id_value is None:
        raise MissingMandatoryFieldError(f"Missing mandatory field: {field_name}")

    identifier = _scalar_string(id_value, field_name)
    try:
        uuid = UUID(identifier)
    except ValueError as exc:
        raise InvalidFieldValueError(
            f"{field_name} must be a UUID when no full URI is provided; got {identifier!r}."
        ) from exc

    suffix = f"{uuid}/" if trailing_slash else str(uuid)
    return _uri_ref(f"{base_uri}{suffix}", field_name)


def _uri_ref(value: Any, field_name: str) -> URIRef:
    text = _scalar_string(value, field_name)
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise InvalidFieldValueError(f"{field_name} must be an absolute HTTP(S) URI; got {text!r}.")
    return URIRef(text)


def _scalar_string(value: Any, field_name: str, *, allow_none: bool = False) -> str | None:
    if value is None and allow_none:
        return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise InvalidFieldValueError(f"{field_name} cannot be empty.")
        return text
    if isinstance(value, (int, float)):
        return str(value)
    raise InvalidFieldValueError(f"{field_name} must be a scalar string; got {type(value).__name__}.")


def _coerce_title(value: Any, field_name: str) -> tuple[str, str | None]:
    if isinstance(value, str):
        return _scalar_string(value, field_name) or "", None

    if isinstance(value, Mapping):
        # Recommended compact shape: {value: "...", lang: "en"}
        if "value" in value:
            text = _scalar_string(value.get("value"), f"{field_name}.value") or ""
            lang = _scalar_string(value.get("lang") or value.get("language"), f"{field_name}.lang", allow_none=True)
            return text, lang

        # Convenient language-map shape: {en: "Reference Ontology of Trust"}
        if len(value) == 1:
            lang, text = next(iter(value.items()))
            return _scalar_string(text, field_name) or "", _scalar_string(lang, f"{field_name}.lang")

    raise InvalidFieldValueError(
        f"{field_name} must be a string, a language map, or {{value, lang}} mapping."
    )


def _coerce_boolean(value: Any, field_name: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "yes", "1"}:
            return True
        if normalized in {"false", "no", "0"}:
            return False
    raise InvalidFieldValueError(
        f"{field_name} must be a boolean value; got {value!r}."
    )


def _date_literal(value: Any, field_name: str) -> Literal:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return Literal(value.isoformat().replace("+00:00", "Z"), datatype=XSD.dateTime, normalize=False)

    if isinstance(value, date):
        return Literal(value.isoformat(), datatype=XSD.date, normalize=False)

    if isinstance(value, int):
        text = str(value)
        if len(text) == 4:
            return Literal(text, datatype=XSD.gYear, normalize=False)
        raise InvalidFieldValueError(f"{field_name} integer values must be four-digit years.")

    text = _scalar_string(value, field_name)
    assert text is not None

    if _matches(text, r"^\d{4}$"):
        return Literal(text, datatype=XSD.gYear, normalize=False)
    if _matches(text, r"^\d{4}-\d{2}$"):
        return Literal(text, datatype=XSD.gYearMonth, normalize=False)
    if _matches(text, r"^\d{4}-\d{2}-\d{2}$"):
        return Literal(text, datatype=XSD.date, normalize=False)
    if _matches(text, r"^\d{4}-\d{2}-\d{2}T.+"):
        return Literal(text, datatype=XSD.dateTime, normalize=False)

    raise InvalidFieldValueError(
        f"{field_name} must be xsd:gYear, xsd:gYearMonth, xsd:date, or xsd:dateTime lexical form; got {text!r}."
    )


def _matches(text: str, pattern: str) -> bool:
    import re

    return re.match(pattern, text) is not None


def _default_download_url(repository: str, branch: str, dataset_slug: str) -> str:
    if "/" not in repository:
        raise InvalidFieldValueError(
            f"Repository must be in owner/name form, e.g., OntoUML/ontouml-models; got {repository!r}."
        )
    return (
        f"https://raw.githubusercontent.com/{repository}/{branch}/"
        f"models/{dataset_slug}/ontology.json"
    )


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)
