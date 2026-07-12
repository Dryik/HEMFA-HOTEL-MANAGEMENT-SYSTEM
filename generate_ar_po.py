"""Generate i18n/ar.po files with proper occurrence lines, offline.

Odoo 19's PO importer only applies entries through their `#:`
occurrence references. The canonical way to obtain them is a server
export (odoo.tools.translate.trans_export) piped through
translate_exported_po.py — but the occurrence formats are fully
deterministic (see odoo/addons/base/models/ir_model.py: model_xmlid,
field_xmlid, selection_xmlid), so this script derives them straight
from the addon source instead. Entries whose msgid does not byte-match
the server-side term are silently skipped at import, so a partial
mismatch degrades to English rather than breaking anything.

Run from the repository root:  python generate_ar_po.py
"""

import ast
import os
import re
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from translate_exported_po import TRANSLATIONS, header_template, po_escape

MODULES = [
    "hotel_base",
    "hotel_reservation",
    "hotel_board",
    "hotel_folio",
    "hotel_rate",
    "hotel_night_audit",
    "hotel_frontdesk_session",
    "hotel_housekeeping",
    "hotel_maintenance",
    "hotel_restricted_services",
    "hotel_pos_room_charge",
    "hotel_reports",
]

RELATIONAL_FIELDS = {"Many2one", "One2many", "Many2many"}
TRANSLATED_ATTRS = {"string", "help", "placeholder", "confirm", "title"}
SKIP_DIRS = {"tests", "i18n", "demo", "__pycache__"}


def add(entries, msgid, occurrence, flag=None):
    if not msgid or not re.search(r"[A-Za-z]", msgid):
        return
    entry = entries.setdefault(msgid, {"occ": [], "flags": set()})
    if occurrence not in entry["occ"]:
        entry["occ"].append(occurrence)
    if flag:
        entry["flags"].add(flag)


def const_str(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def extract_selection(list_node):
    pairs = []
    for elt in list_node.elts:
        if isinstance(elt, ast.Tuple) and len(elt.elts) == 2:
            value = const_str(elt.elts[0])
            label = const_str(elt.elts[1])
            if value is not None and label is not None:
                pairs.append((value, label))
    return pairs


def parse_python(module, path, rel, entries):
    with open(path, encoding="utf-8") as handle:
        tree = ast.parse(handle.read())

    # Module-level selection constants (HK_STATUS, RESERVATION_STATES...)
    consts = {}
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and isinstance(node.value, ast.List)
        ):
            pairs = extract_selection(node.value)
            if pairs:
                consts[node.targets[0].id] = pairs

    # _( ... ) code terms
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "_"
            and node.args
        ):
            term = const_str(node.args[0])
            if term:
                add(
                    entries,
                    term,
                    f"code:addons/{module}/{rel}:0",
                    "odoo-python",
                )

    for cls in [n for n in tree.body if isinstance(n, ast.ClassDef)]:
        model_name = None
        inherit_name = None
        description = None
        field_defs = []
        for stmt in cls.body:
            if not (
                isinstance(stmt, ast.Assign)
                and len(stmt.targets) == 1
                and isinstance(stmt.targets[0], ast.Name)
            ):
                continue
            target = stmt.targets[0].id
            if target == "_name":
                model_name = const_str(stmt.value)
            elif target == "_inherit":
                inherit_name = const_str(stmt.value)
            elif target == "_description":
                description = const_str(stmt.value)
            elif (
                isinstance(stmt.value, ast.Call)
                and isinstance(stmt.value.func, ast.Attribute)
                and isinstance(stmt.value.func.value, ast.Name)
                and stmt.value.func.value.id == "fields"
            ):
                field_defs.append((target, stmt.value))

        model = model_name or inherit_name
        if not model:
            continue
        xmodel = model.replace(".", "_")

        if model_name and description:
            add(
                entries,
                description,
                f"model:ir.model,name:{module}.model_{xmodel}",
            )

        for fname, call in field_defs:
            ftype = call.func.attr
            kwargs = {kw.arg: kw.value for kw in call.keywords if kw.arg}
            pos = call.args
            string_node = kwargs.get("string")
            selection_node = kwargs.get("selection")
            if ftype in RELATIONAL_FIELDS:
                if string_node is None and len(pos) >= 2:
                    string_node = pos[1]
            elif ftype == "Selection":
                if selection_node is None and len(pos) >= 1:
                    selection_node = pos[0]
                if string_node is None and len(pos) >= 2:
                    string_node = pos[1]
            else:
                if string_node is None and len(pos) >= 1:
                    string_node = pos[0]

            label = const_str(string_node) if string_node is not None else None
            if label:
                add(
                    entries,
                    label,
                    f"model:ir.model.fields,field_description:"
                    f"{module}.field_{xmodel}__{fname}",
                )
            help_node = kwargs.get("help")
            help_text = const_str(help_node) if help_node is not None else None
            if help_text:
                add(
                    entries,
                    help_text,
                    f"model:ir.model.fields,help:{module}.field_{xmodel}__{fname}",
                )
            pairs = None
            if selection_node is not None:
                if isinstance(selection_node, ast.List):
                    pairs = extract_selection(selection_node)
                elif isinstance(selection_node, ast.Name):
                    pairs = consts.get(selection_node.id)
            for value, sel_label in pairs or []:
                xvalue = value.replace(".", "_").replace(" ", "_").lower()
                add(
                    entries,
                    sel_label,
                    f"model:ir.model.fields.selection,name:"
                    f"{module}.selection__{xmodel}__{fname}__{xvalue}",
                )


def extract_arch_terms(module, xmlid, elem, entries, occurrence):
    for node in elem.iter():
        for attr in TRANSLATED_ATTRS:
            value = node.get(attr)
            if value:
                add(entries, value.strip(), occurrence)
        # Leaf text only: mixed inline content is segmented differently
        # by odoo.tools.xml_translate and would not byte-match.
        if len(node) == 0 and node.text and node.text.strip():
            add(entries, node.text.strip(), occurrence)


def parse_xml(module, path, entries):
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError:
        return

    for menu in root.iter("menuitem"):
        menu_id = menu.get("id")
        name = menu.get("name")
        if menu_id and name and "." not in menu_id:
            add(entries, name, f"model:ir.ui.menu,name:{module}.{menu_id}")

    for record in root.iter("record"):
        rec_id = record.get("id")
        rec_model = record.get("model")
        if not rec_id or not rec_model or "." in rec_id:
            continue
        for field in record.findall("field"):
            fname = field.get("name")
            if fname == "arch" and rec_model == "ir.ui.view":
                extract_arch_terms(
                    module,
                    rec_id,
                    field,
                    entries,
                    f"model_terms:ir.ui.view,arch_db:{module}.{rec_id}",
                )
            elif fname == "help" and rec_model == "ir.actions.act_window":
                for block in list(field):
                    text = "".join(block.itertext()).strip()
                    text = re.sub(r"\s+", " ", text)
                    add(
                        entries,
                        text,
                        f"model_terms:ir.actions.act_window,help:"
                        f"{module}.{rec_id}",
                    )
            elif (
                fname == "name"
                and rec_model != "ir.ui.view"  # view names are technical
                and field.text
                and field.text.strip()
            ):
                add(
                    entries,
                    field.text.strip(),
                    f"model:{rec_model},name:{module}.{rec_id}",
                )

    for template in root.iter("template"):
        tmpl_id = template.get("id")
        if tmpl_id and "." not in tmpl_id:
            extract_arch_terms(
                module,
                tmpl_id,
                template,
                entries,
                f"model_terms:ir.ui.view,arch_db:{module}.{tmpl_id}",
            )


def parse_static_xml(module, path, rel, entries):
    """Owl client templates: terms are code-type, keyed by file path."""
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError:
        return
    occurrence = f"code:addons/{module}/{rel}:0"
    for node in root.iter():
        for attr in TRANSLATED_ATTRS:
            value = node.get(attr)
            if value and not value.startswith(("{", "props.", "state.")):
                add(entries, value.strip(), occurrence, "odoo-javascript")
        if len(node) == 0 and node.text and node.text.strip():
            add(entries, node.text.strip(), occurrence, "odoo-javascript")


def parse_static_js(module, path, rel, entries):
    with open(path, encoding="utf-8") as handle:
        source = handle.read()
    occurrence = f"code:addons/{module}/{rel}:0"
    for match in re.finditer(r"""_t\(\s*(['"])(.+?)\1""", source):
        add(entries, match.group(2), occurrence, "odoo-javascript")


def generate_module(base_dir, module):
    module_dir = os.path.join(base_dir, module)
    entries = {}
    for dirpath, dirnames, filenames in os.walk(module_dir):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        in_static = os.sep + "static" + os.sep in dirpath + os.sep
        for filename in filenames:
            path = os.path.join(dirpath, filename)
            rel = os.path.relpath(path, module_dir).replace(os.sep, "/")
            if filename == "__manifest__.py":
                continue
            if filename.endswith(".py") and not in_static:
                parse_python(module, path, rel, entries)
            elif filename.endswith(".xml") and in_static:
                parse_static_xml(module, path, rel, entries)
            elif filename.endswith(".xml"):
                parse_xml(module, path, entries)
            elif filename.endswith(".js"):
                parse_static_js(module, path, rel, entries)

    i18n_dir = os.path.join(module_dir, "i18n")
    os.makedirs(i18n_dir, exist_ok=True)
    po_path = os.path.join(i18n_dir, "ar.po")

    untranslated = []
    blocks = []
    for msgid in sorted(entries):
        entry = entries[msgid]
        msgstr = TRANSLATIONS.get(msgid, "")
        if not msgstr:
            untranslated.append(msgid)
        lines = [f"#. module: {module}"]
        for flag in sorted(entry["flags"]):
            lines.append(f"#. {flag}")
        for occurrence in entry["occ"]:
            lines.append(f"#: {occurrence}")
        lines.append(f'msgid "{po_escape(msgid)}"')
        lines.append(f'msgstr "{po_escape(msgstr)}"')
        blocks.append("\n".join(lines))

    with open(po_path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(header_template.format(module_name=module))
        handle.write("\n\n".join(blocks))
        handle.write("\n")

    total = len(entries)
    done = total - len(untranslated)
    print(f"{module}: {total} terms, {done} translated")
    for term in untranslated:
        print(f"    untranslated: {term}")
    return total, done


def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    grand_total = grand_done = 0
    for module in MODULES:
        total, done = generate_module(base_dir, module)
        grand_total += total
        grand_done += done
    print(f"TOTAL: {grand_total} terms, {grand_done} translated")


if __name__ == "__main__":
    main()
