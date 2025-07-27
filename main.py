import os
import json
import argparse
from tree_sitter import Language, Parser
import tree_sitter_go as tsg

# Load Go language
GO_LANGUAGE = Language(tsg.language())
parser = Parser(GO_LANGUAGE)


def get_text(code, node):
    return code[node.start_byte:node.end_byte]

def get_doc_comment(code, node):
    comments = []
    prev_sibling = node.prev_named_sibling
    while prev_sibling and prev_sibling.type == "comment":
        comments.insert(0, get_text(code, prev_sibling).lstrip("//").strip())
        prev_sibling = prev_sibling.prev_named_sibling
    return "\n".join(comments) if comments else None

def collect_definitions(path):
    definitions = []
    symbol_table = {}

    for root_dir, _, files in os.walk(path):
        for file in files:
            if file.endswith(".go"):
                file_path = os.path.join(root_dir, file)
                with open(file_path, "r", encoding="utf8") as f:
                    code = f.read()
                tree = parser.parse(bytes(code, "utf8"))
                root = tree.root_node

                # Get package name
                package_name = None
                for child in root.children:
                    if child.type == "package_clause":
                        package_name = code[child.start_byte:child.end_byte].replace("package", "").strip()

                def traverse(node):
                    if node.type in ["function_declaration", "method_declaration"]:
                        name_node = node.child_by_field_name("name")
                        if name_node:
                            name = get_text(code, name_node)
                            element_type = "function"
                            snippet = get_text(code, node)
                            signature = snippet.split("\n")[0]
                            doc_comment = get_doc_comment(code, node)
                            start_line = node.start_point[0] + 1
                            end_line = node.end_point[0] + 1
                            unique_id = f"{element_type}_{name}_{file}_{start_line}"
                            symbol_table[name] = unique_id
                            definitions.append({
                                "id": unique_id,
                                "type": element_type,
                                "doc_string": doc_comment,
                                "signature": signature,
                                "snippet": snippet,
                                "package_name": package_name,
                                "file_name": file_path,
                                "language": "Go",
                                "line_from": start_line,
                                "line_to": end_line,
                                "references": []
                            })

                    elif node.type in ["const_declaration", "var_declaration"]:
                        snippet = get_text(code, node)
                        start_line = node.start_point[0] + 1
                        end_line = node.end_point[0] + 1
                        doc_comment = get_doc_comment(code, node)
                        names = [get_text(code, c) for c in node.children if c.type == "identifier"]
                        for name in names:
                            element_type = "constant" if node.type == "const_declaration" else "variable"
                            unique_id = f"{element_type}_{name}_{file}_{start_line}"
                            symbol_table[name] = unique_id
                            definitions.append({
                                "id": unique_id,
                                "type": element_type,
                                "doc_string": doc_comment,
                                "signature": snippet.split("\n")[0],
                                "snippet": snippet,
                                "package_name": package_name,
                                "file_name": file_path,
                                "language": "Go",
                                "line_from": start_line,
                                "line_to": end_line,
                                "references": []
                            })

                    elif node.type == "type_declaration":
                        snippet = get_text(code, node)
                        start_line = node.start_point[0] + 1
                        end_line = node.end_point[0] + 1
                        name_node = None
                        for child in node.children:
                            if child.type == "type_spec":
                                name_node = child.child_by_field_name("name")
                        if name_node:
                            name = get_text(code, name_node)
                            element_type = "struct" if "struct" in snippet else "interface"
                            unique_id = f"{element_type}_{name}_{file}_{start_line}"
                            symbol_table[name] = unique_id
                            definitions.append({
                                "id": unique_id,
                                "type": element_type,
                                "doc_string": get_doc_comment(code, node),
                                "signature": snippet.split("\n")[0],
                                "snippet": snippet,
                                "package_name": package_name,
                                "file_name": file_path,
                                "language": "Go",
                                "line_from": start_line,
                                "line_to": end_line,
                                "references": []
                            })

                    for child in node.children:
                        traverse(child)

                traverse(root)

    return definitions, symbol_table

def collect_references(path, symbol_table):
    references = []

    for root_dir, _, files in os.walk(path):
        for file in files:
            if file.endswith(".go"):
                file_path = os.path.join(root_dir, file)
                with open(file_path, "r", encoding="utf8") as f:
                    code = f.read()
                tree = parser.parse(bytes(code, "utf8"))
                root = tree.root_node

                def find_calls(node):
                    if node.type == "call_expression":
                        func_node = node.child_by_field_name("function")
                        if func_node:
                            func_name = get_text(code, func_node)
                            if func_name in symbol_table:
                                references.append({
                                    "type": "function_call",
                                    "name": func_name,
                                    "definition_id": symbol_table[func_name],
                                    "file_name": file_path,
                                    "language": "Go",
                                    "line": node.start_point[0] + 1,
                                    "context": get_text(code, node)
                                })
                    for child in node.children:
                        find_calls(child)

                find_calls(root)

    return references

def merge_definitions_references(definitions, references):
    ref_map = {}
    for ref in references:
        def_id = ref["definition_id"]
        if def_id not in ref_map:
            ref_map[def_id] = []
        ref_map[def_id].append(ref)

    for d in definitions:
        if d["id"] in ref_map:
            d["references"] = ref_map[d["id"]]

    return definitions

if __name__ == "__main__":
    parser_cli = argparse.ArgumentParser()
    parser_cli.add_argument("--path", required=True, help="Path to Go project directory")
    parser_cli.add_argument("--output", required=False, help="Output JSON file")
    args = parser_cli.parse_args()

    definitions, symbol_table = collect_definitions(args.path)
    references = collect_references(args.path, symbol_table)
    merged = merge_definitions_references(definitions, references)

    if args.output:
        with open(args.output, "w") as out_file:
            json.dump(merged, out_file, indent=2)
    else:
        print(json.dumps(merged, indent=2))
