"""Static repository checks that do not require an Odoo database.

Runtime installation, upgrade, and tagged addon tests remain Odoo.sh jobs.  This
script intentionally uses only the Python standard library so it can run in a
plain GitHub Actions worker and in a developer checkout.
"""

from __future__ import annotations

import ast
import csv
import re
import sys
from pathlib import Path
from xml.etree import ElementTree


ROOT = Path(__file__).resolve().parents[1]
ADDONS = sorted(path.parent for path in ROOT.glob("*/__manifest__.py"))
ACL_HEADER = [
    "id",
    "name",
    "model_id:id",
    "group_id:id",
    "perm_read",
    "perm_write",
    "perm_create",
    "perm_unlink",
]

FORBIDDEN_PATTERNS = {
    "Odoo 19 list views must use <list>": re.compile(r"<tree(?:\s|>)"),
    "attrs view modifiers were removed in Odoo 19": re.compile(r"\sattrs\s*="),
    "states view modifiers were removed in Odoo 19": re.compile(r"\sstates\s*="),
    "Odoo 19 kanban cards use t-name=card": re.compile(r't-name=["\']kanban-box["\']'),
    "Odoo 19 action view modes must use list": re.compile(
        r"<field\s+name=[\"']view_mode[\"'][^>]*>[^<]*\btree\b"
    ),
    "Odoo 19 uses models.Constraint": re.compile(r"\b_sql_constraints\s*="),
    "Odoo 19 fields use aggregator": re.compile(r"\bgroup_operator\s*="),
    "Odoo 19 JSON routes use type=jsonrpc": re.compile(r"type\s*=\s*[\"']json[\"']"),
    "Odoo web expressions expose timedelta as datetime.timedelta": re.compile(
        r"context_today\(\)\s*\+\s*timedelta\("
    ),
}


def fail(errors: list[str], message: str) -> None:
    errors.append(message)


def tracked_files(pattern: str) -> list[Path]:
    return sorted(ROOT.glob(pattern))


def check_python(errors: list[str]) -> None:
    for path in tracked_files("**/*.py"):
        if ".git" in path.parts:
            continue
        try:
            compile(path.read_text(encoding="utf-8"), str(path), "exec")
        except Exception as exc:  # pragma: no cover - CI diagnostic
            fail(errors, f"Python compile failed for {path.relative_to(ROOT)}: {exc}")


def check_xml(errors: list[str]) -> None:
    for addon in ADDONS:
        for path in addon.rglob("*.xml"):
            try:
                tree = ElementTree.parse(path)
            except Exception as exc:  # pragma: no cover - CI diagnostic
                fail(errors, f"XML parse failed for {path.relative_to(ROOT)}: {exc}")
                continue

            for element in tree.iter():
                if element.tag == "xpath" and re.search(
                    r"@\s*string\b", element.get("expr", "")
                ):
                    fail(
                        errors,
                        f"{path.relative_to(ROOT)}: inherited views may not select "
                        "elements by their translated string attribute",
                    )
                if (
                    element.tag != "xpath"
                    and element.get("position")
                    and "string" in element.attrib
                ):
                    fail(
                        errors,
                        f"{path.relative_to(ROOT)}: inherited view locators may not "
                        "use their translated string attribute",
                    )


def check_local_xml_references(errors: list[str]) -> None:
    """Resolve references whose owning addon is part of this repository."""
    addon_names = {addon.name for addon in ADDONS}
    ids_by_addon: dict[str, set[str]] = {name: set() for name in addon_names}
    parsed: list[tuple[Path, str, ElementTree.ElementTree]] = []
    id_tags = {"record", "menuitem", "template", "report", "act_window"}
    for addon in ADDONS:
        for path in addon.rglob("*.xml"):
            try:
                tree = ElementTree.parse(path)
            except Exception:
                continue  # The parse error is already reported by check_xml.
            parsed.append((path, addon.name, tree))
            for element in tree.iter():
                if element.tag in id_tags and element.get("id"):
                    ids_by_addon[addon.name].add(element.get("id"))

    def verify(path: Path, current_addon: str, reference: str) -> None:
        reference = reference.strip().lstrip("!")
        if not reference:
            return
        if "." in reference:
            owner, xmlid = reference.split(".", 1)
            if owner not in addon_names:
                return
        else:
            owner, xmlid = current_addon, reference
        # ir.model generates these XML IDs at registry setup rather than from
        # an addon XML file.
        if xmlid.startswith("model_"):
            return
        if xmlid not in ids_by_addon[owner]:
            fail(
                errors,
                f"{path.relative_to(ROOT)}: unresolved local XML reference {reference}",
            )

    ref_pattern = re.compile(r"\bref\(\s*['\"]([^'\"]+)['\"]\s*\)")
    for path, addon_name, tree in parsed:
        for element in tree.iter():
            if element.get("ref"):
                verify(path, addon_name, element.get("ref"))
            if element.tag == "menuitem":
                for attribute in ("action", "parent"):
                    if element.get(attribute):
                        verify(path, addon_name, element.get(attribute))
            if element.get("groups"):
                for reference in element.get("groups").split(","):
                    verify(path, addon_name, reference)
            for reference in ref_pattern.findall(element.get("eval", "")):
                verify(path, addon_name, reference)


def load_manifest(path: Path, errors: list[str]) -> dict:
    try:
        value = ast.literal_eval(path.read_text(encoding="utf-8"))
    except Exception as exc:
        fail(errors, f"Manifest parse failed for {path.relative_to(ROOT)}: {exc}")
        return {}
    if not isinstance(value, dict):
        fail(errors, f"Manifest is not a dict: {path.relative_to(ROOT)}")
        return {}
    return value


def check_manifests(errors: list[str]) -> None:
    addon_names = {addon.name for addon in ADDONS}
    for addon in ADDONS:
        manifest_path = addon / "__manifest__.py"
        manifest = load_manifest(manifest_path, errors)
        for key in ("name", "version", "depends", "installable"):
            if key not in manifest:
                fail(errors, f"{addon.name}: manifest is missing {key!r}")
        for section in ("data", "demo"):
            for relative in manifest.get(section, []):
                if not (addon / relative).is_file():
                    fail(errors, f"{addon.name}: missing manifest file {relative}")
        for dependency in manifest.get("depends", []):
            if dependency.startswith("hotel_") and dependency not in addon_names:
                fail(errors, f"{addon.name}: unknown local dependency {dependency}")


def check_acl_files(errors: list[str]) -> None:
    for path in [
        addon / "security" / "ir.model.access.csv"
        for addon in ADDONS
        if (addon / "security" / "ir.model.access.csv").is_file()
    ]:
        with path.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.reader(handle))
        if not rows or rows[0] != ACL_HEADER:
            fail(errors, f"Invalid ACL header in {path.relative_to(ROOT)}")
            continue
        seen: set[str] = set()
        for number, row in enumerate(rows[1:], start=2):
            if len(row) != len(ACL_HEADER):
                fail(errors, f"{path.relative_to(ROOT)}:{number}: expected 8 columns")
                continue
            if row[0] in seen:
                fail(errors, f"{path.relative_to(ROOT)}:{number}: duplicate id {row[0]}")
            seen.add(row[0])
            if any(value not in {"0", "1"} for value in row[4:]):
                fail(errors, f"{path.relative_to(ROOT)}:{number}: permissions must be 0/1")


def check_odoo19_patterns(errors: list[str]) -> None:
    candidates = [
        path
        for addon in ADDONS
        for path in addon.rglob("*")
        if path.suffix in (".py", ".xml")
        and "i18n" not in path.parts
        and "__pycache__" not in path.parts
    ]
    for path in candidates:
        text = path.read_text(encoding="utf-8")
        for description, pattern in FORBIDDEN_PATTERNS.items():
            if match := pattern.search(text):
                line = text.count("\n", 0, match.start()) + 1
                fail(errors, f"{path.relative_to(ROOT)}:{line}: {description}")


def count_tests() -> int:
    pattern = re.compile(r"^\s+def\s+test_", re.MULTILINE)
    return sum(
        len(pattern.findall(path.read_text(encoding="utf-8")))
        for path in tracked_files("hotel_*/tests/test_*.py")
    )


def main() -> int:
    errors: list[str] = []
    check_python(errors)
    check_xml(errors)
    check_local_xml_references(errors)
    check_manifests(errors)
    check_acl_files(errors)
    check_odoo19_patterns(errors)

    if errors:
        print("Static validation failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    print(
        f"Static validation passed: {len(ADDONS)} addons, "
        f"{count_tests()} test methods."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
