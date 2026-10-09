"""
File validation utilities.

Handles upload validation including file extension checks, size limits,
ZIP archive integrity, Shapefile component validation, and KML structure checks.
Implements security protections against path traversal and malicious archives.
"""

import os
import io
import zipfile
import tempfile
from pathlib import Path, PurePosixPath
from xml.etree import ElementTree

from app.core.config import get_settings
from app.core.exceptions import (
    FileValidationError,
    UnsupportedFormatError,
    FileSizeExceededError,
    CorruptFileError,
    ShapefileValidationError,
    KMLValidationError,
    AmbiguousDatasetError,
)
from app.core.logging import get_logger

logger = get_logger(__name__)

# Required Shapefile components (minimum for a valid dataset)
REQUIRED_SHP_EXTENSIONS = {".shp", ".shx", ".dbf"}
OPTIONAL_SHP_EXTENSIONS = {".prj", ".cpg", ".sbn", ".sbx", ".fbn", ".fbx", ".ain", ".aih", ".shp.xml"}


def validate_file_extension(filename: str) -> str:
    """
    Validate that the file has a supported extension.

    Returns the lowercase extension.
    Raises UnsupportedFormatError if not supported.
    """
    settings = get_settings()
    ext = Path(filename).suffix.lower()

    if ext not in settings.allowed_extensions_list:
        raise UnsupportedFormatError(
            f"Unsupported file format: '{ext}'. Supported formats: {settings.allowed_extensions_list}",
            details={"extension": ext, "supported": settings.allowed_extensions_list},
        )
    return ext


def validate_file_size(content: bytes) -> int:
    """
    Validate that file content does not exceed the configured size limit.

    Returns the size in bytes.
    Raises FileSizeExceededError if too large.
    """
    settings = get_settings()
    size = len(content)

    if size > settings.max_upload_size_bytes:
        raise FileSizeExceededError(
            f"File size ({size} bytes) exceeds maximum allowed "
            f"({settings.max_upload_size_bytes} bytes / {settings.max_upload_size_mb} MB)",
            details={
                "file_size": size,
                "max_size": settings.max_upload_size_bytes,
            },
        )
    return size


def validate_zip_archive(file_path: Path | bytes | io.BytesIO) -> Path:
    """
    Validate a ZIP archive for integrity and Shapefile content.

    Checks for:
    - Valid ZIP format
    - No path traversal attacks
    - Presence of required Shapefile components (.shp, .shx, .dbf)
    - No ambiguous multiple Shapefile datasets

    Returns the path to the .shp file within the archive.
    Raises appropriate exceptions on failure.
    """
    if isinstance(file_path, (bytes, bytearray)):
        file_path = io.BytesIO(file_path)

    # Check ZIP integrity
    if not zipfile.is_zipfile(file_path):
        raise CorruptFileError(
            "The uploaded file is not a valid ZIP archive",
            details={"reason": "Not a ZIP file"},
        )

    try:
        with zipfile.ZipFile(file_path, "r") as zf:
            # Check for corrupt archive
            bad_file = zf.testzip()
            if bad_file is not None:
                raise CorruptFileError(
                    f"Corrupt file found in ZIP archive: {Path(bad_file).name}",
                    details={"corrupt_entry": Path(bad_file).name},
                )

            # Security: check for path traversal
            for entry in zf.namelist():
                _check_path_traversal(entry)

            # Find Shapefile datasets
            shp_files = _find_shapefiles(zf.namelist())

            if not shp_files:
                raise ShapefileValidationError(
                    "No valid Shapefile dataset found in ZIP archive. "
                    "A Shapefile requires at minimum .shp, .shx, and .dbf files.",
                    details={"archive_contents": [Path(n).name for n in zf.namelist()]},
                )

            if len(shp_files) > 1:
                raise AmbiguousDatasetError(
                    f"ZIP archive contains {len(shp_files)} Shapefile datasets. "
                    "Only single-dataset archives are supported.",
                    details={"datasets": [str(s) for s in shp_files]},
                )

            return shp_files[0]

    except zipfile.BadZipFile:
        raise CorruptFileError(
            "The uploaded file is a corrupt ZIP archive",
            details={"reason": "BadZipFile"},
        )


def _check_path_traversal(entry_path: str) -> None:
    """
    Check a ZIP entry path for path traversal attacks.

    Raises FileValidationError if the path attempts to escape the extraction directory.
    """
    # Normalize to forward slashes for consistent checking
    normalized = PurePosixPath(entry_path)

    # Check for absolute paths
    if normalized.is_absolute():
        raise FileValidationError(
            "ZIP archive contains an absolute path entry, which is not allowed",
            details={"entry": str(normalized)},
        )

    # Check for parent directory references
    parts = normalized.parts
    if ".." in parts:
        raise FileValidationError(
            "ZIP archive contains path traversal (.. references), which is not allowed",
            details={"entry": str(normalized)},
        )

    # Check for backslash-based traversal
    if "\\" in entry_path or "..\\" in entry_path:
        for part in entry_path.replace("\\", "/").split("/"):
            if part == "..":
                raise FileValidationError(
                    "ZIP archive contains path traversal, which is not allowed",
                    details={"entry": entry_path},
                )


def _find_shapefiles(names: list[str]) -> list[Path]:
    """
    Find valid Shapefile datasets within a list of ZIP entry names.

    A valid dataset requires at minimum .shp, .shx, and .dbf files
    with matching base names.

    Returns a list of paths to .shp files that have matching required components.
    """
    # Group files by their stem (base name without extension)
    from collections import defaultdict

    # Normalize paths
    path_map: dict[str, dict[str, str]] = defaultdict(dict)

    for name in names:
        p = PurePosixPath(name)
        if p.suffix.lower() in REQUIRED_SHP_EXTENSIONS | OPTIONAL_SHP_EXTENSIONS:
            # Use the full path minus extension as the key (preserves directory structure)
            key = str(p.with_suffix("")).lower()
            path_map[key][p.suffix.lower()] = name

    # Find datasets with all required components
    valid_datasets = []
    for key, extensions in path_map.items():
        if REQUIRED_SHP_EXTENSIONS.issubset(extensions.keys()):
            # Return the path to the .shp file
            valid_datasets.append(Path(extensions[".shp"]))

    return valid_datasets


def extract_zip_safely(zip_path: Path, extract_dir: Path) -> Path:
    """
    Safely extract a ZIP archive into an isolated directory.

    Performs path traversal checks on each entry before extraction.
    Returns the path to the extracted .shp file.
    """
    extract_dir.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(zip_path, "r") as zf:
        for entry in zf.namelist():
            _check_path_traversal(entry)

            # Resolve the target path and verify it's within extract_dir
            target = (extract_dir / entry).resolve()
            if not str(target).startswith(str(extract_dir.resolve())):
                raise FileValidationError(
                    "ZIP entry resolves outside the extraction directory",
                    details={"entry": entry},
                )

        zf.extractall(extract_dir)

    # Find the .shp file in the extracted contents
    shp_files = list(extract_dir.rglob("*.shp"))
    if not shp_files:
        raise ShapefileValidationError(
            "No .shp file found after extraction",
        )
    if len(shp_files) > 1:
        raise AmbiguousDatasetError(
            f"Multiple .shp files found after extraction: {len(shp_files)}",
            details={"files": [f.name for f in shp_files]},
        )

    return shp_files[0]


def validate_kml_content(file_path: Path) -> bool:
    """
    Validate that a file contains valid KML content.

    Checks:
    - File is valid XML
    - Root element is 'kml' with the KML namespace

    Returns True if valid.
    Raises KMLValidationError if invalid.
    """
    try:
        tree = ElementTree.parse(file_path)
        root = tree.getroot()

        # KML namespace
        kml_ns = "http://www.opengis.net/kml/2.2"

        # Check root element
        tag = root.tag
        # Handle namespace prefix
        if tag == f"{{{kml_ns}}}kml" or tag == "kml":
            return True

        # Check without namespace (some KML files may not use namespace)
        local_name = tag.split("}")[-1] if "}" in tag else tag
        if local_name.lower() == "kml":
            return True

        raise KMLValidationError(
            f"File does not appear to be a valid KML document. "
            f"Root element is '{local_name}', expected 'kml'.",
            details={"root_element": local_name},
        )

    except ElementTree.ParseError as e:
        raise KMLValidationError(
            "File is not valid XML and cannot be parsed as KML",
            details={"parse_error": str(e)},
        )
    except Exception as e:
        if isinstance(e, KMLValidationError):
            raise
        raise KMLValidationError(
            "Failed to validate KML file",
            details={"error": str(e)},
        )


def get_file_format(extension: str) -> str:
    """Map file extension to format name."""
    format_map = {
        ".zip": "shapefile",
        ".kml": "kml",
    }
    return format_map.get(extension.lower(), "unknown")
