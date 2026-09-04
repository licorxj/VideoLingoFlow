# -*- coding: utf-8 -*-
"""临时校验脚本：循环节点数据结构与校验层。用完即删。"""
import json

from backend.workflow_validation import normalize_workflow, _port_map_for_node

wf = {
    "id": "wf_test",
    "name": "t",
    "description": "",
    "type": "user",
    "nodes": [
        {"id": "up", "position": {"x": 0, "y": 0},
         "data": {"nodeType": "output_merge_list", "label": "合并", "config": {"inputCount": 2}}},
        {"id": "loop1", "position": {"x": 300, "y": 0},
         "data": {
             "nodeType": "loop", "label": "循环", "kind": "loop",
             "config": {"itemsSource": "upstream", "iterationConcurrency": 2, "onItemError": "stop"},
             "loopMeta": {
                 "version": 1,
                 "internalWorkflow": {
                     "nodes": [
                         {"id": "n1", "position": {"x": 0, "y": 0},
                          "data": {"nodeType": "text_input", "label": "文本", "config": {"text": "第{index}项-{item}"}}},
                         {"id": "n2", "position": {"x": 200, "y": 0},
                          "data": {"nodeType": "text_input", "label": "文本2", "config": {"text": "{total}"}}},
                     ],
                     "edges": [{"id": "e1", "source": "n1", "sourceHandle": "out-text",
                                "target": "n2", "targetHandle": "in-any"}],
                 },
                 "inputMappings": [{"exposedPortId": "items", "exposedLabel": "迭代对象",
                                    "targetNodeId": "n1", "targetPortId": "any", "type": "json"}],
                 "outputMappings": [{"exposedPortId": "gout_1", "exposedLabel": "结果",
                                     "internalNodeId": "n2", "internalPortId": "text",
                                     "type": "text", "enabled": True}],
                 "iterator": {"exposedPortId": "items", "targetNodeId": "n1", "targetPortId": "any"},
             }}},
        {"id": "down", "position": {"x": 600, "y": 0},
         "data": {"nodeType": "text_input", "label": "下游(静态 any 输入)", "config": {"text": ""}}},
        {"id": "down2", "position": {"x": 600, "y": 200},
         "data": {"nodeType": "text_input", "label": "下游2", "config": {"text": ""}}},
    ],
    "edges": [
        {"id": "x1", "source": "up", "sourceHandle": "out-json", "target": "loop1", "targetHandle": "in-items"},
        {"id": "x2", "source": "loop1", "sourceHandle": "out-gout_1", "target": "down", "targetHandle": "in-any"},
        {"id": "x3", "source": "loop1", "sourceHandle": "out-results", "target": "down2", "targetHandle": "in-any"},
    ],
}

out, migrated, removed = normalize_workflow(wf, expand_groups=True)
print("migrated=", migrated, "removed=", removed)
print("node ids:", [n["id"] for n in out["nodes"]])
print("edges kept:", [(e["source"], e["sourceHandle"], e["target"], e["targetHandle"]) for e in out["edges"]])
loop_node = [n for n in out["nodes"] if n["id"] == "loop1"][0]
print("loop ports in :", _port_map_for_node(loop_node, "target"))
print("loop ports out:", _port_map_for_node(loop_node, "source"))

# 嵌套禁令：循环体内再放一个循环
bad = json.loads(json.dumps(wf))
bad["nodes"][1]["data"]["loopMeta"]["internalWorkflow"]["nodes"].append(
    {"id": "n3", "position": {"x": 0, "y": 0},
     "data": {"nodeType": "loop", "label": "内层循环", "kind": "loop",
              "config": {}, "loopMeta": {"version": 1, "internalWorkflow": {"nodes": [], "edges": []},
                                         "inputMappings": [], "outputMappings": []}}}
)
try:
    normalize_workflow(bad, expand_groups=True)
    print("NESTING CHECK: FAILED (未拒绝嵌套)")
except ValueError as exc:
    print("NESTING CHECK ok:", exc)

# ---- loop_runtime 纯函数 ----
from pathlib import Path
from backend.control_plane import loop_runtime as lr

ws = Path(".")
print("items(list):", lr.normalize_items(["a", "", "b"], workspace=ws))
print("items(dict items):", lr.normalize_items({"items": [{"path": "a.mp4"}, {"path": "b.mp4"}]}, workspace=ws))
print("items(json str):", lr.normalize_items('["x","y"]', workspace=ws))
print("items(newline):", lr.normalize_items("p\nq\nr", workspace=ws))
print("items(scalar):", lr.normalize_items("D:/v/a.mp4", workspace=ws))
print("items(limit):", lr.normalize_items(list(range(10)), workspace=ws, limit=3))
print("items(nested):", lr.normalize_items([["a", "b"], "c"], workspace=ws))

ctx = lr._iteration_context({"itemAlias": "item", "indexAlias": "index"}, {"path": "a.mp4"}, 7, 12)
print("render:", lr.render_value(
    {"out": "out_{index:03d}_{item.path}_of_{total}", "keep": "{unknown}", "n": 3}, ctx))

print("resolve inline:", lr.resolve_items(
    {"itemsSource": "inline_json", "inlineItems": '["1","2","3"]', "maxIterations": 0}, {}, ws))
print("resolve upstream:", lr.resolve_items(
    {"itemsSource": "upstream", "maxIterations": 2}, {"items": "a|b|c|d"}, ws))

manifest = {"total": 3, "items": [
    {"index": 0, "status": "succeeded", "outputs": {"n2": {"text": "t0"}}, "artifacts": ["a0.mp4"]},
    {"index": 1, "status": "failed", "outputs": {}, "artifacts": []},
    {"index": 2, "status": "succeeded", "outputs": {"n2": {"text": "t2"}}, "artifacts": ["a2.mp4"]},
]}
print("loop outputs:", lr._loop_outputs("loop1", loop_node["data"]["loopMeta"], manifest))
print("loop artifacts:", lr._loop_artifacts(manifest))
print("concurrency clamp:", lr._clamp_concurrency({"iterationConcurrency": 99}), lr._clamp_concurrency({}), lr._clamp_concurrency({"iterationConcurrency": "x"}))
