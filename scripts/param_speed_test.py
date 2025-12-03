#!/usr/bin/env python3
"""
ROS2 state dumper パラメータ取得方法の速度比較テスト

2つの実装方法を直接実行して比較:
- Method 1: ros2 param list + ros2 param get (個別取得)
- Method 2: ros2 param dump (一括取得 + フラット化)
"""

import json
import subprocess
import sys
import os
import re
import yaml
import time
from typing import Dict, List, Any, Set


IGNORE_SERVICE_NAMES = [
    'describe_parameters',
    'get_parameter_types',
    'get_parameters',
    'list_parameters',
    'set_parameters',
    'set_parameters_atomically',
]

IGNORE_TOPIC_NAMES = [
    'parameter_events',
]

IGNORE_NODE_PATTERNS = [
    r'.*_impl.*',
    r'/_ros2cli_.*',
]


def run_ros2_command(cmd_list: List[str], timeout: int = 10) -> str | None:
    """ROS 2のCLIコマンドを実行"""
    try:
        env = os.environ.copy()
        result = subprocess.run(
            cmd_list,
            check=True,
            capture_output=True,
            text=True,
            env=env,
            timeout=timeout
        )
        return result.stdout.strip()
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        return None


# ============================================================================
# Method 1: param list + param get (個別取得)
# ============================================================================

def parse_param_get_output(output: str) -> Dict[str, Any]:
    """ros2 param getの出力をパース"""
    param = {"value": None, "type": "unknown"}
    
    match_python = re.search(r'(String|Integer|Boolean|Double)\s+value\s+is:\s+(.*)', output, re.DOTALL | re.IGNORECASE)
    if match_python:
        value_type = match_python.group(1).lower()
        value_str = match_python.group(2).strip()
        param["type"] = value_type
        if value_type == 'integer':
            try: param["value"] = int(value_str)
            except ValueError: param["value"] = value_str
        elif value_type == 'double':
            try: param["value"] = float(value_str)
            except ValueError: param["value"] = value_str
        elif value_type == 'boolean':
            param["value"] = value_str.lower() == 'true'
        else:
            param["value"] = value_str
        return param
    
    type_match = re.search(r'Type:\s+(\w+)', output, re.IGNORECASE)
    value_match = re.search(r'Value:\s+(.*)', output, re.DOTALL)
    
    if type_match:
        param["type"] = type_match.group(1).lower()
    if value_match:
        param["value"] = value_match.group(1).strip()
    
    return param


def get_parameters_method1(node_name: str) -> List[Dict[str, Any]]:
    """Method 1: param list + param getで個別取得"""
    parameters = []
    param_list_raw = run_ros2_command(["ros2", "param", "list", node_name, "--include-hidden"])
    
    if param_list_raw:
        for param_name_line in param_list_raw.split('\n'):
            param_name_line = param_name_line.strip()
            if not param_name_line or param_name_line.endswith(':'):
                continue
            
            param_name = param_name_line.split(':')[0].strip()
            param_get_raw = run_ros2_command(["ros2", "param", "get", node_name, param_name])
            
            if param_get_raw:
                parsed_param = parse_param_get_output(param_get_raw)
                param_value_str = str(parsed_param["value"]) if parsed_param["value"] is not None else "None"
                parameters.append({
                    "name": param_name,
                    "value": param_value_str,
                    "type": parsed_param["type"]
                })
    
    return parameters


# ============================================================================
# Method 2: param dump (一括取得 + フラット化)
# ============================================================================

def get_python_type_name(value: Any) -> str:
    """Python値から型名を取得"""
    if isinstance(value, bool):
        return "boolean"
    elif isinstance(value, int):
        return "integer"
    elif isinstance(value, float):
        return "double"
    elif isinstance(value, str):
        return "string"
    elif isinstance(value, list):
        return "array"
    else:
        return "unknown"


def flatten_dict(d: Dict[str, Any], parent_key: str = '') -> List[tuple[str, Any]]:
    """ネストされた辞書をドット記法でフラット化"""
    items = []
    for k, v in d.items():
        new_key = f"{parent_key}.{k}" if parent_key else k
        if isinstance(v, dict):
            items.extend(flatten_dict(v, new_key))
        else:
            if v is None:
                v = ""
            items.append((new_key, v))
    return items


def get_parameters_method2(node_name: str) -> List[Dict[str, Any]]:
    """Method 2: param dumpで一括取得 + フラット化"""
    parameters = []
    param_dump_raw = run_ros2_command(["ros2", "param", "dump", node_name, "--include-hidden-nodes"])
    
    if param_dump_raw:
        try:
            data = yaml.safe_load(param_dump_raw)
            if data is None:
                return parameters
            
            node_params = data.get(node_name, data)
            if isinstance(node_params, dict) and 'ros__parameters' in node_params:
                ros_params = node_params['ros__parameters']
                if isinstance(ros_params, dict):
                    flattened = flatten_dict(ros_params)
                    for param_name, param_value in flattened:
                        if param_value is None:
                            param_value = ""
                        param_type = get_python_type_name(param_value)
                        param_value_str = str(param_value)
                        parameters.append({
                            "name": param_name,
                            "value": param_value_str,
                            "type": param_type
                        })
        except yaml.YAMLError:
            pass
    
    return parameters


def should_skip_node(node_name: str) -> bool:
    """ノードをスキップすべきかチェック"""
    for pattern in IGNORE_NODE_PATTERNS:
        if re.match(pattern, node_name):
            return True
    return False


def check_node_param_service_available(node_name: str) -> bool:
    """ノードのパラメータサービスが利用可能かチェック"""
    result = run_ros2_command(["ros2", "param", "list", node_name], timeout=5)
    return result is not None


def main():
    """メイン実行関数"""
    print("=" * 70, file=sys.stderr)
    print("ROS2 Parameter Retrieval Speed Comparison Test", file=sys.stderr)
    print("=" * 70, file=sys.stderr)
    print(file=sys.stderr)
    
    # ノードリストを取得
    node_list_raw = run_ros2_command(["ros2", "node", "list", "-a"])
    if not node_list_raw:
        print("Error: No nodes found", file=sys.stderr)
        sys.exit(1)
    
    node_list_all = [n.strip() for n in node_list_raw.split('\n') if n.strip()]
    node_list_filtered = [
        n for n in node_list_all 
        if not n.startswith('/_ros2cli_') and n != '/ros2_state_yaml_dumper_node'
    ]
    
    total_nodes = len(node_list_filtered)
    print(f"Found {total_nodes} nodes to test\n", file=sys.stderr)
    
    # 結果を格納
    results = {
        "test_metadata": {
            "timestamp": int(time.time() * 1000),
            "total_nodes": total_nodes
        },
        "method1": {
            "name": "param list + get (individual)",
            "description": "Uses ros2 param list + ros2 param get for each parameter",
            "total_time": 0,
            "total_parameters": 0,
            "nodes_tested": 0
        },
        "method2": {
            "name": "param dump (batch + flatten)",
            "description": "Uses ros2 param dump with YAML parsing and dict flattening",
            "total_time": 0,
            "total_parameters": 0,
            "nodes_tested": 0
        },
        "comparison": {}
    }
    
    # 各ノードでテスト
    for i, node_name in enumerate(node_list_filtered):
        progress = (i + 1) / total_nodes * 100
        print(f"[{i+1}/{total_nodes}] ({progress:.0f}%) Testing: {node_name}", file=sys.stderr)
        
        # スキップ判定
        if should_skip_node(node_name):
            print(f"  → Skipped (pattern matched)", file=sys.stderr)
            continue
        
        if not check_node_param_service_available(node_name):
            print(f"  → Skipped (service unavailable)", file=sys.stderr)
            continue
        
        # Method 1
        start_time = time.time()
        params1 = get_parameters_method1(node_name)
        time1 = time.time() - start_time
        
        # Method 2
        start_time = time.time()
        params2 = get_parameters_method2(node_name)
        time2 = time.time() - start_time
        
        results["method1"]["total_time"] += time1
        results["method1"]["total_parameters"] += len(params1)
        results["method1"]["nodes_tested"] += 1
        
        results["method2"]["total_time"] += time2
        results["method2"]["total_parameters"] += len(params2)
        results["method2"]["nodes_tested"] += 1
        
        print(f"  Method 1: {time1:.3f}s ({len(params1)} params)", file=sys.stderr)
        print(f"  Method 2: {time2:.3f}s ({len(params2)} params)", file=sys.stderr)
        
        if len(params1) != len(params2):
            print(f"  ⚠️  Parameter count mismatch: {len(params1)} vs {len(params2)}", file=sys.stderr)
    
    # 比較結果を計算
    time1_total = results["method1"]["total_time"]
    time2_total = results["method2"]["total_time"]
    
    if time1_total > 0 and time2_total > 0:
        if time1_total > time2_total:
            results["comparison"]["faster_method"] = "method2"
            results["comparison"]["speedup"] = round(time1_total / time2_total, 2)
            results["comparison"]["time_saved_seconds"] = round(time1_total - time2_total, 3)
            results["comparison"]["time_saved_percent"] = round((time1_total - time2_total) / time1_total * 100, 1)
        else:
            results["comparison"]["faster_method"] = "method1"
            results["comparison"]["speedup"] = round(time2_total / time1_total, 2)
            results["comparison"]["time_saved_seconds"] = round(time2_total - time1_total, 3)
            results["comparison"]["time_saved_percent"] = round((time2_total - time1_total) / time2_total * 100, 1)
    
    # 結果を出力
    print("\n" + "=" * 70, file=sys.stderr)
    print("RESULTS", file=sys.stderr)
    print("=" * 70, file=sys.stderr)
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
