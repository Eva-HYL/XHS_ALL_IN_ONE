from __future__ import annotations

from typing import Any

from backend.app.services.wechat_mp_content_analysis_service import VisualCandidate
from backend.app.services.wechat_mp_illustration_method import (
    CHARACTER_ROLE,
    apply_method_contract,
    validate_method_contract,
)


def _comparison_relation(columns: list[str], rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    if len(columns) != 2:
        return []
    relation_text = " ".join(
        str(value)
        for row in rows
        if row["label"] == "关系"
        for value in row["values"]
    )
    if "前" in relation_text and "质量控制" in columns and "确认范围" in columns:
        return [{"from": "质量控制", "to": "确认范围", "label": "先质检，再验收"}]
    return []


def build_visual_plan(candidate: VisualCandidate) -> dict[str, Any]:
    if candidate.kind == "table":
        header, *body = candidate.structure
        if (
            len(header) >= 3
            and header[0].strip().lower() in {"#", "序号", "编号"}
            and body
            and all(row[0].strip().isdigit() for row in body)
        ):
            nodes = [row[1] for row in body]
            groups: dict[str, list[str]] = {}
            for row in body:
                groups.setdefault(row[2], []).append(row[1])
            return apply_method_contract({
                "kind": "flow",
                "nodes": nodes,
                "groups": groups,
                "relations": [
                    {"from": nodes[index], "to": nodes[index + 1], "label": ""}
                    for index in range(len(nodes) - 1)
                ],
                "source_cells": [cell for row in candidate.structure for cell in row],
            })
        columns = list(header[1:])
        rows = [{"label": row[0], "values": list(row[1:])} for row in body]
        kind = "comparison" if len(columns) == 2 else "matrix"
        return apply_method_contract({
            "kind": kind,
            "columns": columns,
            "rows": rows,
            "relations": _comparison_relation(columns, rows),
            "source_cells": [cell for row in candidate.structure for cell in row],
        })
    if candidate.kind == "flow":
        nodes = list(candidate.structure[0])
        return apply_method_contract({
            "kind": "flow",
            "nodes": nodes,
            "relations": [
                {"from": nodes[index], "to": nodes[index + 1], "label": ""}
                for index in range(len(nodes) - 1)
            ],
            "source_cells": nodes,
        })
    return apply_method_contract({
        "kind": candidate.kind,
        "items": [list(item) for item in candidate.structure],
        "relations": [],
        "source_cells": [cell for row in candidate.structure for cell in row],
    })


def validate_visual_plan(candidate: VisualCandidate, plan: dict[str, Any]) -> dict[str, bool]:
    source_cells = [cell for row in candidate.structure for cell in row]
    planned_cells = plan.get("source_cells", [])
    source_coverage = source_cells == planned_cells
    order_valid = candidate.kind != "flow" or plan.get("nodes") == list(candidate.structure[0])
    single_character = plan.get("character_role") == CHARACTER_ROLE
    method_report = validate_method_contract(plan)
    return {
        "valid": source_coverage and order_valid and single_character and all(method_report.values()),
        "source_coverage": source_coverage,
        "order_valid": order_valid,
        "single_character": single_character,
        **method_report,
    }


def compile_visual_prompt(plan: dict[str, Any]) -> str:
    kind = plan.get("kind")
    if kind == "flow":
        nodes = plan.get("nodes", [])
        group_text = "；".join(
            f"{group}组：{'、'.join(str(node) for node in grouped_nodes)}"
            for group, grouped_nodes in plan.get("groups", {}).items()
        )
        return (
            "具体画面：横向有序流程信息图，知识结构占画面主体；固定顺序为"
            + " → ".join(str(node) for node in nodes)
            + f"。{('分组：' + group_text + '。') if group_text else ''}每个节点只出现一次，以箭头依次连接，不得交换、合并、遗漏或新增节点；"
              "主角最多一只，仅在右下角辅助指向流程。"
        )
    if kind == "comparison":
        columns = plan.get("columns", [])
        row_text = "；".join(
            f"{row['label']}：{columns[0]}={row['values'][0]}，{columns[1]}={row['values'][1]}"
            for row in plan.get("rows", [])
        )
        relation_text = "；".join(
            f"{relation['from']} → {relation['to']}（{relation['label']}）"
            for relation in plan.get("relations", [])
        )
        return (
            f"具体画面：双栏对比信息图，左栏“{columns[0]}”，右栏“{columns[1]}”，"
            f"用图标、对象和状态表达每行差异，不画待填写空表。逐行对应：{row_text}。"
            f"关系：{relation_text or '两栏并列对照'}。主角最多一只，仅在边缘辅助讲解。"
        )
    if kind == "matrix":
        columns = "、".join(str(item) for item in plan.get("columns", []))
        rows = "；".join(
            f"{row['label']}：{'；'.join(str(value) for value in row['values'])}"
            for row in plan.get("rows", [])
        )
        return (
            f"具体画面：统一信息矩阵，列为{columns}；各行关系为{rows}。"
            "把长句转成图标、对象、状态和连线，保留必要短标签，不逐字抄成长段文字；"
            "主角最多一只，仅在边缘辅助讲解。"
        )
    return "具体画面：" + "；".join(
        "、".join(str(cell) for cell in row) for row in plan.get("items", [])
    )
