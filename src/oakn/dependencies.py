from __future__ import annotations

import json
import re
from pathlib import Path

from defusedxml import ElementTree as element_tree


class DependencyResolutionError(ValueError):
    """A supported project does not provide an exact dependency version."""


def _dependency(purl: str, version: str) -> dict[str, str]:
    return {"purl": purl, "version": version}


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
        if group and artifact and version:
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
    ]


def resolve_project(project: str | Path) -> list[dict[str, str]]:
    """Resolve direct dependencies with a lockfile/manifest exact version."""
    root = Path(project)
    if (root / "package.json").exists():
        return _npm_dependencies(root)
    if (root / "pom.xml").exists():
        return _maven_dependencies(root)
    if (root / "build.gradle").exists() or (root / "build.gradle.kts").exists():
        return _gradle_dependencies(root)
    raise DependencyResolutionError("supported manifest not found")
