from __future__ import annotations

import json
import os
import re
import tomllib
from pathlib import Path

from defusedxml import ElementTree as element_tree


class DependencyResolutionError(ValueError):
    """A supported project does not provide an exact dependency version."""


def _dependency(purl: str, version: str) -> dict[str, str]:
    return {"purl": purl, "version": version}


def _is_exact_version(version: str) -> bool:
    return bool(version) and not any(
        token in version for token in ("$", "*", "+", "[", "]", "(", ")")
    )


def _npm_dependencies(project: Path) -> list[dict[str, str]]:
    package = json.loads((project / "package.json").read_text())
    names = set(package.get("dependencies", {})) | set(package.get("devDependencies", {}))
    versions: dict[str, str] = {}
    lock = project / "package-lock.json"
    if lock.exists():
        for path, data in json.loads(lock.read_text()).get("packages", {}).items():
            if path.startswith("node_modules/") and isinstance(data, dict) and "version" in data:
                versions[path.removeprefix("node_modules/")] = str(data["version"])
    pnpm = project / "pnpm-lock.yaml"
    if pnpm.exists():
        for name, version in re.findall(
            r"^\s{2}(/?[^:\s]+)@([^:\s]+):", pnpm.read_text(), re.MULTILINE
        ):
            versions.setdefault(name.lstrip("/"), version)
    yarn = project / "yarn.lock"
    if yarn.exists():
        for header, version in re.findall(
            r"^([^\n]+):\n\s+version\s+\"([^\"]+)\"", yarn.read_text(), re.MULTILINE
        ):
            for descriptor in header.split(", "):
                versions.setdefault(descriptor.rsplit("@", 1)[0].strip('"'), version)
    resolved = []
    for name in sorted(names):
        version = versions.get(name)
        if version:
            resolved.append(_dependency(f"pkg:npm/{name}@{version}", version))
    return resolved


def _maven_dependencies(project: Path) -> list[dict[str, str]]:
    pom = project / "pom.xml"
    root = element_tree.fromstring(pom.read_text())
    namespace = {"m": "http://maven.apache.org/POM/4.0.0"}
    properties = {
        element.tag.rsplit("}", 1)[-1]: (element.text or "").strip()
        for element in root.findall("m:properties/*", namespace)
    }
    dependencies = []
    for dependency in root.findall(".//m:dependencies/m:dependency", namespace):
        group = dependency.findtext("m:groupId", namespaces=namespace)
        artifact = dependency.findtext("m:artifactId", namespaces=namespace)
        version = dependency.findtext("m:version", namespaces=namespace)
        if version and version.startswith("${") and version.endswith("}"):
            version = properties.get(version[2:-1])
        if group and artifact and version and _is_exact_version(version):
            dependencies.append(_dependency(f"pkg:maven/{group}/{artifact}@{version}", version))
    return sorted(dependencies, key=lambda item: item["purl"])


def _gradle_dependencies(project: Path) -> list[dict[str, str]]:
    build_files = [project / "build.gradle", project / "build.gradle.kts"]
    content = "\n".join(path.read_text() for path in build_files if path.exists())
    matches = re.findall(
        r"(?:implementation|api|compileOnly|runtimeOnly)\s*\(?\s*[\"']([^:\"']+):([^:\"']+):([^@\"']+)",
        content,
    )
    return [
        _dependency(f"pkg:maven/{group}/{artifact}@{version}", version)
        for group, artifact, version in sorted(set(matches))
        if _is_exact_version(version)
    ]


def _cargo_dependencies(project: Path) -> list[dict[str, str]]:
    manifest = tomllib.loads((project / "Cargo.toml").read_text())
    names = set(manifest.get("dependencies", {})) | set(manifest.get("dev-dependencies", {}))
    versions: dict[str, str] = {}
    lock = project / "Cargo.lock"
    if lock.exists():
        for entry in tomllib.loads(lock.read_text()).get("package", []):
            name = entry.get("name")
            version = entry.get("version")
            if name and version and name not in versions:
                versions[name] = str(version)
    resolved = []
    for name in sorted(names):
        version = versions.get(name)
        if version:
            resolved.append(_dependency(f"pkg:cargo/{name}@{version}", version))
    return resolved


_PYPI_EXACT_PIN = re.compile(
    r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*(?:\[[^\]]*\])?\s*==\s*([A-Za-z0-9.+!_-]+)\s*(?:;.*)?$"
)


def _pypi_dependencies(project: Path) -> list[dict[str, str]]:
    resolved: dict[str, dict[str, str]] = {}
    for filename in ("requirements.txt", "requirements-dev.txt"):
        path = project / filename
        if not path.exists():
            continue
        for line in path.read_text().splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or stripped.startswith("-"):
                continue
            match = _PYPI_EXACT_PIN.match(stripped)
            if not match:
                continue
            name, version = match.group(1), match.group(2)
            normalized = name.lower().replace("_", "-")
            resolved.setdefault(
                normalized, _dependency(f"pkg:pypi/{normalized}@{version}", version)
            )
    return [resolved[name] for name in sorted(resolved)]


_GO_REQUIRE_LINE = re.compile(r"^\s*([^\s]+)\s+(v[0-9][^\s]*)\s*(?://.*)?$")


def _go_dependencies(project: Path) -> list[dict[str, str]]:
    content = (project / "go.mod").read_text()
    in_require_block = False
    resolved: dict[str, dict[str, str]] = {}
    for raw_line in content.splitlines():
        line = raw_line.split("//", 1)[0].strip()
        if not line:
            continue
        if line == "require (":
            in_require_block = True
            continue
        if in_require_block and line == ")":
            in_require_block = False
            continue
        if in_require_block:
            match = _GO_REQUIRE_LINE.match(line)
        elif line.startswith("require "):
            match = _GO_REQUIRE_LINE.match(line.removeprefix("require ").strip())
        else:
            match = None
        if not match:
            continue
        module_path, version = match.group(1), match.group(2)
        resolved.setdefault(
            module_path, _dependency(f"pkg:golang/{module_path}@{version}", version)
        )
    return [resolved[name] for name in sorted(resolved)]


_IGNORED_PROJECT_DIRECTORIES = {
    ".git",
    ".venv",
    "build",
    "coverage",
    "dist",
    "node_modules",
    "target",
    "venv",
}


def _project_dependencies(project: Path) -> list[dict[str, str]] | None:
    if (project / "package.json").exists():
        return _npm_dependencies(project)
    if (project / "pom.xml").exists():
        return _maven_dependencies(project)
    if (project / "build.gradle").exists() or (project / "build.gradle.kts").exists():
        return _gradle_dependencies(project)
    if (project / "Cargo.toml").exists():
        return _cargo_dependencies(project)
    if (project / "requirements.txt").exists():
        return _pypi_dependencies(project)
    if (project / "go.mod").exists():
        return _go_dependencies(project)
    return None


def _nested_project_roots(root: Path) -> list[Path]:
    manifests = {
        "package.json",
        "pom.xml",
        "build.gradle",
        "build.gradle.kts",
        "Cargo.toml",
        "requirements.txt",
        "go.mod",
    }
    candidates: set[Path] = set()
    for directory, subdirectories, files in os.walk(root):
        subdirectories[:] = [
            name for name in subdirectories if name not in _IGNORED_PROJECT_DIRECTORIES
        ]
        if manifests.intersection(files):
            candidates.add(Path(directory))
    return sorted(candidates)


def resolve_project(project: str | Path) -> list[dict[str, str]]:
    """Resolve exact dependencies, including nested supported projects when needed."""
    root = Path(project)
    direct = _project_dependencies(root)
    if direct is not None:
        return direct
    dependencies: dict[str, dict[str, str]] = {}
    for nested_project in _nested_project_roots(root):
        for dependency in _project_dependencies(nested_project) or []:
            dependencies[dependency["purl"]] = dependency
    if dependencies:
        return [dependencies[purl] for purl in sorted(dependencies)]
    raise DependencyResolutionError("supported manifest not found")
